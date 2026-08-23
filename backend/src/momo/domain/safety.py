"""Pure Stage 2 safety diagnostics before any future command boundary."""

from __future__ import annotations

from math import isfinite

from momo.domain.calibration import CalibrationJoint
from momo.domain.errors import HardwareMappingError
from momo.domain.hardware_mapping import effective_logical_limits_from_raw_bounds
from momo.domain.robot import RobotProfile


def validate_logical_value(
    joint_id: str,
    logical_value: float,
    profile: RobotProfile,
    calibration: CalibrationJoint,
) -> float:
    """Validate one unit-explicit domain value against logical and raw reachability."""

    value = float(logical_value)
    if not isfinite(value):
        raise HardwareMappingError("logical_value must be finite")
    lower, upper = effective_logical_limits_from_raw_bounds(joint_id, profile, calibration)
    if not lower <= value <= upper:
        unit = profile.definitions_by_id[joint_id].domain_unit.value
        raise HardwareMappingError(f"{joint_id} value {value} {unit} is outside [{lower}, {upper}]")
    return value
