"""Adapt product Motion commands to the reviewed exact-trajectory REAL executor."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from collections.abc import Callable
from uuid import UUID

from momo.adapters.hardware.real_robot_driver import AuthorizedServoBusBinding
from momo.adapters.motion.real_motion_executor import RealMotionExecutor
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.robot_service import RobotApplicationService
from momo.domain.calibration import CalibrationDocument
from momo.domain.enums import MotionCommandState
from momo.domain.motion_preflight import (
    MotionCommandStatus,
    PreparedContinuousJog,
    PreparedMotion,
)
from momo.domain.real_hardware import (
    RealHardwareAuthorizationPurpose,
    calibration_fingerprint,
)
from momo.domain.real_motion import (
    RealExecutionAuthorization,
    RealExecutionContext,
    RealMotionAuditEvent,
    RealMotionState,
    RealMotionStatus,
)
from momo.domain.robot import JointState
from momo.domain.trajectory import PreparedTrajectory
from momo.ports.clock import Clock


class _CommandExecutionContext:
    def __init__(
        self,
        robot: RobotApplicationService,
        prepared: PreparedTrajectory,
        calibration: CalibrationDocument,
        binding: AuthorizedServoBusBinding,
    ) -> None:
        self.robot = robot
        self.prepared = prepared
        self.calibration = calibration
        self.binding = binding

    async def current_real_execution_context(self) -> RealExecutionContext:
        status, profile, state = await self.robot.get_motion_snapshot()
        plan = self.prepared.plan
        return RealExecutionContext(
            robot_id=status.robot_id,
            variant=status.variant,
            connected=status.connected and self.binding.connected,
            state_fresh=not status.stale,
            stop_capable=self.binding.connected,
            state_sequence=status.state_sequence,
            joint_state=state,
            motion_id=plan.motion_id,
            motion_revision=plan.motion_revision,
            trajectory_digest=plan.digest.sha256,
            profile_fingerprint=profile.fingerprint,
            calibration_fingerprint=calibration_fingerprint(self.calibration),
            kinematics_fingerprint=plan.kinematics_fingerprint,
            observed_at=status.updated_at,
        )


class RealCommandMotionExecutor:
    """MotionExecutor implementation that never accepts an unauthenticated command."""

    def __init__(
        self,
        robot: RobotApplicationService,
        kinematics: KinematicsService,
        binding: AuthorizedServoBusBinding,
        clock: Clock,
        *,
        update_hz: float = 25.0,
        history_limit: int = 256,
    ) -> None:
        self.robot = robot
        self.kinematics = kinematics
        self.binding = binding
        self.clock = clock
        self.update_hz = float(update_hz)
        self.history_limit = max(8, int(history_limit))
        self._inner: RealMotionExecutor | None = None
        self._command_by_execution: dict[UUID, UUID] = {}
        self._prepared_by_command: dict[UUID, PreparedMotion | PreparedContinuousJog] = {}
        self._statuses: OrderedDict[UUID, MotionCommandStatus] = OrderedDict()
        self._latest_command_id: UUID | None = None
        self._audit: deque[RealMotionAuditEvent] = deque(maxlen=512)
        self._guard = asyncio.Lock()

    @property
    def active_command_id(self) -> UUID | None:
        inner = self._inner
        if inner is None or inner.active_execution_id is None:
            return None
        return self._command_by_execution.get(inner.active_execution_id)

    def get_status(self, command_id: UUID) -> MotionCommandStatus | None:
        self._refresh_from_inner()
        return self._statuses.get(command_id)

    def active_status(self) -> MotionCommandStatus | None:
        command_id = self.active_command_id
        return self.get_status(command_id) if command_id is not None else None

    def latest_status(self) -> MotionCommandStatus | None:
        if self._latest_command_id is None:
            return None
        return self.get_status(self._latest_command_id)

    async def submit(
        self,
        prepared: PreparedMotion,
        *,
        authorization: RealExecutionAuthorization | None = None,
        execution_purpose: RealHardwareAuthorizationPurpose | None = None,
        continuous_write_guard: Callable[[], bool] | None = None,
    ) -> MotionCommandStatus:
        return await self._submit_prepared(
            prepared,
            authorization,
            execution_purpose,
            continuous_write_guard,
        )

    async def submit_continuous_jog(
        self,
        prepared: PreparedContinuousJog,
        *,
        authorization: RealExecutionAuthorization | None = None,
        execution_purpose: RealHardwareAuthorizationPurpose | None = None,
        continuous_write_guard: Callable[[], bool] | None = None,
    ) -> MotionCommandStatus:
        return await self._submit_prepared(
            prepared,
            authorization,
            execution_purpose,
            continuous_write_guard,
        )

    async def _submit_prepared(
        self,
        prepared: PreparedMotion | PreparedContinuousJog,
        authorization: RealExecutionAuthorization | None,
        execution_purpose: RealHardwareAuthorizationPurpose | None,
        continuous_write_guard: Callable[[], bool] | None,
    ) -> MotionCommandStatus:
        if authorization is None or execution_purpose is None:
            raise PermissionError("REAL motion requires a purpose-bound execution authorization")
        self.binding.require_execution_scope(
            session_id=authorization.session_id,
            purpose=execution_purpose,
        )
        async with self._guard:
            if self.active_command_id is not None:
                raise RuntimeError("another REAL motion command is active")
            status, profile, _ = await self.robot.get_motion_snapshot()
            calibration = self.robot.calibration_service.get_for_variant(profile.variant)
            if calibration is None:
                raise RuntimeError("REAL motion calibration is unavailable")
            if prepared.executable_trajectory is None:
                raise RuntimeError(
                    "REAL execution requires the exact digest-bound trajectory "
                    "returned by MotionSafetyGateway"
                )
            trajectory = PreparedTrajectory.model_validate(prepared.executable_trajectory)
            current_kinematics = self.kinematics.model_for(profile).fingerprint
            if (
                trajectory.plan.start_state_sequence != status.state_sequence
                or trajectory.plan.profile_fingerprint != profile.fingerprint
                or trajectory.plan.kinematics_fingerprint != current_kinematics
                or trajectory.plan.motion_id != prepared.command_id
                or trajectory.plan.sample_rate_hz != self.update_hz
            ):
                raise RuntimeError(
                    "Gateway executable trajectory became stale before REAL dispatch"
                )
            expected_checks = tuple(
                (check.name, check.passed, check.detail) for check in prepared.preflight.checks
            )
            actual_checks = tuple(
                (check.name, check.passed, check.detail)
                for check in trajectory.preflight.checks[: len(expected_checks)]
            )
            if actual_checks != expected_checks:
                raise RuntimeError("Gateway command report does not match the executable preflight")
            context = _CommandExecutionContext(self.robot, trajectory, calibration, self.binding)
            inner = RealMotionExecutor(
                self.binding.require_bus(),
                self.clock,
                robot_id=status.robot_id,
                profile=profile,
                calibration=calibration,
                kinematics_fingerprint=trajectory.plan.kinematics_fingerprint,
                context_provider=context,
                observer=self,
                divergence_tolerance_raw=32,
            )
            accepted = await inner.submit(
                trajectory,
                expected_digest=trajectory.plan.digest.sha256,
                authorization=authorization,
                execution_purpose=execution_purpose,
                continuous_write_guard=continuous_write_guard,
            )
            self._inner = inner
            self._command_by_execution[accepted.execution_id] = prepared.command_id
            self._prepared_by_command[prepared.command_id] = prepared
            mapped = self._map_status(prepared.command_id, accepted)
            self._remember(mapped)
            return mapped

    async def cancel_active(self) -> MotionCommandStatus | None:
        inner = self._inner
        if inner is None:
            return None
        status = await inner.cancel_active()
        if status is None:
            return None
        command_id = self._command_by_execution[status.execution_id]
        mapped = self._map_status(command_id, status)
        self._remember(mapped)
        return mapped

    async def cancel(self, command_id: UUID) -> MotionCommandStatus | None:
        if self.active_command_id == command_id:
            return await self.cancel_active()
        return self.get_status(command_id)

    async def shutdown(self) -> None:
        inner = self._inner
        if inner is not None:
            await inner.shutdown()
        self._refresh_from_inner()

    async def apply_real_readback(self, execution_id: UUID, state: JointState) -> int:
        return await self.robot.apply_real_readback(execution_id, state)

    async def record_real_motion_audit(self, event: RealMotionAuditEvent) -> None:
        self._audit.append(event)

    def audit_events(self) -> tuple[RealMotionAuditEvent, ...]:
        return tuple(self._audit)

    def _refresh_from_inner(self) -> None:
        inner = self._inner
        if inner is None:
            return
        status = inner.latest_status()
        if status is None:
            return
        command_id = self._command_by_execution.get(status.execution_id)
        if command_id is None:
            return
        self._remember(self._map_status(command_id, status))

    def _map_status(self, command_id: UUID, status: RealMotionStatus) -> MotionCommandStatus:
        prepared = self._prepared_by_command.get(command_id)
        if prepared is None:
            raise RuntimeError("REAL command preflight history is unavailable")
        state = {
            RealMotionState.ACCEPTED: MotionCommandState.ACCEPTED,
            RealMotionState.RUNNING: MotionCommandState.RUNNING,
            RealMotionState.COMPLETED: MotionCommandState.COMPLETED,
            RealMotionState.CANCELLED: MotionCommandState.CANCELLED,
            RealMotionState.FAULTED: MotionCommandState.FAULTED,
        }[status.state]
        return MotionCommandStatus(
            command_id=command_id,
            state=state,
            progress=status.progress,
            preflight=prepared.preflight,
            trajectory_preflight=status.preflight,
            error=(status.fault_code.value if status.fault_code is not None else None),
            started_at=status.started_at,
            updated_at=status.updated_at,
            finished_at=status.finished_at,
            hardware_accessed=status.hardware_accessed,
        )

    def _remember(self, status: MotionCommandStatus) -> None:
        self._statuses[status.command_id] = status
        self._statuses.move_to_end(status.command_id)
        self._latest_command_id = status.command_id
        while len(self._statuses) > self.history_limit:
            self._statuses.popitem(last=False)


__all__ = ["RealCommandMotionExecutor"]
