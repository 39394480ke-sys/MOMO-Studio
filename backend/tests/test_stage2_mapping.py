"""Golden characterization tests for pure logical/raw mapping and safety."""

from math import inf, nan

import pytest

from momo.domain.calibration import CalibrationJoint
from momo.domain.enums import CalibrationOperatingMode, DomainUnit, JointType, RobotVariant
from momo.domain.errors import HardwareMappingError
from momo.domain.hardware_mapping import (
    effective_logical_limits_from_raw_bounds,
    goal_raw_to_logical,
    logical_to_goal_raw,
    logical_to_relative_raw,
    mapping_round_trip_tolerance,
    validate_goal_raw,
)
from momo.domain.profiles import canonical_robot_profile
from momo.domain.robot import JointDefinition, RobotProfile
from momo.domain.safety import validate_logical_value
from tests.stage2_helpers import make_calibration


def with_definition(
    profile: RobotProfile,
    joint_id: str,
    **updates: object,
) -> RobotProfile:
    definitions = list(profile.joint_definitions)
    index = list(profile.enabled_joints).index(joint_id)
    definitions[index] = definitions[index].model_copy(update=updates)
    return profile.model_copy(update={"joint_definitions": definitions})


def test_logical_zero_maps_to_calibrated_home_raw() -> None:
    profile = canonical_robot_profile(RobotVariant.V2)
    calibration = (
        make_calibration(profile).joints_by_id["j10"].model_copy(update={"home_present_raw": 1234})
    )
    assert logical_to_goal_raw("j10", 0.0, profile, calibration) == 1234


def test_positive_and_negative_directions_are_symmetric() -> None:
    profile = canonical_robot_profile(RobotVariant.V1)
    positive = make_calibration(profile).joints_by_id["j11"]
    negative = positive.model_copy(update={"direction": -1})
    positive_raw = logical_to_goal_raw("j11", 10.0, profile, positive)
    negative_raw = logical_to_goal_raw("j11", 10.0, profile, negative)
    assert positive_raw == 114
    assert negative_raw == -114


def test_j10_uses_mm_metadata_and_revolute_joint_uses_degrees() -> None:
    profile = canonical_robot_profile(RobotVariant.V2)
    calibration = make_calibration(profile).joints_by_id
    assert profile.definitions_by_id["j10"].domain_unit is DomainUnit.MM
    assert logical_to_goal_raw("j10", 1.0, profile, calibration["j10"]) == 328
    assert profile.definitions_by_id["j11"].domain_unit is DomainUnit.DEG
    assert logical_to_goal_raw("j11", 10.0, profile, calibration["j11"]) == 114


@pytest.mark.parametrize("joint_id", ["j10", "j11"])
def test_logical_raw_round_trips_use_an_explicit_quantization_tolerance(
    joint_id: str,
) -> None:
    profile = canonical_robot_profile(RobotVariant.V2)
    calibration = make_calibration(profile).joints_by_id[joint_id]
    definition = profile.definitions_by_id[joint_id]
    logical = 1.25 if joint_id == "j10" else 23.75
    raw = logical_to_goal_raw(joint_id, logical, profile, calibration)
    restored = goal_raw_to_logical(joint_id, raw, profile, calibration)
    assert restored == pytest.approx(logical, abs=mapping_round_trip_tolerance(definition))

    source_raw = 1234
    restored_logical = goal_raw_to_logical(joint_id, source_raw, profile, calibration)
    assert logical_to_goal_raw(joint_id, restored_logical, profile, calibration) == source_raw


def test_absolute_raw_bounds_accept_endpoints_and_reject_values_outside() -> None:
    profile = canonical_robot_profile(RobotVariant.V1)
    calibration = make_calibration(profile).joints_by_id["j11"]
    assert validate_goal_raw("j11", -30719, profile, calibration) == -30719
    assert validate_goal_raw("j11", 30719, profile, calibration) == 30719
    with pytest.raises(HardwareMappingError, match="outside"):
        validate_goal_raw("j11", -30720, profile, calibration)
    with pytest.raises(HardwareMappingError, match="outside"):
        validate_goal_raw("j11", 30720, profile, calibration)


def test_dynamic_reachability_accounts_for_home_raw_near_an_absolute_limit() -> None:
    profile = canonical_robot_profile(RobotVariant.V2)
    calibration = (
        make_calibration(profile).joints_by_id["j10"].model_copy(update={"home_present_raw": 30700})
    )
    lower, upper = effective_logical_limits_from_raw_bounds(
        "j10",
        profile,
        calibration,
    )
    assert lower == 0.0
    assert 0.0 < upper < 0.1


