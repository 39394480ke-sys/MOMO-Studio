"""Focused controller, lease, and cancellation evidence for Stage 7 Follow."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.robot_service import RobotApplicationService
from momo.application.services.vision_command_coordinator import VisionCommandCoordinator
from momo.application.services.vision_follow import VisionFollowService
from momo.domain.enums import (
    CalibrationStatus,
    ControlMode,
    HardwareAccessPolicy,
    MotionCommandSource,
    MotionCommandState,
    MotionCommandType,
    ProfileVerificationStatus,
    RobotConnectionState,
    RobotVariant,
)
from momo.domain.errors import (
    MotionCommandNotFoundError,
    MotionConflictError,
    VisionFollowConflictError,
)
from momo.domain.motion_command import JointMovePayload, MotionCommand
from momo.domain.motion_preflight import MotionAccepted, MotionCommandStatus
from momo.domain.profiles import canonical_robot_profile
from momo.domain.robot import JointState, RobotProfile
from momo.domain.runtime import RobotStatus
from momo.domain.vision import (
    FrameMetadata,
    NormalizedBoundingBox,
    TrackingResult,
    TrackingStatus,
)
from momo.domain.vision_follow import (
    FollowActuatorMapping,
    FollowConfiguration,
    FollowController,
    FollowControllerState,
    FollowOperatorIntent,
    FollowState,
    FollowStopReason,
)
from tests.stage3_helpers import FakeClock, make_preflight


@dataclass(frozen=True, slots=True)
class _Model:
    fingerprint: str = "b" * 64


class FakeKinematics:
    def model_for(self, profile: RobotProfile) -> _Model:
        del profile
        return _Model()


class FakeRobot:
    def __init__(self) -> None:
        self.profile = canonical_robot_profile(RobotVariant.V2)
        self.current = JointState(
            positions={
                definition.joint_id: definition.home
                for definition in self.profile.joint_definitions
            },
            units={
                definition.joint_id: definition.domain_unit
                for definition in self.profile.joint_definitions
            },
        )
        self.connection_state = RobotConnectionState.CONNECTED
        self.stale = False
        self.control_mode = ControlMode.DRY_RUN
        self.hardware_policy = HardwareAccessPolicy.DISABLED

    async def get_motion_snapshot(
        self,
    ) -> tuple[RobotStatus, RobotProfile, JointState]:
        connected = self.connection_state is RobotConnectionState.CONNECTED
        status = RobotStatus(
            robot_id="primary",
            variant=self.profile.variant,
            control_mode=self.control_mode,
            hardware_access_policy=self.hardware_policy,
            connection_state=self.connection_state,
            connected=connected,
            profile_fingerprint=self.profile.fingerprint,
            profile_verification_status=ProfileVerificationStatus.VERIFIED_FOR_DRY_RUN,
            calibration_status=CalibrationStatus.TEMPLATE_ONLY,
            positions=dict(self.current.positions),
            units={joint_id: unit.value for joint_id, unit in (self.current.units or {}).items()},
            state_sequence=1,
            stale=self.stale,
        )
        return status, self.profile, self.current


class RecordingSafetyGateway:
    """Narrow MotionApplicationService-like surface; no driver/executor is exposed."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.commands: list[MotionCommand] = []
        self.statuses: dict[UUID, MotionCommandStatus] = {}
        self.cancel_calls: list[UUID] = []
        self.raise_conflict = False
        self.block_before_accept = False
        self.block_after_accept = False
        self.lifecycle_fenced = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def submit(self, command: MotionCommand) -> MotionAccepted:
        self.commands.append(command)
        if self.raise_conflict:
            raise MotionConflictError("synthetic motion conflict")
        if self.block_before_accept:
            self.entered.set()
            await self.release.wait()
            if self.lifecycle_fenced:
                raise MotionConflictError("synthetic lifecycle fence")
        status = MotionCommandStatus(
            command_id=command.command_id,
            state=MotionCommandState.RUNNING,
            progress=0.0,
            preflight=make_preflight(command.command_id),
            updated_at=self.clock.now(),
        )
        self.statuses[command.command_id] = status
        if self.block_after_accept:
            self.entered.set()
            await self.release.wait()
        return MotionAccepted(
            command_id=command.command_id,
            status=status.state,
            preflight=status.preflight,
        )

    def get_status(self, command_id: UUID) -> MotionCommandStatus:
        status = self.statuses.get(command_id)
        if status is None:
            raise MotionCommandNotFoundError(f"unknown: {command_id}")
        return status

    async def cancel_command(self, command_id: UUID) -> MotionCommandStatus | None:
        self.cancel_calls.append(command_id)
        status = self.statuses.get(command_id)
        if status is None:
            return None
        if status.state in {
            MotionCommandState.CANCELLED,
            MotionCommandState.COMPLETED,
            MotionCommandState.FAULTED,
        }:
            return status
        cancelled = status.model_copy(
            update={
                "state": MotionCommandState.CANCELLED,
                "updated_at": self.clock.now(),
                "finished_at": self.clock.now(),
            }
        )
        self.statuses[command_id] = cancelled
        return cancelled

    def complete_latest(self) -> None:
        command = self.commands[-1]
        status = self.statuses[command.command_id]
        self.statuses[command.command_id] = status.model_copy(
            update={
                "state": MotionCommandState.COMPLETED,
                "progress": 1.0,
                "updated_at": self.clock.now(),
                "finished_at": self.clock.now(),
            }
        )


