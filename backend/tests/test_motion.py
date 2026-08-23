"""Motion invariants and embedded snapshot tests (requirements 9-16)."""

from math import inf, nan
from typing import cast
from uuid import uuid4

import pytest
from pydantic import JsonValue, ValidationError

from momo.domain.enums import MotionMode, RobotVariant
from momo.domain.motion import Motion, MotionKeyframe, MotionTransition
from momo.domain.pose import Pose, PoseSnapshot
from momo.domain.profiles import canonical_robot_profile
from momo.domain.robot import RobotProfile
from tests.factories import make_motion, make_snapshot, make_transition


def test_motion_json_round_trip() -> None:
    motion = make_motion()
    restored = Motion.model_validate_json(motion.model_dump_json())
    assert restored == motion
    assert restored.keyframes[1].pose_snapshot == motion.keyframes[1].pose_snapshot


def test_motion_requires_at_least_two_keyframes() -> None:
    with pytest.raises(ValidationError, match=r"at least 2 items|at least two keyframes"):
        Motion(
            name="Too short",
            robot_variant=RobotVariant.V2,
            keyframes=[MotionKeyframe(label="Only", pose_snapshot=make_snapshot())],
        )


def test_first_keyframe_cannot_have_incoming_transition() -> None:
    with pytest.raises(ValidationError, match="first keyframe"):
        Motion(
            name="Invalid first transition",
            robot_variant=RobotVariant.V2,
            keyframes=[
                MotionKeyframe(
                    label="Start",
                    pose_snapshot=make_snapshot(),
                    incoming_transition=make_transition(),
                ),
                MotionKeyframe(
                    label="End",
                    pose_snapshot=make_snapshot(),
                    incoming_transition=make_transition(),
                ),
            ],
        )


def test_later_keyframes_require_incoming_transition() -> None:
    with pytest.raises(ValidationError, match="keyframe 1 must have"):
        Motion(
            name="Missing transition",
            robot_variant=RobotVariant.V2,
            keyframes=[
                MotionKeyframe(label="Start", pose_snapshot=make_snapshot()),
                MotionKeyframe(label="End", pose_snapshot=make_snapshot()),
            ],
        )


@pytest.mark.parametrize("duration", [0.0, -1.0])
def test_transition_duration_must_be_positive(duration: float) -> None:
    with pytest.raises(ValidationError, match="greater than 0"):
        MotionTransition(duration_s=duration, motion_mode=MotionMode.JOINT)


def test_hold_must_be_non_negative() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        MotionKeyframe(label="Invalid hold", pose_snapshot=make_snapshot(), hold_s=-0.1)


@pytest.mark.parametrize("not_finite", [nan, inf, -inf])
def test_motion_rejects_nonfinite_duration_and_hardware_snapshot(
    not_finite: float,
) -> None:
    with pytest.raises(ValidationError, match="finite number"):
        MotionTransition(duration_s=not_finite, motion_mode=MotionMode.JOINT)

    motion_data = make_motion().model_dump(mode="python")
    motion_data["keyframes"][0]["pose_snapshot"]["hardware_snapshot"] = {"raw": {"j10": not_finite}}
    with pytest.raises(ValidationError, match=r"hardware_snapshot.*finite"):
        Motion.model_validate(motion_data)


def test_motion_rejects_snapshot_variant_mismatch() -> None:
    with pytest.raises(ValidationError, match="does not match Motion variant V2"):
        Motion(
            name="Mixed variants",
            robot_variant=RobotVariant.V2,
            keyframes=[
                MotionKeyframe(label="V1", pose_snapshot=make_snapshot(RobotVariant.V1)),
                MotionKeyframe(
                    label="V2",
                    pose_snapshot=make_snapshot(RobotVariant.V2),
                    incoming_transition=make_transition(),
                ),
            ],
        )


def test_motion_validates_joint_states_against_variant_profile() -> None:
    snapshot_data = make_snapshot(RobotVariant.V2).model_dump(mode="python")
    snapshot_data["joint_state"]["positions"]["j10"] = 1001.0
    with pytest.raises(ValidationError, match=r"snapshot joint state is invalid.*outside"):
        Motion.model_validate(
            {
                "name": "Out of range",
                "robot_variant": "V2",
                "keyframes": [
                    {"label": "Start", "pose_snapshot": snapshot_data},
                    {
                        "label": "End",
                        "pose_snapshot": make_snapshot().model_dump(mode="python"),
                        "incoming_transition": {
                            "duration_s": 1.0,
                            "motion_mode": "JOINT",
                        },
                    },
                ],
            }
        )


