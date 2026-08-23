"""Product-contract and keyed joint-state tests (requirements 1-6)."""

from copy import deepcopy
from math import inf, nan

import pytest
from pydantic import ValidationError

from momo.domain.enums import DomainUnit, RobotVariant
from momo.domain.errors import JointStateValidationError
from momo.domain.profiles import canonical_robot_profile
from momo.domain.robot import JointState, RobotProfile


def test_v1_profile_allows_only_j11_through_j15() -> None:
    profile = canonical_robot_profile(RobotVariant.V1)
    assert profile.has_linear_rail is False
    assert list(profile.enabled_joints) == ["j11", "j12", "j13", "j14", "j15"]

    invalid = profile.model_dump(mode="json")
    invalid["enabled_joints"] = ["j10", *invalid["enabled_joints"]]
    invalid["joint_definitions"] = [
        {
            "joint_id": "j10",
            "joint_type": "PRISMATIC",
            "domain_unit": "mm",
            "minimum": 0,
            "maximum": 1000,
            "home": 0,
            "hardware_mapping_placeholder": None,
        },
        *invalid["joint_definitions"],
    ]
    with pytest.raises(ValidationError, match="V1 enabled_joints"):
        RobotProfile.model_validate(invalid)


def test_v2_profile_allows_j10_through_j15() -> None:
    profile = canonical_robot_profile(RobotVariant.V2)
    assert profile.has_linear_rail is True
    assert list(profile.enabled_joints) == ["j10", "j11", "j12", "j13", "j14", "j15"]
    assert profile.definitions_by_id["j10"].domain_unit is DomainUnit.MM
    assert all(
        profile.definitions_by_id[joint_id].domain_unit is DomainUnit.DEG
        for joint_id in profile.enabled_joints[1:]
    )


def test_profile_rejects_duplicate_joint_ids() -> None:
    data = canonical_robot_profile(RobotVariant.V2).model_dump(mode="json")
    data["enabled_joints"][-1] = "j14"
    data["joint_definitions"][-1]["joint_id"] = "j14"
    with pytest.raises(ValidationError, match="duplicate joint IDs"):
        RobotProfile.model_validate(data)


@pytest.mark.parametrize(
    ("variant", "joint_id", "replacement_type", "replacement_unit", "expected"),
    [
        (RobotVariant.V1, "j11", "PRISMATIC", "mm", "V1 j11 joint_type must be REVOLUTE"),
        (RobotVariant.V2, "j10", "REVOLUTE", "deg", "V2 j10 joint_type must be PRISMATIC"),
        (RobotVariant.V2, "j11", "PRISMATIC", "mm", "V2 j11 joint_type must be REVOLUTE"),
    ],
)
def test_profile_enforces_variant_joint_type_and_unit_semantics(
    variant: RobotVariant,
    joint_id: str,
    replacement_type: str,
    replacement_unit: str,
    expected: str,
) -> None:
    data = canonical_robot_profile(variant).model_dump(mode="json")
    definition = next(item for item in data["joint_definitions"] if item["joint_id"] == joint_id)
    definition["joint_type"] = replacement_type
    definition["domain_unit"] = replacement_unit
    with pytest.raises(ValidationError, match=expected):
        RobotProfile.model_validate(data)


def test_joint_definition_rejects_a_variant_unit_mismatch() -> None:
    data = canonical_robot_profile(RobotVariant.V2).model_dump(mode="json")
    data["joint_definitions"][0]["domain_unit"] = "deg"
    with pytest.raises(ValidationError, match="PRISMATIC joints must use mm"):
        RobotProfile.model_validate(data)


def test_joint_state_rejects_missing_enabled_joint() -> None:
    profile = canonical_robot_profile(RobotVariant.V1)
    positions = {joint_id: 0.0 for joint_id in profile.enabled_joints}
    del positions["j15"]
    with pytest.raises(JointStateValidationError, match=r"missing enabled joints.*j15"):
        JointState(positions=positions).validate_against(profile)


def test_joint_state_rejects_unknown_joint() -> None:
    profile = canonical_robot_profile(RobotVariant.V1)
    positions = {joint_id: 0.0 for joint_id in profile.enabled_joints}
    positions["j10"] = 0.0
    with pytest.raises(JointStateValidationError, match=r"unknown joints.*j10"):
        JointState(positions=positions).validate_against(profile)


@pytest.mark.parametrize("not_finite", [nan, inf, -inf])
def test_joint_state_rejects_nan_and_infinity(not_finite: float) -> None:
    with pytest.raises(ValidationError, match="finite number"):
        JointState(positions={"j11": not_finite})


def test_joint_state_checks_range_and_explicit_units() -> None:
    profile = canonical_robot_profile(RobotVariant.V2)
    positions = {joint_id: 0.0 for joint_id in profile.enabled_joints}
    positions["j10"] = 1001.0
    units = {
        definition.joint_id: definition.domain_unit for definition in profile.joint_definitions
    }
    with pytest.raises(JointStateValidationError, match="outside"):
        JointState(positions=positions, units=units).validate_against(profile)

    positions["j10"] = 500.0
    wrong_units = deepcopy(units)
    wrong_units["j10"] = DomainUnit.DEG
    with pytest.raises(JointStateValidationError, match="j10 unit must be mm"):
        JointState(positions=positions, units=wrong_units).validate_against(profile)