def configuration(
    *,
    pan_joint: str = "j11",
    tilt_joint: str = "j12",
    pan_sign: Literal[-1, 1] = 1,
    tilt_sign: Literal[-1, 1] = -1,
    dead_zone_x: float = 0.05,
    dead_zone_y: float = 0.05,
    ema_alpha: float = 0.5,
    gain: float = 10.0,
    max_step: float = 2.0,
    max_rate: float = 20.0,
    confidence_threshold: float = 0.5,
    frame_freshness_limit_s: float = 1.0,
    target_lost_limit_s: float = 0.2,
    lease_ttl_s: float = 2.0,
) -> FollowConfiguration:
    return FollowConfiguration(
        dead_zone_x=dead_zone_x,
        dead_zone_y=dead_zone_y,
        ema_alpha=ema_alpha,
        gain=gain,
        max_step=max_step,
        max_rate=max_rate,
        confidence_threshold=confidence_threshold,
        frame_freshness_limit_s=frame_freshness_limit_s,
        target_lost_limit_s=target_lost_limit_s,
        lease_ttl_s=lease_ttl_s,
        mapping=FollowActuatorMapping(
            pan_joint=pan_joint,
            tilt_joint=tilt_joint,
            pan_sign=pan_sign,
            tilt_sign=tilt_sign,
            verification_status=ProfileVerificationStatus.VERIFIED_FOR_DRY_RUN,
        ),
    )


def follow_service(
    *,
    clock: FakeClock | None = None,
    robot: FakeRobot | None = None,
    motion: RecordingSafetyGateway | None = None,
) -> tuple[VisionFollowService, FakeClock, FakeRobot, RecordingSafetyGateway]:
    resolved_clock = clock or FakeClock()
    resolved_robot = robot or FakeRobot()
    resolved_motion = motion or RecordingSafetyGateway(resolved_clock)
    service = VisionFollowService(
        cast(RobotApplicationService, resolved_robot),
        cast(KinematicsService, FakeKinematics()),
        resolved_motion,
        resolved_clock,
    )
    return service, resolved_clock, resolved_robot, resolved_motion


def intent(config: FollowConfiguration | None = None) -> FollowOperatorIntent:
    return FollowOperatorIntent(confirmed=True, configuration=config or configuration())


def locked_result(
    clock: FakeClock,
    frame_number: int,
    *,
    center_x: float,
    center_y: float,
    confidence: float = 0.9,
    captured_at: datetime | None = None,
) -> TrackingResult:
    metadata = FrameMetadata(
        frame_id=f"synthetic-{frame_number:08d}",
        source_id="synthetic-stage7",
        captured_at=captured_at or clock.now(),
        width_px=640,
        height_px=480,
    )
    box = NormalizedBoundingBox.from_metadata(
        x=center_x - 0.05,
        y=center_y - 0.05,
        width=0.1,
        height=0.1,
        metadata=metadata,
    )
    return TrackingResult(
        metadata=metadata,
        status=TrackingStatus.LOCKED,
        bounding_box=box,
        confidence=confidence,
    )


