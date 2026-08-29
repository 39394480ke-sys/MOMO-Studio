"""Adapt product Motion commands to the reviewed exact-trajectory REAL executor."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from datetime import datetime
from math import ceil
from uuid import UUID, uuid4

from momo.adapters.hardware.real_robot_driver import AuthorizedServoBusBinding
from momo.adapters.motion.real_motion_executor import RealMotionExecutor
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.robot_service import RobotApplicationService
from momo.domain.calibration import CalibrationDocument
from momo.domain.enums import Easing, MotionCommandState
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
from momo.domain.robot import JointState, RobotProfile
from momo.domain.trajectory import (
    PreparedTrajectory,
    TrajectoryDigest,
    TrajectoryPlan,
    TrajectoryPreflightCheck,
    TrajectoryPreflightReport,
    TrajectorySample,
    TrajectorySegment,
    TrajectorySegmentKind,
)
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
    ) -> MotionCommandStatus:
        return await self._submit_prepared(prepared, authorization, execution_purpose)

    async def submit_continuous_jog(
        self,
        prepared: PreparedContinuousJog,
        *,
        authorization: RealExecutionAuthorization | None = None,
        execution_purpose: RealHardwareAuthorizationPurpose | None = None,
    ) -> MotionCommandStatus:
        return await self._submit_prepared(prepared, authorization, execution_purpose)

    async def _submit_prepared(
        self,
        prepared: PreparedMotion | PreparedContinuousJog,
        authorization: RealExecutionAuthorization | None,
        execution_purpose: RealHardwareAuthorizationPurpose | None,
    ) -> MotionCommandStatus:
        if authorization is None or execution_purpose is None:
            raise PermissionError("REAL motion requires a purpose-bound execution authorization")
        async with self._guard:
            if self.active_command_id is not None:
                raise RuntimeError("another REAL motion command is active")
            status, profile, _ = await self.robot.get_motion_snapshot()
            calibration = self.robot.calibration_service.get_for_variant(profile.variant)
            if calibration is None:
                raise RuntimeError("REAL motion calibration is unavailable")
            trajectory = _prepared_command_trajectory(
                prepared,
                profile,
                status.state_sequence,
                execution_purpose,
                compiled_at=self.clock.now(),
                update_hz=self.update_hz,
            )
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


def _prepared_command_trajectory(
    prepared: PreparedMotion | PreparedContinuousJog,
    profile: RobotProfile,
    state_sequence: int,
    purpose: RealHardwareAuthorizationPurpose,
    *,
    compiled_at: datetime,
    update_hz: float,
) -> PreparedTrajectory:
    start_id = uuid4()
    end_id = uuid4()
    kind = (
        TrajectorySegmentKind.CARTESIAN_LINEAR
        if purpose is RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION
        else TrajectorySegmentKind.JOINT
    )
    if isinstance(prepared, PreparedMotion):
        duration_s = prepared.duration_s
        samples: list[TrajectorySample] = []
        if prepared.trajectory_samples is not None:
            for index, prepared_sample in enumerate(prepared.trajectory_samples):
                samples.append(
                    TrajectorySample(
                        time_s=float(prepared_sample.time_s),
                        positions=dict(prepared_sample.joint_state.positions),
                        units=dict(prepared_sample.joint_state.units or {}),
                        keyframe_id=(start_id if index == 0 else end_id),
                        segment_index=0,
                        sample_index=index,
                    )
                )
        else:
            count = max(2, ceil(duration_s * update_hz) + 1)
            for index in range(count):
                time_s = duration_s if index == count - 1 else index / update_hz
                progress = min(1.0, time_s / duration_s)
                interpolation = progress * progress * (3.0 - 2.0 * progress)
                positions = {
                    joint_id: prepared.start_state.positions[joint_id]
                    + (
                        prepared.target_state.positions[joint_id]
                        - prepared.start_state.positions[joint_id]
                    )
                    * interpolation
                    for joint_id in profile.enabled_joints
                }
                samples.append(
                    TrajectorySample(
                        time_s=float(time_s),
                        positions=positions,
                        units=dict(prepared.target_state.units or {}),
                        keyframe_id=(start_id if index == 0 else end_id),
                        segment_index=0,
                        sample_index=index,
                    )
                )
    else:
        start_value = prepared.start_state.positions[prepared.joint_id]
        travel = (
            prepared.maximum - start_value
            if prepared.direction > 0
            else start_value - prepared.minimum
        )
        ramp_duration = prepared.speed_units_s / prepared.acceleration_units_s2
        ramp_distance = 0.5 * prepared.acceleration_units_s2 * ramp_duration * ramp_duration
        duration_s = (
            (2.0 * travel / prepared.acceleration_units_s2) ** 0.5
            if travel <= ramp_distance
            else ramp_duration + (travel - ramp_distance) / prepared.speed_units_s
        )
        duration_s = max(0.05, min(30.0, duration_s))
        count = max(2, ceil(duration_s * update_hz) + 1)
        samples = []
        for index in range(count):
            time_s = duration_s if index == count - 1 else index / update_hz
            if time_s < ramp_duration:
                distance = 0.5 * prepared.acceleration_units_s2 * time_s * time_s
            else:
                distance = ramp_distance + prepared.speed_units_s * (time_s - ramp_duration)
            value = start_value + prepared.direction * min(travel, distance)
            positions = dict(prepared.start_state.positions)
            positions[prepared.joint_id] = value
            samples.append(
                TrajectorySample(
                    time_s=float(time_s),
                    positions=positions,
                    units=dict(prepared.start_state.units or {}),
                    keyframe_id=(start_id if index == 0 else end_id),
                    segment_index=0,
                    sample_index=index,
                )
            )

    segment = TrajectorySegment(
        segment_index=0,
        kind=kind,
        from_keyframe_id=start_id,
        to_keyframe_id=end_id,
        easing=(
            Easing.LINEAR
            if isinstance(prepared, PreparedMotion) and prepared.trajectory_samples is not None
            else Easing.SMOOTHSTEP
        ),
        start_time_s=0.0,
        end_time_s=float(duration_s),
        duration_s=float(duration_s),
        start_sample_index=0,
        end_sample_index=len(samples) - 1,
        generated_sample_count=len(samples) - 1,
    )
    provisional = TrajectoryPlan.model_construct(
        motion_id=prepared.command_id,
        motion_revision=1,
        robot_variant=profile.variant,
        profile_fingerprint=profile.fingerprint,
        kinematics_fingerprint=prepared.preflight.kinematics_fingerprint,
        start_state_sequence=state_sequence,
        sample_rate_hz=float(update_hz),
        duration_s=float(duration_s),
        segments=[segment],
        samples=samples,
        digest=TrajectoryDigest(sha256="0" * 64),
        compiled_at=compiled_at,
    )
    digest = TrajectoryDigest(sha256=provisional.computed_sha256)
    plan = TrajectoryPlan(
        motion_id=prepared.command_id,
        motion_revision=1,
        robot_variant=profile.variant,
        profile_fingerprint=profile.fingerprint,
        kinematics_fingerprint=prepared.preflight.kinematics_fingerprint,
        start_state_sequence=state_sequence,
        sample_rate_hz=float(update_hz),
        duration_s=float(duration_s),
        segments=[segment],
        samples=samples,
        digest=digest,
        compiled_at=compiled_at,
    )
    report = TrajectoryPreflightReport(
        accepted=True,
        motion_id=plan.motion_id,
        motion_revision=plan.motion_revision,
        digest=digest,
        duration_s=plan.duration_s,
        sample_count=len(plan.samples),
        segment_count=len(plan.segments),
        sample_rate_hz=plan.sample_rate_hz,
        checks=[
            TrajectoryPreflightCheck(
                name="motion_safety_gateway",
                passed=True,
                detail="Command prepared by the single Motion Safety Gateway",
            )
        ],
        violations=[],
        real_motion_ready=True,
        field_acceptance_ready=False,
    )
    return PreparedTrajectory(plan=plan, preflight=report)


__all__ = ["RealCommandMotionExecutor"]
