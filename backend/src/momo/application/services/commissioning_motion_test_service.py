"""Backend-owned execution boundary for bounded single-joint commissioning tests.

This service is deliberately separate from the production motion executor.  Its
only hardware dependency is the capability-narrow ``CommissioningMotionServoBus``
and every adapter write receives an immutable, service-prepared command.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Protocol
from uuid import UUID, uuid4

from momo.domain.calibration import CalibrationJoint
from momo.domain.commissioning import (
    CommissioningDirection,
    CommissioningMotionTestState,
    CommissioningSafetyEnvelope,
    CommissioningTestEvidence,
    CommissioningTestResult,
    PhysicalStopVerification,
    PreparedCommissioningTestCommand,
    StopBehavior,
)
from momo.domain.enums import DomainUnit
from momo.domain.errors import HardwareMappingError, RobotApplicationError
from momo.domain.hardware_mapping import (
    effective_logical_limits_from_raw_bounds,
    goal_raw_to_logical,
    logical_to_goal_raw,
    mapping_round_trip_tolerance,
    validate_goal_raw,
)
from momo.domain.real_hardware import (
    OperatorSessionEvidence,
    RealHardwareAuthorizationPurpose,
    RealHardwareContext,
    RealStopResult,
    ServoWriteResult,
    calibration_fingerprint,
    explicit_device_fingerprint,
)
from momo.domain.robot import JointDefinition
from momo.ports.clock import Clock
from momo.ports.commissioning_evidence_repository import (
    CommissioningTestEvidenceRepository,
)
from momo.ports.servo_bus import (
    CommissioningMotionServoBus,
    CommissioningMotionServoBusFacade,
    CommissioningPositionReadback,
)


class CommissioningMotionSessionError(RobotApplicationError):
    code = "COMMISSIONING_MOTION_SESSION_REQUIRED"
    status_code = 403


class CommissioningMotionConflictError(RobotApplicationError):
    code = "COMMISSIONING_MOTION_CONFLICT"
    status_code = 409


class CommissioningEnvelopeExceededError(RobotApplicationError):
    code = "COMMISSIONING_ENVELOPE_EXCEEDED"
    status_code = 422


class MultiJointTestForbiddenError(RobotApplicationError):
    code = "MULTI_JOINT_TEST_FORBIDDEN"
    status_code = 422


class CommissioningDeadmanExpiredError(RobotApplicationError):
    code = "DEADMAN_EXPIRED"
    status_code = 409


class CommissioningRobotUnitError(RobotApplicationError):
    code = "ROBOT_UNIT_MISMATCH"
    status_code = 409


class CommissioningRobotUnitRequiredError(RobotApplicationError):
    code = "ROBOT_UNIT_ID_REQUIRED"
    status_code = 409


class CommissioningReadbackError(RobotApplicationError):
    code = "COMMISSIONING_READBACK_INVALID"
    status_code = 409


class CommissioningEvidenceStorageError(RobotApplicationError):
    code = "COMMISSIONING_EVIDENCE_STORAGE_FAILED"
    status_code = 500


class _SessionAuthorizer(Protocol):
    async def authorize(
        self,
        token: str,
        context: RealHardwareContext,
        *,
        purpose: RealHardwareAuthorizationPurpose,
    ) -> OperatorSessionEvidence: ...


@dataclass(frozen=True, slots=True)
class CommissioningMotionStatus:
    state: CommissioningMotionTestState
    session_id: UUID | None
    active_joint_id: str | None
    command_count: int
    session_expires_at: datetime | None
    deadman_expires_at: datetime | None
    last_evidence_id: UUID | None
    failure_reason: str | None
    physical_stop_verification: PhysicalStopVerification = PhysicalStopVerification.PENDING


@dataclass(slots=True)
class _Attempt:
    attempt_id: UUID
    request_id: str
    joint_id: str
    started_at: datetime
    start_readback: CommissioningPositionReadback | None = None
    start_value: float | None = None
    target_value: float | None = None
    target_raw: int | None = None
    requested_delta: float | None = None
    requested_speed: float | None = None
    prepared: PreparedCommissioningTestCommand | None = None
    final_readback: CommissioningPositionReadback | None = None
    final_value: float | None = None
    stop_behavior: StopBehavior = StopBehavior.NOT_REQUESTED
    abort_reason: str | None = None


@dataclass(slots=True)
class _Runtime:
    session: OperatorSessionEvidence
    envelope: CommissioningSafetyEnvelope
    session_deadline_monotonic: float
    state: CommissioningMotionTestState = CommissioningMotionTestState.AUTHORIZED
    active_joint_id: str | None = None
    deadman_deadline_monotonic: float | None = None
    command_count: int = 0
    attempt: _Attempt | None = None
    last_evidence: CommissioningTestEvidence | None = None
    failure_reason: str | None = None
    watchdog: asyncio.Task[None] | None = None
    watchdog_generation: int = 0


class _AttemptFailed(RuntimeError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class CommissioningMotionTestService:
    """One-session, one-active-joint commissioning executor.

    The service never retains the raw operator token.  Public mutating methods
    re-authorize it against the current context, while the watchdog uses the
    immutable session expiry/envelope snapshot to stop on frontend or network loss.
    """

    def __init__(
        self,
        *,
        context: RealHardwareContext | Callable[[], RealHardwareContext],
        sessions: _SessionAuthorizer,
        bus: CommissioningMotionServoBus,
        allowed_servo_ids: tuple[int, ...],
        repository: CommissioningTestEvidenceRepository,
        clock: Clock,
        software_commit: str,
        readback_max_age_s: float = 0.25,
        divergence_tolerance_raw: int = 8,
    ) -> None:
        if not allowed_servo_ids or len(allowed_servo_ids) != len(set(allowed_servo_ids)):
            raise ValueError("commissioning service requires unique explicit Servo IDs")
        if any(
            isinstance(servo_id, bool) or not isinstance(servo_id, int) or not 1 <= servo_id <= 253
            for servo_id in allowed_servo_ids
        ):
            raise ValueError("commissioning service Servo IDs must be integers from 1 to 253")
        if not isfinite(readback_max_age_s) or not 0.01 <= readback_max_age_s <= 1.0:
            raise ValueError("readback_max_age_s must be between 0.01 and 1 second")
        if (
            isinstance(divergence_tolerance_raw, bool)
            or not isinstance(divergence_tolerance_raw, int)
            or not 0 <= divergence_tolerance_raw <= 64
        ):
            raise ValueError("divergence_tolerance_raw must be between 0 and 64")
        normalized_commit = software_commit.strip()
        if not 7 <= len(normalized_commit) <= 64:
            raise ValueError("software_commit must contain 7 to 64 characters")

        self._context_provider = context if callable(context) else lambda: context
        self.sessions = sessions
        self._bus = CommissioningMotionServoBusFacade(
            bus,
            allowed_servo_ids=allowed_servo_ids,
        )
        self.allowed_servo_ids = allowed_servo_ids
        self.repository = repository
        self.clock = clock
        self.software_commit = normalized_commit
        self.readback_max_age_s = float(readback_max_age_s)
        self.divergence_tolerance_raw = divergence_tolerance_raw
        self._runtime: _Runtime | None = None
        self._guard = asyncio.Lock()
        self._closed = False

    async def start_session(self, token: str) -> CommissioningMotionStatus:
        """Bind the already-issued motion-test session without opening hardware."""

        session = await self._authorize(token)
        context = self._context()
        self._validate_session_identity(session, context)
        envelope = session.commissioning_envelope
        if envelope is None:  # protected again at this narrower boundary
            raise CommissioningMotionSessionError(
                "Commissioning motion session omitted its safety-envelope snapshot"
            )
        effective_expiry = min(
            session.expires_at,
            session.issued_at + timedelta(seconds=envelope.max_session_duration_s),
        )
        remaining_s = (effective_expiry - self.clock.now()).total_seconds()
        if remaining_s <= 0:
            raise CommissioningMotionSessionError("Commissioning motion session has expired")
        async with self._guard:
            if self._closed:
                raise CommissioningMotionConflictError("Commissioning service is shut down")
            retained = self._runtime
            if retained is not None:
                if retained.session.session_id == session.session_id:
                    return self._status_unlocked(retained)
                if retained.attempt is not None or retained.state in {
                    CommissioningMotionTestState.ARMED,
                    CommissioningMotionTestState.MOVING,
                    CommissioningMotionTestState.VERIFYING,
                    CommissioningMotionTestState.STOPPING,
                }:
                    raise CommissioningMotionConflictError(
                        "The prior commissioning session has not reached a safe terminal state",
                        details={"session_id": str(retained.session.session_id)},
                    )
                self._cancel_watchdog_unlocked(retained)
                retained.state = CommissioningMotionTestState.EXPIRED
                retained.failure_reason = "SESSION_REPLACED"
                await self._bus.reset_for_session(session.session_id)
            runtime = _Runtime(
                session=session,
                envelope=envelope,
                session_deadline_monotonic=self.clock.monotonic() + remaining_s,
            )
            self._runtime = runtime
            self._restart_watchdog_unlocked(runtime)
            return self._status_unlocked(runtime)

    async def arm(
        self,
        token: str,
        *,
        joint_id: str,
    ) -> CommissioningMotionStatus:
        session = await self._authorize_current(token)
        context = self._context()
        definition, _ = self._joint_contract(context, joint_id)
        if definition.servo_id not in self.allowed_servo_ids:
            raise MultiJointTestForbiddenError(
                "Joint is outside the explicit commissioning allowlist"
            )

        async with self._guard:
            runtime = self._require_runtime_unlocked(session.session_id)
            self._require_session_alive_unlocked(runtime)
            if runtime.state not in {
                CommissioningMotionTestState.AUTHORIZED,
                CommissioningMotionTestState.COMPLETED,
                CommissioningMotionTestState.FAILED,
            }:
                raise CommissioningMotionConflictError(
                    "A commissioning joint is already armed or moving",
                    details={"state": runtime.state.value},
                )
            if runtime.command_count >= runtime.envelope.max_commands_per_session:
                raise CommissioningEnvelopeExceededError(
                    "Commissioning command-count cap has been reached",
                    details={"max_commands": runtime.envelope.max_commands_per_session},
                )
            runtime.active_joint_id = joint_id
            runtime.deadman_deadline_monotonic = (
                self.clock.monotonic() + runtime.envelope.deadman_lease_ms / 1000.0
            )
            runtime.state = CommissioningMotionTestState.ARMED
            runtime.failure_reason = None
            runtime.attempt = None
            self._restart_watchdog_unlocked(runtime)
            return self._status_unlocked(runtime)

    async def heartbeat(self, token: str) -> CommissioningMotionStatus:
        session = await self._authorize_current(token)
        async with self._guard:
            runtime = self._require_runtime_unlocked(session.session_id)
            self._require_session_alive_unlocked(runtime)
            if runtime.state not in {
                CommissioningMotionTestState.ARMED,
                CommissioningMotionTestState.MOVING,
                CommissioningMotionTestState.VERIFYING,
            }:
                raise CommissioningDeadmanExpiredError(
                    "No armed commissioning test accepts a heartbeat",
                    details={"state": runtime.state.value},
                )
            deadline = runtime.deadman_deadline_monotonic
            if deadline is None or self.clock.monotonic() >= deadline:
                raise CommissioningDeadmanExpiredError("Commissioning deadman lease has expired")
            runtime.deadman_deadline_monotonic = (
                self.clock.monotonic() + runtime.envelope.deadman_lease_ms / 1000.0
            )
            self._restart_watchdog_unlocked(runtime)
            return self._status_unlocked(runtime)

    async def run_relative_test(
        self,
        token: str,
        *,
        joint_id: str,
        signed_delta: float,
        requested_speed: float,
        requested_acceleration: float,
        command_duration_s: float,
        request_id: str,
    ) -> CommissioningTestEvidence:
        """Execute and verify one relative move from the latest position readback."""

        session = await self._authorize_current(token)
        context = self._context()
        definition, calibration_joint = self._joint_contract(context, joint_id)
        profile = context.profile
        if profile is None:  # narrowed again for static and runtime fail-closed behavior
            raise CommissioningMotionSessionError("Profile is required")
        self._validate_request(
            unit=definition.domain_unit,
            envelope=session.commissioning_envelope,
            signed_delta=signed_delta,
            requested_speed=requested_speed,
            requested_acceleration=requested_acceleration,
            command_duration_s=command_duration_s,
            request_id=request_id,
        )
        servo_id = definition.servo_id
        if servo_id is None or servo_id not in self.allowed_servo_ids:
            raise MultiJointTestForbiddenError(
                "Joint is outside the explicit commissioning allowlist"
            )

        attempt = _Attempt(
            attempt_id=uuid4(),
            request_id=request_id.strip(),
            joint_id=joint_id,
            started_at=self.clock.now(),
            requested_delta=float(signed_delta),
            requested_speed=float(requested_speed),
        )
        async with self._guard:
            runtime = self._require_runtime_unlocked(session.session_id)
            self._require_session_alive_unlocked(runtime)
            if runtime.state is not CommissioningMotionTestState.ARMED:
                raise CommissioningMotionConflictError(
                    "Commissioning joint must be armed before a test move",
                    details={"state": runtime.state.value},
                )
            if runtime.attempt is not None:
                raise CommissioningMotionConflictError(
                    "A commissioning test is already preparing or active",
                    details={"state": runtime.state.value},
                )
            if runtime.active_joint_id != joint_id:
                raise MultiJointTestForbiddenError(
                    "The request does not match the one armed commissioning joint"
                )
            if runtime.command_count >= runtime.envelope.max_commands_per_session:
                raise CommissioningEnvelopeExceededError(
                    "Commissioning command-count cap has been reached"
                )
            runtime.command_count += 1
            runtime.attempt = attempt

        try:
            start = await self._bus.read_present_position(servo_id)
            attempt.start_readback = start
            attempt.start_value = goal_raw_to_logical(
                joint_id,
                start.raw_position,
                profile,
                calibration_joint,
            )
            target_value = attempt.start_value + float(signed_delta)
            attempt.target_value = target_value
            attempt.target_raw = logical_to_goal_raw(
                joint_id,
                target_value,
                profile,
                calibration_joint,
            )
            self._require_logical_and_raw_limits(
                context,
                joint_id,
                target_value,
                attempt.target_raw,
                calibration_joint,
            )
            self._require_fresh(start)
            prepared_at = self.clock.now()
            prepared = PreparedCommissioningTestCommand(
                session_id=session.session_id,
                robot_unit_id=session.robot_unit_id,
                joint_id=joint_id,
                servo_id=servo_id,
                unit=definition.domain_unit,
                start_value=attempt.start_value,
                requested_delta=float(signed_delta),
                target_value=target_value,
                start_raw=start.raw_position,
                target_raw=attempt.target_raw,
                requested_speed=float(requested_speed),
                requested_acceleration=float(requested_acceleration),
                command_duration_s=float(command_duration_s),
                prepared_at=prepared_at,
                readback_fresh_until=start.captured_at + timedelta(seconds=self.readback_max_age_s),
                envelope=self._required_envelope(session),
            )
            attempt.prepared = prepared
            await self._transition_attempt(
                session.session_id,
                attempt.attempt_id,
                CommissioningMotionTestState.MOVING,
            )
            write = await self._bus.write_prepared_command(prepared)
            await self._checkpoint(session.session_id, attempt.attempt_id)
            self._require_complete_single_write(write, servo_id)
            await self._transition_attempt(
                session.session_id,
                attempt.attempt_id,
                CommissioningMotionTestState.VERIFYING,
            )
            final = await self._bus.read_present_position(servo_id)
            attempt.final_readback = final
            await self._checkpoint(session.session_id, attempt.attempt_id)
            self._require_fresh(final)
            attempt.final_value = goal_raw_to_logical(
                joint_id,
                final.raw_position,
                profile,
                calibration_joint,
            )
            self._verify_result(context, attempt, calibration_joint)
            await self._checkpoint(session.session_id, attempt.attempt_id)
            stop_behavior = await self._stop_for_attempt(
                session.session_id,
                attempt.attempt_id,
                servo_id,
            )
            attempt.stop_behavior = stop_behavior
            await self._checkpoint(session.session_id, attempt.attempt_id)
            if stop_behavior is StopBehavior.SOFTWARE_PATH_FAILED:
                raise _AttemptFailed(
                    "PHYSICAL_STOP_NOT_VERIFIED",
                    "Commissioning software Stop/Hold request did not reach a known adapter path",
                )
            return await self._finish_attempt(
                session.session_id,
                attempt,
                result=CommissioningTestResult.PASSED,
                failure_reason=None,
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                self._fail_cancelled_attempt(
                    session.session_id,
                    attempt,
                    servo_id,
                    "TEST_TASK_CANCELLED",
                )
            )
            raise
        except _AttemptFailed as error:
            await self._ensure_attempt_stop(session.session_id, attempt, servo_id)
            return await self._finish_attempt(
                session.session_id,
                attempt,
                result=CommissioningTestResult.FAILED,
                failure_reason=error.reason,
                observed_detail=error.detail,
            )
        except CommissioningEnvelopeExceededError as error:
            await self._ensure_attempt_stop(session.session_id, attempt, servo_id)
            return await self._finish_attempt(
                session.session_id,
                attempt,
                result=CommissioningTestResult.FAILED,
                failure_reason="COMMISSIONING_ENVELOPE_EXCEEDED",
                observed_detail=error.message,
            )
        except (HardwareMappingError, ValueError) as error:
            await self._ensure_attempt_stop(session.session_id, attempt, servo_id)
            return await self._finish_attempt(
                session.session_id,
                attempt,
                result=CommissioningTestResult.FAILED,
                failure_reason="COMMISSIONING_PREFLIGHT_OR_READBACK_FAILED",
                observed_detail=str(error),
            )
        except Exception as error:
            await self._ensure_attempt_stop(session.session_id, attempt, servo_id)
            return await self._finish_attempt(
                session.session_id,
                attempt,
                result=CommissioningTestResult.FAILED,
                failure_reason="COMMISSIONING_ADAPTER_OPERATION_FAILED",
                observed_detail=type(error).__name__,
            )

    async def stop(
        self,
        token: str,
        *,
        reason: str = "OPERATOR_STOP",
    ) -> CommissioningMotionStatus:
        session = await self._authorize_current(token)
        return await self._abort_active(session.session_id, reason=reason, expired=False)

    async def priority_stop(self) -> CommissioningMotionStatus:
        """Stop an active test without making safety depend on its session token.

        The API boundary still authenticates this as a priority CONTROL request;
        this narrower method only avoids letting an expired or lost commissioning
        cookie prevent a requested stop from reaching the bus.
        """

        runtime = self._runtime
        if runtime is None:
            return await self.status()
        return await self._abort_active(
            runtime.session.session_id,
            reason="OPERATOR_PRIORITY_STOP",
            expired=False,
        )

    async def network_disconnected(self) -> CommissioningMotionStatus:
        """Fail closed without retaining or requiring a now-lost browser token."""

        runtime = self._runtime
        if runtime is None:
            return CommissioningMotionStatus(
                state=CommissioningMotionTestState.IDLE,
                session_id=None,
                active_joint_id=None,
                command_count=0,
                session_expires_at=None,
                deadman_expires_at=None,
                last_evidence_id=None,
                failure_reason=None,
            )
        return await self._abort_active(
            runtime.session.session_id,
            reason="NETWORK_DISCONNECTED",
            expired=True,
        )

    async def session_invalidated(self) -> CommissioningMotionStatus:
        runtime = self._runtime
        if runtime is None:
            return await self.status()
        return await self._abort_active(
            runtime.session.session_id,
            reason="SESSION_INVALIDATED",
            expired=True,
        )

    async def status(self) -> CommissioningMotionStatus:
        async with self._guard:
            runtime = self._runtime
            if runtime is None:
                return CommissioningMotionStatus(
                    state=CommissioningMotionTestState.IDLE,
                    session_id=None,
                    active_joint_id=None,
                    command_count=0,
                    session_expires_at=None,
                    deadman_expires_at=None,
                    last_evidence_id=None,
                    failure_reason=None,
                )
            return self._status_unlocked(runtime)

    async def shutdown(self) -> None:
        runtime = self._runtime
        if runtime is not None:
            await self._abort_active(
                runtime.session.session_id,
                reason="BACKEND_SHUTDOWN",
                expired=True,
            )
        async with self._guard:
            retained = self._runtime
            if retained is not None:
                self._cancel_watchdog_unlocked(retained)
            self._closed = True
        await self._bus.close()

    async def _authorize(self, token: str) -> OperatorSessionEvidence:
        if not token:
            raise CommissioningMotionSessionError("Commissioning motion token is required")
        return await self.sessions.authorize(
            token,
            self._context(),
            purpose=RealHardwareAuthorizationPurpose.COMMISSIONING_SINGLE_JOINT_TEST,
        )

    async def _authorize_current(self, token: str) -> OperatorSessionEvidence:
        try:
            session = await self._authorize(token)
        except Exception:
            runtime = self._runtime
            if runtime is not None:
                await self._abort_active(
                    runtime.session.session_id,
                    reason="SESSION_AUTHORIZATION_FAILED",
                    expired=True,
                )
            raise
        async with self._guard:
            self._require_runtime_unlocked(session.session_id)
        return session

    def _context(self) -> RealHardwareContext:
        return self._context_provider()

    @staticmethod
    def _required_envelope(session: OperatorSessionEvidence) -> CommissioningSafetyEnvelope:
        envelope = session.commissioning_envelope
        if envelope is None:
            raise CommissioningMotionSessionError("Commissioning envelope is missing")
        return envelope

    def _validate_session_identity(
        self,
        session: OperatorSessionEvidence,
        context: RealHardwareContext,
    ) -> None:
        profile = context.profile
        calibration = context.calibration
        device = context.device
        robot_unit_id = context.robot_unit_id
        if profile is None or calibration is None or device is None:
            raise CommissioningMotionSessionError(
                "Commissioning requires current Profile, Calibration, and explicit Device"
            )
        if not robot_unit_id:
            raise CommissioningRobotUnitRequiredError(
                "A stable robot_unit_id is required for commissioning"
            )
        if session.robot_unit_id != robot_unit_id or device.robot_unit_id != robot_unit_id:
            raise CommissioningRobotUnitError("Commissioning robot unit identity does not match")
        calibration_unit = getattr(calibration, "robot_unit_id", None)
        if calibration_unit != robot_unit_id:
            raise CommissioningRobotUnitError(
                "Calibration must be explicitly bound to this robot unit"
            )
        if session.profile_fingerprint != profile.fingerprint:
            raise CommissioningMotionSessionError("Commissioning Profile fingerprint changed")
        if session.calibration_fingerprint != calibration_fingerprint(calibration):
            raise CommissioningMotionSessionError("Commissioning Calibration fingerprint changed")
        if session.device_fingerprint != explicit_device_fingerprint(device):
            raise CommissioningMotionSessionError("Commissioning Device fingerprint changed")
        if self.software_commit != context.software_commit or context.software_commit == "unknown":
            raise CommissioningMotionSessionError(
                "Commissioning software commit identity is missing or changed"
            )
        if session.allowed_servo_ids != self.allowed_servo_ids:
            raise CommissioningMotionSessionError("Commissioning Servo allowlist changed")

    @staticmethod
    def _joint_contract(
        context: RealHardwareContext,
        joint_id: str,
    ) -> tuple[JointDefinition, CalibrationJoint]:
        profile = context.profile
        calibration = context.calibration
        if profile is None or calibration is None:
            raise CommissioningMotionSessionError("Profile and Calibration are required")
        if joint_id not in profile.enabled_joints:
            raise MultiJointTestForbiddenError("Only one explicitly enabled joint may be tested")
        definition = profile.definitions_by_id[joint_id]
        calibration_joint = calibration.joints_by_id.get(joint_id)
        if calibration_joint is None:
            raise CommissioningMotionSessionError("Joint Calibration is missing")
        if calibration_joint.servo_id != definition.servo_id:
            raise CommissioningMotionSessionError(
                "Joint Calibration Servo ID does not match the Profile mapping"
            )
        return definition, calibration_joint

    @staticmethod
    def _validate_request(
        *,
        unit: DomainUnit,
        envelope: CommissioningSafetyEnvelope | None,
        signed_delta: float,
        requested_speed: float,
        requested_acceleration: float,
        command_duration_s: float,
        request_id: str,
    ) -> None:
        if envelope is None:
            raise CommissioningMotionSessionError("Commissioning envelope is missing")
        values = (signed_delta, requested_speed, requested_acceleration, command_duration_s)
        if any(isinstance(value, bool) or not isfinite(float(value)) for value in values):
            raise CommissioningEnvelopeExceededError("Commissioning request values must be finite")
        if signed_delta == 0 or requested_speed <= 0 or requested_acceleration <= 0:
            raise CommissioningEnvelopeExceededError(
                "Commissioning delta must be non-zero and dynamic caps must be positive"
            )
        if command_duration_s <= 0:
            raise CommissioningEnvelopeExceededError("Commissioning duration must be positive")
        delta_cap = (
            envelope.max_prismatic_delta_mm
            if unit is DomainUnit.MM
            else envelope.max_revolute_delta_deg
        )
        speed_cap = (
            envelope.max_prismatic_speed_mm_s
            if unit is DomainUnit.MM
            else envelope.max_revolute_speed_deg_s
        )
        acceleration_cap = (
            envelope.max_prismatic_acceleration_mm_s2
            if unit is DomainUnit.MM
            else envelope.max_revolute_acceleration_deg_s2
        )
        if (
            abs(signed_delta) > delta_cap
            or requested_speed > speed_cap
            or requested_acceleration > acceleration_cap
            or command_duration_s > envelope.max_command_duration_s
        ):
            raise CommissioningEnvelopeExceededError(
                "Commissioning request exceeds the snapshotted safety envelope"
            )
        peak_speed = 1.5 * abs(signed_delta) / command_duration_s
        peak_acceleration = 6.0 * abs(signed_delta) / command_duration_s**2
        if (
            peak_speed > requested_speed + 1e-12
            or peak_acceleration > requested_acceleration + 1e-12
        ):
            raise CommissioningEnvelopeExceededError(
                "Requested duration cannot honor the requested speed/acceleration caps"
            )
        if not isinstance(request_id, str) or not 1 <= len(request_id.strip()) <= 128:
            raise CommissioningEnvelopeExceededError("request_id must contain 1 to 128 characters")

    @staticmethod
    def _require_logical_and_raw_limits(
        context: RealHardwareContext,
        joint_id: str,
        target_value: float,
        target_raw: int,
        calibration_joint: CalibrationJoint,
    ) -> None:
        profile = context.profile
        if profile is None:
            raise CommissioningMotionSessionError("Profile is required")
        definition = profile.definitions_by_id[joint_id]
        if not definition.minimum <= target_value <= definition.maximum:
            raise CommissioningEnvelopeExceededError("Target exceeds logical joint limits")
        logical_lower, logical_upper = effective_logical_limits_from_raw_bounds(
            joint_id,
            profile,
            calibration_joint,
        )
        if not logical_lower <= target_value <= logical_upper:
            raise CommissioningEnvelopeExceededError("Target exceeds raw-derived logical limits")
        validate_goal_raw(joint_id, target_raw, profile, calibration_joint)

    def _require_fresh(self, readback: CommissioningPositionReadback) -> None:
        age_s = (self.clock.now() - readback.captured_at).total_seconds()
        if age_s < -1e-6 or age_s > self.readback_max_age_s:
            raise _AttemptFailed(
                "READBACK_STALE",
                "Commissioning position readback is stale or future-dated",
            )

    @staticmethod
    def _require_complete_single_write(write: ServoWriteResult, servo_id: int) -> None:
        expected = (servo_id,)
        if (
            write.requested_ids != expected
            or write.written_ids != expected
            or write.failed_ids
            or not write.connected
            or not write.complete
            or not write.safety_state_known
        ):
            raise _AttemptFailed(
                "COMMISSIONING_WRITE_FAILED",
                "The single-joint adapter write did not complete exactly",
            )

    def _verify_result(
        self,
        context: RealHardwareContext,
        attempt: _Attempt,
        calibration_joint: CalibrationJoint,
    ) -> None:
        profile = context.profile
        prepared = attempt.prepared
        start = attempt.start_readback
        final = attempt.final_readback
        final_value = attempt.final_value
        start_value = attempt.start_value
        target_value = attempt.target_value
        if (
            profile is None
            or prepared is None
            or start is None
            or final is None
            or final_value is None
            or start_value is None
            or target_value is None
        ):
            raise _AttemptFailed("READBACK_INCOMPLETE", "Commissioning verification is incomplete")
        self._require_logical_and_raw_limits(
            context,
            attempt.joint_id,
            final_value,
            final.raw_position,
            calibration_joint,
        )
        logical_change = final_value - start_value
        expected_direction = 1 if prepared.requested_delta > 0 else -1
        observed_direction = 1 if logical_change > 0 else -1 if logical_change < 0 else 0
        if observed_direction != expected_direction:
            raise _AttemptFailed(
                "DIRECTION_MISMATCH",
                "Observed logical direction differs from the requested direction",
            )
        raw_divergence = abs(final.raw_position - prepared.target_raw)
        logical_divergence = abs(final_value - target_value)
        definition = profile.definitions_by_id[attempt.joint_id]
        logical_tolerance = mapping_round_trip_tolerance(definition) * (
            self.divergence_tolerance_raw + 1
        )
        if raw_divergence > self.divergence_tolerance_raw or logical_divergence > logical_tolerance:
            raise _AttemptFailed(
                "DIVERGENCE_EXCEEDED",
                "Observed joint position diverges from the prepared target",
            )

    async def _transition_attempt(
        self,
        session_id: UUID,
        attempt_id: UUID,
        state: CommissioningMotionTestState,
    ) -> None:
        async with self._guard:
            runtime = self._require_runtime_unlocked(session_id)
            self._require_attempt_active_unlocked(runtime, attempt_id)
            runtime.state = state

    async def _checkpoint(self, session_id: UUID, attempt_id: UUID) -> None:
        async with self._guard:
            runtime = self._require_runtime_unlocked(session_id)
            self._require_attempt_active_unlocked(runtime, attempt_id)
            self._require_session_alive_unlocked(runtime)
            deadline = runtime.deadman_deadline_monotonic
            if deadline is None or self.clock.monotonic() >= deadline:
                raise _AttemptFailed("DEADMAN_EXPIRED", "Commissioning deadman lease expired")

    @staticmethod
    def _require_attempt_active_unlocked(runtime: _Runtime, attempt_id: UUID) -> _Attempt:
        attempt = runtime.attempt
        if attempt is None or attempt.attempt_id != attempt_id:
            raise _AttemptFailed("TEST_CANCELLED", "Commissioning test is no longer active")
        if attempt.abort_reason is not None:
            raise _AttemptFailed(attempt.abort_reason, "Commissioning test was stopped")
        if runtime.state is CommissioningMotionTestState.EXPIRED:
            raise _AttemptFailed("DEADMAN_EXPIRED", "Commissioning session expired")
        return attempt

    async def _stop_for_attempt(
        self,
        session_id: UUID,
        attempt_id: UUID,
        servo_id: int,
    ) -> StopBehavior:
        async with self._guard:
            runtime = self._require_runtime_unlocked(session_id)
            attempt = self._require_attempt_active_unlocked(runtime, attempt_id)
            runtime.state = CommissioningMotionTestState.STOPPING
        outcome = await self._bus.stop_or_hold(servo_id)
        behavior = self._stop_behavior(outcome.result)
        attempt.stop_behavior = behavior
        return behavior

    @staticmethod
    def _stop_behavior(result: RealStopResult) -> StopBehavior:
        if result in {
            RealStopResult.STOPPED_AND_VERIFIED,
            RealStopResult.HOLD_REQUESTED,
            RealStopResult.TORQUE_DISABLE_REQUESTED,
        }:
            # Even a successful Fake/software path is not physical field evidence.
            return StopBehavior.PHYSICAL_BEHAVIOR_PENDING
        return StopBehavior.SOFTWARE_PATH_FAILED

    async def _ensure_attempt_stop(
        self,
        session_id: UUID,
        attempt: _Attempt,
        servo_id: int,
    ) -> None:
        if attempt.stop_behavior is not StopBehavior.NOT_REQUESTED:
            return
        try:
            outcome = await self._bus.stop_or_hold(servo_id)
        except Exception:
            attempt.stop_behavior = StopBehavior.SOFTWARE_PATH_FAILED
        else:
            attempt.stop_behavior = self._stop_behavior(outcome.result)
        async with self._guard:
            runtime = self._runtime
            if (
                runtime is not None
                and runtime.session.session_id == session_id
                and runtime.state is not CommissioningMotionTestState.EXPIRED
            ):
                runtime.state = CommissioningMotionTestState.STOPPING

    async def _fail_cancelled_attempt(
        self,
        session_id: UUID,
        attempt: _Attempt,
        servo_id: int,
        reason: str,
    ) -> None:
        await self._ensure_attempt_stop(session_id, attempt, servo_id)
        await self._finish_attempt(
            session_id,
            attempt,
            result=CommissioningTestResult.FAILED,
            failure_reason=reason,
            observed_detail="Commissioning test task was cancelled",
        )

    async def _finish_attempt(
        self,
        session_id: UUID,
        attempt: _Attempt,
        *,
        result: CommissioningTestResult,
        failure_reason: str | None,
        observed_detail: str | None = None,
    ) -> CommissioningTestEvidence:
        context = self._context()
        profile = context.profile
        calibration = context.calibration
        device = context.device
        runtime = self._runtime
        if (
            profile is None
            or calibration is None
            or device is None
            or runtime is None
            or runtime.session.session_id != session_id
        ):
            raise CommissioningMotionSessionError(
                "Commissioning evidence identity became unavailable"
            )
        start = attempt.start_readback
        if start is None:
            raise CommissioningReadbackError(
                "No position readback exists for commissioning evidence"
            )
        start_value = attempt.start_value
        if start_value is None:
            definition, calibration_joint = self._joint_contract(context, attempt.joint_id)
            del definition
            start_value = goal_raw_to_logical(
                attempt.joint_id,
                start.raw_position,
                profile,
                calibration_joint,
            )
        target_value = attempt.target_value if attempt.target_value is not None else start_value
        target_raw = attempt.target_raw if attempt.target_raw is not None else start.raw_position
        final = attempt.final_readback or start
        final_value = attempt.final_value
        if final_value is None:
            try:
                _, calibration_joint = self._joint_contract(context, attempt.joint_id)
                final_value = goal_raw_to_logical(
                    attempt.joint_id,
                    final.raw_position,
                    profile,
                    calibration_joint,
                )
            except (HardwareMappingError, ValueError):
                final_value = start_value
        requested_delta = attempt.requested_delta or 0.0
        expected = (
            CommissioningDirection.POSITIVE
            if requested_delta > 0
            else CommissioningDirection.NEGATIVE
        )
        actual_delta = final_value - start_value
        observed = (
            CommissioningDirection.POSITIVE
            if actual_delta > 0
            else CommissioningDirection.NEGATIVE
            if actual_delta < 0
            else None
        )
        divergence = abs(final_value - target_value)
        detail = observed_detail or (
            f"raw {start.raw_position}->{final.raw_position}; "
            f"logical {start_value:.9g}->{final_value:.9g}"
        )
        evidence = CommissioningTestEvidence(
            robot_unit_id=runtime.session.robot_unit_id,
            robot_variant=profile.variant,
            profile_fingerprint=profile.fingerprint,
            calibration_fingerprint=calibration_fingerprint(calibration),
            device_fingerprint=explicit_device_fingerprint(device),
            joint_id=attempt.joint_id,
            unit=profile.definitions_by_id[attempt.joint_id].domain_unit,
            start_value=start_value,
            requested_delta=requested_delta,
            target_value=target_value,
            final_value=final_value,
            start_raw=start.raw_position,
            final_raw=final.raw_position,
            requested_speed=attempt.requested_speed or 1e-12,
            measured_or_observed_result=detail[:500],
            direction_expected=expected,
            direction_observed=observed,
            divergence=divergence,
            stop_behavior=attempt.stop_behavior,
            started_at=attempt.started_at,
            completed_at=self.clock.now(),
            software_commit=self.software_commit,
            operator_id=runtime.session.operator_id,
            request_id=attempt.request_id,
            session_id=session_id,
            prepared_target_raw=target_raw,
            prepared_command=attempt.prepared,
            result=result,
            failure_reason_optional=failure_reason,
        )
        try:
            await self.repository.save(evidence)
        except Exception as error:
            async with self._guard:
                retained = self._runtime
                if retained is not None and retained.session.session_id == session_id:
                    retained.state = CommissioningMotionTestState.FAILED
                    retained.failure_reason = "COMMISSIONING_EVIDENCE_STORAGE_FAILED"
            raise CommissioningEvidenceStorageError(
                "Commissioning test evidence could not be persisted atomically"
            ) from error

        async with self._guard:
            retained = self._require_runtime_unlocked(session_id)
            if retained.attempt is not None and retained.attempt.attempt_id == attempt.attempt_id:
                retained.attempt = None
                retained.active_joint_id = None
                retained.deadman_deadline_monotonic = None
                retained.last_evidence = evidence
                retained.failure_reason = failure_reason
                if retained.state is not CommissioningMotionTestState.EXPIRED:
                    retained.state = (
                        CommissioningMotionTestState.COMPLETED
                        if result is CommissioningTestResult.PASSED
                        else CommissioningMotionTestState.FAILED
                    )
                self._restart_watchdog_unlocked(retained)
        return evidence

    async def _abort_active(
        self,
        session_id: UUID,
        *,
        reason: str,
        expired: bool,
    ) -> CommissioningMotionStatus:
        servo_id: int | None = None
        async with self._guard:
            runtime = self._require_runtime_unlocked(session_id)
            if runtime.active_joint_id is None and runtime.attempt is None and not expired:
                return self._status_unlocked(runtime)
            joint_id = runtime.active_joint_id
            if joint_id is not None:
                context = self._context()
                profile = context.profile
                if profile is not None and joint_id in profile.definitions_by_id:
                    servo_id = profile.definitions_by_id[joint_id].servo_id
            if runtime.attempt is not None:
                runtime.attempt.abort_reason = reason
            runtime.failure_reason = reason
            runtime.deadman_deadline_monotonic = None
            runtime.state = (
                CommissioningMotionTestState.EXPIRED
                if expired
                else CommissioningMotionTestState.STOPPING
            )
            self._cancel_watchdog_unlocked(runtime)
        if servo_id is not None:
            try:
                outcome = await self._bus.stop_or_hold(servo_id)
            except Exception:
                behavior = StopBehavior.SOFTWARE_PATH_FAILED
            else:
                behavior = self._stop_behavior(outcome.result)
            async with self._guard:
                retained = self._runtime
                if retained is not None and retained.session.session_id == session_id:
                    if retained.attempt is not None:
                        retained.attempt.stop_behavior = behavior
                    elif not expired:
                        retained.active_joint_id = None
                        retained.state = CommissioningMotionTestState.AUTHORIZED
                        retained.failure_reason = None
                        self._restart_watchdog_unlocked(retained)
        async with self._guard:
            return self._status_unlocked(self._require_runtime_unlocked(session_id))

    async def _watchdog(self, session_id: UUID, generation: int, deadline: float) -> None:
        try:
            await self.clock.sleep(max(0.0, deadline - self.clock.monotonic()))
            async with self._guard:
                runtime = self._runtime
                if (
                    runtime is None
                    or runtime.session.session_id != session_id
                    or runtime.watchdog_generation != generation
                ):
                    return
                session_expired = self.clock.monotonic() >= runtime.session_deadline_monotonic
                deadman_expired = (
                    runtime.deadman_deadline_monotonic is not None
                    and self.clock.monotonic() >= runtime.deadman_deadline_monotonic
                )
            if session_expired or deadman_expired:
                await self._abort_active(
                    session_id,
                    reason="SESSION_EXPIRED" if session_expired else "DEADMAN_EXPIRED",
                    expired=True,
                )
        except asyncio.CancelledError:
            return

    def _restart_watchdog_unlocked(self, runtime: _Runtime) -> None:
        self._cancel_watchdog_unlocked(runtime)
        runtime.watchdog_generation += 1
        deadlines = [runtime.session_deadline_monotonic]
        if runtime.deadman_deadline_monotonic is not None:
            deadlines.append(runtime.deadman_deadline_monotonic)
        deadline = min(deadlines)
        runtime.watchdog = asyncio.create_task(
            self._watchdog(runtime.session.session_id, runtime.watchdog_generation, deadline),
            name=f"commissioning-motion-watchdog-{runtime.session.session_id}",
        )

    @staticmethod
    def _cancel_watchdog_unlocked(runtime: _Runtime) -> None:
        task = runtime.watchdog
        runtime.watchdog = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    def _require_runtime_unlocked(self, session_id: UUID) -> _Runtime:
        runtime = self._runtime
        if runtime is None or runtime.session.session_id != session_id:
            raise CommissioningMotionSessionError("Commissioning motion session is not active")
        return runtime

    def _require_session_alive_unlocked(self, runtime: _Runtime) -> None:
        if (
            runtime.state is CommissioningMotionTestState.EXPIRED
            or self.clock.monotonic() >= runtime.session_deadline_monotonic
        ):
            raise CommissioningMotionSessionError("Commissioning motion session has expired")

    def _status_unlocked(self, runtime: _Runtime) -> CommissioningMotionStatus:
        session_remaining = max(
            0.0,
            runtime.session_deadline_monotonic - self.clock.monotonic(),
        )
        session_expires_at = self.clock.now() + timedelta(seconds=session_remaining)
        deadman_expires_at = None
        if runtime.deadman_deadline_monotonic is not None:
            deadman_remaining = max(
                0.0,
                runtime.deadman_deadline_monotonic - self.clock.monotonic(),
            )
            deadman_expires_at = self.clock.now() + timedelta(seconds=deadman_remaining)
        return CommissioningMotionStatus(
            state=runtime.state,
            session_id=runtime.session.session_id,
            active_joint_id=runtime.active_joint_id,
            command_count=runtime.command_count,
            session_expires_at=session_expires_at,
            deadman_expires_at=deadman_expires_at,
            last_evidence_id=(
                runtime.last_evidence.id if runtime.last_evidence is not None else None
            ),
            failure_reason=runtime.failure_reason,
        )


__all__ = [
    "CommissioningDeadmanExpiredError",
    "CommissioningEnvelopeExceededError",
    "CommissioningEvidenceStorageError",
    "CommissioningMotionConflictError",
    "CommissioningMotionSessionError",
    "CommissioningMotionStatus",
    "CommissioningMotionTestService",
    "CommissioningReadbackError",
    "CommissioningRobotUnitError",
    "CommissioningRobotUnitRequiredError",
    "MultiJointTestForbiddenError",
]
