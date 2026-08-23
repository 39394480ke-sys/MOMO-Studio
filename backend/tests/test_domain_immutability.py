"""Validated aggregates cannot be mutated into an invalid state in place."""

import pytest
from pydantic import ValidationError

from momo.domain.enums import RobotVariant
from momo.domain.pose import Pose
from momo.domain.profiles import canonical_robot_profile
from tests.factories import make_motion, make_snapshot


def test_robot_profile_collections_and_mapping_are_immutable() -> None:
    profile = canonical_robot_profile(RobotVariant.V2)
    with pytest.raises(TypeError, match="immutable"):
        profile.enabled_joints.append("j99")
    with pytest.raises(TypeError, match="immutable"):
        profile.joint_definitions.pop()

    mapping = profile.joint_definitions[0].hardware_mapping_placeholder
    assert mapping is not None
    with pytest.raises(TypeError, match="immutable"):
        mapping["status"] = "verified-without-review"


def test_pose_and_motion_edits_require_a_new_validated_revision() -> None:
    pose = Pose(name="Frozen pose", snapshot=make_snapshot())
    pose_name_field = "name"
    with pytest.raises(ValidationError, match="Instance is frozen"):
        setattr(pose, pose_name_field, "Changed without a revision")
    with pytest.raises(TypeError, match="immutable"):
        pose.tags.append("unvalidated")

    motion = make_motion()
    variant_field = "robot_variant"
    with pytest.raises(ValidationError, match="Instance is frozen"):
        setattr(motion, variant_field, RobotVariant.V1)
    with pytest.raises(TypeError, match="immutable"):
        motion.keyframes.pop()
    with pytest.raises(TypeError, match="immutable"):
        motion.tags.append("unvalidated")
