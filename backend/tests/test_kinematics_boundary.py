"""Unit conversion is explicit and confined to kinematics boundary helpers."""

from math import pi

import pytest

from momo.domain.enums import RobotVariant
from momo.domain.errors import JointStateValidationError
from momo.domain.profiles import canonical_robot_profile
from momo.domain.robot import JointState
from momo.ports.kinematics import (
    KinematicsJointState,
    from_kinematics_joint_state,
    to_kinematics_joint_state,
)


def test_joint_boundary_converts_deg_mm_to_rad_m_and_back() -> None:
    profile = canonical_robot_profile(RobotVariant.V2)
    state = JointState(
        positions={
            "j10": 500.0,
            "j11": 180.0,
            "j12": 0.0,
            "j13": 0.0,
            "j14": 0.0,
            "j15": 0.0,
        }
    )
    adapter_state = to_kinematics_joint_state(state, profile)
    assert adapter_state.positions_si["j10"] == pytest.approx(0.5)
    assert adapter_state.positions_si["j11"] == pytest.approx(pi)
    round_trip = from_kinematics_joint_state(adapter_state, profile)
    assert round_trip.positions == state.positions
    assert round_trip.units == {
        definition.joint_id: definition.domain_unit for definition in profile.joint_definitions
    }


def test_inverse_joint_boundary_rejects_missing_and_unknown_keys() -> None:
    profile = canonical_robot_profile(RobotVariant.V2)
    valid = {joint_id: 0.0 for joint_id in profile.enabled_joints}

    missing = dict(valid)
    del missing["j15"]
    with pytest.raises(JointStateValidationError, match=r"missing kinematics joints.*j15"):
        from_kinematics_joint_state(KinematicsJointState(missing), profile)

    unknown = {**valid, "j99": 0.0}
    with pytest.raises(JointStateValidationError, match=r"unknown kinematics joints.*j99"):
        from_kinematics_joint_state(KinematicsJointState(unknown), profile)


@pytest.mark.parametrize("not_finite", [float("nan"), float("inf"), float("-inf")])
def test_inverse_joint_boundary_rejects_nonfinite_values(not_finite: float) -> None:
    profile = canonical_robot_profile(RobotVariant.V2)
    values = {joint_id: 0.0 for joint_id in profile.enabled_joints}
    values["j10"] = not_finite
    with pytest.raises(JointStateValidationError, match=r"j10.*finite number"):
        from_kinematics_joint_state(KinematicsJointState(values), profile)