def non_locked_result(
    clock: FakeClock,
    frame_number: int,
    status: TrackingStatus,
) -> TrackingResult:
    return TrackingResult(
        metadata=FrameMetadata(
            frame_id=f"synthetic-{frame_number:08d}",
            source_id="synthetic-stage7",
            captured_at=clock.now(),
            width_px=640,
            height_px=480,
        ),
        status=status,
    )


def test_configuration_is_dry_run_verified_and_rejects_unsafe_mapping() -> None:
    with pytest.raises(ValidationError, match="distinct"):
        FollowActuatorMapping(
            pan_joint="j11",
            tilt_joint="j11",
            pan_sign=1,
            tilt_sign=1,
        )
    with pytest.raises(ValidationError, match="bounded motion duration"):
        configuration(max_step=90.0, max_rate=1.0)
    with pytest.raises(ValidationError):
        FollowOperatorIntent.model_validate(
            {
                "confirmed": True,
                "requested_mode": "REAL",
                "configuration": configuration().model_dump(mode="json"),
            }
        )

    async def scenario() -> None:
        service, _, _, _ = follow_service()
        with pytest.raises(VisionFollowConflictError) as rail_mapping:
            await service.start(intent(configuration(pan_joint="j10", tilt_joint="j11")))
        details = cast(dict[str, list[str]], rail_mapping.value.details)
        assert "PAN_JOINT_MUST_BE_REVOLUTE_DEG" in details["reasons"]
        with pytest.raises(VisionFollowConflictError) as unknown_mapping:
            await service.start(intent(configuration(pan_joint="j99", tilt_joint="j11")))
        unknown_details = cast(dict[str, list[str]], unknown_mapping.value.details)
        assert "PAN_JOINT_NOT_ENABLED" in unknown_details["reasons"]

        started = await service.start(intent())
        assert started.state is FollowState.ACTIVE
        assert started.real_follow_allowed is False
        assert started.configuration is not None
        assert (
            started.configuration.mapping.verification_status
            is ProfileVerificationStatus.VERIFIED_FOR_DRY_RUN
        )
        assert started.lease is not None
        await service.stop(started.lease.lease_id)

    asyncio.run(scenario())


def test_pure_follow_controller_calculates_ema_dead_zone_and_rate_without_io() -> None:
    config = configuration()
    first = FollowController.update(
        config,
        FollowControllerState(),
        frame_id="synthetic-00000001",
        source_id="synthetic-stage7",
        captured_at=FakeClock().now(),
        frame_age_s=0.0,
        confidence=0.9,
        center_x=0.8,
        center_y=0.5,
        now_monotonic=0.0,
    )
    assert first.metrics.error_x == pytest.approx(0.3)
    assert first.metrics.pan_step == pytest.approx(2.0)
    dispatched = FollowController.mark_dispatched(first.state, 0.0)
    second = FollowController.update(
        config,
        dispatched,
        frame_id="synthetic-00000002",
        source_id="synthetic-stage7",
        captured_at=FakeClock().now(),
        frame_age_s=0.0,
        confidence=0.9,
        center_x=0.4,
        center_y=0.5,
        now_monotonic=0.05,
    )
    assert second.metrics.ema_error_x == pytest.approx(0.1)
    assert second.metrics.pan_step == pytest.approx(1.0)


