"""Canonical quaternion and Pose serialization tests (requirements 7-8)."""

from math import sqrt

import pytest
from pydantic import ValidationError

from momo.domain.enums import RobotVariant
from momo.domain.pose import Pose, PoseSnapshot, QuaternionXYZW
from momo.domain.profiles import canonical_robot_profile
from tests.factories import make_snapshot


def test_tcp_quaternion_is_normalized_and_zero_is_rejected() -> None:
    quaternion = QuaternionXYZW(x=1.0, y=2.0, z=3.0, w=4.0)
    norm = sqrt(quaternion.x**2 + quaternion.y**2 + quaternion.z**2 + quaternion.w**2)
    assert norm == pytest.approx(1.0)

    with pytest.raises(ValidationError, match="norm must be non-zero"):
        QuaternionXYZW(x=0.0, y=0.0, z=0.0, w=0.0)


def test_pose_json_round_trip() -> None:
    pose = Pose(
        name="Hero angle",
        description="A repeatable framing position",
        tags=["portrait", "eye-level"],
        snapshot=make_snapshot(),
    )
    restored = Pose.model_validate_json(pose.model_dump_json())
    assert restored == pose
    assert restored.id == pose.id


def test_v1_snapshot_rejects_a_missing_enabled_joint() -> None:
    data = make_snapshot(RobotVariant.V1).model_dump(mode="python")
    del data["joint_state"]["positions"]["j15"]
    with pytest.raises(ValidationError, match=r"snapshot joint state.*missing.*j15"):
        PoseSnapshot.model_validate(data)


def test_v2_snapshot_rejects_an_unknown_joint() -> None:
    data = make_snapshot(RobotVariant.V2).model_dump(mode="python")
    data["joint_state"]["positions"]["j99"] = 0.0
    with pytest.raises(ValidationError, match=r"snapshot joint state.*unknown.*j99"):
        PoseSnapshot.model_validate(data)


def test_snapshot_rejects_joint_state_from_another_variant() -> None:
    data = make_snapshot(RobotVariant.V2).model_dump(mode="python")
    data["robot_variant"] = "V1"
    with pytest.raises(ValidationError, match=r"snapshot joint state.*unknown.*j10"):
        PoseSnapshot.model_validate(data)


def test_snapshot_rejects_a_supplied_profile_for_another_variant() -> None:
    data = make_snapshot(RobotVariant.V1).model_dump(mode="python")
    with pytest.raises(ValidationError, match=r"profile V2 does not match snapshot variant V1"):
        PoseSnapshot.model_validate(
            data,
            context={"robot_profile": canonical_robot_profile(RobotVariant.V2)},
        )


def test_snapshot_rejects_a_position_outside_its_profile_range() -> None:
    data = make_snapshot(RobotVariant.V2).model_dump(mode="python")
    data["joint_state"]["positions"]["j10"] = 1001.0
    with pytest.raises(ValidationError, match=r"snapshot joint state.*outside"):
        PoseSnapshot.model_validate(data)