def test_profile_logical_limits_intersect_raw_dynamic_limits() -> None:
    profile = with_definition(
        canonical_robot_profile(RobotVariant.V1),
        "j11",
        minimum=-5.0,
        maximum=5.0,
    )
    calibration = (
        make_calibration(profile).joints_by_id["j11"].model_copy(update={"raw_bounds": (-100, 100)})
    )
    assert effective_logical_limits_from_raw_bounds("j11", profile, calibration) == (-5.0, 5.0)
    assert validate_logical_value("j11", 5.0, profile, calibration) == 5.0
    with pytest.raises(HardwareMappingError, match="outside"):
        validate_logical_value("j11", 5.1, profile, calibration)


def test_profile_and_calibration_raw_bounds_are_intersected() -> None:
    profile = canonical_robot_profile(RobotVariant.V1)
    calibration = (
        make_calibration(profile).joints_by_id["j11"].model_copy(update={"raw_bounds": (-50, 75)})
    )
    assert validate_goal_raw("j11", -50, profile, calibration) == -50
    assert validate_goal_raw("j11", 75, profile, calibration) == 75
    with pytest.raises(HardwareMappingError, match="outside"):
        validate_goal_raw("j11", 76, profile, calibration)


def test_zero_scale_and_invalid_direction_fail_closed() -> None:
    profile = with_definition(
        canonical_robot_profile(RobotVariant.V1),
        "j11",
        motor_degrees_per_domain_unit=0.0,
    )
    calibration = make_calibration(profile).joints_by_id["j11"]
    with pytest.raises(HardwareMappingError, match="greater than zero"):
        logical_to_goal_raw("j11", 1.0, profile, calibration)

    valid_profile = canonical_robot_profile(RobotVariant.V1)
    invalid_direction = (
        make_calibration(valid_profile).joints_by_id["j11"].model_copy(update={"direction": 0})
    )
    with pytest.raises(HardwareMappingError, match="direction"):
        logical_to_goal_raw("j11", 1.0, valid_profile, invalid_direction)


@pytest.mark.parametrize("invalid", [nan, inf, -inf])
def test_non_finite_logical_values_are_rejected(invalid: float) -> None:
    profile = canonical_robot_profile(RobotVariant.V2)
    calibration = make_calibration(profile).joints_by_id["j10"]
    with pytest.raises(HardwareMappingError, match="finite"):
        logical_to_goal_raw("j10", invalid, profile, calibration)
    with pytest.raises(HardwareMappingError, match="finite"):
        validate_logical_value("j10", invalid, profile, calibration)


def test_unknown_and_mismatched_calibration_joints_fail_closed() -> None:
    profile = canonical_robot_profile(RobotVariant.V2)
    calibration = make_calibration(profile).joints_by_id["j10"]
    with pytest.raises(HardwareMappingError, match="unknown joint"):
        logical_to_goal_raw("j99", 0.0, profile, calibration)
    with pytest.raises(HardwareMappingError, match="does not match"):
        logical_to_goal_raw("j11", 0.0, profile, calibration)


def test_mapping_uses_explicit_metadata_instead_of_joint_name_guessing() -> None:
    definition = JointDefinition(
        joint_id="j99",
        joint_type=JointType.PRISMATIC,
        domain_unit=DomainUnit.MM,
        minimum=-10.0,
        maximum=10.0,
        home=0.0,
        servo_id=99,
        motor_degrees_per_domain_unit=2.0,
        raw_counts_per_motor_revolution=4096.0,
        raw_bounds=(-1000, 1000),
    )
    calibration = CalibrationJoint(
        joint_id="j99",
        servo_id=99,
        operating_mode=CalibrationOperatingMode.MULTI_TURN,
        direction=1,
        home_present_raw=0,
        phase=0,
        raw_bounds=(-1000, 1000),
    )
    assert logical_to_relative_raw(1.0, definition, calibration) == 23


def test_variant_contract_remains_explicit_at_the_mapping_boundary() -> None:
    v1 = canonical_robot_profile(RobotVariant.V1)
    v2 = canonical_robot_profile(RobotVariant.V2)
    assert "j10" not in v1.enabled_joints
    assert "j10" in v2.enabled_joints