def test_command_coordinator_directly_cancels_manual_race_but_not_global_hook() -> None:
    def command(key: str) -> MotionCommand:
        robot = FakeRobot()
        positions = dict(robot.current.positions)
        positions["j11"] += 1.0
        return MotionCommand(
            robot_id="primary",
            source=MotionCommandSource.VISION,
            expected_state_sequence=1,
            expected_profile_fingerprint=robot.profile.fingerprint,
            expected_kinematics_fingerprint="b" * 64,
            command_type=MotionCommandType.MOVE_JOINTS,
            payload=JointMovePayload(
                joint_state=JointState(
                    positions=positions,
                    units=dict(robot.current.units or {}),
                ),
                duration_s=0.1,
            ),
            idempotency_key=key,
        )

    async def scenario() -> None:
        clock = FakeClock()
        motion = RecordingSafetyGateway(clock)
        motion.block_after_accept = True
        coordinator = VisionCommandCoordinator(motion)
        epoch = await coordinator.begin_owner()
        intent_command = command("coordinator-manual-race")
        dispatch = asyncio.create_task(coordinator.dispatch(epoch, intent_command))
        await motion.entered.wait()
        await coordinator.stop(epoch, global_stop=False)
        assert await dispatch is None
        assert intent_command.command_id in motion.cancel_calls

        global_motion = RecordingSafetyGateway(clock)
        global_motion.block_before_accept = True
        global_coordinator = VisionCommandCoordinator(global_motion)
        global_epoch = await global_coordinator.begin_owner()
        global_command = command("coordinator-global-race")
        global_dispatch = asyncio.create_task(
            global_coordinator.dispatch(global_epoch, global_command)
        )
        await global_motion.entered.wait()
        global_motion.lifecycle_fenced = True
        await global_coordinator.stop(global_epoch, global_stop=True)
        assert global_motion.cancel_calls == []
        global_motion.release.set()
        with pytest.raises(MotionConflictError):
            await global_dispatch
        assert global_motion.cancel_calls == []

        idle = VisionCommandCoordinator(RecordingSafetyGateway(clock))
        for _ in range(512):
            idle_epoch = await idle.begin_owner()
            await idle.stop(idle_epoch, global_stop=True)
        assert idle._global_stop_epochs == set()

    asyncio.run(scenario())


def test_center_error_ema_dead_zone_sign_gain_rate_and_max_step() -> None:
    async def scenario() -> None:
        service, clock, _, motion = follow_service()
        started = await service.start(intent())
        assert started.lease is not None
        lease_id = started.lease.lease_id

        first = await service.process_tracking(
            lease_id,
            locked_result(clock, 1, center_x=0.8, center_y=0.5),
        )
        assert first.metrics is not None
        assert first.metrics.error_x == pytest.approx(0.3)
        assert first.metrics.ema_error_x == pytest.approx(0.3)
        assert first.metrics.pan_step == pytest.approx(2.0)
        assert first.metrics.tilt_step == pytest.approx(0.0)
        assert len(motion.commands) == 1
        command = motion.commands[0]
        assert command.source is MotionCommandSource.VISION
        assert isinstance(command.payload, JointMovePayload)
        assert command.payload.joint_state.positions["j11"] == pytest.approx(2.0)
        assert command.payload.joint_state.positions["j12"] == pytest.approx(0.0)

        motion.complete_latest()
        await clock.advance(0.05)
        second = await service.process_tracking(
            lease_id,
            locked_result(clock, 2, center_x=0.4, center_y=0.5),
        )
        assert second.metrics is not None
        assert second.metrics.error_x == pytest.approx(-0.1)
        assert second.metrics.ema_error_x == pytest.approx(0.1)
        # 20 units/s * 0.05 s = a 1-unit rate-limited increment.
        assert second.metrics.pan_step == pytest.approx(1.0)
        assert len(motion.commands) == 2

        motion.complete_latest()
        await clock.advance(0.1)
        centered = await service.process_tracking(
            lease_id,
            locked_result(clock, 3, center_x=0.46, center_y=0.5),
        )
        assert centered.metrics is not None
        # EMA is 0.03 and therefore inside the configured 0.05 dead zone.
        assert centered.metrics.ema_error_x == pytest.approx(0.03)
        assert centered.metrics.pan_step == pytest.approx(0.0)
        assert len(motion.commands) == 2
        await service.stop(lease_id)

    asyncio.run(scenario())


def test_loss_cancels_last_direction_then_watchdog_stops() -> None:
    async def scenario() -> None:
        service, clock, _, motion = follow_service()
        started = await service.start(intent())
        assert started.lease is not None
        lease_id = started.lease.lease_id
        moving = await service.process_tracking(
            lease_id,
            locked_result(clock, 1, center_x=0.8, center_y=0.5),
        )
        assert moving.active_command_id is not None

        lost = await service.process_tracking(
            lease_id,
            # A tracker may revise its result for the same frame. LOST must
            # still cancel the prior direction; duplicate LOCKED alone is deduped.
            non_locked_result(clock, 1, TrackingStatus.LOST),
        )
        assert lost.state is FollowState.ACTIVE
        assert lost.active_command_id is None
        assert motion.cancel_calls == [moving.active_command_id]
        commands_before_expiry = len(motion.commands)

        await clock.advance(0.21)
        assert service.get_status().state is FollowState.STOPPED
        assert service.get_status().stop_reason is FollowStopReason.TARGET_LOST
        assert len(motion.commands) == commands_before_expiry

    asyncio.run(scenario())


