"""Stage 5 deterministic trajectory compiler and whole-plan preflight tests."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from itertools import pairwise
from math import atan2, cos, degrees, radians, sin
from typing import Any, TypeVar

import pytest
from pydantic import ValidationError

from momo.adapters.kinematics.model_repository import FileKinematicsModelRepository
from momo.adapters.kinematics.serial_chain import SerialChainKinematics
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.trajectory_compiler import (
    MAX_TRAJECTORY_SAMPLES,
    TrajectoryCompiler,
)
from momo.domain.calibration import CalibrationDocument
from momo.domain.enums import (
    ControlMode,
    DomainUnit,
    Easing,
    HardwareAccessPolicy,
    MotionCommandSource,
    MotionMode,
    RealReadiness,
    RobotVariant,
)
from momo.domain.kinematics.model import KinematicsModel
from momo.domain.kinematics.results import ForwardKinematicsResult, InverseKinematicsResult
from momo.domain.motion import Motion, MotionKeyframe, MotionTransition
from momo.domain.pose import PoseSnapshot, QuaternionXYZW, SnapshotJointState, TcpPose, Vector3
from momo.domain.profiles import canonical_robot_profile
from momo.domain.robot import JointState, RobotProfile
from momo.domain.trajectory import PreparedTrajectory, TrajectoryPlan, TrajectorySegmentKind
from momo.settings import repository_root
from tests.stage2_helpers import make_calibration

Result = TypeVar("Result")


def run(coroutine: Coroutine[Any, Any, Result]) -> Result:
    return asyncio.run(coroutine)


def yaw_quaternion(yaw_deg: float) -> QuaternionXYZW:
    half = radians(yaw_deg) / 2.0
    return QuaternionXYZW(x=0.0, y=0.0, z=sin(half), w=cos(half))


class SyntheticTrajectoryKinematics:
    """Deterministic Cartesian mapping with observable IK seed use."""

    def __init__(self) -> None:
        self.repository = FileKinematicsModelRepository(repository_root() / "kinematics_models")
        self.inverse_calls: list[tuple[TcpPose, JointState]] = []
        self.fail_inverse_call: int | None = None
        self.position_residual_mm = 0.0
        self.orientation_residual_deg: float | None = 0.0
        self.jump_inverse_call: int | None = None

    def model_for(self, profile: RobotProfile) -> KinematicsModel:
        return self.repository.get(profile.variant).validate_against_profile(profile)

    @staticmethod
    def tcp_for(profile: RobotProfile, state: JointState) -> TcpPose:
        positions = state.positions
        if profile.variant is RobotVariant.V1:
            x, y, z = positions["j11"], positions["j12"], 300.0 + positions["j13"]
            yaw = positions["j14"]
        else:
            x, y, z = positions["j10"], positions["j11"], 300.0 + positions["j12"]
            yaw = positions["j13"]
        return TcpPose(
            frame="base",
            position_mm=Vector3(x=x, y=y, z=z),
            orientation_quaternion_xyzw=yaw_quaternion(yaw),
        )

    async def forward(
        self,
        profile: RobotProfile,
        state: JointState,
        *,
        state_sequence: int,
        robot_id: str = "primary",
    ) -> ForwardKinematicsResult:
        state.validate_against(profile)
        return ForwardKinematicsResult(
            robot_id=robot_id,
            variant=profile.variant,
            state_sequence=state_sequence,
            profile_fingerprint=profile.fingerprint,
            kinematics_fingerprint=self.model_for(profile).fingerprint,
            tcp_pose=self.tcp_for(profile, state),
            hardware_accessed=False,
        )

    async def inverse(
        self,
        profile: RobotProfile,
        target: TcpPose,
        *,
        seed: JointState | None = None,
        position_only: bool = False,
        maximum_iterations: int = 200,
    ) -> InverseKinematicsResult:
        del position_only, maximum_iterations
        assert seed is not None
        detached_seed = JointState.model_validate(seed.model_dump(mode="python", round_trip=True))
        self.inverse_calls.append((target, detached_seed))
        call_number = len(self.inverse_calls)
        if self.fail_inverse_call == call_number:
            return InverseKinematicsResult(
                success=False,
                joint_state_optional=None,
                best_joint_state=seed,
                iterations=8,
                position_error_mm=5.0,
                orientation_error_deg=3.0,
                termination_reason="SYNTHETIC_UNREACHABLE",
                warnings=[],
                kinematics_fingerprint=self.model_for(profile).fingerprint,
            )
        position = target.position_mm
        quaternion = target.orientation_quaternion_xyzw
        yaw = degrees(
            atan2(
                2.0 * (quaternion.w * quaternion.z + quaternion.x * quaternion.y),
                1.0 - 2.0 * (quaternion.y**2 + quaternion.z**2),
            )
        )
        values = dict(seed.positions)
        if profile.variant is RobotVariant.V1:
            values.update(
                {
                    "j11": position.x,
                    "j12": position.y,
                    "j13": position.z - 300.0,
                    "j14": yaw,
                }
            )
        else:
            values.update(
                {
                    "j10": position.x,
                    "j11": position.y,
                    "j12": position.z - 300.0,
                    "j13": yaw,
                }
            )
        if self.jump_inverse_call == call_number:
            values["j15"] += 30.0
        state = JointState(positions=values, units=seed.units).validate_against(profile)
        return InverseKinematicsResult(
            success=True,
            joint_state_optional=state,
            best_joint_state=state,
            iterations=3,
            position_error_mm=self.position_residual_mm,
            orientation_error_deg=self.orientation_residual_deg,
            termination_reason="CONVERGED",
            warnings=[],
            kinematics_fingerprint=self.model_for(profile).fingerprint,
        )


def state_for(
    profile: RobotProfile,
    positions: dict[str, float] | None = None,
) -> JointState:
    overrides = positions or {}
    return JointState(
        positions={
            definition.joint_id: float(overrides.get(definition.joint_id, definition.home))
            for definition in profile.joint_definitions
        },
        units={
            definition.joint_id: definition.domain_unit for definition in profile.joint_definitions
        },
    )


def snapshot_for(
    kinematics: SyntheticTrajectoryKinematics,
    profile: RobotProfile,
    state: JointState,
    *,
    tcp_pose: TcpPose | None = None,
) -> PoseSnapshot:
    return PoseSnapshot(
        robot_variant=profile.variant,
        joint_state=SnapshotJointState.model_validate(
            state.model_dump(mode="python", round_trip=True)
        ),
        tcp_pose=tcp_pose or kinematics.tcp_for(profile, state),
        profile_fingerprint=profile.fingerprint,
        kinematics_fingerprint=kinematics.model_for(profile).fingerprint,
        state_sequence=7,
    )


def two_keyframe_motion(
    kinematics: SyntheticTrajectoryKinematics,
    profile: RobotProfile,
    *,
    start: JointState | None = None,
    end: JointState | None = None,
    duration_s: float = 1.0,
    mode: MotionMode = MotionMode.JOINT,
    easing: Easing = Easing.LINEAR,
    start_hold_s: float = 0.0,
    end_hold_s: float = 0.0,
    end_tcp_pose: TcpPose | None = None,
) -> Motion:
    first = start or state_for(profile)
    second = end or state_for(profile, {profile.enabled_joints[0]: 10.0})
    return Motion(
        name="Synthetic trajectory",
        robot_variant=profile.variant,
        keyframes=[
            MotionKeyframe(
                label="Start",
                pose_snapshot=snapshot_for(kinematics, profile, first),
                hold_s=start_hold_s,
            ),
            MotionKeyframe(
                label="End",
                pose_snapshot=snapshot_for(
                    kinematics,
                    profile,
                    second,
                    tcp_pose=end_tcp_pose,
                ),
                hold_s=end_hold_s,
                incoming_transition=MotionTransition(
                    duration_s=duration_s,
                    motion_mode=mode,
                    easing=easing,
                ),
            ),
        ],
    )


async def compile_motion(
    compiler: TrajectoryCompiler,
    motion: Motion,
    profile: RobotProfile,
    *,
    start_state: JointState | None = None,
    start_state_sequence: int = 9,
    expected_motion_revision: int | None = None,
    expected_robot_variant: RobotVariant | None = None,
    expected_profile_fingerprint: str | None = None,
    expected_kinematics_fingerprint: str | None = None,
    expected_state_sequence: int | None = None,
    sample_rate_hz: float = 20.0,
    calibration: CalibrationDocument | None = None,
    connected: bool = True,
    state_fresh: bool = True,
    hardware_access_policy: HardwareAccessPolicy = HardwareAccessPolicy.DISABLED,
    control_mode: ControlMode = ControlMode.DRY_RUN,
    stop_capable: bool = True,
    source: MotionCommandSource = MotionCommandSource.LIBRARY,
    real_readiness: RealReadiness = RealReadiness.BLOCKED_BY_STAGE_POLICY,
    field_acceptance_complete: bool = False,
    cancellation_requested: Any = None,
) -> Any:
    model = compiler.kinematics.model_for(profile)
    return await compiler.compile(
        motion=motion,
        profile=profile,
        start_state=start_state or motion.keyframes[0].pose_snapshot.joint_state,
        start_state_sequence=start_state_sequence,
        expected_motion_revision=(
            motion.revision if expected_motion_revision is None else expected_motion_revision
        ),
        expected_robot_variant=expected_robot_variant or profile.variant,
        expected_profile_fingerprint=(
            profile.fingerprint
            if expected_profile_fingerprint is None
            else expected_profile_fingerprint
        ),
        expected_kinematics_fingerprint=(
            model.fingerprint
            if expected_kinematics_fingerprint is None
            else expected_kinematics_fingerprint
        ),
        expected_state_sequence=(
            start_state_sequence if expected_state_sequence is None else expected_state_sequence
        ),
        connected=connected,
        state_fresh=state_fresh,
        hardware_access_policy=hardware_access_policy,
        sample_rate_hz=sample_rate_hz,
        calibration=calibration,
        control_mode=control_mode,
        stop_capable=stop_capable,
        source=source,
        real_readiness=real_readiness,
        field_acceptance_complete=field_acceptance_complete,
        cancellation_requested=cancellation_requested,
    )


def prepared(outcome: Any) -> PreparedTrajectory:
    assert outcome.report.accepted is True
    assert isinstance(outcome.prepared, PreparedTrajectory)
    return outcome.prepared


def violation_codes(outcome: Any) -> set[str]:
    return {violation.code for violation in outcome.report.violations}


def test_joint_linear_has_exact_endpoints_duration_units_and_monotonic_time() -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V1)
    motion = two_keyframe_motion(
        kinematics,
        profile,
        end=state_for(profile, {"j11": 10.0, "j12": -4.0}),
    )

    plan = prepared(run(compile_motion(TrajectoryCompiler(kinematics), motion, profile))).plan

    assert plan.duration_s == 1.0
    assert len(plan.samples) == 21
    assert plan.samples[0].time_s == 0.0
    assert plan.samples[-1].time_s == plan.duration_s
    assert all(current.time_s > previous.time_s for previous, current in pairwise(plan.samples))
    assert plan.samples[0].positions == motion.keyframes[0].pose_snapshot.joint_state.positions
    assert plan.samples[-1].positions == motion.keyframes[-1].pose_snapshot.joint_state.positions
    assert plan.samples[-1].units == {
        definition.joint_id: definition.domain_unit for definition in profile.joint_definitions
    }
    assert plan.segments[0].kind is TrajectorySegmentKind.JOINT


@pytest.mark.parametrize(
    ("easing", "expected_quarter"),
    [
        (Easing.SMOOTHSTEP, 1.5625),
        (Easing.EASE_IN_OUT, 1.03515625),
    ],
)
def test_joint_easing_curves_are_deterministic(
    easing: Easing,
    expected_quarter: float,
) -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V1)
    motion = two_keyframe_motion(
        kinematics,
        profile,
        end=state_for(profile, {"j11": 10.0}),
        easing=easing,
    )

    plan = prepared(
        run(
            compile_motion(
                TrajectoryCompiler(kinematics),
                motion,
                profile,
                sample_rate_hz=4.0,
            )
        )
    ).plan

    assert plan.samples[1].time_s == 0.25
    assert plan.samples[1].positions["j11"] == pytest.approx(expected_quarter)
    assert plan.samples[-1].positions["j11"] == 10.0


def test_holds_are_explicit_without_duplicate_boundary_times() -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V1)
    motion = two_keyframe_motion(
        kinematics,
        profile,
        end=state_for(profile, {"j11": 10.0}),
        start_hold_s=0.5,
        end_hold_s=0.5,
    )

    plan = prepared(
        run(
            compile_motion(
                TrajectoryCompiler(kinematics),
                motion,
                profile,
                sample_rate_hz=4.0,
            )
        )
    ).plan

    assert plan.duration_s == 2.0
    assert [segment.kind for segment in plan.segments] == [
        TrajectorySegmentKind.HOLD,
        TrajectorySegmentKind.JOINT,
        TrajectorySegmentKind.HOLD,
    ]
    assert [sample.time_s for sample in plan.samples] == [
        0.0,
        0.25,
        0.5,
        0.75,
        1.0,
        1.25,
        1.5,
        1.75,
        2.0,
    ]
    assert len({sample.time_s for sample in plan.samples}) == len(plan.samples)
    assert all(sample.positions["j11"] == 0.0 for sample in plan.samples[:3])
    assert all(sample.positions["j11"] == 10.0 for sample in plan.samples[-3:])
    assert all(sample.is_hold for sample in plan.samples[:3])
    assert all(sample.is_hold for sample in plan.samples[-2:])


@pytest.mark.parametrize(
    ("end_value", "duration_s", "code"),
    [
        (100.0, 0.5, "JOINT_VELOCITY_LIMIT"),
        (40.0, 1.0, "JOINT_ACCELERATION_LIMIT"),
    ],
)
def test_joint_velocity_and_acceleration_limits_fail_whole_plan(
    end_value: float,
    duration_s: float,
    code: str,
) -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V1)
    motion = two_keyframe_motion(
        kinematics,
        profile,
        end=state_for(profile, {"j11": end_value}),
        duration_s=duration_s,
    )

    outcome = run(compile_motion(TrajectoryCompiler(kinematics), motion, profile))

    assert outcome.prepared is None
    assert code in violation_codes(outcome)


def test_motion_duration_and_sample_count_are_bounded_before_allocation() -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V1)
    home = state_for(profile)
    snapshots = [snapshot_for(kinematics, profile, home) for _ in range(3)]
    too_long = Motion(
        name="Too long",
        robot_variant=profile.variant,
        keyframes=[
            MotionKeyframe(label="A", pose_snapshot=snapshots[0]),
            MotionKeyframe(
                label="B",
                pose_snapshot=snapshots[1],
                incoming_transition=MotionTransition(
                    duration_s=400.0,
                    motion_mode=MotionMode.JOINT,
                    easing=Easing.LINEAR,
                ),
            ),
            MotionKeyframe(
                label="C",
                pose_snapshot=snapshots[2],
                incoming_transition=MotionTransition(
                    duration_s=400.0,
                    motion_mode=MotionMode.JOINT,
                    easing=Easing.LINEAR,
                ),
            ),
        ],
    )
    sample_heavy = two_keyframe_motion(
        kinematics,
        profile,
        start=home,
        end=home,
        duration_s=600.0,
    )

    long_outcome = run(compile_motion(TrajectoryCompiler(kinematics), too_long, profile))
    sample_outcome = run(
        compile_motion(
            TrajectoryCompiler(kinematics),
            sample_heavy,
            profile,
            sample_rate_hz=100.0,
        )
    )

    assert "MOTION_DURATION_LIMIT" in violation_codes(long_outcome)
    assert "SAMPLE_COUNT_LIMIT" in violation_codes(sample_outcome)
    assert sample_outcome.report.sample_count == MAX_TRAJECTORY_SAMPLES
    sample_violation = next(
        violation
        for violation in sample_outcome.report.violations
        if violation.code == "SAMPLE_COUNT_LIMIT"
    )
    assert sample_violation.actual == 60_001
    assert sample_outcome.prepared is None


def test_digest_is_deterministic_and_excludes_compilation_timestamp() -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V1)
    motion = two_keyframe_motion(kinematics, profile)
    compiler = TrajectoryCompiler(kinematics)

    first = prepared(run(compile_motion(compiler, motion, profile)))
    second = prepared(run(compile_motion(compiler, motion, profile)))
    changed_rate = prepared(run(compile_motion(compiler, motion, profile, sample_rate_hz=10.0)))

    assert first.plan.compiled_at != second.plan.compiled_at
    assert first.plan.digest == second.plan.digest
    assert changed_rate.plan.digest != first.plan.digest


def test_v2_samples_preserve_prismatic_mm_and_revolute_deg_units() -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V2)
    motion = two_keyframe_motion(
        kinematics,
        profile,
        end=state_for(profile, {"j10": 20.0, "j11": 5.0}),
        duration_s=2.0,
    )

    plan = prepared(run(compile_motion(TrajectoryCompiler(kinematics), motion, profile))).plan

    assert plan.samples[-1].units["j10"] is DomainUnit.MM
    assert plan.samples[-1].units["j11"] is DomainUnit.DEG


def test_cartesian_position_is_straight_and_ik_runs_at_every_generated_sample() -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V1)
    motion = two_keyframe_motion(
        kinematics,
        profile,
        end=state_for(profile, {"j11": 20.0, "j12": -8.0}),
        duration_s=2.0,
        mode=MotionMode.CARTESIAN_LINEAR,
    )

    plan = prepared(
        run(
            compile_motion(
                TrajectoryCompiler(kinematics),
                motion,
                profile,
                sample_rate_hz=4.0,
            )
        )
    ).plan

    assert len(kinematics.inverse_calls) == 8
    for sample in plan.samples:
        fraction = sample.time_s / plan.duration_s
        assert sample.tcp_pose is not None
        assert sample.tcp_pose.position_mm.x == pytest.approx(20.0 * fraction)
        assert sample.tcp_pose.position_mm.y == pytest.approx(-8.0 * fraction)
    assert plan.samples[-1].positions == motion.keyframes[-1].pose_snapshot.joint_state.positions
    assert plan.segments[0].kind is TrajectorySegmentKind.CARTESIAN_LINEAR


def test_cartesian_quaternion_uses_shortest_path_slerp() -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V1)
    start = state_for(profile)
    end = state_for(profile, {"j14": -160.0})
    # +200 degrees is the sign-opposite quaternion for the same endpoint as -160.
    motion = two_keyframe_motion(
        kinematics,
        profile,
        start=start,
        end=end,
        duration_s=4.0,
        mode=MotionMode.CARTESIAN_LINEAR,
        end_tcp_pose=TcpPose(
            frame="base",
            position_mm=kinematics.tcp_for(profile, end).position_mm,
            orientation_quaternion_xyzw=yaw_quaternion(200.0),
        ),
    )

    plan = prepared(
        run(
            compile_motion(
                TrajectoryCompiler(kinematics),
                motion,
                profile,
                sample_rate_hz=4.0,
            )
        )
    ).plan
    midpoint = next(sample for sample in plan.samples if sample.time_s == 2.0)
    assert midpoint.tcp_pose is not None
    quaternion = midpoint.tcp_pose.orientation_quaternion_xyzw
    midpoint_yaw = degrees(atan2(2.0 * quaternion.w * quaternion.z, 1.0 - 2.0 * quaternion.z**2))

    assert midpoint_yaw == pytest.approx(-80.0)
    assert plan.samples[-1].positions["j14"] == pytest.approx(-160.0)


def test_cartesian_each_ik_seed_is_the_previous_solution() -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V1)
    motion = two_keyframe_motion(
        kinematics,
        profile,
        end=state_for(profile, {"j11": 12.0, "j12": 4.0}),
        duration_s=2.0,
        mode=MotionMode.CARTESIAN_LINEAR,
    )

    plan = prepared(
        run(
            compile_motion(
                TrajectoryCompiler(kinematics),
                motion,
                profile,
                sample_rate_hz=4.0,
            )
        )
    ).plan

    assert kinematics.inverse_calls[0][1].positions == plan.samples[0].positions
    for call_index, (_, seed) in enumerate(kinematics.inverse_calls[1:], start=1):
        assert seed.positions == plan.samples[call_index].positions


def test_cartesian_real_serial_chain_reaches_tcp_endpoint_without_joint_fallback() -> None:
    profile = canonical_robot_profile(RobotVariant.V1)
    service = KinematicsService(
        FileKinematicsModelRepository(repository_root() / "kinematics_models"),
        SerialChainKinematics(),
    )
    model = service.model_for(profile)
    start = state_for(profile)
    end = state_for(profile, {"j11": 5.0})

    async def scenario() -> tuple[Any, TcpPose]:
        start_fk = await service.forward(profile, start, state_sequence=9)
        end_fk = await service.forward(profile, end, state_sequence=9)
        motion = Motion(
            name="Real serial-chain Cartesian",
            robot_variant=profile.variant,
            keyframes=[
                MotionKeyframe(
                    label="Start",
                    pose_snapshot=PoseSnapshot(
                        robot_variant=profile.variant,
                        joint_state=SnapshotJointState.model_validate(
                            start.model_dump(mode="python", round_trip=True)
                        ),
                        tcp_pose=start_fk.tcp_pose,
                        profile_fingerprint=profile.fingerprint,
                        kinematics_fingerprint=model.fingerprint,
                        state_sequence=9,
                    ),
                ),
                MotionKeyframe(
                    label="End",
                    pose_snapshot=PoseSnapshot(
                        robot_variant=profile.variant,
                        joint_state=SnapshotJointState.model_validate(
                            end.model_dump(mode="python", round_trip=True)
                        ),
                        tcp_pose=end_fk.tcp_pose,
                        profile_fingerprint=profile.fingerprint,
                        kinematics_fingerprint=model.fingerprint,
                        state_sequence=9,
                    ),
                    incoming_transition=MotionTransition(
                        duration_s=3.0,
                        motion_mode=MotionMode.CARTESIAN_LINEAR,
                        easing=Easing.SMOOTHSTEP,
                    ),
                ),
            ],
        )
        outcome = await compile_motion(
            TrajectoryCompiler(service),
            motion,
            profile,
            sample_rate_hz=5.0,
        )
        result = prepared(outcome)
        last = result.plan.samples[-1]
        actual_fk = await service.forward(
            profile,
            JointState(positions=dict(last.positions), units=dict(last.units)),
            state_sequence=9,
        )
        return result, actual_fk.tcp_pose

    value, actual_tcp = run(scenario())

    assert len(value.plan.samples) == 16
    assert value.plan.segments[0].kind is TrajectorySegmentKind.CARTESIAN_LINEAR
    expected_tcp = value.plan.samples[-1].tcp_pose
    assert expected_tcp is not None
    assert actual_tcp.position_mm.x == pytest.approx(expected_tcp.position_mm.x, abs=1.0)
    assert actual_tcp.position_mm.y == pytest.approx(expected_tcp.position_mm.y, abs=1.0)
    assert actual_tcp.position_mm.z == pytest.approx(expected_tcp.position_mm.z, abs=1.0)


def test_production_cpu_kinematics_yields_before_accepting_a_cancelled_compile() -> None:
    profile = canonical_robot_profile(RobotVariant.V1)
    service = KinematicsService(
        FileKinematicsModelRepository(repository_root() / "kinematics_models"),
        SerialChainKinematics(),
    )
    model = service.model_for(profile)
    start = state_for(profile)
    end = state_for(profile, {"j11": 0.1})

    async def scenario() -> tuple[Any, list[str]]:
        start_fk = await service.forward(profile, start, state_sequence=9)
        end_fk = await service.forward(profile, end, state_sequence=9)
        motion = Motion(
            name="Cancelable serial-chain compile",
            robot_variant=profile.variant,
            keyframes=[
                MotionKeyframe(
                    label="Start",
                    pose_snapshot=PoseSnapshot(
                        robot_variant=profile.variant,
                        joint_state=SnapshotJointState.model_validate(
                            start.model_dump(mode="python", round_trip=True)
                        ),
                        tcp_pose=start_fk.tcp_pose,
                        profile_fingerprint=profile.fingerprint,
                        kinematics_fingerprint=model.fingerprint,
                        state_sequence=9,
                    ),
                ),
                MotionKeyframe(
                    label="End",
                    pose_snapshot=PoseSnapshot(
                        robot_variant=profile.variant,
                        joint_state=SnapshotJointState.model_validate(
                            end.model_dump(mode="python", round_trip=True)
                        ),
                        tcp_pose=end_fk.tcp_pose,
                        profile_fingerprint=profile.fingerprint,
                        kinematics_fingerprint=model.fingerprint,
                        state_sequence=9,
                    ),
                    incoming_transition=MotionTransition(
                        duration_s=300.0,
                        motion_mode=MotionMode.JOINT,
                        easing=Easing.LINEAR,
                    ),
                ),
            ],
        )
        cancellation = asyncio.Event()
        order: list[str] = []

        async def lifecycle_stop() -> None:
            await asyncio.sleep(0)
            order.append("stop")
            cancellation.set()

        stop_task = asyncio.create_task(lifecycle_stop())
        outcome = await compile_motion(
            TrajectoryCompiler(service),
            motion,
            profile,
            sample_rate_hz=50.0,
            cancellation_requested=cancellation.is_set,
        )
        order.append("compile")
        await stop_task
        return outcome, order

    outcome, order = run(scenario())

    assert outcome.prepared is None
    assert "COMPILATION_CANCELLED" in violation_codes(outcome)
    assert order == ["stop", "compile"]


@pytest.mark.parametrize(
    ("configure", "expected_code"),
    [
        (lambda fake: setattr(fake, "fail_inverse_call", 2), "IK_FAILED"),
        (lambda fake: setattr(fake, "jump_inverse_call", 1), "CARTESIAN_JOINT_JUMP"),
        (lambda fake: setattr(fake, "position_residual_mm", 2.0), "IK_POSITION_RESIDUAL"),
        (
            lambda fake: setattr(fake, "orientation_residual_deg", None),
            "IK_ORIENTATION_RESIDUAL",
        ),
    ],
)
def test_cartesian_failure_rejects_whole_plan_without_joint_fallback(
    configure: Any,
    expected_code: str,
) -> None:
    kinematics = SyntheticTrajectoryKinematics()
    configure(kinematics)
    profile = canonical_robot_profile(RobotVariant.V1)
    motion = two_keyframe_motion(
        kinematics,
        profile,
        end=state_for(profile, {"j11": 20.0}),
        duration_s=2.0,
        mode=MotionMode.CARTESIAN_LINEAR,
    )

    outcome = run(
        compile_motion(
            TrajectoryCompiler(kinematics),
            motion,
            profile,
            sample_rate_hz=4.0,
        )
    )

    assert outcome.report.accepted is False
    assert outcome.prepared is None
    assert expected_code in violation_codes(outcome)
    assert all(check.name != "digest" for check in outcome.report.checks)


def test_workspace_violation_rejects_valid_joint_state() -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V2)
    outside = state_for(profile, {"j10": 800.0})
    motion = two_keyframe_motion(
        kinematics,
        profile,
        start=outside,
        end=outside,
        mode=MotionMode.CARTESIAN_LINEAR,
    )

    outcome = run(compile_motion(TrajectoryCompiler(kinematics), motion, profile))

    assert "WORKSPACE_VIOLATION" in violation_codes(outcome)
    assert outcome.prepared is None


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("state_sequence", "STATE_SEQUENCE_MISMATCH"),
        ("motion_revision", "MOTION_REVISION_MISMATCH"),
        ("profile", "PROFILE_MISMATCH"),
        ("kinematics", "KINEMATICS_MISMATCH"),
        ("variant", "VARIANT_MISMATCH"),
        ("connected", "ROBOT_NOT_CONNECTED"),
        ("fresh", "ROBOT_STATE_STALE"),
        ("hardware_policy", "HARDWARE_ACCESS_POLICY_INVALID"),
        ("stop", "STOP_CAPABILITY_UNAVAILABLE"),
        ("control_mode", "REAL_MOTION_DISABLED"),
        ("source", "SOURCE_NOT_ALLOWED"),
        ("real_readiness", "REAL_READINESS_INVALID"),
        ("field_acceptance", "FIELD_ACCEPTANCE_INVALID"),
    ],
)
def test_preflight_binding_and_readiness_mismatches_fail_closed(
    case: str,
    expected_code: str,
) -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V1)
    motion = two_keyframe_motion(kinematics, profile)

    outcome = run(
        compile_motion(
            TrajectoryCompiler(kinematics),
            motion,
            profile,
            expected_state_sequence=8 if case == "state_sequence" else None,
            expected_motion_revision=2 if case == "motion_revision" else None,
            expected_profile_fingerprint="f" * 64 if case == "profile" else None,
            expected_kinematics_fingerprint="e" * 64 if case == "kinematics" else None,
            expected_robot_variant=RobotVariant.V2 if case == "variant" else None,
            connected=case != "connected",
            state_fresh=case != "fresh",
            hardware_access_policy=(
                HardwareAccessPolicy.READ_ONLY
                if case == "hardware_policy"
                else HardwareAccessPolicy.DISABLED
            ),
            stop_capable=case != "stop",
            control_mode=ControlMode.REAL if case == "control_mode" else ControlMode.DRY_RUN,
            source=(
                MotionCommandSource.STUDIO if case == "source" else MotionCommandSource.LIBRARY
            ),
            real_readiness=(
                RealReadiness.READY
                if case == "real_readiness"
                else RealReadiness.BLOCKED_BY_STAGE_POLICY
            ),
            field_acceptance_complete=case == "field_acceptance",
        )
    )

    assert expected_code in violation_codes(outcome)
    assert outcome.prepared is None
    assert outcome.report.real_motion_ready is False
    assert outcome.report.field_acceptance_ready is False
    assert outcome.report.hardware_accessed is False


def test_start_state_must_match_first_keyframe_without_implicit_entry_move() -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V1)
    motion = two_keyframe_motion(kinematics, profile)

    outcome = run(
        compile_motion(
            TrajectoryCompiler(kinematics),
            motion,
            profile,
            start_state=state_for(profile, {"j11": 1.0}),
        )
    )

    assert "START_STATE_MISMATCH" in violation_codes(outcome)
    assert outcome.prepared is None


def test_embedded_joint_limit_violation_is_rejected() -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V1)
    motion = two_keyframe_motion(
        kinematics,
        profile,
        end=state_for(profile).model_copy(
            update={
                "positions": {
                    **state_for(profile).positions,
                    "j11": 181.0,
                }
            }
        ),
    )

    outcome = run(compile_motion(TrajectoryCompiler(kinematics), motion, profile))

    assert "JOINT_LIMIT_VIOLATION" in violation_codes(outcome)
    assert outcome.prepared is None


def test_compatible_calibration_enforces_raw_derived_limits() -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V1)
    motion = two_keyframe_motion(
        kinematics,
        profile,
        end=state_for(profile, {"j11": 1.0}),
        duration_s=2.0,
    )
    calibration = make_calibration(profile)
    narrowed_joints = [
        joint.model_copy(update={"raw_bounds": (-5, 5)}) for joint in calibration.joints
    ]
    narrowed = calibration.model_copy(update={"joints": narrowed_joints})

    outcome = run(
        compile_motion(
            TrajectoryCompiler(kinematics),
            motion,
            profile,
            calibration=narrowed,
        )
    )

    assert "RAW_DERIVED_LIMIT_VIOLATION" in violation_codes(outcome)
    assert outcome.prepared is None


def test_compilation_can_be_cancelled_during_sampling() -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V1)
    motion = two_keyframe_motion(
        kinematics,
        profile,
        end=state_for(profile, {"j11": 10.0}),
        duration_s=2.0,
    )
    calls = 0

    def cancellation_requested() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 4

    outcome = run(
        compile_motion(
            TrajectoryCompiler(kinematics),
            motion,
            profile,
            cancellation_requested=cancellation_requested,
        )
    )

    assert "COMPILATION_CANCELLED" in violation_codes(outcome)
    assert outcome.prepared is None
    assert calls == 4


def test_prepared_trajectory_is_deeply_immutable_and_rechecks_all_bindings() -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V1)
    motion = two_keyframe_motion(kinematics, profile)
    value = prepared(run(compile_motion(TrajectoryCompiler(kinematics), motion, profile)))

    with pytest.raises(ValidationError, match="frozen"):
        value.plan.duration_s = 2.0  # type: ignore[misc]
    with pytest.raises(TypeError, match="immutable"):
        value.plan.samples.append(value.plan.samples[-1])
    with pytest.raises(TypeError, match="immutable"):
        value.plan.samples[0].positions["j11"] = 50.0
    with pytest.raises(TypeError, match="immutable"):
        value.preflight.violations.append(
            value.binding_violations(
                motion_revision=2,
                robot_variant=profile.variant,
                profile_fingerprint=profile.fingerprint,
                kinematics_fingerprint=kinematics.model_for(profile).fingerprint,
                state_sequence=9,
            )[0]
        )

    assert value.trajectory_id == value.plan.digest.sha256
    assert value.initial_state_sequence == 9
    assert value.sampling_interval_s == pytest.approx(0.05)
    assert {
        violation.code
        for violation in value.binding_violations(
            motion_revision=2,
            robot_variant=RobotVariant.V2,
            profile_fingerprint="f" * 64,
            kinematics_fingerprint="e" * 64,
            state_sequence=10,
        )
    } == {
        "MOTION_REVISION_CHANGED",
        "VARIANT_CHANGED",
        "PROFILE_CHANGED",
        "KINEMATICS_CHANGED",
        "STATE_SEQUENCE_CHANGED",
    }

    tampered = value.plan.model_dump(mode="python", round_trip=True)
    tampered["samples"][1]["positions"]["j11"] += 0.01
    with pytest.raises(ValidationError, match="digest"):
        TrajectoryPlan.model_validate(tampered)


def test_sample_rate_and_nonfinite_requests_are_bounded_structured_rejections() -> None:
    kinematics = SyntheticTrajectoryKinematics()
    profile = canonical_robot_profile(RobotVariant.V1)
    motion = two_keyframe_motion(kinematics, profile)

    for invalid in (0.0, 101.0, float("nan"), float("inf")):
        outcome = run(
            compile_motion(
                TrajectoryCompiler(kinematics),
                motion,
                profile,
                sample_rate_hz=invalid,
            )
        )
        assert "SAMPLE_RATE_INVALID" in violation_codes(outcome)
        assert outcome.prepared is None
