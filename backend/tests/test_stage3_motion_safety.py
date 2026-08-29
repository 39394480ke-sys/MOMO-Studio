"""Unified Stage 3 motion gateway rejection and lifecycle race contracts."""

from __future__ import annotations

import asyncio
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

import momo.application.services.robot_service as robot_service_module
from momo.api.app import create_app
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.motion_safety_gateway import MotionSafetyGateway
from momo.application.services.motion_service import MotionApplicationService
from momo.application.services.robot_service import RobotApplicationService
from momo.domain.enums import (
    CartesianFrame,
    DomainUnit,
    MotionCommandSource,
    MotionCommandState,
    MotionCommandType,
)
from momo.domain.errors import (
    IdempotencyConflictError,
    MotionConflictError,
    MotionPreflightError,
)
from momo.domain.kinematics.results import ForwardKinematicsResult
from momo.domain.motion_command import (
    CartesianJogPayload,
    ContinuousJogPayload,
    JointMovePayload,
    MotionCommand,
    MovePosePayload,
)
from momo.domain.motion_preflight import PreparedContinuousJog, PreparedMotion
from momo.domain.pose import QuaternionXYZW, TcpPose, Vector3
from momo.domain.robot import JointState, RobotProfile
from momo.domain.runtime import RuntimeState
from momo.settings import Settings
from tests.stage3_helpers import FakeClock


def app_for(tmp_path: Path, *, use_calibration_examples: bool = False) -> FastAPI:
    calibration_directory = (
        "calibration/examples" if use_calibration_examples else str(tmp_path / "no-calibration")
    )
    return create_app(
        Settings(
            runtime_state_directory=str(tmp_path / "runtime"),
            calibration_directory=calibration_directory,
        )
    )


async def move_command(
    app: FastAPI,
    *,
    changes: dict[str, float] | None = None,
    duration_s: float = 1.0,
    key: str = "move",
) -> MotionCommand:
    robot: RobotApplicationService = app.state.robot_service
    kinematics: KinematicsService = app.state.kinematics_service
    status, profile, current = await robot.get_motion_snapshot()
    positions = dict(current.positions)
    positions.update(changes or {"j11": positions["j11"] + 5.0})
    target = JointState(positions=positions, units=dict(current.units or {}))
    return MotionCommand(
        robot_id=status.robot_id,
        source=MotionCommandSource.CONTROL,
        expected_state_sequence=status.state_sequence,
        expected_profile_fingerprint=profile.fingerprint,
        expected_kinematics_fingerprint=kinematics.model_for(profile).fingerprint,
        command_type=MotionCommandType.MOVE_JOINTS,
        payload=JointMovePayload(joint_state=target, duration_s=duration_s),
        idempotency_key=key,
    )


async def continuous_command(
    app: FastAPI,
    *,
    joint_id: str = "j12",
    direction: Literal[-1, 1] = 1,
    speed_units_s: float = 10.0,
    speed_scale: float = 1.0,
    key: str = "continuous",
) -> MotionCommand:
    robot: RobotApplicationService = app.state.robot_service
    kinematics: KinematicsService = app.state.kinematics_service
    status, profile, _ = await robot.get_motion_snapshot()
    definition = profile.definitions_by_id[joint_id]
    return MotionCommand(
        robot_id=status.robot_id,
        source=MotionCommandSource.CONTROL,
        expected_state_sequence=status.state_sequence,
        expected_profile_fingerprint=profile.fingerprint,
        expected_kinematics_fingerprint=kinematics.model_for(profile).fingerprint,
        command_type=MotionCommandType.CONTINUOUS_JOG,
        payload=ContinuousJogPayload(
            joint_id=joint_id,
            direction=direction,
            speed_units_s=speed_units_s,
            unit=definition.domain_unit,
        ),
        speed_scale=speed_scale,
        idempotency_key=key,
    )


def failed_checks(error: MotionPreflightError) -> set[str]:
    details = cast(dict[str, Any], error.details)
    return {item["name"] for item in details["preflight"]["checks"] if item["passed"] is False}