def test_stale_frame_low_confidence_and_tracker_fault_fail_closed() -> None:
    async def stale_scenario() -> None:
        service, clock, _, motion = follow_service()
        started = await service.start(intent())
        assert started.lease is not None
        lease_id = started.lease.lease_id
        await clock.advance(1.1)
        stale = await service.process_tracking(
            lease_id,
            locked_result(
                clock,
                1,
                center_x=0.8,
                center_y=0.5,
                captured_at=clock.now().replace(year=2025),
            ),
        )
        assert stale.state is FollowState.STOPPED
        assert stale.stop_reason is FollowStopReason.FRAME_STALE
        assert motion.commands == []

    async def confidence_scenario() -> None:
        service, clock, _, motion = follow_service()
        started = await service.start(intent())
        assert started.lease is not None
        lease_id = started.lease.lease_id
        await service.process_tracking(
            lease_id,
            locked_result(clock, 1, center_x=0.8, center_y=0.5),
        )
        low = await service.process_tracking(
            lease_id,
            locked_result(clock, 1, center_x=0.8, center_y=0.5, confidence=0.2),
        )
        assert low.state is FollowState.ACTIVE
        assert low.active_command_id is None
        assert motion.cancel_calls
        await clock.advance(0.21)
        assert service.get_status().stop_reason is FollowStopReason.CONFIDENCE_LOW

    async def non_advancing_timestamp_scenario() -> None:
        service, clock, _, motion = follow_service()
        started = await service.start(intent())
        assert started.lease is not None
        lease_id = started.lease.lease_id
        first = await service.process_tracking(
            lease_id,
            locked_result(clock, 1, center_x=0.8, center_y=0.5),
        )
        assert first.active_command_id is not None
        stopped = await service.process_tracking(
            lease_id,
            # New identity with the same capture timestamp cannot extend freshness.
            locked_result(clock, 2, center_x=0.8, center_y=0.5),
        )
        assert stopped.stop_reason is FollowStopReason.FRAME_STALE
        assert first.active_command_id in motion.cancel_calls

    async def fault_scenario() -> None:
        service, clock, _, _ = follow_service()
        started = await service.start(intent())
        assert started.lease is not None
        faulted = await service.process_tracking(
            started.lease.lease_id,
            non_locked_result(clock, 1, TrackingStatus.FAULTED),
        )
        assert faulted.stop_reason is FollowStopReason.TRACKER_FAULT

    asyncio.run(stale_scenario())
    asyncio.run(confidence_scenario())
    asyncio.run(non_advancing_timestamp_scenario())
    asyncio.run(fault_scenario())


def test_lease_heartbeat_and_frame_watchdog_are_backend_owned() -> None:
    async def scenario() -> None:
        service, clock, _, _ = follow_service()
        started = await service.start(
            intent(
                configuration(
                    frame_freshness_limit_s=1.0,
                    target_lost_limit_s=0.5,
                    lease_ttl_s=0.25,
                )
            )
        )
        assert started.lease is not None
        lease_id = started.lease.lease_id
        await clock.advance(0.2)
        heartbeat = await service.heartbeat(lease_id)
        assert heartbeat.state is FollowState.ACTIVE
        await clock.advance(0.2)
        assert service.get_status().state is FollowState.ACTIVE
        await clock.advance(0.06)
        assert service.get_status().state is FollowState.STOPPED
        assert service.get_status().stop_reason is FollowStopReason.LEASE_EXPIRED

        service2, clock2, _, _ = follow_service()
        started2 = await service2.start(
            intent(
                configuration(
                    frame_freshness_limit_s=0.1,
                    target_lost_limit_s=0.5,
                    lease_ttl_s=1.0,
                )
            )
        )
        assert started2.lease is not None
        await clock2.advance(0.11)
        assert service2.get_status().stop_reason is FollowStopReason.FRAME_STALE

    asyncio.run(scenario())


