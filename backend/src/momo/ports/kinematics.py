"""Kinematics port and explicit domain-unit/SI boundary conversions."""

from __future__ import annotations

from dataclasses import dataclass
from math import degrees, isfinite, radians
from typing import Protocol, runtime_checkable

from momo.domain.enums import CartesianFrame, DomainUnit
from momo.domain.errors import JointStateValidationError
from momo.domain.immutable import freeze_mapping
from momo.domain.kinematics.model import KinematicsModel
from momo.domain.pose import QuaternionXYZW, TcpPose, Vector3
from momo.domain.robot import JointState, RobotProfile


@dataclass(frozen=True, slots=True)
class KinematicsJointState:
    """Adapter values: radians for revolute joints and metres for prismatic joints."""

    positions_si: dict[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "positions_si", freeze_mapping(self.positions_si))


@dataclass(frozen=True, slots=True)
class KinematicsTcpPose:
    """Adapter TCP pose: xyz in metres and an XYZW unit quaternion."""

    frame: str
    position_m: tuple[float, float, float]
    orientation_quaternion_xyzw: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class KinematicsInverseResult:
    success: bool
    solution: KinematicsJointState | None
    best_solution: KinematicsJointState | None
    iterations: int
    position_error_m: float
    orientation_error_rad: float | None
    termination_reason: str
    warnings: tuple[str, ...] = ()


def to_kinematics_joint_state(
    state: JointState,
    profile: RobotProfile,
) -> KinematicsJointState:
    """Explicitly convert canonical deg/mm joint values to adapter rad/m values."""

    state.validate_against(profile)
    definitions = profile.definitions_by_id
    positions_si = {
        joint_id: (
            radians(state.positions[joint_id])
            if definitions[joint_id].domain_unit is DomainUnit.DEG
            else state.positions[joint_id] / 1000.0
        )
        for joint_id in profile.enabled_joints
    }
    return KinematicsJointState(positions_si=positions_si)


def from_kinematics_joint_state(
    state: KinematicsJointState,
    profile: RobotProfile,
) -> JointState:
    """Explicitly convert adapter rad/m values to canonical deg/mm values."""

    expected = set(profile.enabled_joints)
    actual = set(state.positions_si)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise JointStateValidationError(f"missing kinematics joints: {missing}")
    if unknown:
        raise JointStateValidationError(f"unknown kinematics joints: {unknown}")

    for joint_id, value in state.positions_si.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            raise JointStateValidationError(
                f"{joint_id} kinematics position must be a finite number"
            )

    definitions = profile.definitions_by_id
    positions = {
        joint_id: (
            degrees(state.positions_si[joint_id])
            if definitions[joint_id].domain_unit is DomainUnit.DEG
            else state.positions_si[joint_id] * 1000.0
        )
        for joint_id in profile.enabled_joints
    }
    return JointState(
        positions=positions,
        units={joint_id: definitions[joint_id].domain_unit for joint_id in profile.enabled_joints},
    ).validate_against(profile)


def to_kinematics_tcp_pose(pose: TcpPose) -> KinematicsTcpPose:
    """Explicitly convert canonical millimetres to adapter metres."""

    position = pose.position_mm
    quaternion = pose.orientation_quaternion_xyzw
    return KinematicsTcpPose(
        frame=pose.frame,
        position_m=(position.x / 1000.0, position.y / 1000.0, position.z / 1000.0),
        orientation_quaternion_xyzw=(
            quaternion.x,
            quaternion.y,
            quaternion.z,
            quaternion.w,
        ),
    )


def from_kinematics_tcp_pose(pose: KinematicsTcpPose) -> TcpPose:
    """Explicitly convert adapter metres to canonical millimetres."""

    x, y, z = pose.position_m
    qx, qy, qz, qw = pose.orientation_quaternion_xyzw
    return TcpPose(
        frame=pose.frame,
        position_mm=Vector3(x=x * 1000.0, y=y * 1000.0, z=z * 1000.0),
        orientation_quaternion_xyzw=QuaternionXYZW(x=qx, y=qy, z=qz, w=qw),
    )


@runtime_checkable
class Kinematics(Protocol):
    """An adapter contract whose numeric boundary is explicitly SI."""

    async def forward(
        self,
        model: KinematicsModel,
        joints: KinematicsJointState,
    ) -> KinematicsTcpPose: ...

    async def inverse(
        self,
        model: KinematicsModel,
        target: KinematicsTcpPose,
        seed: KinematicsJointState | None = None,
        *,
        position_only: bool = False,
        maximum_iterations: int = 200,
        position_tolerance_m: float = 0.001,
        orientation_tolerance_rad: float = 0.02,
    ) -> KinematicsInverseResult: ...

    def compose_delta(
        self,
        current: KinematicsTcpPose,
        delta_position_m: tuple[float, float, float],
        delta_rpy_rad: tuple[float, float, float],
        frame: CartesianFrame,
    ) -> KinematicsTcpPose: ...
