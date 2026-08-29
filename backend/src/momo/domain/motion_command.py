"""Unified, unit-explicit command intent for every Stage 3 motion."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from momo.domain.enums import (
    CartesianFrame,
    DomainUnit,
    MotionCommandSource,
    MotionCommandType,
)
from momo.domain.pose import TcpPose, Vector3, utc_now
from momo.domain.robot import JointId, JointState

MIN_SPEED_SCALE = 0.05
MIN_CONTINUOUS_SPEED_UNITS_S = 0.1
MIN_MOTION_DURATION_S = 0.1
MAX_EFFECTIVE_MOTION_DURATION_S = 60.0
Duration = Annotated[
    float,
    Field(
        strict=True,
        ge=MIN_MOTION_DURATION_S,
        le=MAX_EFFECTIVE_MOTION_DURATION_S,
        allow_inf_nan=False,
    ),
]


class JointMovePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    joint_state: JointState
    duration_s: Duration = 1.0

    @model_validator(mode="after")
    def require_explicit_units(self) -> Self:
        if self.joint_state.units is None:
            raise ValueError("joint move units must be explicit")
        return self


class JointJogStepPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    joint_id: JointId
    delta: Annotated[float, Field(strict=True, allow_inf_nan=False)]
    unit: DomainUnit
    duration_s: Duration = 0.25


class ContinuousJogPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    joint_id: JointId
    direction: Literal[-1, 1]
    speed_units_s: Annotated[
        float,
        Field(
            strict=True,
            ge=MIN_CONTINUOUS_SPEED_UNITS_S,
            le=100.0,
            allow_inf_nan=False,
        ),
    ]
    unit: DomainUnit

    @field_validator("direction", mode="before")
    @classmethod
    def reject_boolean_direction(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("direction must be numeric -1 or 1, not boolean")
        return value


class CartesianJogPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    delta_position_mm: Vector3
    delta_rotation_deg: Vector3
    frame: CartesianFrame
    duration_s: Duration = 0.5
    lease_controlled: bool = False


class MovePosePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    target_pose: TcpPose
    duration_s: Duration = 1.0


class HomePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    confirm: Literal["HOME"]
    duration_s: Duration = 2.0


MotionPayload = (
    JointMovePayload
    | JointJogStepPayload
    | ContinuousJogPayload
    | CartesianJogPayload
    | MovePosePayload
    | HomePayload
)


class MotionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    command_id: UUID = Field(default_factory=uuid4)
    robot_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
    source: MotionCommandSource
    issued_at: datetime = Field(default_factory=utc_now)
    expected_state_sequence: Annotated[int, Field(strict=True, ge=0)]
    expected_profile_fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    expected_kinematics_fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    command_type: MotionCommandType
    payload: MotionPayload
    speed_scale: Annotated[
        float,
        Field(strict=True, ge=MIN_SPEED_SCALE, le=1.0, allow_inf_nan=False),
    ] = 1.0
    idempotency_key: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ]

    @field_validator("issued_at")
    @classmethod
    def require_aware_issued_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("issued_at must include a timezone offset")
        return value

    @model_validator(mode="after")
    def payload_matches_command_type(self) -> Self:
        expected: dict[MotionCommandType, type[BaseModel]] = {
            MotionCommandType.MOVE_JOINTS: JointMovePayload,
            MotionCommandType.JOINT_JOG_STEP: JointJogStepPayload,
            MotionCommandType.CONTINUOUS_JOG: ContinuousJogPayload,
            MotionCommandType.CARTESIAN_JOG: CartesianJogPayload,
            MotionCommandType.MOVE_POSE: MovePosePayload,
            MotionCommandType.HOME: HomePayload,
        }
        if not isinstance(self.payload, expected[self.command_type]):
            raise ValueError("motion payload does not match command_type")
        return self
