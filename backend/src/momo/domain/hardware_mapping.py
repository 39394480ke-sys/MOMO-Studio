"""Pure, unit-neutral logical value and servo raw mapping functions."""

from __future__ import annotations

from math import isfinite

from momo.domain.calibration import CalibrationJoint
from momo.domain.errors import HardwareMappingError
from momo.domain.robot import JointDefinition, RobotProfile

MOTOR_DEGREES_PER_REVOLUTION = 360.0


def _require_finite(value: float, name: str) -> float:
    parsed = float(value)
    if not isfinite(parsed):
        raise HardwareMappingError(f"{name} must be finite")
    return parsed


def _mapping_inputs(
    definition: JointDefinition,
    calibration: CalibrationJoint,
) -> tuple[float, float, int, int]:
    scale = definition.motor_degrees_per_domain_unit
    if scale is None:
        raise HardwareMappingError(f"{definition.joint_id} has no mapping scale")
    scale = _require_finite(scale, "motor_degrees_per_domain_unit")
    counts = _require_finite(
        definition.raw_counts_per_motor_revolution,
        "raw_counts_per_motor_revolution",
    )
    if scale == 0 or counts <= 0:
        raise HardwareMappingError("mapping scale and raw counts must be greater than zero")
    if definition.direction not in {-1, 1} or calibration.direction not in {-1, 1}:
        raise HardwareMappingError("direction must be -1 or 1")
    if calibration.home_present_raw is None:
        raise HardwareMappingError(f"{definition.joint_id} has no calibrated Home raw")
    return scale, counts, definition.direction * calibration.direction, calibration.home_present_raw


def _joint_inputs(
    joint_id: str,
    profile: RobotProfile,
    calibration: CalibrationJoint,
) -> JointDefinition:
    definition = profile.definitions_by_id.get(joint_id)
    if definition is None:
        raise HardwareMappingError(f"unknown joint: {joint_id}")
    if calibration.joint_id != joint_id:
        raise HardwareMappingError(
            f"calibration joint {calibration.joint_id} does not match {joint_id}"
        )
    if calibration.operating_mode is not definition.operating_mode:
        raise HardwareMappingError(f"{joint_id} operating mode does not match the profile")
    return definition


def effective_raw_bounds(
    definition: JointDefinition,
    calibration: CalibrationJoint,
) -> tuple[int, int]:
    """Intersect profile hardware bounds with an optional local calibrated range."""

    if definition.raw_bounds is None:
        raise HardwareMappingError(f"{definition.joint_id} profile has no explicit raw bounds")
    lower, upper = definition.raw_bounds
    if lower >= upper:
        raise HardwareMappingError("profile raw bounds are invalid")
    if calibration.raw_bounds is not None:
        calibration_lower, calibration_upper = calibration.raw_bounds
        if calibration_lower >= calibration_upper:
            raise HardwareMappingError("calibration raw bounds are invalid")
        lower = max(lower, calibration_lower)
        upper = min(upper, calibration_upper)
    if lower >= upper:
        raise HardwareMappingError("profile and calibration raw bounds do not overlap")
    return lower, upper


def logical_to_relative_raw(
    logical_value: float,
    definition: JointDefinition,
    calibration: CalibrationJoint,
) -> int:
    """Map a domain value (mm or deg) to signed raw displacement."""

    logical = _require_finite(logical_value, "logical_value")
    scale, counts, direction, _ = _mapping_inputs(definition, calibration)
    motor_degrees = logical * scale * direction
    return round(motor_degrees / MOTOR_DEGREES_PER_REVOLUTION * counts)


def logical_to_goal_raw(
    joint_id: str,
    logical_value: float,
    profile: RobotProfile,
    calibration: CalibrationJoint,
) -> int:
    definition = _joint_inputs(joint_id, profile, calibration)
    _, _, _, home_raw = _mapping_inputs(definition, calibration)
    goal_raw = home_raw + logical_to_relative_raw(logical_value, definition, calibration)
    validate_goal_raw(joint_id, goal_raw, profile, calibration)
    return goal_raw


def goal_raw_to_logical(
    joint_id: str,
    goal_raw: int,
    profile: RobotProfile,
    calibration: CalibrationJoint,
) -> float:
    definition = _joint_inputs(joint_id, profile, calibration)
    validated_raw = validate_goal_raw(joint_id, goal_raw, profile, calibration)
    scale, counts, direction, home_raw = _mapping_inputs(definition, calibration)
    motor_degrees = (validated_raw - home_raw) * MOTOR_DEGREES_PER_REVOLUTION / counts
    return motor_degrees / (scale * direction)


def validate_goal_raw(
    joint_id: str,
    goal_raw: int,
    profile: RobotProfile,
    calibration: CalibrationJoint,
) -> int:
    definition = _joint_inputs(joint_id, profile, calibration)
    if isinstance(goal_raw, bool) or not isinstance(goal_raw, int):
        raise HardwareMappingError("goal_raw must be an integer")
    lower, upper = effective_raw_bounds(definition, calibration)
    if not lower <= goal_raw <= upper:
        raise HardwareMappingError(f"{joint_id} goal raw {goal_raw} is outside [{lower}, {upper}]")
    return goal_raw


def effective_logical_limits_from_raw_bounds(
    joint_id: str,
    profile: RobotProfile,
    calibration: CalibrationJoint,
) -> tuple[float, float]:
    """Intersect logical limits with the range dynamically reachable from Home raw."""

    definition = _joint_inputs(joint_id, profile, calibration)
    raw_lower, raw_upper = effective_raw_bounds(definition, calibration)
    reachable = sorted(
        (
            goal_raw_to_logical(joint_id, raw_lower, profile, calibration),
            goal_raw_to_logical(joint_id, raw_upper, profile, calibration),
        )
    )
    lower = max(definition.minimum, reachable[0])
    upper = min(definition.maximum, reachable[1])
    if lower > upper:
        raise HardwareMappingError(
            f"{joint_id} logical limits and raw-reachable range do not overlap"
        )
    return lower, upper


def mapping_round_trip_tolerance(definition: JointDefinition) -> float:
    scale = definition.motor_degrees_per_domain_unit
    if scale is None or scale <= 0 or definition.raw_counts_per_motor_revolution <= 0:
        raise HardwareMappingError("mapping scale is invalid")
    one_count = MOTOR_DEGREES_PER_REVOLUTION / (definition.raw_counts_per_motor_revolution * scale)
    return one_count / 2.0 + 1e-12
