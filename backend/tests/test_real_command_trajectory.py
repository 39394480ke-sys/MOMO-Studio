"""Formal command compilation must preserve gateway-reviewed Cartesian samples."""

from datetime import UTC, datetime
from uuid import uuid4

from momo.application.services.command_trajectory_compiler import (
    compile_gateway_command_trajectory,
)
from momo.domain.enums import Easing
from momo.domain.motion_preflight import PreparedMotion, PreparedMotionSample
from momo.domain.robot import JointState
from momo.domain.trajectory import TrajectorySegmentKind
from tests.stage3_helpers import make_preflight
from tests.stage8_hardware_helpers import real_profile


def test_real_cartesian_command_consumes_exact_gateway_samples() -> None:
    profile = real_profile()
    units = {
        definition.joint_id: definition.domain_unit for definition in profile.joint_definitions
    }
    start_positions = {
        definition.joint_id: definition.home for definition in profile.joint_definitions
    }
    middle_positions = dict(start_positions)
    target_positions = dict(start_positions)
    middle_positions["j11"] = 17.0
    target_positions["j11"] = 20.0
    start = JointState(positions=start_positions, units=units)
    middle = JointState(positions=middle_positions, units=units)
    target = JointState(positions=target_positions, units=units)
    command_id = uuid4()
    prepared = PreparedMotion(
        command_id=command_id,
        start_state=start,
        target_state=target,
        duration_s=1.0,
        trajectory_samples=[
            PreparedMotionSample(time_s=0.0, joint_state=start),
            PreparedMotionSample(time_s=0.25, joint_state=middle),
            PreparedMotionSample(time_s=1.0, joint_state=target),
        ],
        preflight=make_preflight(command_id),
    )

    trajectory = compile_gateway_command_trajectory(
        prepared,
        profile,
        state_sequence=7,
        segment_kind=TrajectorySegmentKind.CARTESIAN_LINEAR,
        compiled_at=datetime(2026, 8, 29, tzinfo=UTC),
        update_hz=25.0,
    )

    assert [sample.time_s for sample in trajectory.plan.samples] == [0.0, 0.25, 1.0]
    assert trajectory.plan.samples[1].positions["j11"] == 17.0
    assert trajectory.plan.segments[0].kind is TrajectorySegmentKind.CARTESIAN_LINEAR
    assert trajectory.plan.segments[0].easing is Easing.LINEAR
    assert trajectory.preflight.digest == trajectory.plan.digest
    assert trajectory.preflight.real_motion_ready is False
    assert trajectory.preflight.field_acceptance_ready is False