def test_motion_can_validate_against_an_explicit_supplied_profile() -> None:
    profile_data = canonical_robot_profile(RobotVariant.V2).model_dump(mode="json")
    profile_data["joint_definitions"][0]["maximum"] = 50.0
    supplied_profile = RobotProfile.model_validate(profile_data)

    motion_data = make_motion().model_dump(mode="python")
    for keyframe in motion_data["keyframes"]:
        keyframe["pose_snapshot"]["joint_state"]["positions"]["j10"] = 100.0

    # The product placeholder profile permits 100 mm, while the supplied profile does not.
    canonical_motion = Motion.model_validate(motion_data)
    assert canonical_motion.keyframes
    with pytest.raises(ValidationError, match=r"snapshot joint state is invalid.*outside"):
        Motion.model_validate(motion_data, context={"robot_profile": supplied_profile})
    with pytest.raises(ValidationError, match=r"joint state is invalid.*outside"):
        Motion.model_validate(canonical_motion, context={"robot_profile": supplied_profile})


def test_source_pose_changes_or_deletion_do_not_change_embedded_snapshot() -> None:
    source = Pose(name="Source", snapshot=make_snapshot())
    keyframe = MotionKeyframe(
        label="Captured",
        pose_snapshot=source.snapshot,
        source_pose_id=source.id,
    )
    captured_json = keyframe.pose_snapshot.model_dump_json()

    # Simulate a later, fully revalidated Pose revision rather than mutating the entity.
    revised_data = source.model_dump(mode="python")
    revised_data.update(
        name="Renamed source",
        snapshot=make_snapshot(RobotVariant.V1).model_dump(mode="python"),
        revision=source.revision + 1,
    )
    revised_source = Pose.model_validate(revised_data)
    assert revised_source.id == source.id
    assert revised_source.snapshot.robot_variant is RobotVariant.V1
    assert keyframe.pose_snapshot.model_dump_json() == captured_json
    assert keyframe.source_pose_id is not None

    source_id = source.id
    del source
    assert keyframe.source_pose_id == source_id
    assert keyframe.pose_snapshot.model_dump_json() == captured_json


def test_embedded_snapshot_mappings_are_deeply_detached_and_immutable() -> None:
    raw_snapshot = make_snapshot().model_dump(mode="python")
    raw_snapshot["hardware_snapshot"] = {"raw": {"j10": 100, "history": [95, 98, 100]}}
    source = Pose(name="Nested source", snapshot=PoseSnapshot.model_validate(raw_snapshot))
    motion = Motion(
        name="Immutable capture",
        robot_variant=RobotVariant.V2,
        keyframes=[
            MotionKeyframe(
                label="Captured",
                pose_snapshot=source.snapshot,
                source_pose_id=source.id,
            ),
            MotionKeyframe(
                label="End",
                pose_snapshot=make_snapshot(),
                incoming_transition=make_transition(),
            ),
        ],
    )
    captured = motion.keyframes[0].pose_snapshot
    captured_json = captured.model_dump_json()

    # Mutating the caller's original dictionaries/lists cannot reach Pose or Motion.
    raw_snapshot["joint_state"]["positions"]["j11"] = 99.0
    raw_snapshot["hardware_snapshot"]["raw"]["j10"] = 999
    raw_snapshot["hardware_snapshot"]["raw"]["history"].append(999)
    assert captured.model_dump_json() == captured_json

    with pytest.raises(TypeError, match="immutable"):
        source.snapshot.joint_state.positions["j11"] = 12.0
    with pytest.raises(TypeError, match="immutable"):
        captured.joint_state.positions["j11"] = 12.0

    hardware = captured.hardware_snapshot
    assert hardware is not None
    with pytest.raises(TypeError, match="immutable"):
        hardware["raw"] = {}
    raw_hardware = cast(dict[str, JsonValue], hardware["raw"])
    with pytest.raises(TypeError, match="immutable"):
        raw_hardware["j10"] = 400
    history = cast(list[JsonValue], raw_hardware["history"])
    with pytest.raises(TypeError, match="immutable"):
        history.append(400)

    # Frozen dict/list subclasses remain ordinary JSON arrays/objects on the wire.
    assert Motion.model_validate_json(motion.model_dump_json()) == motion


def test_source_pose_id_is_metadata_not_a_required_reference() -> None:
    nonexistent_pose_id = uuid4()
    motion = Motion(
        name="Portable motion",
        robot_variant=RobotVariant.V2,
        keyframes=[
            MotionKeyframe(
                label="Start",
                pose_snapshot=make_snapshot(),
                source_pose_id=nonexistent_pose_id,
            ),
            MotionKeyframe(
                label="End",
                pose_snapshot=make_snapshot(),
                source_pose_id=nonexistent_pose_id,
                incoming_transition=make_transition(),
            ),
        ],
    )
    assert Motion.model_validate_json(motion.model_dump_json()) == motion


@pytest.mark.parametrize(
    "malformed_context",
    [
        {"robot_profile": {"variant": "V2"}},
        {"robot_profiles": {}},
        {"robot_profiles": {"V2": {"variant": "V2"}}},
    ],
)
def test_explicit_profile_context_fails_closed(malformed_context: object) -> None:
    with pytest.raises(ValidationError, match=r"validated RobotProfile|does not contain"):
        Motion.model_validate(make_motion().model_dump(mode="python"), context=malformed_context)
