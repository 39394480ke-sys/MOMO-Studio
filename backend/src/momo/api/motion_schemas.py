"""Unit-explicit HTTP DTOs translated into the unified MotionCommand model."""

from __future__ import annotations

from typing import Annotated, Literal, Self

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
from momo.domain.motion_command import (
    MAX_EFFECTIVE_MOTION_DURATION_S,
    MIN_CONTINUOUS_SPEED_UNITS_S,
    MIN_MOTION_DURATION_S,
    MIN_SPEED_SCALE,
    CartesianJogPayload,
    ContinuousJogPayload,
    HomePayload,
    JointJogStepPayload,
    JointMovePayload,
    MotionCommand,
    MovePosePayload,
)
from momo.domain.pose import TcpPose, Vector3
from momo.domain.robot import JointId, JointState


class MotionRequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_state_sequence: Annotated[int, Field(strict=True, ge=0)]
    expected_profile_fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    expected_kinematics_fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    source: Literal[MotionCommandSource.CONTROL] = MotionCommandSource.CONTROL
    idempotency_key: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ]
    speed_scale: Annotated[
        float,
        Field(strict=True, ge=MIN_SPEED_SCALE, le=1, allow_inf_nan=False),
    ] = 1.0

    def to_command(
        self,
        command_type: MotionCommandType,
        payload: object,
    ) -> MotionCommand:
        if not isinstance(
            payload,
            (
                JointMovePayload,
                JointJogStepPayload,
                ContinuousJogPayload,
                CartesianJogPayload,
                MovePosePayload,
                HomePayload,
            ),
        ):
            raise TypeError("invalid motion payload")
        return MotionCommand(
            robot_id="primary",
            source=self.source,
            expected_state_sequence=self.expected_state_sequence,
            expected_profile_fingerprint=self.expected_profile_fingerprint,
            expected_kinematics_fingerprint=self.expected_kinematics_fingerprint,
            command_type=command_type,
            payload=payload,
            speed_scale=self.speed_scale,
            idempotency_key=self.idempotency_key,
        )


class MoveJointsRequest(MotionRequestBase):
    joint_state: JointState
    duration_s: Annotated[
        float,
        Field(
            strict=True,
            ge=MIN_MOTION_DURATION_S,
            le=MAX_EFFECTIVE_MOTION_DURATION_S,
            allow_inf_nan=False,
        ),
    ] = 1.0

    @field_validator("joint_state")
    @classmethod
    def require_explicit_joint_units(cls, value: JointState) -> JointState:
        if value.units is None:
            raise ValueError("joint_state.units is required at the HTTP boundary")
        return value

    def command(self) -> MotionCommand:
        return self.to_command(
            MotionCommandType.MOVE_JOINTS,
            JointMovePayload(joint_state=self.joint_state, duration_s=self.duration_s),
        )


class ForwardKinematicsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    joint_state: JointState

    @field_validator("joint_state")
    @classmethod
    def require_explicit_joint_units(cls, value: JointState) -> JointState:
        if value.units is None:
            raise ValueError("joint_state.units is required at the HTTP boundary")
        return value


class JointJogStepRequest(MotionRequestBase):
    joint_id: JointId
    delta: Annotated[float, Field(strict=True, allow_inf_nan=False)]
    unit: DomainUnit
    duration_s: Annotated[
        float,
        Field(
            strict=True,
            ge=MIN_MOTION_DURATION_S,
            le=MAX_EFFECTIVE_MOTION_DURATION_S,
            allow_inf_nan=False,
        ),
    ] = 0.25

    def command(self) -> MotionCommand:
        return self.to_command(
            MotionCommandType.JOINT_JOG_STEP,
            JointJogStepPayload(
                joint_id=self.joint_id,
                delta=self.delta,
                unit=self.unit,
                duration_s=self.duration_s,
            ),
        )


