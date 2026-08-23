"""Stage 4 persisted-schema compatibility and resource-bound invariants."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from momo.domain.motion import LegacyImportMetadata, Motion, MotionKeyframe, PlaybackDefaults
from momo.domain.pose import Pose, PoseSnapshot
from tests.factories import make_motion, make_snapshot, make_transition


def test_v1_pose_and_motion_require_explicit_migration() -> None:
    pose_data = Pose(name="Current", snapshot=make_snapshot()).model_dump(mode="python")
    pose_data["schema_version"] = "1.0.0"
    for field in ("profile_fingerprint", "kinematics_fingerprint", "state_sequence"):
        pose_data["snapshot"].pop(field)
    with pytest.raises(ValidationError, match=r"2\.0\.0"):
        Pose.model_validate(pose_data)

    motion_data = make_motion().model_dump(mode="python")
    motion_data["schema_version"] = "1.0.0"
    with pytest.raises(ValidationError, match=r"2\.0\.0"):
        Motion.model_validate(motion_data)


def test_v2_schema_artifacts_require_new_snapshot_contract() -> None:
    from momo.settings import repository_root

    root = repository_root()
    pose_schema = json.loads((root / "docs/schemas/pose.schema.json").read_text())
    motion_schema = json.loads((root / "docs/schemas/motion.schema.json").read_text())
    assert pose_schema["properties"]["schema_version"]["const"] == "2.0.0"
    assert motion_schema["properties"]["schema_version"]["const"] == "2.0.0"
    required = set(pose_schema["$defs"]["PoseSnapshot"]["required"])
    assert {"profile_fingerprint", "kinematics_fingerprint", "state_sequence"} <= required
    assert "units" in pose_schema["$defs"]["SnapshotJointState"]["required"]
    assert "units" in motion_schema["$defs"]["SnapshotJointState"]["required"]


def test_snapshot_joint_units_are_required_and_exact_without_changing_generic_state() -> None:
    snapshot = make_snapshot().model_dump(mode="python")
    del snapshot["joint_state"]["units"]
    with pytest.raises(ValidationError, match="Field required"):
        PoseSnapshot.model_validate(snapshot)

    snapshot = make_snapshot().model_dump(mode="python")
    snapshot["joint_state"]["units"] = None
    with pytest.raises(ValidationError, match="valid dictionary"):
        PoseSnapshot.model_validate(snapshot)

    snapshot = make_snapshot().model_dump(mode="python")
    snapshot["joint_state"]["units"]["j10"] = "deg"
    with pytest.raises(ValidationError, match="units must exactly match"):
        PoseSnapshot.model_validate(snapshot)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("description", "x" * 5001, "at most 5000"),
        ("tags", [f"tag-{index}" for index in range(33)], "at most 32"),
        ("tags", ["x" * 65], "at most 64"),
    ],
)
def test_pose_bounds_apply_outside_the_http_layer(field: str, value: object, match: str) -> None:
    data = Pose(name="Bounded", snapshot=make_snapshot()).model_dump(mode="python")
    data[field] = value
    with pytest.raises(ValidationError, match=match):
        Pose.model_validate(data)


def test_motion_bounds_and_mixed_fingerprints_fail_closed() -> None:
    with pytest.raises(ValidationError, match="at most 200"):
        MotionKeyframe(label="x" * 201, pose_snapshot=make_snapshot())
    with pytest.raises(ValidationError, match="less than or equal to 600"):
        make_transition(601.0)
    with pytest.raises(ValidationError, match="less than or equal to 4"):
        PlaybackDefaults(speed_multiplier=4.1)

    mismatched = make_snapshot().model_dump(mode="python")
    mismatched["kinematics_fingerprint"] = "c" * 64
    with pytest.raises(ValidationError, match="kinematics_fingerprint"):
        Motion(
            name="Mixed compatibility",
            robot_variant=make_snapshot().robot_variant,
            keyframes=[
                MotionKeyframe(label="Start", pose_snapshot=make_snapshot()),
                MotionKeyframe(
                    label="End",
                    pose_snapshot=PoseSnapshot.model_validate(mismatched),
                    incoming_transition=make_transition(),
                ),
            ],
        )


def test_legacy_provenance_is_typed_bounded_and_cannot_hold_raw_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        LegacyImportMetadata.model_validate(
            {
                "source_file_name": "fixture.json",
                "source_sha256": "a" * 64,
                "raw_present_position": {"j11": 1234},
            }
        )
    with pytest.raises(ValidationError, match="at most 32"):
        LegacyImportMetadata(
            source_file_name="fixture.json",
            source_sha256="a" * 64,
            warnings=[f"warning {index}" for index in range(33)],
        )


def test_hardware_snapshot_json_shape_is_bounded() -> None:
    data = make_snapshot().model_dump(mode="python")
    nested: object = "leaf"
    for _ in range(10):
        nested = {"child": nested}
    data["hardware_snapshot"] = {"nested": nested}
    with pytest.raises(ValidationError, match="nesting is too deep"):
        PoseSnapshot.model_validate(data)
