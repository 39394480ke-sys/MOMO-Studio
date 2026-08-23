"""Committed Stage 1 examples must stay synchronized with domain contracts."""

import json
from pathlib import Path

import yaml
from scripts.generate_schemas import generate_schemas

from momo.domain.motion import Motion
from momo.domain.pose import Pose
from momo.domain.robot import RobotProfile
from momo.settings import repository_root


def test_committed_pose_and_motion_examples_validate() -> None:
    examples = repository_root() / "data" / "examples"
    pose = Pose.model_validate_json((examples / "pose.example.json").read_text(encoding="utf-8"))
    motion = Motion.model_validate_json(
        (examples / "motion.example.json").read_text(encoding="utf-8")
    )
    assert motion.keyframes[0].source_pose_id == pose.id
    assert motion.keyframes[0].pose_snapshot == pose.snapshot

    raw_motion = json.loads((examples / "motion.example.json").read_text(encoding="utf-8"))
    raw_quaternion = raw_motion["keyframes"][1]["pose_snapshot"]["tcp_pose"][
        "orientation_quaternion_xyzw"
    ]
    canonical_quaternion = motion.keyframes[1].pose_snapshot.tcp_pose.orientation_quaternion_xyzw
    assert canonical_quaternion.model_dump(mode="json") == raw_quaternion


def test_committed_robot_profile_examples_validate() -> None:
    profile_directory = repository_root() / "robot_profiles"
    for filename in ("v1.example.yaml", "v2.example.yaml"):
        raw = yaml.safe_load((profile_directory / filename).read_text(encoding="utf-8"))
        profile = RobotProfile.model_validate(raw)
        assert profile.schema_version == "1.0.0"


def test_committed_json_schemas_match_reproducible_generator(tmp_path: Path) -> None:
    generated = generate_schemas(tmp_path)
    committed_directory = repository_root() / "docs" / "schemas"
    assert generated
    for generated_path in generated:
        committed_path = committed_directory / generated_path.name
        assert generated_path.read_bytes() == committed_path.read_bytes()