def test_disconnected_stale_and_fingerprint_mismatches_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        gateway: MotionSafetyGateway = app.state.motion_service.gateway
        disconnected = await move_command(app)
        with pytest.raises(MotionPreflightError) as rejected:
            await gateway.prepare(disconnected)
        assert failed_checks(rejected.value) == {"connected"}

        await robot.connect()
        valid = await move_command(app)
        for field, expected_check in (
            ("expected_profile_fingerprint", "profile_fingerprint"),
            ("expected_kinematics_fingerprint", "kinematics_fingerprint"),
            ("expected_state_sequence", "state_sequence"),
        ):
            bad_value: object = 0 if field == "expected_state_sequence" else "0" * 64
            with pytest.raises(MotionPreflightError) as mismatch:
                await gateway.prepare(valid.model_copy(update={field: bad_value}))
            assert expected_check in failed_checks(mismatch.value)

        runtime = robot.manager.get_active()
        original_read = runtime.driver.read_joint_state
        read_count = 0

        async def successful_observation() -> JointState:
            nonlocal read_count
            read_count += 1
            return await original_read()

        monkeypatch.setattr(runtime.driver, "read_joint_state", successful_observation)
        runtime.observed_monotonic -= robot.settings.robot_state_freshness_limit_s + 1.0
        refreshed = await robot.get_status()
        assert refreshed.stale is False
        assert read_count == 1

        async def failed_observation() -> JointState:
            raise RuntimeError("synthetic observation failure")

        monkeypatch.setattr(runtime.driver, "read_joint_state", failed_observation)
        runtime.observed_monotonic -= robot.settings.robot_state_freshness_limit_s + 1.0
        assert (await robot.get_status()).stale is True
        with pytest.raises(MotionPreflightError) as stale:
            await gateway.prepare(valid)
        assert "state_freshness" in failed_checks(stale.value)

    asyncio.run(scenario())


def test_timed_out_high_level_observation_is_cancelled_and_remains_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        await robot.connect()
        runtime = robot.manager.get_active()
        observation_cancelled = False

        async def blocked_observation() -> JointState:
            nonlocal observation_cancelled
            try:
                await asyncio.Event().wait()
                raise AssertionError("synthetic blocked observation unexpectedly resumed")
            finally:
                observation_cancelled = True

        monkeypatch.setattr(runtime.driver, "read_joint_state", blocked_observation)
        monkeypatch.setattr(robot_service_module, "STATE_OBSERVATION_TIMEOUT_S", 0.01)
        runtime.observed_monotonic -= robot.settings.robot_state_freshness_limit_s + 1.0
        status = await robot.get_status()

        assert status.stale is True
        assert observation_cancelled is True

    asyncio.run(scenario())


