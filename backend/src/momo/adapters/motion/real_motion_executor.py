"""Bounded Real trajectory execution over the narrow explicit-ID ServoBus."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from collections.abc import Awaitable, Mapping
from contextlib import suppress
from typing import Protocol, TypeVar
from uuid import UUID, uuid4

from momo.domain.calibration import CalibrationDocument
from momo.domain.errors import HardwareMappingError
from momo.domain.hardware_mapping import goal_raw_to_logical, logical_to_goal_raw
from momo.domain.real_hardware import (
    RealHardwareAuthorizationPurpose,
    RealStopOutcome,
    RealStopResult,
    ServoWriteResult,
    calibration_fingerprint,
)
from momo.domain.real_motion import (
    RealExecutionAuthorization,
    RealExecutionContext,
    RealMotionAuditEvent,
    RealMotionAuditKind,
    RealMotionError,
    RealMotionFaultCode,
    RealMotionState,
    RealMotionStatus,
)
from momo.domain.robot import JointState, RobotProfile
from momo.domain.trajectory import PreparedTrajectory, TrajectorySegmentKind
from momo.ports.clock import Clock
from momo.ports.servo_bus import ServoBus

Result = TypeVar("Result")


class RealExecutionContextProvider(Protocol):
    """Resolve current safety/artifact evidence without carrying credentials."""

    async def current_real_execution_context(self) -> RealExecutionContext: ...


class RealMotionObserver(Protocol):
    """Optional application observer; it receives no raw token or device path."""

    async def apply_real_readback(self, execution_id: UUID, state: JointState) -> int: ...

    async def record_real_motion_audit(self, event: RealMotionAuditEvent) -> None: ...


class _ExecutionFault(RuntimeError):
    def __init__(self, code: RealMotionFaultCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class RealMotionExecutor:
    """Execute the exact prepared samples without compiling or opening hardware.

    Connection lifecycle belongs to the authorized hardware adapter/service. This
    executor never scans IDs and never exposes SDK, register, torque, or mode APIs.
    """

    def __init__(
        self,
        servo_bus: ServoBus,
        clock: Clock,
        *,
        robot_id: str,
        profile: RobotProfile,
        calibration: CalibrationDocument,
        kinematics_fingerprint: str,
        context_provider: RealExecutionContextProvider,
        observer: RealMotionObserver,
        divergence_tolerance_raw: int = 8,
        following_lag_s: float = 0.4,
        final_settle_timeout_s: float = 1.5,
        continuity_tolerance: float = 1e-6,
        bus_operation_timeout_s: float = 1.0,
        history_limit: int = 256,
        audit_history_limit: int = 512,
    ) -> None:
        if not robot_id or len(robot_id) > 64:
            raise ValueError("robot_id must be a non-empty bounded identifier")
        if len(kinematics_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in kinematics_fingerprint
        ):
            raise ValueError("kinematics_fingerprint must be lowercase SHA-256")
        if (
            isinstance(divergence_tolerance_raw, bool)
            or not isinstance(divergence_tolerance_raw, int)
            or not 0 <= divergence_tolerance_raw <= 4096
        ):
            raise ValueError("divergence_tolerance_raw must be between 0 and 4096")
        if not 0.0 <= continuity_tolerance <= 1.0:
            raise ValueError("continuity_tolerance must be between 0 and 1 domain unit")
        if not 0.04 <= following_lag_s <= 2.0:
            raise ValueError("following_lag_s must be between 0.04 and 2 seconds")
        if not 0.1 <= final_settle_timeout_s <= 10.0:
            raise ValueError("final_settle_timeout_s must be between 0.1 and 10 seconds")
        if not 0.01 <= bus_operation_timeout_s <= 10.0:
            raise ValueError("bus_operation_timeout_s must be between 0.01 and 10 seconds")
        self._validate_calibration(profile, calibration)

        self.servo_bus = servo_bus
        self.clock = clock
        self.robot_id = robot_id
        self.profile = profile
        self.calibration = calibration
        self.kinematics_fingerprint = kinematics_fingerprint
        self.context_provider = context_provider
        self.observer = observer
        self.divergence_tolerance_raw = divergence_tolerance_raw
        self.following_lag_s = float(following_lag_s)
        self.final_settle_timeout_s = float(final_settle_timeout_s)
        self.continuity_tolerance = float(continuity_tolerance)
        self.bus_operation_timeout_s = float(bus_operation_timeout_s)
        self.history_limit = max(8, int(history_limit))
        self._audit_events: deque[RealMotionAuditEvent] = deque(
            maxlen=max(16, int(audit_history_limit))
        )
        self._audit_sequence = 0
        self._profile_fingerprint = profile.fingerprint
        self._calibration_fingerprint = calibration_fingerprint(calibration)
        self._servo_ids = tuple(
            self._required_servo_id(joint_id) for joint_id in profile.enabled_joints
        )
        self._guard = asyncio.Lock()
        self._active_execution_id: UUID | None = None
        self._active_task: asyncio.Task[None] | None = None
        self._cancel_event: asyncio.Event | None = None
        self._active_authorization: RealExecutionAuthorization | None = None
        self._terminal_future: asyncio.Future[None] | None = None
        self._statuses: OrderedDict[UUID, RealMotionStatus] = OrderedDict()
        self._latest_execution_id: UUID | None = None
        self._closed = False

    @property
    def active_execution_id(self) -> UUID | None:
        task = self._active_task
        if self._active_execution_id is None or task is None or task.done():
            return None
        return self._active_execution_id

    def get_status(self, execution_id: UUID) -> RealMotionStatus | None:
        return self._statuses.get(execution_id)

    def active_status(self) -> RealMotionStatus | None:
        execution_id = self.active_execution_id
        return self._statuses.get(execution_id) if execution_id is not None else None

    def latest_status(self) -> RealMotionStatus | None:
        execution_id = self._latest_execution_id
        return self._statuses.get(execution_id) if execution_id is not None else None

    def audit_events(self, execution_id: UUID | None = None) -> tuple[RealMotionAuditEvent, ...]:
        if execution_id is None:
            return tuple(self._audit_events)
        return tuple(event for event in self._audit_events if event.execution_id == execution_id)

    async def submit(
        self,
        prepared: PreparedTrajectory,
        *,
        expected_digest: str,
        authorization: RealExecutionAuthorization,
        execution_purpose: RealHardwareAuthorizationPurpose,
    ) -> RealMotionStatus:
        """Accept only the exact immutable prepared plan and its caller-held digest."""

        self._require_authorization(authorization, execution_purpose)
        raw_samples = self._validate_and_map_prepared(
            prepared,
            expected_digest,
            execution_purpose,
        )
        async with self._guard:
            if self._closed:
                raise RealMotionError("REAL_EXECUTOR_CLOSED", "Real motion executor is closed")
            if self.active_execution_id is not None:
                raise RealMotionError(
                    "REAL_MOTION_CONFLICT",
                    "Another Real trajectory execution is active",
                    details={"active_execution_id": str(self.active_execution_id)},
                )
            # Authorization may have expired while the complete plan was mapped.
            self._require_authorization(authorization, execution_purpose)
            execution_id = uuid4()
            now = self.clock.now()
            status = RealMotionStatus(
                execution_id=execution_id,
                authorization_session_id=authorization.session_id,
                robot_id=self.robot_id,
                variant=self.profile.variant,
                profile_fingerprint=self._profile_fingerprint,
                calibration_fingerprint=self._calibration_fingerprint,
                trajectory_digest=prepared.plan.digest.sha256,
                execution_purpose=execution_purpose,
                state=RealMotionState.ACCEPTED,
                progress=0.0,
                sample_count=len(prepared.plan.samples),
                expected_state_sequence=prepared.plan.start_state_sequence,
                hardware_accessed=False,
                safety_state_known=False,
                accepted_at=now,
                updated_at=now,
            )
            self._remember(status)
            cancel_event = asyncio.Event()
            self._active_execution_id = execution_id
            self._cancel_event = cancel_event
            self._active_authorization = authorization
            self._terminal_future = asyncio.get_running_loop().create_future()
            await self._emit(
                status,
                RealMotionAuditKind.ACCEPTED,
                requested_ids=self._servo_ids,
                safety_state_known=False,
                detail="Exact PreparedTrajectory accepted; hardware not yet accessed",
            )
            self._active_task = asyncio.create_task(
                self._run(
                    execution_id,
                    prepared,
                    raw_samples,
                    authorization,
                    execution_purpose,
                    cancel_event,
                ),
                name=f"real-motion-{execution_id}",
            )
            return status

    async def wait(self, execution_id: UUID) -> RealMotionStatus:
        async with self._guard:
            status = self._statuses.get(execution_id)
            if status is None:
                raise RealMotionError(
                    "REAL_EXECUTION_NOT_FOUND",
                    "Real trajectory execution was not found",
                )
            task = self._active_task if self._active_execution_id == execution_id else None
            terminal_future = (
                self._terminal_future if self._active_execution_id == execution_id else None
            )
        if terminal_future is not None:
            with suppress(asyncio.CancelledError):
                await asyncio.shield(terminal_future)
        elif task is not None:
            with suppress(asyncio.CancelledError):
                await asyncio.shield(task)
        resolved = self._statuses.get(execution_id)
        assert resolved is not None
        return resolved

    async def cancel_active(self) -> RealMotionStatus | None:
        async with self._guard:
            execution_id = self.active_execution_id
            task = self._active_task
            cancel_event = self._cancel_event
            terminal_future = self._terminal_future
            if execution_id is None or task is None or cancel_event is None:
                return None
            if not cancel_event.is_set():
                cancel_event.set()
                task.cancel()
        if terminal_future is not None:
            with suppress(asyncio.CancelledError):
                await asyncio.shield(terminal_future)
        else:
            with suppress(asyncio.CancelledError):
                await asyncio.shield(task)
        return self._statuses.get(execution_id)

    async def cancel(self, execution_id: UUID) -> RealMotionStatus | None:
        if self.active_execution_id != execution_id:
            return self._statuses.get(execution_id)
        return await self.cancel_active()

    async def stop(self) -> RealStopOutcome:
        """Request a typed software Stop; never claim or represent a physical E-stop."""

        status = await self.cancel_active()
        if status is not None and status.stop_outcome is not None:
            return status.stop_outcome
        return await self._call_stop()

    async def shutdown(self) -> None:
        async with self._guard:
            self._closed = True
        await self.cancel_active()

    async def _run(
        self,
        execution_id: UUID,
        prepared: PreparedTrajectory,
        raw_samples: tuple[dict[int, int], ...],
        authorization: RealExecutionAuthorization,
        execution_purpose: RealHardwareAuthorizationPurpose,
        cancel_event: asyncio.Event,
    ) -> None:
        try:
            self._set_running(execution_id)
            start = self.clock.monotonic()
            samples = prepared.plan.samples
            index = 0
            expected_state_sequence = prepared.plan.start_state_sequence
            expected_positions = dict(samples[0].positions)
            recent_goals: deque[tuple[float, dict[int, int]]] = deque()
            final_aligned = False
            first_write = True
            while index < len(samples):
                sample = samples[index]
                await self._sleep_until(
                    start + sample.time_s,
                    authorization,
                    cancel_event,
                )
                if cancel_event.is_set():
                    raise asyncio.CancelledError
                if not authorization.active(self.clock.now()):
                    raise _ExecutionFault(
                        RealMotionFaultCode.AUTHORIZATION_EXPIRED,
                        "Operator authorization expired during execution",
                    )

                # Never replay every missed sample in a burst. Jump to the most
                # recent due sample while preserving the exact prepared values.
                elapsed = max(0.0, self.clock.monotonic() - start)
                while index + 1 < len(samples) and samples[index + 1].time_s <= elapsed:
                    index += 1
                    sample = samples[index]
                await self._validate_current_context(
                    prepared,
                    authorization,
                    execution_purpose,
                    expected_state_sequence=expected_state_sequence,
                    expected_positions=expected_positions,
                    first_write=first_write,
                )
                goals = raw_samples[index]
                recent_goals.append((sample.time_s, goals))
                while (
                    len(recent_goals) > 1
                    and sample.time_s - recent_goals[0][0] > self.following_lag_s
                ):
                    recent_goals.popleft()
                (
                    expected_state_sequence,
                    expected_positions,
                    final_aligned,
                ) = await self._write_and_readback(
                    execution_id,
                    prepared,
                    index,
                    goals,
                    authorization,
                    tuple(item[1] for item in recent_goals),
                )
                first_write = False
                index += 1
            if not final_aligned:
                expected_state_sequence, expected_positions = await self._settle_final_goal(
                    execution_id,
                    prepared,
                    len(samples) - 1,
                    raw_samples[-1],
                    authorization,
                )
            self._set_completed(execution_id)
            await self._emit(
                self._statuses[execution_id],
                RealMotionAuditKind.TERMINAL,
                requested_ids=self._servo_ids,
                affected_ids=self._servo_ids,
                safety_state_known=True,
                detail="Exact prepared trajectory completed with bounded readback",
            )
        except asyncio.CancelledError:
            cancel_event.set()
            await self._cancel_and_stop(execution_id)
        except _ExecutionFault as fault:
            cancel_event.set()
            await self._fault_and_stop(execution_id, fault.code, fault.detail)
        except Exception as error:
            cancel_event.set()
            await self._fault_and_stop(
                execution_id,
                RealMotionFaultCode.BUS_FAULT,
                f"Unexpected execution failure: {type(error).__name__}",
            )
        finally:
            self._ensure_terminal(execution_id)
            await self._clear_active(execution_id)

    async def _write_and_readback(
        self,
        execution_id: UUID,
        prepared: PreparedTrajectory,
        sample_index: int,
        goals: dict[int, int],
        authorization: RealExecutionAuthorization,
        acceptable_goals: tuple[dict[int, int], ...],
    ) -> tuple[int, dict[str, float], bool]:
        if not authorization.active(self.clock.now()):
            raise _ExecutionFault(
                RealMotionFaultCode.AUTHORIZATION_EXPIRED,
                "Operator authorization expired before a ServoBus write",
            )
        self._set_goal_attempt(execution_id, sample_index, goals)
        try:
            result = await self._bounded_bus_call(
                self.servo_bus.write_goal_positions(goals),
                operation="goal write",
            )
        except _ExecutionFault:
            raise
        except Exception as error:
            raise _ExecutionFault(
                RealMotionFaultCode.BUS_FAULT,
                f"ServoBus write failed: {type(error).__name__}",
            ) from error
        self._validate_write_result(result)
        await self._emit(
            self._statuses[execution_id],
            RealMotionAuditKind.WRITE,
            sample_index=sample_index,
            requested_ids=result.requested_ids,
            affected_ids=result.written_ids,
            safety_state_known=result.safety_state_known,
            detail=result.detail or "Bounded explicit-ID goal write completed",
        )
        next_state_sequence, logical_positions, actual_raw = await self._read_and_publish(
            execution_id,
            prepared,
            sample_index,
            goals,
            authorization,
        )
        outside_following_window = {
            servo_id: actual_raw[servo_id]
            for servo_id in self._servo_ids
            if not (
                min(item[servo_id] for item in acceptable_goals)
                - self.divergence_tolerance_raw
                <= actual_raw[servo_id]
                <= max(item[servo_id] for item in acceptable_goals)
                + self.divergence_tolerance_raw
            )
        }
        if outside_following_window:
            raise _ExecutionFault(
                RealMotionFaultCode.READBACK_DIVERGENCE,
                "Readback fell outside the bounded trajectory following window",
            )
        final_aligned = all(
            abs(actual_raw[servo_id] - goals[servo_id]) <= self.divergence_tolerance_raw
            for servo_id in self._servo_ids
        )
        return next_state_sequence, logical_positions, final_aligned

    async def _read_and_publish(
        self,
        execution_id: UUID,
        prepared: PreparedTrajectory,
        sample_index: int,
        goals: dict[int, int],
        authorization: RealExecutionAuthorization,
    ) -> tuple[int, dict[str, float], dict[int, int]]:
        if not authorization.active(self.clock.now()):
            raise _ExecutionFault(
                RealMotionFaultCode.AUTHORIZATION_EXPIRED,
                "Operator authorization expired before ServoBus readback",
            )
        try:
            readback = await self._bounded_bus_call(
                self.servo_bus.read_present_positions(self._servo_ids),
                operation="position readback",
            )
        except _ExecutionFault:
            raise
        except Exception as error:
            raise _ExecutionFault(
                RealMotionFaultCode.BUS_FAULT,
                f"ServoBus readback failed: {type(error).__name__}",
            ) from error
        if not authorization.active(self.clock.now()):
            raise _ExecutionFault(
                RealMotionFaultCode.AUTHORIZATION_EXPIRED,
                "Operator authorization expired during ServoBus readback",
            )
        if set(readback) != set(self._servo_ids):
            raise _ExecutionFault(
                RealMotionFaultCode.READBACK_INVALID,
                "Readback IDs did not exactly match the explicit enabled Servo IDs",
            )

        actual_raw: dict[int, int] = {}
        logical_positions: dict[str, float] = {}
        try:
            for joint_id, servo_id in zip(
                self.profile.enabled_joints,
                self._servo_ids,
                strict=True,
            ):
                raw = readback[servo_id]
                if isinstance(raw, bool) or not isinstance(raw, int):
                    raise HardwareMappingError("readback raw must be an integer")
                actual_raw[servo_id] = raw
                logical_positions[joint_id] = goal_raw_to_logical(
                    joint_id,
                    raw,
                    self.profile,
                    self.calibration.joints_by_id[joint_id],
                )
        except (HardwareMappingError, KeyError, ValueError) as error:
            raise _ExecutionFault(
                RealMotionFaultCode.READBACK_INVALID,
                f"Readback could not be mapped safely: {type(error).__name__}",
            ) from error

        self._set_readback(
            execution_id,
            prepared,
            sample_index,
            goals,
            actual_raw,
            logical_positions,
        )
        state = JointState(
            positions=logical_positions,
            units={
                joint_id: self.profile.definitions_by_id[joint_id].domain_unit
                for joint_id in self.profile.enabled_joints
            },
        ).validate_against(self.profile)
        try:
            next_state_sequence = await self.observer.apply_real_readback(
                execution_id,
                state,
            )
            current_expected_sequence = self._statuses[execution_id].expected_state_sequence
            if (
                isinstance(next_state_sequence, bool)
                or not isinstance(next_state_sequence, int)
                or next_state_sequence <= current_expected_sequence
            ):
                raise ValueError("observer returned a non-increasing state sequence")
        except Exception as error:
            raise _ExecutionFault(
                RealMotionFaultCode.STATE_UPDATE_FAILED,
                f"Readback state update failed: {type(error).__name__}",
            ) from error
        await self._emit(
            self._statuses[execution_id],
            RealMotionAuditKind.READBACK,
            sample_index=sample_index,
            requested_ids=self._servo_ids,
            affected_ids=self._servo_ids,
            safety_state_known=True,
            detail="Explicit-ID present-position readback mapped to domain state",
        )
        self._replace_status(
            execution_id,
            expected_state_sequence=next_state_sequence,
            updated_at=self.clock.now(),
        )
        return next_state_sequence, logical_positions, actual_raw

    async def _settle_final_goal(
        self,
        execution_id: UUID,
        prepared: PreparedTrajectory,
        sample_index: int,
        goals: dict[int, int],
        authorization: RealExecutionAuthorization,
    ) -> tuple[int, dict[str, float]]:
        deadline = self.clock.monotonic() + self.final_settle_timeout_s
        readback_interval_s = 1.0 / prepared.plan.sample_rate_hz
        while self.clock.monotonic() < deadline:
            await self.clock.sleep(
                min(readback_interval_s, max(0.0, deadline - self.clock.monotonic()))
            )
            next_state_sequence, logical_positions, actual_raw = await self._read_and_publish(
                execution_id,
                prepared,
                sample_index,
                goals,
                authorization,
            )
            if all(
                abs(actual_raw[servo_id] - goals[servo_id])
                <= self.divergence_tolerance_raw
                for servo_id in self._servo_ids
            ):
                return next_state_sequence, logical_positions
        raise _ExecutionFault(
            RealMotionFaultCode.READBACK_DIVERGENCE,
            "Final goal did not settle within the bounded following timeout",
        )

    async def _validate_current_context(
        self,
        prepared: PreparedTrajectory,
        authorization: RealExecutionAuthorization,
        execution_purpose: RealHardwareAuthorizationPurpose,
        *,
        expected_state_sequence: int,
        expected_positions: Mapping[str, float],
        first_write: bool,
    ) -> None:
        try:
            self._require_authorization(authorization, execution_purpose)
        except RealMotionError as error:
            code = (
                RealMotionFaultCode.AUTHORIZATION_EXPIRED
                if error.code == RealMotionFaultCode.AUTHORIZATION_EXPIRED.value
                else RealMotionFaultCode.AUTHORIZATION_MISMATCH
            )
            raise _ExecutionFault(code, str(error)) from error
        try:
            supplied_context = await self.context_provider.current_real_execution_context()
            context = RealExecutionContext.model_validate(supplied_context)
        except Exception as error:
            raise _ExecutionFault(
                RealMotionFaultCode.EXECUTION_CONTEXT_UNAVAILABLE,
                f"Current execution context unavailable: {type(error).__name__}",
            ) from error
        if not context.connected:
            raise _ExecutionFault(
                RealMotionFaultCode.ROBOT_DISCONNECTED,
                "Robot disconnected before a Real ServoBus write",
            )
        if not context.state_fresh or context.observed_at > self.clock.now():
            raise _ExecutionFault(
                RealMotionFaultCode.ROBOT_STATE_STALE,
                "Robot state is not fresh before a Real ServoBus write",
            )
        if not context.stop_capable:
            raise _ExecutionFault(
                RealMotionFaultCode.STOP_CAPABILITY_UNAVAILABLE,
                "Verified software Stop capability is unavailable",
            )
        plan = prepared.plan
        if (
            context.robot_id != self.robot_id
            or context.variant is not self.profile.variant
            or context.motion_id != plan.motion_id
            or context.motion_revision != plan.motion_revision
            or context.trajectory_digest != plan.digest.sha256
            or context.profile_fingerprint != self._profile_fingerprint
            or context.calibration_fingerprint != self._calibration_fingerprint
            or context.kinematics_fingerprint != self.kinematics_fingerprint
        ):
            raise _ExecutionFault(
                RealMotionFaultCode.MOTION_ARTIFACT_CHANGED,
                "Mutable motion or artifact identity changed after preflight",
            )
        if context.state_sequence != expected_state_sequence:
            raise _ExecutionFault(
                RealMotionFaultCode.STATE_SEQUENCE_CHANGED,
                "Robot state sequence changed outside this execution",
            )
        try:
            current = context.joint_state.validate_against(self.profile)
        except ValueError as error:
            raise _ExecutionFault(
                RealMotionFaultCode.ROBOT_STATE_STALE,
                "Current logical joint state violates the reviewed profile",
            ) from error
        if set(expected_positions) != set(self.profile.enabled_joints):
            raise _ExecutionFault(
                RealMotionFaultCode.TRAJECTORY_SAMPLE_INVALID,
                "Expected continuity state does not match explicit enabled_joints",
            )
        discontinuous = tuple(
            joint_id
            for joint_id in self.profile.enabled_joints
            if abs(current.positions[joint_id] - expected_positions[joint_id])
            > self.continuity_tolerance
        )
        if discontinuous:
            raise _ExecutionFault(
                (
                    RealMotionFaultCode.FIRST_SAMPLE_DISCONTINUITY
                    if first_write
                    else RealMotionFaultCode.CURRENT_STATE_CHANGED
                ),
                "Current logical state is not continuous with the prepared execution",
            )

    def _validate_write_result(self, result: ServoWriteResult) -> None:
        if result.requested_ids != self._servo_ids:
            raise _ExecutionFault(
                RealMotionFaultCode.PARTIAL_WRITE,
                "ServoBus write result did not preserve the exact requested ID order",
            )
        if not result.connected:
            raise _ExecutionFault(
                RealMotionFaultCode.BUS_DISCONNECTED,
                "ServoBus disconnected during goal write",
            )
        if not result.safety_state_known:
            raise _ExecutionFault(
                RealMotionFaultCode.SAFETY_STATE_UNCERTAIN,
                "ServoBus reported an unknown safety state",
            )
        if not result.complete or result.failed_ids or result.written_ids != self._servo_ids:
            raise _ExecutionFault(
                RealMotionFaultCode.PARTIAL_WRITE,
                "ServoBus goal write was partial",
            )

    async def _sleep_until(
        self,
        deadline: float,
        authorization: RealExecutionAuthorization,
        cancel_event: asyncio.Event,
    ) -> None:
        while True:
            if cancel_event.is_set():
                raise asyncio.CancelledError
            now = self.clock.now()
            if not authorization.active(now):
                raise _ExecutionFault(
                    RealMotionFaultCode.AUTHORIZATION_EXPIRED,
                    "Operator authorization expired while awaiting a sample deadline",
                )
            remaining = deadline - self.clock.monotonic()
            if remaining <= 0.0:
                return
            until_expiry = (authorization.expires_at - now).total_seconds()
            await self.clock.sleep(max(0.0, min(remaining, until_expiry)))

    async def _cancel_and_stop(self, execution_id: UUID) -> None:
        outcome = await self._stop_for_execution(execution_id)
        if outcome.result is RealStopResult.STOPPED_AND_VERIFIED:
            self._set_cancelled(execution_id, outcome)
            terminal = self._statuses[execution_id]
            detail = "Cancellation completed with a verified software Stop outcome"
        else:
            code = (
                RealMotionFaultCode.SAFETY_STATE_UNCERTAIN
                if not outcome.safety_state_known
                else RealMotionFaultCode.STOP_NOT_VERIFIED
            )
            self._set_faulted(
                execution_id,
                code,
                "Cancellation requested, but software Stop was not verified",
                outcome,
            )
            terminal = self._statuses[execution_id]
            detail = "Cancellation ended without a verified physical stop state"
        await self._emit(
            terminal,
            RealMotionAuditKind.TERMINAL,
            requested_ids=outcome.requested_ids,
            affected_ids=outcome.affected_ids,
            safety_state_known=outcome.safety_state_known,
            detail=detail,
        )

    async def _fault_and_stop(
        self,
        execution_id: UUID,
        code: RealMotionFaultCode,
        detail: str,
    ) -> None:
        outcome = await self._stop_for_execution(execution_id)
        self._set_faulted(execution_id, code, detail, outcome)
        await self._emit(
            self._statuses[execution_id],
            RealMotionAuditKind.TERMINAL,
            requested_ids=outcome.requested_ids,
            affected_ids=outcome.affected_ids,
            safety_state_known=outcome.safety_state_known,
            detail=f"{detail}; Stop={outcome.result.value}",
        )

    async def _stop_for_execution(self, execution_id: UUID) -> RealStopOutcome:
        self._mark_hardware_attempt(execution_id)
        outcome = await self._call_stop()
        await self._emit(
            self._statuses[execution_id],
            RealMotionAuditKind.STOP,
            requested_ids=outcome.requested_ids,
            affected_ids=outcome.affected_ids,
            safety_state_known=outcome.safety_state_known,
            detail=outcome.detail,
        )
        return outcome

    async def _call_stop(self) -> RealStopOutcome:
        try:
            outcome = await asyncio.wait_for(
                self.servo_bus.stop_or_hold(self._servo_ids),
                timeout=self.bus_operation_timeout_s,
            )
            if outcome.requested_ids != self._servo_ids:
                raise ValueError("Stop outcome IDs did not match the explicit allowlist")
            return outcome
        except TimeoutError:
            return RealStopOutcome(
                result=RealStopResult.SAFETY_STATE_UNCERTAIN,
                requested_ids=self._servo_ids,
                affected_ids=(),
                connected=False,
                safety_state_known=False,
                detail="Software Stop exceeded its bounded operation deadline",
            )
        except Exception as error:
            return RealStopOutcome(
                result=RealStopResult.FAILED,
                requested_ids=self._servo_ids,
                affected_ids=(),
                connected=False,
                safety_state_known=False,
                detail=f"Software Stop failed: {type(error).__name__}",
            )

    async def _bounded_bus_call(
        self,
        operation_awaitable: Awaitable[Result],
        *,
        operation: str,
    ) -> Result:
        try:
            return await asyncio.wait_for(
                operation_awaitable,
                timeout=self.bus_operation_timeout_s,
            )
        except TimeoutError as error:
            raise _ExecutionFault(
                RealMotionFaultCode.SAFETY_STATE_UNCERTAIN,
                f"ServoBus {operation} exceeded its bounded deadline",
            ) from error

    def _validate_and_map_prepared(
        self,
        prepared: PreparedTrajectory,
        expected_digest: str,
        execution_purpose: RealHardwareAuthorizationPurpose,
    ) -> tuple[dict[int, int], ...]:
        plan = prepared.plan
        if (
            expected_digest != plan.digest.sha256
            or plan.computed_sha256 != plan.digest.sha256
            or prepared.preflight.digest != plan.digest
        ):
            raise RealMotionError(
                RealMotionFaultCode.PREPARED_TRAJECTORY_CHANGED.value,
                "PreparedTrajectory or caller-held digest changed after preflight",
            )
        if (
            plan.robot_variant is not self.profile.variant
            or plan.profile_fingerprint != self._profile_fingerprint
            or plan.kinematics_fingerprint != self.kinematics_fingerprint
        ):
            raise RealMotionError(
                RealMotionFaultCode.TRAJECTORY_BINDING_MISMATCH.value,
                "PreparedTrajectory is not bound to the configured Real artifacts",
            )
        segment_kinds = tuple(segment.kind for segment in plan.segments)
        if execution_purpose is RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION:
            compatible = TrajectorySegmentKind.JOINT in segment_kinds and all(
                kind in {TrajectorySegmentKind.JOINT, TrajectorySegmentKind.HOLD}
                for kind in segment_kinds
            )
        elif execution_purpose is RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION:
            compatible = TrajectorySegmentKind.CARTESIAN_LINEAR in segment_kinds and all(
                kind
                in {
                    TrajectorySegmentKind.CARTESIAN_LINEAR,
                    TrajectorySegmentKind.HOLD,
                }
                for kind in segment_kinds
            )
        elif execution_purpose is RealHardwareAuthorizationPurpose.REAL_PLAYBACK:
            compatible = all(
                kind
                in {
                    TrajectorySegmentKind.JOINT,
                    TrajectorySegmentKind.CARTESIAN_LINEAR,
                    TrajectorySegmentKind.HOLD,
                }
                for kind in segment_kinds
            )
        else:
            compatible = False
        if not compatible:
            raise RealMotionError(
                RealMotionFaultCode.AUTHORIZATION_MISMATCH.value,
                "Execution purpose does not match validated trajectory segment metadata",
            )
        expected_joints = set(self.profile.enabled_joints)
        raw_samples: list[dict[int, int]] = []
        try:
            for sample in plan.samples:
                if set(sample.positions) != expected_joints or set(sample.units) != expected_joints:
                    raise HardwareMappingError(
                        "sample joints must exactly match explicit enabled_joints"
                    )
                goals: dict[int, int] = {}
                for joint_id in self.profile.enabled_joints:
                    definition = self.profile.definitions_by_id[joint_id]
                    if sample.units[joint_id] is not definition.domain_unit:
                        raise HardwareMappingError("sample domain unit mismatch")
                    logical_value = sample.positions[joint_id]
                    if not definition.minimum <= logical_value <= definition.maximum:
                        raise HardwareMappingError(
                            "sample logical value exceeds reviewed profile limits"
                        )
                    goal = logical_to_goal_raw(
                        joint_id,
                        logical_value,
                        self.profile,
                        self.calibration.joints_by_id[joint_id],
                    )
                    goals[self._required_servo_id(joint_id)] = goal
                if tuple(goals) != self._servo_ids:
                    raise HardwareMappingError("sample Servo IDs changed from explicit order")
                raw_samples.append(goals)
        except (HardwareMappingError, KeyError, ValueError) as error:
            raise RealMotionError(
                RealMotionFaultCode.RAW_MAPPING_INVALID.value,
                "Prepared trajectory cannot be mapped within reviewed raw bounds",
                details={"error_type": type(error).__name__},
            ) from error
        return tuple(raw_samples)

    def _require_authorization(
        self,
        authorization: RealExecutionAuthorization,
        execution_purpose: RealHardwareAuthorizationPurpose,
    ) -> None:
        purpose_ready = {
            RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION: (
                authorization.capabilities.real_joint_motion_ready
            ),
            RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION: (
                authorization.capabilities.real_cartesian_motion_ready
            ),
            RealHardwareAuthorizationPurpose.REAL_PLAYBACK: (
                authorization.capabilities.real_playback_ready
            ),
        }.get(execution_purpose, False)
        if not authorization.active(self.clock.now()):
            raise RealMotionError(
                RealMotionFaultCode.AUTHORIZATION_EXPIRED.value,
                "Real execution authorization is not active",
            )
        if (
            authorization.robot_id != self.robot_id
            or authorization.variant is not self.profile.variant
            or authorization.profile_fingerprint != self._profile_fingerprint
            or authorization.calibration_fingerprint != self._calibration_fingerprint
            or authorization.allowed_servo_ids != self._servo_ids
            or authorization.purpose is not execution_purpose
            or not purpose_ready
        ):
            raise RealMotionError(
                RealMotionFaultCode.AUTHORIZATION_MISMATCH.value,
                "Real execution authorization does not match configured artifacts and IDs",
            )

    @staticmethod
    def _validate_calibration(
        profile: RobotProfile,
        calibration: CalibrationDocument,
    ) -> None:
        if calibration.template:
            raise ValueError("template/example calibration cannot execute Real motion")
        if (
            calibration.robot_variant is not profile.variant
            or calibration.profile_fingerprint != profile.fingerprint
            or tuple(joint.joint_id for joint in calibration.joints)
            != tuple(profile.enabled_joints)
            or not all(joint.complete for joint in calibration.joints)
        ):
            raise ValueError("calibration must exactly match the Real profile")
        for joint in calibration.joints:
            definition = profile.definitions_by_id[joint.joint_id]
            if (
                joint.servo_id != definition.servo_id
                or joint.operating_mode is not definition.operating_mode
            ):
                raise ValueError("calibration mapping must match the Real profile")
            # Home must be representable; every prepared sample is validated below.
            logical_to_goal_raw(joint.joint_id, definition.home, profile, joint)

    def _required_servo_id(self, joint_id: str) -> int:
        if joint_id not in self.profile.enabled_joints:
            raise ValueError("joint is not explicitly enabled")
        servo_id = self.profile.definitions_by_id[joint_id].servo_id
        if servo_id is None or not 1 <= servo_id <= 253:
            raise ValueError("enabled joint has no valid explicit Servo ID")
        return servo_id

    def _set_running(self, execution_id: UUID) -> None:
        now = self.clock.now()
        self._replace_status(
            execution_id,
            state=RealMotionState.RUNNING,
            started_at=now,
            updated_at=now,
        )

    def _set_goal_attempt(
        self,
        execution_id: UUID,
        sample_index: int,
        goals: Mapping[int, int],
    ) -> None:
        self._replace_status(
            execution_id,
            sample_index=sample_index,
            last_goal_raw=dict(goals),
            hardware_accessed=True,
            safety_state_known=False,
            updated_at=self.clock.now(),
        )

    def _set_readback(
        self,
        execution_id: UUID,
        prepared: PreparedTrajectory,
        sample_index: int,
        goals: Mapping[int, int],
        actual_raw: Mapping[int, int],
        logical_positions: Mapping[str, float],
    ) -> None:
        sample = prepared.plan.samples[sample_index]
        self._replace_status(
            execution_id,
            progress=min(1.0, sample.time_s / prepared.plan.duration_s),
            sample_index=sample_index,
            last_goal_raw=dict(goals),
            last_readback_raw=dict(actual_raw),
            last_logical_positions=dict(logical_positions),
            hardware_accessed=True,
            safety_state_known=True,
            updated_at=self.clock.now(),
        )

    def _set_completed(self, execution_id: UUID) -> None:
        now = self.clock.now()
        self._replace_status(
            execution_id,
            state=RealMotionState.COMPLETED,
            progress=1.0,
            safety_state_known=True,
            updated_at=now,
            finished_at=now,
        )

    def _set_cancelled(self, execution_id: UUID, outcome: RealStopOutcome) -> None:
        now = self.clock.now()
        self._replace_status(
            execution_id,
            state=RealMotionState.CANCELLED,
            safety_state_known=True,
            stop_outcome=outcome,
            updated_at=now,
            finished_at=now,
        )

    def _set_faulted(
        self,
        execution_id: UUID,
        code: RealMotionFaultCode,
        detail: str,
        outcome: RealStopOutcome,
    ) -> None:
        now = self.clock.now()
        self._replace_status(
            execution_id,
            state=RealMotionState.FAULTED,
            fault_code=code,
            detail=self._safe_detail(detail),
            stop_outcome=outcome,
            hardware_accessed=True,
            safety_state_known=outcome.safety_state_known,
            updated_at=now,
            finished_at=now,
        )

    def _mark_hardware_attempt(self, execution_id: UUID) -> None:
        self._replace_status(
            execution_id,
            hardware_accessed=True,
            safety_state_known=False,
            updated_at=self.clock.now(),
        )

    def _replace_status(self, execution_id: UUID, **updates: object) -> None:
        current = self._statuses[execution_id]
        payload = current.model_dump(mode="python")
        payload.update(updates)
        self._remember(RealMotionStatus.model_validate(payload))

    async def _emit(
        self,
        status: RealMotionStatus,
        kind: RealMotionAuditKind,
        *,
        requested_ids: tuple[int, ...],
        affected_ids: tuple[int, ...] = (),
        safety_state_known: bool,
        detail: str,
        sample_index: int | None = None,
    ) -> None:
        self._audit_sequence += 1
        event = RealMotionAuditEvent(
            sequence=self._audit_sequence,
            execution_id=status.execution_id,
            authorization_session_id=status.authorization_session_id,
            trajectory_digest=status.trajectory_digest,
            execution_purpose=status.execution_purpose,
            kind=kind,
            occurred_at=self.clock.now(),
            monotonic_s=max(0.0, self.clock.monotonic()),
            sample_index=sample_index,
            requested_ids=requested_ids,
            affected_ids=affected_ids,
            safety_state_known=safety_state_known,
            detail=self._safe_detail(detail),
        )
        self._audit_events.append(event)
        with suppress(Exception):
            await self.observer.record_real_motion_audit(event)

    async def _clear_active(self, execution_id: UUID) -> None:
        async with self._guard:
            if self._active_execution_id == execution_id:
                terminal_future = self._terminal_future
                self._active_execution_id = None
                self._active_task = None
                self._cancel_event = None
                self._active_authorization = None
                self._terminal_future = None
                if terminal_future is not None and not terminal_future.done():
                    terminal_future.set_result(None)

    def _ensure_terminal(self, execution_id: UUID) -> None:
        status = self._statuses[execution_id]
        if status.state in {
            RealMotionState.COMPLETED,
            RealMotionState.CANCELLED,
            RealMotionState.FAULTED,
        }:
            return
        outcome = RealStopOutcome(
            result=RealStopResult.SAFETY_STATE_UNCERTAIN,
            requested_ids=self._servo_ids,
            affected_ids=(),
            connected=False,
            safety_state_known=False,
            detail="Execution terminalization failed; physical safety state is uncertain",
        )
        self._set_faulted(
            execution_id,
            RealMotionFaultCode.SAFETY_STATE_UNCERTAIN,
            "Execution could not complete terminalization safely",
            outcome,
        )

    def _remember(self, status: RealMotionStatus) -> None:
        self._latest_execution_id = status.execution_id
        self._statuses[status.execution_id] = status
        self._statuses.move_to_end(status.execution_id)
        while len(self._statuses) > self.history_limit:
            oldest_id, oldest = next(iter(self._statuses.items()))
            if oldest_id == self.active_execution_id:
                break
            if oldest.state in {RealMotionState.ACCEPTED, RealMotionState.RUNNING}:
                break
            self._statuses.popitem(last=False)

    @staticmethod
    def _safe_detail(detail: str) -> str:
        return (detail.strip().replace("\n", " ") or "No detail")[:500]


__all__ = ["RealMotionExecutor", "RealMotionObserver"]