def test_robot_disconnect_and_motion_conflict_auto_stop() -> None:
    async def disconnected_scenario() -> None:
        service, clock, robot, motion = follow_service()
        started = await service.start(intent())
        assert started.lease is not None
        robot.connection_state = RobotConnectionState.DISCONNECTED
        stopped = await service.process_tracking(
            started.lease.lease_id,
            locked_result(clock, 1, center_x=0.5, center_y=0.5),
        )
        assert stopped.stop_reason is FollowStopReason.ROBOT_DISCONNECTED
        assert motion.commands == []

    async def faulted_scenario() -> None:
        service, clock, robot, motion = follow_service()
        started = await service.start(intent())
        assert started.lease is not None
        robot.connection_state = RobotConnectionState.FAULTED
        stopped = await service.process_tracking(
            started.lease.lease_id,
            locked_result(clock, 1, center_x=0.5, center_y=0.5),
        )
        assert stopped.stop_reason is FollowStopReason.ROBOT_FAULTED
        assert motion.commands == []

    async def active_command_disconnect_scenario() -> None:
        service, clock, robot, motion = follow_service()
        started = await service.start(intent())
        assert started.lease is not None
        moving = await service.process_tracking(
            started.lease.lease_id,
            locked_result(clock, 1, center_x=0.8, center_y=0.5),
        )
        assert moving.active_command_id is not None
        robot.connection_state = RobotConnectionState.DISCONNECTED
        await clock.advance(0.01)
        stopped = await service.process_tracking(
            started.lease.lease_id,
            locked_result(clock, 2, center_x=0.8, center_y=0.5),
        )
        assert stopped.stop_reason is FollowStopReason.ROBOT_DISCONNECTED
        assert moving.active_command_id in motion.cancel_calls

    async def conflict_scenario() -> None:
        service, clock, _, motion = follow_service()
        motion.raise_conflict = True
        started = await service.start(intent())
        assert started.lease is not None
        stopped = await service.process_tracking(
            started.lease.lease_id,
            locked_result(clock, 1, center_x=0.8, center_y=0.5),
        )
        assert stopped.stop_reason is FollowStopReason.MOTION_CONFLICT
        assert motion.commands[0].source is MotionCommandSource.VISION

    asyncio.run(disconnected_scenario())
    asyncio.run(faulted_scenario())
    asyncio.run(active_command_disconnect_scenario())
    asyncio.run(conflict_scenario())


def test_manual_stop_cancels_command_accepted_during_dispatch_race() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        motion = RecordingSafetyGateway(clock)
        motion.block_after_accept = True
        service, _, _, _ = follow_service(clock=clock, motion=motion)
        started = await service.start(intent())
        assert started.lease is not None
        lease_id = started.lease.lease_id

        tracking = asyncio.create_task(
            service.process_tracking(
                lease_id,
                locked_result(clock, 1, center_x=0.8, center_y=0.5),
            )
        )
        await motion.entered.wait()
        command_id = motion.commands[0].command_id
        stopped = await service.stop(lease_id)
        assert stopped.stop_reason is FollowStopReason.OPERATOR_STOP
        await tracking
        assert command_id in motion.cancel_calls
        assert motion.statuses[command_id].state is MotionCommandState.CANCELLED

    asyncio.run(scenario())


def test_internal_motion_boundary_failures_stop_follow_before_propagating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def build_failure_scenario() -> None:
        service, clock, _, _ = follow_service()
        started = await service.start(intent())
        assert started.lease is not None

        def fail_build(**values: object) -> object:
            del values
            raise RuntimeError("synthetic command factory fault")

        monkeypatch.setattr(service.command_factory, "build", fail_build)
        with pytest.raises(RuntimeError, match="command factory fault"):
            await service.process_tracking(
                started.lease.lease_id,
                locked_result(clock, 1, center_x=0.8, center_y=0.5),
            )
        assert service.get_status().state is FollowState.STOPPED
        assert service.get_status().stop_reason is FollowStopReason.MOTION_REJECTED

    async def inspect_failure_scenario() -> None:
        service, clock, _, _ = follow_service()
        started = await service.start(intent())
        assert started.lease is not None

        async def fail_inspect(epoch: int) -> object:
            del epoch
            raise RuntimeError("synthetic ownership inspection fault")

        monkeypatch.setattr(service.commands, "inspect", fail_inspect)
        with pytest.raises(RuntimeError, match="ownership inspection fault"):
            await service.process_tracking(
                started.lease.lease_id,
                locked_result(clock, 1, center_x=0.8, center_y=0.5),
            )
        assert service.get_status().state is FollowState.STOPPED
        assert service.get_status().stop_reason is FollowStopReason.MOTION_REJECTED

    asyncio.run(build_failure_scenario())
    asyncio.run(inspect_failure_scenario())