def test_failed_observation_is_stale_even_when_wall_clock_moves_backward(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        clock = FakeClock()
        robot.clock = clock
        await robot.connect()
        runtime = robot.manager.get_active()
        last_good_wall_time = runtime.updated_at

        await clock.advance(robot.settings.robot_state_freshness_limit_s + 1.0)
        monkeypatch.setattr(clock, "now", lambda: last_good_wall_time - timedelta(hours=1))

        async def failed_observation() -> JointState:
            raise RuntimeError("synthetic observation failure after wall-clock rollback")

        monkeypatch.setattr(runtime.driver, "read_joint_state", failed_observation)
        status = await robot.get_status()

        assert status.updated_at == last_good_wall_time
        assert status.stale is True

    asyncio.run(scenario())


def test_accepted_preflight_evidence_is_truthful_unique_and_source_is_enforced(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        gateway: MotionSafetyGateway = app.state.motion_service.gateway
        await robot.connect()
        intent = await move_command(app, key="truthful-evidence")
        prepared = await gateway.prepare(intent)

        passed_checks = [check for check in prepared.preflight.checks if check.passed]
        names = [check.name for check in prepared.preflight.checks]
        assert len(names) == len(set(names))
        for check in passed_checks:
            detail = check.detail.lower()
            assert not any(
                negative in detail
                for negative in ("does not", "unknown", "stale", "rejected", "exceeds")
            ), (check.name, check.detail)

        untrusted = intent.model_copy(
            update={
                "source": MotionCommandSource.LIBRARY,
                "command_type": MotionCommandType.HOME,
            }
        )
        with pytest.raises(MotionPreflightError) as rejected:
            await gateway.prepare(untrusted)
        assert "command_source" in failed_checks(rejected.value)

    asyncio.run(scenario())


@pytest.mark.parametrize("shape", ["missing", "unknown"])
def test_exact_joint_set_and_explicit_units_are_enforced(tmp_path: Path, shape: str) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        gateway: MotionSafetyGateway = app.state.motion_service.gateway
        await robot.connect()
        intent = await move_command(app)
        payload = cast(JointMovePayload, intent.payload)
        positions = dict(payload.joint_state.positions)
        units = dict(payload.joint_state.units or {})
        if shape == "missing":
            positions.pop("j15")
            units.pop("j15")
        else:
            positions["j99"] = 0.0
            units["j99"] = units["j11"]
        malformed = intent.model_copy(
            update={
                "payload": JointMovePayload(
                    joint_state=JointState(positions=positions, units=units),
                    duration_s=payload.duration_s,
                )
            }
        )
        with pytest.raises(MotionPreflightError) as rejected:
            await gateway.prepare(malformed)
        assert "logical_limits" in failed_checks(rejected.value)

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_joint_targets_never_reach_gateway(invalid: float) -> None:
    with pytest.raises(ValidationError):
        JointState(positions={"j11": invalid}, units={"j11": DomainUnit.DEG})


@pytest.mark.parametrize(
    ("changes", "duration_s", "expected_check"),
    [
        ({"j11": 181.0}, 3.0, "logical_limits"),
        ({"j11": 130.0}, 3.0, "target_delta"),
        ({"j11": 10.0}, 0.1, "provisional_dynamic_limits"),
    ],
)
def test_logical_delta_velocity_and_acceleration_limits_reject(
    tmp_path: Path,
    changes: dict[str, float],
    duration_s: float,
    expected_check: str,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        gateway: MotionSafetyGateway = app.state.motion_service.gateway
        await robot.connect()
        intent = await move_command(app, changes=changes, duration_s=duration_s)
        with pytest.raises(MotionPreflightError) as rejected:
            await gateway.prepare(intent)
        assert expected_check in failed_checks(rejected.value)

    asyncio.run(scenario())


def test_gateway_uses_cubic_smoothstep_peak_velocity_not_average_velocity(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        gateway: MotionSafetyGateway = app.state.motion_service.gateway
        await robot.connect()

        with pytest.raises(MotionPreflightError) as rejected:
            await gateway.prepare(
                await move_command(
                    app,
                    changes={"j11": 60.000001},
                    duration_s=1.0,
                    key="smoothstep-over-peak-speed",
                )
            )
        assert "provisional_dynamic_limits" in failed_checks(rejected.value)
        assert "speed limit" in str(rejected.value)

        accepted = await gateway.prepare(
            await move_command(
                app,
                changes={"j11": 60.0},
                duration_s=1.0,
                key="smoothstep-at-peak-speed",
            )
        )
        assert accepted.preflight.accepted is True

    asyncio.run(scenario())


def test_template_raw_derived_limit_is_checked_without_authorizing_real_motion(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path, use_calibration_examples=True)
        robot: RobotApplicationService = app.state.robot_service
        gateway: MotionSafetyGateway = app.state.motion_service.gateway
        await robot.connect()
        intent = await move_command(app, changes={"j12": 100.0}, duration_s=2.0)
        with pytest.raises(MotionPreflightError) as rejected:
            await gateway.prepare(intent)
        assert "raw_derived_limits" in failed_checks(rejected.value)

    asyncio.run(scenario())


def test_configured_calibration_mismatch_rejects_instead_of_falling_back_to_logical_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path, use_calibration_examples=True)
        robot: RobotApplicationService = app.state.robot_service
        gateway: MotionSafetyGateway = app.state.motion_service.gateway
        await robot.connect()
        calibration = gateway.calibration_service.get_for_variant(
            robot.manager.get_active().profile.variant
        )
        assert calibration is not None
        mismatched = calibration.model_copy(update={"profile_fingerprint": "0" * 64})
        monkeypatch.setattr(
            gateway.calibration_service,
            "get_for_variant",
            lambda _variant: mismatched,
        )

        with pytest.raises(MotionPreflightError) as rejected:
            await gateway.prepare(await move_command(app))
        assert "raw_derived_limits" in failed_checks(rejected.value)
        assert "incompatible" in str(rejected.value)

    asyncio.run(scenario())


def test_captured_current_state_must_also_be_within_raw_derived_limits(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path, use_calibration_examples=True)
        robot: RobotApplicationService = app.state.robot_service
        gateway: MotionSafetyGateway = app.state.motion_service.gateway
        await robot.connect()
        runtime = robot.manager.get_active()
        runtime.positions["j12"] = 100.0
        cast(Any, runtime.driver)._positions["j12"] = 100.0
        intent = await move_command(app, changes={"j11": 5.0}, key="raw-current")

        with pytest.raises(MotionPreflightError) as rejected:
            await gateway.prepare(intent)
        assert "raw_derived_limits" in failed_checks(rejected.value)
        assert "current state" in str(rejected.value)

    asyncio.run(scenario())


def test_continuous_jog_uses_bounded_raw_derived_envelope_and_path_preflight(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path, use_calibration_examples=True)
        robot: RobotApplicationService = app.state.robot_service
        gateway: MotionSafetyGateway = app.state.motion_service.gateway
        await robot.connect()
        intent = await continuous_command(app, joint_id="j12", speed_units_s=10.0)
        prepared = await gateway.prepare(intent)

        assert isinstance(prepared, PreparedContinuousJog)
        assert 0.0 < prepared.maximum < 120.0
        assert prepared.minimum == 0.0
        assert prepared.speed_units_s == 10.0
        assert 0.0 < prepared.acceleration_units_s2 <= 720.0
        passed = {check.name for check in prepared.preflight.checks if check.passed}
        assert {
            "raw_derived_limits",
            "target_delta",
            "provisional_dynamic_limits",
            "fk_valid",
            "workspace",
        } <= passed

    asyncio.run(scenario())


def test_effective_duration_and_continuous_effective_speed_have_resource_bounds(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        gateway: MotionSafetyGateway = app.state.motion_service.gateway
        await robot.connect()
        slow_move = (await move_command(app, duration_s=60.0)).model_copy(
            update={"speed_scale": 0.05}
        )
        with pytest.raises(MotionPreflightError) as duration_rejected:
            await gateway.prepare(slow_move)
        assert "provisional_dynamic_limits" in failed_checks(duration_rejected.value)

        slow_jog = await continuous_command(
            app,
            speed_units_s=0.1,
            speed_scale=0.05,
            key="too-slow",
        )
        with pytest.raises(MotionPreflightError) as speed_rejected:
            await gateway.prepare(slow_jog)
        assert "provisional_dynamic_limits" in failed_checks(speed_rejected.value)

    asyncio.run(scenario())


def test_workspace_and_ik_residual_failures_are_structured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        kinematics: KinematicsService = app.state.kinematics_service
        gateway: MotionSafetyGateway = app.state.motion_service.gateway
        await robot.connect()
        valid = await move_command(app)
        original_forward = kinematics.forward

        async def outside_workspace(*args: object, **kwargs: object) -> object:
            result = await original_forward(*args, **kwargs)  # type: ignore[arg-type]
            pose = result.tcp_pose.model_copy(
                update={"position_mm": Vector3(x=1000.0, y=0.0, z=0.0)}
            )
            return result.model_copy(update={"tcp_pose": pose})

        monkeypatch.setattr(kinematics, "forward", outside_workspace)
        with pytest.raises(MotionPreflightError) as workspace:
            await gateway.prepare(valid)
        assert "workspace" in failed_checks(workspace.value)
        monkeypatch.setattr(kinematics, "forward", original_forward)

        status, profile, _ = await robot.get_motion_snapshot()
        unreachable = MotionCommand(
            robot_id=status.robot_id,
            source=MotionCommandSource.CONTROL,
            expected_state_sequence=status.state_sequence,
            expected_profile_fingerprint=profile.fingerprint,
            expected_kinematics_fingerprint=kinematics.model_for(profile).fingerprint,
            command_type=MotionCommandType.MOVE_POSE,
            payload=MovePosePayload(
                target_pose=TcpPose(
                    frame="base",
                    position_mm=Vector3(x=10000.0, y=10000.0, z=10000.0),
                    orientation_quaternion_xyzw=QuaternionXYZW(x=0.0, y=0.0, z=0.0, w=1.0),
                ),
                duration_s=2.0,
            ),
            idempotency_key="unreachable",
        )
        with pytest.raises(MotionPreflightError) as ik:
            await gateway.prepare(unreachable)
        assert "ik_residual" in failed_checks(ik.value)

    asyncio.run(scenario())


def test_cartesian_jog_is_prepared_as_reviewed_tcp_samples(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        kinematics: KinematicsService = app.state.kinematics_service
        gateway: MotionSafetyGateway = app.state.motion_service.gateway
        await robot.connect()
        status, profile, _ = await robot.get_motion_snapshot()
        command = MotionCommand(
            robot_id=status.robot_id,
            source=MotionCommandSource.CONTROL,
            expected_state_sequence=status.state_sequence,
            expected_profile_fingerprint=profile.fingerprint,
            expected_kinematics_fingerprint=kinematics.model_for(profile).fingerprint,
            command_type=MotionCommandType.CARTESIAN_JOG,
            payload=CartesianJogPayload(
                delta_position_mm=Vector3(x=0.5, y=0.0, z=0.0),
                delta_rotation_deg=Vector3(x=0.0, y=0.0, z=0.0),
                frame=CartesianFrame.BASE,
                duration_s=1.0,
            ),
            idempotency_key="reviewed-cartesian-path",
        )

        prepared = await gateway.prepare(command)

        assert isinstance(prepared, PreparedMotion)
        assert prepared.trajectory_samples is not None
        assert len(prepared.trajectory_samples) == 26
        assert prepared.trajectory_samples[0].time_s == 0.0
        assert prepared.trajectory_samples[-1].time_s == pytest.approx(1.0)
        assert prepared.target_state == prepared.trajectory_samples[-1].joint_state
        passed = {check.name for check in prepared.preflight.checks if check.passed}
        assert {"ik_residual", "cartesian_continuity", "workspace"} <= passed

    asyncio.run(scenario())


def test_joint_path_sampling_rejects_midpoint_outside_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        kinematics: KinematicsService = app.state.kinematics_service
        gateway: MotionSafetyGateway = app.state.motion_service.gateway
        await robot.connect()
        intent = await move_command(app, changes={"j11": 10.0}, duration_s=1.0)
        original_forward = kinematics.forward

        async def midpoint_outside(
            profile: RobotProfile,
            state: JointState,
            *,
            state_sequence: int,
            robot_id: str = "primary",
        ) -> ForwardKinematicsResult:
            result = await original_forward(
                profile,
                state,
                state_sequence=state_sequence,
                robot_id=robot_id,
            )
            if state.positions["j11"] == pytest.approx(5.0):
                pose = result.tcp_pose.model_copy(
                    update={"position_mm": Vector3(x=1000.0, y=0.0, z=0.0)}
                )
                return result.model_copy(update={"tcp_pose": pose})
            return result

        monkeypatch.setattr(kinematics, "forward", midpoint_outside)
        with pytest.raises(MotionPreflightError) as rejected:
            await gateway.prepare(intent)
        assert "workspace" in failed_checks(rejected.value)
        assert "path sample 1/2" in str(rejected.value)

    asyncio.run(scenario())


def test_conflict_idempotency_and_stop_are_unified(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        motion: MotionApplicationService = app.state.motion_service
        await robot.connect()
        first = await move_command(app, duration_s=3.0, key="idempotent")
        accepted = await motion.submit(first)
        repeated = await motion.submit(first)
        assert repeated.command_id == accepted.command_id

        changed = await move_command(app, changes={"j11": 6.0}, key="idempotent")
        with pytest.raises(IdempotencyConflictError):
            await motion.submit(changed)
        competing = await move_command(app, key="competing")
        with pytest.raises(MotionPreflightError) as conflict:
            await motion.gateway.prepare(competing)
        assert "command_conflict" in failed_checks(conflict.value)

        stopped = await motion.stop()
        final = motion.get_status(accepted.command_id)
        assert stopped.result == "STOPPED"
        assert stopped.hardware_accessed is False
        assert final.state is MotionCommandState.CANCELLED
        assert motion.executor.active_command_id is None

    asyncio.run(scenario())


def test_stop_returns_while_inflight_preflight_is_blocked_and_invalidates_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        motion: MotionApplicationService = app.state.motion_service
        await robot.connect()
        intent = await move_command(app, duration_s=3.0, key="inflight")
        entered = asyncio.Event()
        release = asyncio.Event()
        original_prepare = motion.gateway.prepare

        async def slow_prepare(command: MotionCommand) -> object:
            prepared = await original_prepare(command)
            entered.set()
            await release.wait()
            return prepared

        monkeypatch.setattr(motion.gateway, "prepare", slow_prepare)
        submit_task = asyncio.create_task(motion.submit(intent))
        await entered.wait()
        stop_task = asyncio.create_task(motion.stop())
        stopped = await asyncio.wait_for(stop_task, timeout=0.2)
        assert stopped.result == "STOPPED"
        assert motion.executor.active_command_id is None
        assert motion.executor.get_status(intent.command_id) is None
        release.set()
        with pytest.raises(MotionConflictError, match="superseded"):
            await submit_task
        assert motion.executor.active_command_id is None
        assert motion.executor.get_status(intent.command_id) is None

    asyncio.run(scenario())


def test_intent_queued_during_stop_is_invalidated_and_never_starts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        motion: MotionApplicationService = app.state.motion_service
        await robot.connect()
        entered = asyncio.Event()
        release = asyncio.Event()
        original_stop = robot.stop

        async def slow_stop() -> object:
            entered.set()
            await release.wait()
            return await original_stop()

        monkeypatch.setattr(robot, "stop", slow_stop)
        stop_task = asyncio.create_task(motion.stop())
        await entered.wait()
        queued = await move_command(app, key="queued-during-stop")
        submit_task = asyncio.create_task(motion.submit(queued))
        await asyncio.sleep(0)
        release.set()
        await stop_task
        with pytest.raises(MotionConflictError, match="superseded"):
            await submit_task
        assert motion.executor.active_command_id is None
        assert motion.executor.get_status(queued.command_id) is None

    asyncio.run(scenario())


def test_stop_recovers_faulted_dry_run_robot_to_stable_disconnected_state(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        motion: MotionApplicationService = app.state.motion_service
        await robot.connect()
        await robot.mark_motion_fault(uuid4(), "SyntheticFailure")
        assert (await robot.get_status()).connection_state.value == "FAULTED"

        recovered = await motion.stop()
        assert recovered.result == "STOPPED"
        assert recovered.status.connection_state.value == "DISCONNECTED"
        assert recovered.status.last_error is None
        repeated = await motion.stop()
        assert repeated.result == "NOT_CONNECTED"
        assert repeated.status.connection_state.value == "DISCONNECTED"

    asyncio.run(scenario())


def test_global_stop_returns_without_waiting_for_blocked_runtime_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        motion: MotionApplicationService = app.state.motion_service
        await robot.connect()
        await robot.drain_runtime_persistence()
        entered = threading.Event()
        release = threading.Event()
        original_save = robot.runtime_repository.save

        def blocked_save(snapshot: RuntimeState) -> None:
            entered.set()
            if not release.wait(timeout=1.0):
                raise RuntimeError("synthetic persistence release timed out")
            original_save(snapshot)

        monkeypatch.setattr(robot.runtime_repository, "save", blocked_save)
        try:
            stopped = await asyncio.wait_for(motion.stop(), timeout=0.2)
            assert stopped.result == "STOPPED"
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(0)
            assert entered.is_set()
        finally:
            release.set()
            await robot.drain_runtime_persistence()

    asyncio.run(scenario())


def test_stale_jog_history_cannot_block_global_stop_of_active_motion(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = app_for(tmp_path)
        robot: RobotApplicationService = app.state.robot_service
        motion: MotionApplicationService = app.state.motion_service
        jog = cast(Any, app.state.jog_service)
        executor = cast(Any, motion.executor)
        await robot.connect()

        lease = await jog.start(await continuous_command(app, key="stale-jog"))
        await jog.stop(lease.jog_session_id)
        stale_session = jog._sessions[lease.jog_session_id]
        stale_session.stopped = False
        stale_session.last_state = MotionCommandState.RUNNING
        executor._statuses.pop(lease.command_id)

        active = await motion.submit(
            await move_command(app, duration_s=3.0, key="active-after-stale-jog")
        )
        assert motion.executor.active_command_id == active.command_id

        stopped = await motion.stop()

        assert stopped.result == "STOPPED"
        assert motion.get_status(active.command_id).state is MotionCommandState.CANCELLED
        assert motion.executor.active_command_id is None
        assert lease.jog_session_id not in jog._sessions

    asyncio.run(scenario())
