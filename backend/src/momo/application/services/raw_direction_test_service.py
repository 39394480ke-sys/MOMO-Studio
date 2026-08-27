"""Backend-owned Raw +/- direction characterization with no Calibration dependency."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from momo.domain.errors import RobotApplicationError
from momo.domain.raw_direction import (
    LEGACY_V2_MULTI_TURN_PHASE_CANDIDATE,
    RAW_DIRECTION_DRAFT_CONFIRMATION,
    PreparedRawDirectionCommand,
    RawDirection,
    RawDirectionCalibrationDraft,
    RawDirectionJointDraft,
    RawDirectionObservation,
    RawDirectionSafetyEnvelope,
    RawDirectionTestState,
    RawDirectionZeroSnapshot,
)
from momo.domain.real_hardware import (
    OperatorSessionEvidence,
    RealHardwareAuthorizationPurpose,
    RealHardwareContext,
)
from momo.ports.clock import Clock
from momo.ports.servo_bus import RawDirectionServoBus, RawDirectionServoBusFacade


class RawDirectionSessionError(RobotApplicationError):
    code = "RAW_DIRECTION_SESSION_REQUIRED"
    status_code = 403


class RawDirectionConflictError(RobotApplicationError):
    code = "RAW_DIRECTION_CONFLICT"
    status_code = 409


class RawDirectionEnvelopeError(RobotApplicationError):
    code = "RAW_DIRECTION_ENVELOPE_EXCEEDED"
    status_code = 422


class RawDirectionExecutionError(RobotApplicationError):
    code = "RAW_DIRECTION_EXECUTION_FAILED"
    status_code = 409


class _SessionAuthorizer(Protocol):
    async def authorize(
        self,
        token: str,
        context: RealHardwareContext,
        *,
        purpose: RealHardwareAuthorizationPurpose,
    ) -> OperatorSessionEvidence: ...


@dataclass(frozen=True, slots=True)
class RawDirectionStatus:
    state: RawDirectionTestState
    session_id: UUID | None
    active_joint_id: str | None
    command_count: int
    session_expires_at: datetime | None
    deadman_expires_at: datetime | None
    zero_snapshot: RawDirectionZeroSnapshot | None
    last_observation: RawDirectionObservation | None
    observations: tuple[RawDirectionObservation, ...]
    calibration_draft: RawDirectionCalibrationDraft | None
    failure_reason: str | None


@dataclass(slots=True)
class _Runtime:
    session: OperatorSessionEvidence
    envelope: RawDirectionSafetyEnvelope
    zero_snapshot: RawDirectionZeroSnapshot
    session_deadline: float
    state: RawDirectionTestState = RawDirectionTestState.ZERO_CAPTURED
    active_joint_id: str | None = None
    deadman_deadline: float | None = None
    command_count: int = 0
    last_observation: RawDirectionObservation | None = None
    observations_by_joint_direction: dict[tuple[str, RawDirection], RawDirectionObservation] = (
        field(default_factory=dict)
    )
    urdf_matches_by_joint: dict[str, bool] = field(default_factory=dict)
    draft_confirmed_at: datetime | None = None
    failure_reason: str | None = None
    zero_recapture_required: bool = False
    watchdog: asyncio.Task[None] | None = None
    generation: int = 0


class RawDirectionTestService:
    """One-session, one-joint, fixed-count test around a captured Raw zero."""

    def __init__(
        self,
        *,
        context: RealHardwareContext | Callable[[], RealHardwareContext],
        sessions: _SessionAuthorizer,
        bus: RawDirectionServoBus,
        allowed_servo_ids: tuple[int, ...],
        clock: Clock,
        readback_max_age_s: float = 0.25,
    ) -> None:
        self._context_provider = context if callable(context) else lambda: context
        self._sessions = sessions
        self._bus = RawDirectionServoBusFacade(bus, allowed_servo_ids=allowed_servo_ids)
        self._allowed_servo_ids = allowed_servo_ids
        self._clock = clock
        self._readback_max_age_s = readback_max_age_s
        self._runtime: _Runtime | None = None
        self._guard = asyncio.Lock()

    async def start_session(self, token: str) -> RawDirectionStatus:
        session = await self._authorize(token)
        context = self._context()
        profile = context.profile
        device = context.device
        envelope = session.raw_direction_envelope
        if profile is None or device is None or envelope is None:
            raise RawDirectionSessionError("Raw direction identity or safety envelope is missing")
        if session.allowed_servo_ids != self._allowed_servo_ids:
            raise RawDirectionSessionError("Raw direction Servo allowlist changed")
        if session.robot_unit_id != context.robot_unit_id:
            raise RawDirectionSessionError("Raw direction robot unit changed")
        # The physical adapter is lazy: opening the exact configured device and
        # verifying the allowlisted IDs happens only after this session grant.
        await self._bus.reset_for_session(session.session_id)
        raw_by_joint: dict[str, int] = {}
        for joint_id in profile.enabled_joints:
            definition = profile.definitions_by_id[joint_id]
            servo_id = definition.servo_id
            if servo_id is None or servo_id not in self._allowed_servo_ids:
                raise RawDirectionSessionError("Profile contains an unmapped Raw direction joint")
            readback = await self._bus.read_present_position(servo_id)
            self._require_fresh(readback.captured_at)
            raw_by_joint[joint_id] = readback.raw_position
        snapshot = RawDirectionZeroSnapshot(
            session_id=session.session_id,
            robot_unit_id=session.robot_unit_id,
            captured_at=self._clock.now(),
            raw_by_joint=raw_by_joint,
        )
        remaining_s = min(
            (session.expires_at - self._clock.now()).total_seconds(),
            envelope.max_session_duration_s,
        )
        if remaining_s <= 0:
            raise RawDirectionSessionError("Raw direction session has expired")
        async with self._guard:
            previous = self._runtime
            if previous is not None and previous.watchdog is not None:
                previous.watchdog.cancel()
            runtime = _Runtime(
                session=session,
                envelope=envelope,
                zero_snapshot=snapshot,
                session_deadline=self._clock.monotonic() + remaining_s,
            )
            self._runtime = runtime
            self._restart_watchdog(runtime)
            return self._status(runtime)

    async def arm(self, token: str, joint_id: str) -> RawDirectionStatus:
        session = await self._authorize_current(token)
        self._joint_servo_id(joint_id)
        async with self._guard:
            runtime = self._require_runtime(session.session_id)
            self._require_alive(runtime)
            if runtime.state in {RawDirectionTestState.MOVING, RawDirectionTestState.STOPPING}:
                raise RawDirectionConflictError("A Raw direction command is already active")
            if runtime.zero_recapture_required:
                raise RawDirectionConflictError(
                    "The previous Raw direction step failed; recapture zero before retrying",
                    details={"reason": "ZERO_RECAPTURE_REQUIRED"},
                )
            if runtime.command_count >= runtime.envelope.max_commands_per_session:
                raise RawDirectionEnvelopeError("Raw direction command-count cap reached")
            runtime.active_joint_id = joint_id
            runtime.deadman_deadline = (
                self._clock.monotonic() + runtime.envelope.deadman_lease_ms / 1000.0
            )
            runtime.state = RawDirectionTestState.ARMED
            runtime.failure_reason = None
            self._restart_watchdog(runtime)
            return self._status(runtime)

    async def heartbeat(self, token: str) -> RawDirectionStatus:
        session = await self._authorize_current(token)
        async with self._guard:
            runtime = self._require_runtime(session.session_id)
            self._require_alive(runtime)
            if runtime.state not in {RawDirectionTestState.ARMED, RawDirectionTestState.MOVING}:
                raise RawDirectionConflictError("No armed Raw direction test accepts heartbeat")
            if (
                runtime.deadman_deadline is None
                or self._clock.monotonic() >= runtime.deadman_deadline
            ):
                raise RawDirectionConflictError("Raw direction deadman expired")
            runtime.deadman_deadline = (
                self._clock.monotonic() + runtime.envelope.deadman_lease_ms / 1000.0
            )
            self._restart_watchdog(runtime)
            return self._status(runtime)

    async def step(
        self,
        token: str,
        *,
        joint_id: str,
        direction: RawDirection,
    ) -> RawDirectionStatus:
        session = await self._authorize_current(token)
        servo_id = self._joint_servo_id(joint_id)
        async with self._guard:
            runtime = self._require_runtime(session.session_id)
            self._require_alive(runtime)
            if runtime.state is not RawDirectionTestState.ARMED:
                raise RawDirectionConflictError("Raw direction joint must be armed first")
            if runtime.active_joint_id != joint_id:
                raise RawDirectionConflictError("Raw direction request does not match armed joint")
            runtime.state = RawDirectionTestState.MOVING
            self._restart_watchdog(runtime)
            zero_raw = runtime.zero_snapshot.raw_by_joint[joint_id]
            envelope = runtime.envelope
        start_raw_for_error: int | None = None
        target_raw_for_error: int | None = None
        try:
            start = await self._bus.read_present_position(servo_id)
            start_raw_for_error = start.raw_position
            self._require_fresh(start.captured_at)
            profile = self._context().profile
            if profile is None:
                raise RawDirectionSessionError("Raw direction Profile disappeared")
            definition = profile.definitions_by_id[joint_id]
            scale = definition.motor_degrees_per_domain_unit
            counts = definition.raw_counts_per_motor_revolution
            if scale is None or scale <= 0 or counts <= 0:
                raise RawDirectionEnvelopeError("Profile has no usable Raw comparison scale")
            # Exactly one UI/domain unit: 1 mm for the rail or 1 degree for a
            # revolute joint.  Clients never choose a Raw target or distance.
            step_counts = max(1, round(scale / 360.0 * counts))
            if step_counts > envelope.max_step_counts:
                raise RawDirectionEnvelopeError("Profile Raw comparison step exceeds hard cap")
            target_raw = start.raw_position + direction.sign * step_counts
            target_raw_for_error = target_raw
            if abs(target_raw - zero_raw) > envelope.max_zero_offset_counts:
                raise RawDirectionEnvelopeError(
                    "Raw direction target exceeds the captured-zero envelope; recapture zero",
                    details={
                        "reason": "ZERO_RECAPTURE_REQUIRED",
                        "joint_id": joint_id,
                        "zero_raw": zero_raw,
                        "start_raw": start.raw_position,
                        "target_raw": target_raw,
                    },
                )
            prepared_at = self._clock.now()
            command = PreparedRawDirectionCommand(
                session_id=session.session_id,
                robot_unit_id=session.robot_unit_id,
                joint_id=joint_id,
                servo_id=servo_id,
                direction=direction,
                step_counts=step_counts,
                zero_raw=zero_raw,
                start_raw=start.raw_position,
                target_raw=target_raw,
                prepared_at=prepared_at,
                readback_fresh_until=start.captured_at
                + timedelta(seconds=self._readback_max_age_s),
                envelope=envelope,
            )
            async with self._guard:
                runtime = self._require_runtime(session.session_id)
                runtime.command_count += 1
            result = await self._bus.write_prepared_raw_direction_command(command)
            if not result.complete or result.written_ids != (servo_id,):
                raise RuntimeError("Raw direction adapter did not complete the single-Servo write")
            final = await self._bus.read_present_position(servo_id)
            self._require_fresh(final.captured_at)
            if (final.raw_position - start.raw_position) * direction.sign <= 0:
                raise RuntimeError("Raw readback did not move in the commanded Raw direction")
            await self._bus.stop_or_hold(servo_id)
            observation = RawDirectionObservation(
                command_id=command.command_id,
                joint_id=joint_id,
                servo_id=servo_id,
                direction=direction,
                zero_raw=zero_raw,
                start_raw=start.raw_position,
                target_raw=target_raw,
                final_raw=final.raw_position,
                completed_at=self._clock.now(),
                software_only_adapter=not bool(getattr(self._bus, "is_physical_adapter", False)),
            )
            async with self._guard:
                runtime = self._require_runtime(session.session_id)
                runtime.state = RawDirectionTestState.COMPLETED
                runtime.deadman_deadline = None
                runtime.last_observation = observation
                runtime.observations_by_joint_direction[(joint_id, direction)] = observation
                runtime.urdf_matches_by_joint.pop(joint_id, None)
                runtime.draft_confirmed_at = None
                self._restart_watchdog(runtime)
                return self._status(runtime)
        except Exception as error:
            hold_error: Exception | None = None
            try:
                await self._bus.stop_or_hold(servo_id)
            except Exception as caught_hold_error:
                hold_error = caught_hold_error
            finally:
                async with self._guard:
                    runtime = self._require_runtime(session.session_id)
                    runtime.state = RawDirectionTestState.FAILED
                    runtime.deadman_deadline = None
                    runtime.zero_recapture_required = True
                    runtime.failure_reason = (
                        "STEP_SETTLE_TIMEOUT"
                        if isinstance(error, TimeoutError)
                        else type(error).__name__
                    )
                    self._restart_watchdog(runtime)
            if isinstance(error, RobotApplicationError):
                raise
            details: dict[str, object] = {
                "reason": "STEP_SETTLE_TIMEOUT"
                if isinstance(error, TimeoutError)
                else "ADAPTER_EXECUTION_FAILED",
                "joint_id": joint_id,
                "zero_raw": zero_raw,
                "hold_requested": hold_error is None,
            }
            if start_raw_for_error is not None:
                details["start_raw"] = start_raw_for_error
            if target_raw_for_error is not None:
                details["target_raw"] = target_raw_for_error
            observed_raw = getattr(error, "observed_raw", None)
            if isinstance(observed_raw, int):
                details["observed_raw"] = observed_raw
            tolerance_counts = getattr(error, "tolerance_counts", None)
            if isinstance(tolerance_counts, int):
                details["tolerance_counts"] = tolerance_counts
            progress_counts = getattr(error, "progress_counts", None)
            if isinstance(progress_counts, int):
                details["progress_counts"] = progress_counts
            required_progress_counts = getattr(error, "required_progress_counts", None)
            if isinstance(required_progress_counts, int):
                details["required_progress_counts"] = required_progress_counts
            raise RawDirectionExecutionError(
                "Raw direction step did not complete; Hold was requested. "
                "Recapture zero before retrying.",
                details=details,
            ) from error

    async def priority_stop(self) -> RawDirectionStatus:
        async with self._guard:
            runtime = self._runtime
            if runtime is None or runtime.active_joint_id is None:
                return self._idle_status() if runtime is None else self._status(runtime)
            servo_id = self._joint_servo_id(runtime.active_joint_id)
            runtime.state = RawDirectionTestState.STOPPING
        await self._bus.stop_or_hold(servo_id)
        async with self._guard:
            runtime = self._runtime
            if runtime is None:
                return self._idle_status()
            runtime.state = RawDirectionTestState.COMPLETED
            runtime.deadman_deadline = None
            runtime.failure_reason = "OPERATOR_STOP"
            self._restart_watchdog(runtime)
            return self._status(runtime)

    async def record_urdf_alignment(
        self,
        token: str,
        *,
        joint_id: str,
        matches_urdf: bool,
    ) -> RawDirectionStatus:
        session = await self._authorize_current(token)
        if not isinstance(matches_urdf, bool):
            raise RawDirectionConflictError("URDF direction observation must be explicit")
        async with self._guard:
            runtime = self._require_runtime(session.session_id)
            observation = runtime.last_observation
            if observation is None or observation.joint_id != joint_id:
                raise RawDirectionConflictError(
                    "Test this joint once before recording its URDF direction observation"
                )
            tested_directions = {
                direction
                for observed_joint, direction in runtime.observations_by_joint_direction
                if observed_joint == joint_id
            }
            if tested_directions != {RawDirection.RAW_MINUS, RawDirection.RAW_PLUS}:
                raise RawDirectionConflictError(
                    "Test both Raw - and Raw + before recording the URDF direction observation"
                )
            runtime.urdf_matches_by_joint[joint_id] = matches_urdf
            runtime.draft_confirmed_at = None
            return self._status(runtime)

    async def confirm_calibration_draft(
        self,
        token: str,
        *,
        confirmation_text: str,
    ) -> RawDirectionStatus:
        session = await self._authorize_current(token)
        if confirmation_text != RAW_DIRECTION_DRAFT_CONFIRMATION:
            raise RawDirectionConflictError("Raw direction draft confirmation text mismatch")
        async with self._guard:
            runtime = self._require_runtime(session.session_id)
            draft = self._calibration_draft(runtime)
            if not draft.complete_for_review:
                raise RawDirectionConflictError(
                    "All enabled joints require both Raw directions and one URDF observation"
                )
            runtime.draft_confirmed_at = self._clock.now()
            return self._status(runtime)

    async def status(self) -> RawDirectionStatus:
        async with self._guard:
            return self._idle_status() if self._runtime is None else self._status(self._runtime)

    async def shutdown(self) -> None:
        """Request a hold, disable adapter torque, and release the exact port."""

        try:
            await self.priority_stop()
        finally:
            async with self._guard:
                runtime = self._runtime
                if runtime is not None and runtime.watchdog is not None:
                    runtime.watchdog.cancel()
            await self._bus.close()

    def _context(self) -> RealHardwareContext:
        return self._context_provider()

    async def _authorize(self, token: str) -> OperatorSessionEvidence:
        return await self._sessions.authorize(
            token,
            self._context(),
            purpose=RealHardwareAuthorizationPurpose.RAW_DIRECTION_TEST,
        )

    async def _authorize_current(self, token: str) -> OperatorSessionEvidence:
        session = await self._authorize(token)
        async with self._guard:
            self._require_runtime(session.session_id)
        return session

    def _joint_servo_id(self, joint_id: str) -> int:
        profile = self._context().profile
        if profile is None or joint_id not in profile.enabled_joints:
            raise RawDirectionEnvelopeError("Joint is outside the enabled Profile")
        servo_id = profile.definitions_by_id[joint_id].servo_id
        if servo_id is None or servo_id not in self._allowed_servo_ids:
            raise RawDirectionEnvelopeError("Joint Servo is outside the explicit allowlist")
        return servo_id

    def _require_fresh(self, captured_at: datetime) -> None:
        age = (self._clock.now() - captured_at).total_seconds()
        if age < 0 or age > self._readback_max_age_s:
            raise RawDirectionConflictError("Raw direction readback is stale")

    def _require_runtime(self, session_id: UUID) -> _Runtime:
        runtime = self._runtime
        if runtime is None or runtime.session.session_id != session_id:
            raise RawDirectionSessionError("Raw direction session is not bound")
        return runtime

    def _require_alive(self, runtime: _Runtime) -> None:
        if self._clock.monotonic() >= runtime.session_deadline:
            runtime.state = RawDirectionTestState.EXPIRED
            runtime.failure_reason = "SESSION_EXPIRED"
            raise RawDirectionSessionError("Raw direction session expired")

    def _restart_watchdog(self, runtime: _Runtime) -> None:
        runtime.generation += 1
        if runtime.watchdog is not None:
            runtime.watchdog.cancel()
        generation = runtime.generation
        runtime.watchdog = asyncio.create_task(
            self._watchdog(runtime.session.session_id, generation)
        )

    async def _watchdog(self, session_id: UUID, generation: int) -> None:
        try:
            await self._clock.sleep(0.1)
            async with self._guard:
                runtime = self._runtime
                if runtime is None or runtime.session.session_id != session_id:
                    return
                if runtime.generation != generation:
                    return
                expired = self._clock.monotonic() >= runtime.session_deadline
                deadman_expired = (
                    runtime.deadman_deadline is not None
                    and self._clock.monotonic() >= runtime.deadman_deadline
                )
                if not expired and not deadman_expired:
                    self._restart_watchdog(runtime)
                    return
                joint_id = runtime.active_joint_id
                runtime.state = RawDirectionTestState.EXPIRED
                runtime.deadman_deadline = None
                runtime.failure_reason = "SESSION_EXPIRED" if expired else "DEADMAN_EXPIRED"
            if joint_id is not None:
                await self._bus.stop_or_hold(self._joint_servo_id(joint_id))
        except asyncio.CancelledError:
            return

    def _calibration_draft(self, runtime: _Runtime) -> RawDirectionCalibrationDraft:
        profile = self._context().profile
        if profile is None:
            raise RawDirectionSessionError("Raw direction Profile disappeared")
        joints: list[RawDirectionJointDraft] = []
        for joint_id in profile.enabled_joints:
            definition = profile.definitions_by_id[joint_id]
            if definition.servo_id is None or definition.raw_bounds is None:
                raise RawDirectionSessionError("Raw direction Profile mapping is incomplete")
            matches = runtime.urdf_matches_by_joint.get(joint_id)
            resolved = None
            if matches is not None:
                resolved = definition.direction if matches else -definition.direction
            joints.append(
                RawDirectionJointDraft(
                    joint_id=joint_id,
                    servo_id=definition.servo_id,
                    home_present_raw=runtime.zero_snapshot.raw_by_joint[joint_id],
                    profile_direction_candidate=definition.direction,
                    matches_urdf=matches,
                    resolved_calibration_direction=resolved,
                    phase_candidate=LEGACY_V2_MULTI_TURN_PHASE_CANDIDATE,
                    raw_bounds_candidate=definition.raw_bounds,
                )
            )
        return RawDirectionCalibrationDraft(
            robot_unit_id=runtime.session.robot_unit_id,
            profile_fingerprint=profile.fingerprint,
            source=profile.source,
            source_revision=profile.source_revision,
            complete_for_review=all(
                item.resolved_calibration_direction is not None for item in joints
            ),
            confirmed_for_review=runtime.draft_confirmed_at is not None,
            confirmed_at=runtime.draft_confirmed_at,
            joints=tuple(joints),
        )

    def _status(self, runtime: _Runtime) -> RawDirectionStatus:
        return RawDirectionStatus(
            state=runtime.state,
            session_id=runtime.session.session_id,
            active_joint_id=runtime.active_joint_id,
            command_count=runtime.command_count,
            session_expires_at=runtime.session.expires_at,
            deadman_expires_at=None,
            zero_snapshot=runtime.zero_snapshot,
            last_observation=runtime.last_observation,
            observations=tuple(runtime.observations_by_joint_direction.values()),
            calibration_draft=self._calibration_draft(runtime),
            failure_reason=runtime.failure_reason,
        )

    @staticmethod
    def _idle_status() -> RawDirectionStatus:
        return RawDirectionStatus(
            state=RawDirectionTestState.IDLE,
            session_id=None,
            active_joint_id=None,
            command_count=0,
            session_expires_at=None,
            deadman_expires_at=None,
            zero_snapshot=None,
            last_observation=None,
            observations=(),
            calibration_draft=None,
            failure_reason=None,
        )


__all__ = ["RawDirectionStatus", "RawDirectionTestService"]
