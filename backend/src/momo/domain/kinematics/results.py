"""Canonical application-facing FK and IK result contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from momo.domain.enums import RobotVariant
from momo.domain.immutable import freeze_sequence
from momo.domain.pose import TcpPose
from momo.domain.robot import JointState


class ForwardKinematicsResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    robot_id: str = "primary"
    variant: RobotVariant
    state_sequence: Annotated[int, Field(ge=0)]
    profile_fingerprint: str
    kinematics_fingerprint: str
    tcp_pose: TcpPose
    hardware_accessed: Literal[False] = False


class InverseKinematicsResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    success: bool
    joint_state_optional: JointState | None
    best_joint_state: JointState | None
    iterations: Annotated[int, Field(ge=0)]
    position_error_mm: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    orientation_error_deg: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None
    termination_reason: str
    warnings: list[str]
    kinematics_fingerprint: str

    @field_validator("warnings")
    @classmethod
    def freeze_warnings(cls, value: list[str]) -> list[str]:
        return freeze_sequence(value)