class ContinuousJogStartRequest(MotionRequestBase):
    joint_id: JointId
    direction: Literal[-1, 1]
    speed_units_s: Annotated[
        float,
        Field(
            strict=True,
            ge=MIN_CONTINUOUS_SPEED_UNITS_S,
            le=100,
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

    def command(self) -> MotionCommand:
        return self.to_command(
            MotionCommandType.CONTINUOUS_JOG,
            ContinuousJogPayload(
                joint_id=self.joint_id,
                direction=self.direction,
                speed_units_s=self.speed_units_s,
                unit=self.unit,
            ),
        )


class CartesianJogRequest(MotionRequestBase):
    delta_position_mm: Vector3
    delta_rotation_deg: Vector3
    frame: CartesianFrame
    translation_unit: Literal["mm"]
    rotation_unit: Literal["deg"]
    duration_s: Annotated[
        float,
        Field(
            strict=True,
            ge=MIN_MOTION_DURATION_S,
            le=MAX_EFFECTIVE_MOTION_DURATION_S,
            allow_inf_nan=False,
        ),
    ] = 0.5

    def command(self) -> MotionCommand:
        return self.to_command(
            MotionCommandType.CARTESIAN_JOG,
            CartesianJogPayload(
                delta_position_mm=self.delta_position_mm,
                delta_rotation_deg=self.delta_rotation_deg,
                frame=self.frame,
                duration_s=self.duration_s,
            ),
        )


class CartesianJogStartRequest(MotionRequestBase):
    kind: Literal["translation", "rotation"]
    axis: Literal["x", "y", "z"]
    direction: Literal[-1, 1]
    speed_units_s: Annotated[
        float,
        Field(strict=True, ge=0.1, le=50.0, allow_inf_nan=False),
    ]
    unit: Literal["mm", "deg"]
    frame: CartesianFrame

    @field_validator("direction", mode="before")
    @classmethod
    def reject_boolean_direction(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("direction must be numeric -1 or 1, not boolean")
        return value

    @model_validator(mode="after")
    def unit_matches_kind(self) -> Self:
        expected = "mm" if self.kind == "translation" else "deg"
        if self.unit != expected:
            raise ValueError(f"{self.kind} Cartesian jog unit must be {expected}")
        return self

    def command(self) -> MotionCommand:
        horizon_s = 30.0
        translation = {"x": 0.0, "y": 0.0, "z": 0.0}
        rotation = {"x": 0.0, "y": 0.0, "z": 0.0}
        target = translation if self.kind == "translation" else rotation
        target[self.axis] = self.direction * self.speed_units_s * horizon_s
        return self.to_command(
            MotionCommandType.CARTESIAN_JOG,
            CartesianJogPayload(
                delta_position_mm=Vector3(**translation),
                delta_rotation_deg=Vector3(**rotation),
                frame=self.frame,
                duration_s=horizon_s,
                lease_controlled=True,
            ),
        )


class MovePoseRequest(MotionRequestBase):
    target_pose: TcpPose
    position_unit: Literal["mm"]
    orientation_unit: Literal["quaternion_xyzw"]
    duration_s: Annotated[
        float,
        Field(
            strict=True,
            ge=MIN_MOTION_DURATION_S,
            le=MAX_EFFECTIVE_MOTION_DURATION_S,
            allow_inf_nan=False,
        ),
    ] = 1.0

    def command(self) -> MotionCommand:
        return self.to_command(
            MotionCommandType.MOVE_POSE,
            MovePosePayload(target_pose=self.target_pose, duration_s=self.duration_s),
        )


class HomeRequest(MotionRequestBase):
    confirm: Literal["HOME"]
    duration_s: Annotated[
        float,
        Field(
            strict=True,
            ge=MIN_MOTION_DURATION_S,
            le=MAX_EFFECTIVE_MOTION_DURATION_S,
            allow_inf_nan=False,
        ),
    ] = 2.0

    def command(self) -> MotionCommand:
        return self.to_command(
            MotionCommandType.HOME,
            HomePayload(confirm=self.confirm, duration_s=self.duration_s),
        )


class InverseKinematicsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_pose: TcpPose
    position_unit: Literal["mm"]
    orientation_unit: Literal["quaternion_xyzw"]
    seed_joint_state: JointState | None = None
    position_only: Annotated[bool, Field(strict=True)] = False
    maximum_iterations: Annotated[int, Field(strict=True, ge=1, le=1000)] = 200

    @field_validator("seed_joint_state")
    @classmethod
    def require_explicit_seed_units(cls, value: JointState | None) -> JointState | None:
        if value is not None and value.units is None:
            raise ValueError("seed_joint_state.units is required at the HTTP boundary")
        return value