def test_global_stop_hook_never_reenters_motion_dispatch_and_fences_late_submit() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        motion = RecordingSafetyGateway(clock)
        motion.block_before_accept = True
        service, _, _, _ = follow_service(clock=clock, motion=motion)
        started = await service.start(intent())
        assert started.lease is not None

        tracking = asyncio.create_task(
            service.process_tracking(
                started.lease.lease_id,
                locked_result(clock, 1, center_x=0.8, center_y=0.5),
            )
        )
        await motion.entered.wait()
        # Mirrors MotionApplicationService: fence/cancel executor first, then invoke hook.
        motion.lifecycle_fenced = True
        await service.stop_all()
        assert service.get_status().stop_reason is FollowStopReason.GLOBAL_STOP
        assert motion.cancel_calls == []

        motion.release.set()
        result = await tracking
        assert result.stop_reason is FollowStopReason.GLOBAL_STOP
        assert motion.statuses == {}
        assert motion.cancel_calls == []

    asyncio.run(scenario())


def test_global_stop_fences_start_blocked_before_lease_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        robot = FakeRobot()
        motion = RecordingSafetyGateway(clock)
        service, _, _, _ = follow_service(clock=clock, robot=robot, motion=motion)
        snapshot_entered = asyncio.Event()
        release_snapshot = asyncio.Event()
        original_snapshot = robot.get_motion_snapshot

        async def blocked_snapshot() -> tuple[RobotStatus, RobotProfile, JointState]:
            snapshot_entered.set()
            await release_snapshot.wait()
            return await original_snapshot()

        monkeypatch.setattr(robot, "get_motion_snapshot", blocked_snapshot)
        starting = asyncio.create_task(service.start(intent()))
        await snapshot_entered.wait()

        # Global Stop must fence an in-progress start even though no lease or
        # command exists yet, and its hook must not call back into motion.
        await service.stop_all()
        assert service.get_status().state is FollowState.IDLE
        assert motion.commands == []
        assert motion.cancel_calls == []

        release_snapshot.set()
        with pytest.raises(VisionFollowConflictError, match="superseded"):
            await starting
        assert service.get_status().state is FollowState.IDLE
        assert service.follow_active is False
        assert motion.commands == []
        assert motion.cancel_calls == []

    asyncio.run(scenario())


def test_shutdown_fences_blocked_start_and_permanently_rejects_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        robot = FakeRobot()
        motion = RecordingSafetyGateway(clock)
        service, _, _, _ = follow_service(clock=clock, robot=robot, motion=motion)
        snapshot_entered = asyncio.Event()
        release_snapshot = asyncio.Event()
        original_snapshot = robot.get_motion_snapshot

        async def blocked_snapshot() -> tuple[RobotStatus, RobotProfile, JointState]:
            snapshot_entered.set()
            await release_snapshot.wait()
            return await original_snapshot()

        monkeypatch.setattr(robot, "get_motion_snapshot", blocked_snapshot)
        starting = asyncio.create_task(service.start(intent()))
        await snapshot_entered.wait()

        await service.shutdown()
        assert service.get_status().state is FollowState.IDLE
        assert motion.commands == []
        assert motion.cancel_calls == []

        release_snapshot.set()
        with pytest.raises(VisionFollowConflictError, match="shutdown"):
            await starting
        assert service.follow_active is False
        assert motion.commands == []
        assert motion.cancel_calls == []

        with pytest.raises(VisionFollowConflictError, match="shut down"):
            await service.start(intent())
        assert service.follow_active is False
        assert motion.commands == []

    asyncio.run(scenario())
