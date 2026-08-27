"""Stage 3 mesh-free serial-chain kinematics contracts."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from math import sqrt
from pathlib import Path
from typing import Any, TypeVar

import pytest

from momo.adapters.kinematics.model_repository import FileKinematicsModelRepository
from momo.adapters.kinematics.serial_chain import SerialChainKinematics, compose_delta_pose
from momo.domain.enums import CartesianFrame, JointType, RobotVariant
from momo.domain.kinematics.model import KinematicsModel
from momo.domain.profiles import canonical_robot_profile
from momo.domain.robot import JointState
from momo.ports.kinematics import (
    KinematicsInverseResult,
    KinematicsJointState,
    KinematicsTcpPose,
    from_kinematics_joint_state,
    to_kinematics_joint_state,
)
from momo.settings import repository_root


def repository() -> FileKinematicsModelRepository:
    return FileKinematicsModelRepository(repository_root() / "kinematics_models")


Result = TypeVar("Result")


def run(coroutine: Coroutine[Any, Any, Result]) -> Result:
    return asyncio.run(coroutine)


def test_variant_models_have_exact_product_joint_sets_and_provisional_sources() -> None:
    models = repository()
    v1 = models.get(RobotVariant.V1)
    v2 = models.get(RobotVariant.V2)

    assert tuple(joint.joint_id for joint in v1.joints) == (
        "j11",
        "j12",
        "j13",
        "j14",
        "j15",
    )
    assert "j10" not in {joint.joint_id for joint in v1.joints}
    assert tuple(joint.joint_id for joint in v2.joints) == (
        "j10",
        "j11",
        "j12",
        "j13",
        "j14",
        "j15",
    )
    assert v2.joints[0].joint_type is JointType.PRISMATIC
    assert v1.verification_status.value == v2.verification_status.value == "PROVISIONAL_DRY_RUN"
    assert v1.source_revision == v2.source_revision == ("ff8bbda0c2222cb57951c7913f7f12f5777b98fa")


def test_fingerprint_is_deterministic_ui_independent_and_geometry_sensitive() -> None:
    source = repository().get(RobotVariant.V2)
    same = KinematicsModel.model_validate(source.model_dump(mode="json"))
    visual = source.model_dump(mode="json")
    visual["display_name"] = "A different UI label"
    visual["description"] = "UI-only text"
    visual_model = KinematicsModel.model_validate(visual)

    changed_joint = source.joints[1].model_copy(
        update={
            "origin_translation_m": (
                source.joints[1].origin_translation_m[0] + 0.000001,
                *source.joints[1].origin_translation_m[1:],
            )
        }
    )
    changed_joints = list(source.joints)
    changed_joints[1] = changed_joint
    geometry_model = source.model_copy(update={"joints": changed_joints})

    assert same.fingerprint == source.fingerprint == source.kinematics_fingerprint
    assert visual_model.fingerprint == source.fingerprint
    assert geometry_model.fingerprint != source.fingerprint
    assert len(source.fingerprint) == 64


def test_declared_fingerprint_rejects_tampered_geometry() -> None:
    source = repository().get(RobotVariant.V1)
    tampered = source.model_dump(mode="json")
    tampered["joints"][0]["axis"] = [1.0, 0.0, 0.0]
    with pytest.raises(ValueError, match="kinematics_fingerprint"):
        KinematicsModel.model_validate(tampered)

    missing = source.model_dump(mode="json")
    missing.pop("kinematics_fingerprint")
    with pytest.raises(ValueError, match="kinematics_fingerprint"):
        KinematicsModel.model_validate(missing)


@pytest.mark.parametrize(
    ("variant", "expected_position"),
    [
        (RobotVariant.V1, (-0.00330005, 0.08982656, 0.24225710)),
        (RobotVariant.V2, (-0.00655498, 0.21154490, 0.28160004)),
    ],
)
def test_fk_known_home_pose_is_finite_and_dictionary_order_independent(
    variant: RobotVariant,
    expected_position: tuple[float, float, float],
) -> None:
    model = repository().get(variant)
    profile = canonical_robot_profile(variant)
    values = {joint_id: 0.0 for joint_id in profile.enabled_joints}
    forward = SerialChainKinematics()
    first = run(
        forward.forward(
            model,
            to_kinematics_joint_state(JointState(positions=values), profile),
        )
    )
    second = run(
        forward.forward(
            model,
            KinematicsJointState(positions_si=dict(reversed(list(values.items())))),
        )
    )

    assert isinstance(first, KinematicsTcpPose)
    assert first.position_m == pytest.approx(expected_position, abs=1e-8)
    assert second == first
    assert sum(value * value for value in first.orientation_quaternion_xyzw) == pytest.approx(1.0)


@pytest.mark.parametrize("variant", [RobotVariant.V1, RobotVariant.V2])
@pytest.mark.parametrize("position_only", [False, True])
def test_ik_fk_round_trip_is_deterministic_with_seed(
    variant: RobotVariant,
    position_only: bool,
) -> None:
    model = repository().get(variant)
    profile = canonical_robot_profile(variant)
    values = {
        joint_id: value
        for joint_id, value in zip(
            profile.enabled_joints,
            ((25.0,) if variant is RobotVariant.V2 else ()) + (10.0, -15.0, 20.0, -10.0, 5.0),
            strict=True,
        )
    }
    seed = to_kinematics_joint_state(JointState(positions=values), profile)
    adapter = SerialChainKinematics()

    async def scenario() -> tuple[KinematicsInverseResult, KinematicsInverseResult]:
        target = await adapter.forward(model, seed)
        first = await adapter.inverse(model, target, seed, position_only=position_only)
        second = await adapter.inverse(model, target, seed, position_only=position_only)
        return first, second

    first, second = run(scenario())
    assert first == second
    assert first.success is True
    assert first.solution == seed
    assert first.position_error_m <= 1e-12
    assert first.orientation_error_rad in (None, 0.0)


@pytest.mark.parametrize("variant", [RobotVariant.V1, RobotVariant.V2])
@pytest.mark.parametrize("use_default_seed", [False, True])
def test_full_pose_ik_converges_from_offset_or_default_seed(
    variant: RobotVariant,
    use_default_seed: bool,
) -> None:
    model = repository().get(variant)
    profile = canonical_robot_profile(variant)
    target_values = {joint_id: 0.0 for joint_id in profile.enabled_joints}
    target_values.update({"j11": 10.0, "j12": -15.0, "j13": 20.0, "j14": -10.0, "j15": 5.0})
    if variant is RobotVariant.V2:
        target_values["j10"] = 25.0
    target_joints = to_kinematics_joint_state(JointState(positions=target_values), profile)
    offset_seed = to_kinematics_joint_state(
        JointState(positions={joint_id: 0.0 for joint_id in profile.enabled_joints}),
        profile,
    )
    adapter = SerialChainKinematics()

    async def scenario() -> KinematicsInverseResult:
        target = await adapter.forward(model, target_joints)
        return await adapter.inverse(
            model,
            target,
            None if use_default_seed else offset_seed,
            maximum_iterations=500,
        )

    result = run(scenario())
    assert result.success is True
    assert result.position_error_m <= 0.001
    assert result.orientation_error_rad is not None
    assert result.orientation_error_rad <= 0.02
    if variant is RobotVariant.V2:
        assert result.solution is not None
        assert result.solution.positions_si["j10"] == pytest.approx(0.025, abs=1e-5)


@pytest.mark.parametrize("variant", [RobotVariant.V1, RobotVariant.V2])
def test_position_only_ik_numerically_converges_from_offset_seed(
    variant: RobotVariant,
) -> None:
    model = repository().get(variant)
    profile = canonical_robot_profile(variant)
    target_values = {joint_id: 0.0 for joint_id in profile.enabled_joints}
    target_values.update({"j11": 20.0, "j12": -25.0, "j13": 15.0, "j14": -5.0, "j15": 10.0})
    seed_values = {joint_id: 0.0 for joint_id in profile.enabled_joints}
    if variant is RobotVariant.V2:
        target_values["j10"] = 40.0
        seed_values["j10"] = 5.0
    target_joints = to_kinematics_joint_state(JointState(positions=target_values), profile)
    offset_seed = to_kinematics_joint_state(JointState(positions=seed_values), profile)
    adapter = SerialChainKinematics()

    async def scenario() -> tuple[
        KinematicsInverseResult,
        KinematicsInverseResult,
        KinematicsTcpPose,
        KinematicsTcpPose,
    ]:
        target = await adapter.forward(model, target_joints)
        first = await adapter.inverse(
            model,
            target,
            offset_seed,
            position_only=True,
            maximum_iterations=500,
        )
        second = await adapter.inverse(
            model,
            target,
            offset_seed,
            position_only=True,
            maximum_iterations=500,
        )
        assert first.solution is not None
        reconverged = await adapter.forward(model, first.solution)
        return first, second, target, reconverged

    first, second, target, reconverged = run(scenario())
    assert first == second
    assert first.success is True
    assert first.iterations > 0
    assert first.position_error_m <= 0.001
    assert reconverged.position_m == pytest.approx(target.position_m, abs=0.001)
    if variant is RobotVariant.V2:
        assert first.solution is not None
        assert first.solution.positions_si["j10"] > offset_seed.positions_si["j10"]


def test_ik_unreachable_and_invalid_inputs_return_finite_safe_results() -> None:
    model = repository().get(RobotVariant.V1)
    adapter = SerialChainKinematics()
    unreachable = KinematicsTcpPose(
        frame="base",
        position_m=(10.0, 10.0, 10.0),
        orientation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
    )
    wrong_frame = KinematicsTcpPose(
        frame="base_link",
        position_m=(0.0, 0.0, 0.0),
        orientation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
    )

    async def scenario() -> tuple[KinematicsInverseResult, KinematicsInverseResult]:
        return (
            await adapter.inverse(model, unreachable, maximum_iterations=30),
            await adapter.inverse(model, wrong_frame),
        )

    unreachable_result, invalid_result = run(scenario())
    assert unreachable_result.success is False
    assert unreachable_result.best_solution is not None
    assert unreachable_result.position_error_m < 100.0
    assert invalid_result.success is False
    assert invalid_result.termination_reason == "INVALID_TARGET"
    assert invalid_result.position_error_m == 1e9


def test_quaternion_is_normalized_and_joint_limits_are_enforced() -> None:
    model = repository().get(RobotVariant.V2)
    adapter = SerialChainKinematics()
    target = KinematicsTcpPose(
        frame="base",
        position_m=(0.0, 0.0, 0.0),
        orientation_quaternion_xyzw=(0.0, 0.0, 0.0, 2.0),
    )
    result = run(adapter.inverse(model, target, maximum_iterations=1))
    assert result.termination_reason != "INVALID_TARGET"

    invalid = KinematicsJointState(
        positions_si={
            joint.joint_id: (0.6 if joint.joint_id == "j10" else 0.0) for joint in model.joints
        }
    )
    with pytest.raises(ValueError, match="j10 is outside kinematics limits"):
        run(adapter.forward(model, invalid))


def test_base_and_tool_deltas_apply_in_different_frames() -> None:
    half = sqrt(0.5)
    current = KinematicsTcpPose(
        frame="base",
        position_m=(1.0, 2.0, 3.0),
        orientation_quaternion_xyzw=(0.0, 0.0, half, half),
    )
    base = compose_delta_pose(
        current,
        (0.1, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        CartesianFrame.BASE,
    )
    tool = compose_delta_pose(
        current,
        (0.1, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        CartesianFrame.TOOL,
    )
    assert base.position_m == pytest.approx((1.1, 2.0, 3.0))
    assert tool.position_m == pytest.approx((1.0, 2.1, 3.0))


def test_mm_m_and_degree_radian_boundaries_are_explicit_and_reversible() -> None:
    profile = canonical_robot_profile(RobotVariant.V2)
    state = JointState(
        positions={
            "j10": 25.0,
            "j11": 180.0,
            "j12": 0.0,
            "j13": 0.0,
            "j14": 0.0,
            "j15": 0.0,
        }
    )
    si = to_kinematics_joint_state(state, profile)
    assert si.positions_si["j10"] == pytest.approx(0.025)
    assert si.positions_si["j11"] == pytest.approx(3.141592653589793)
    assert from_kinematics_joint_state(si, profile).positions == pytest.approx(state.positions)
    with pytest.raises(TypeError):
        si.positions_si["j10"] = 0.1


def test_model_profile_variant_mismatch_is_rejected() -> None:
    model = repository().get(RobotVariant.V1)
    with pytest.raises(ValueError, match="variant"):
        model.validate_against_profile(canonical_robot_profile(RobotVariant.V2))


def test_model_loader_does_not_accept_paths_outside_its_fixed_directory(tmp_path: Path) -> None:
    # Fixed filenames plus parent equality ensure callers cannot request arbitrary YAML.
    models = FileKinematicsModelRepository(tmp_path)
    with pytest.raises(FileNotFoundError):
        models.get(RobotVariant.V1)
