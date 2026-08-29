"""Committed examples must stay synchronized with current Dry Run boundaries."""

import asyncio
import json
from pathlib import Path

import pytest
import yaml
from scripts.generate_schemas import generate_schemas

from momo.bootstrap import (
    build_simulation_product_services,
    build_simulation_robot_service,
)
from momo.domain.motion import Motion
from momo.domain.pose import Pose
from momo.domain.robot import RobotProfile
from momo.settings import Settings, repository_root


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

    async def verify_current_boundaries() -> None:
        settings = Settings()
        robot = build_simulation_robot_service(settings)
        services = build_simulation_product_services(settings, robot)
        snapshots = (pose.snapshot, *(frame.pose_snapshot for frame in motion.keyframes))
        for snapshot in snapshots:
            profile = robot.profile_service.get_profile(snapshot.robot_variant)
            model = services.kinematics.model_for(profile)
            assert snapshot.profile_fingerprint == profile.fingerprint
            assert snapshot.kinematics_fingerprint == model.fingerprint
            snapshot.validate_against(profile)
            assert snapshot.state_sequence is not None
            forward = await services.kinematics.forward(
                profile,
                snapshot.joint_state,
                state_sequence=snapshot.state_sequence,
                robot_id="example-validation",
            )
            actual = forward.tcp_pose
            expected = snapshot.tcp_pose
            assert actual.frame == expected.frame
            assert (
                actual.position_mm.x,
                actual.position_mm.y,
                actual.position_mm.z,
            ) == pytest.approx(
                (
                    expected.position_mm.x,
                    expected.position_mm.y,
                    expected.position_mm.z,
                ),
                abs=1e-9,
            )
            assert (
                actual.orientation_quaternion_xyzw.x,
                actual.orientation_quaternion_xyzw.y,
                actual.orientation_quaternion_xyzw.z,
                actual.orientation_quaternion_xyzw.w,
            ) == pytest.approx(
                (
                    expected.orientation_quaternion_xyzw.x,
                    expected.orientation_quaternion_xyzw.y,
                    expected.orientation_quaternion_xyzw.z,
                    expected.orientation_quaternion_xyzw.w,
                ),
                abs=1e-12,
            )

    asyncio.run(verify_current_boundaries())


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
    generated_names = {path.name for path in generated}
    committed_names = {path.name for path in committed_directory.glob("*.json")}
    assert committed_names == generated_names
    for generated_path in generated:
        committed_path = committed_directory / generated_path.name
        assert generated_path.read_bytes() == committed_path.read_bytes()


def test_kinematics_schema_generation_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_paths = generate_schemas(first)
    second_paths = generate_schemas(second)
    assert [path.name for path in first_paths] == [path.name for path in second_paths]
    assert [path.read_bytes() for path in first_paths] == [
        path.read_bytes() for path in second_paths
    ]

    schema = json.loads((first / "kinematics-model.schema.json").read_text(encoding="utf-8"))
    assert schema["title"] == "KinematicsModel"
    assert {
        "schema_version",
        "variant",
        "verification_status",
        "base_frame",
        "tcp_frame",
        "joints",
        "kinematics_fingerprint",
    } <= set(schema["properties"])
    assert "kinematics_fingerprint" in schema["required"]
