"""Immutable preflight evidence and prepared Dry Run motion values."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from momo.domain.enums import DomainUnit, MotionCommandState
from momo.domain.immutable import freeze_sequence
from momo.domain.motion_command import MAX_EFFECTIVE_MOTION_DURATION_S, MIN_MOTION_DURATION_S
from momo.domain.pose import utc_now
from momo.domain.robot import JointState


class PreflightCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    passed: bool
    detail: str


class MotionPreflight(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    accepted: bool
    command_id: UUID
    checks: list[PreflightCheck]
    warnings: list[str]
    profile_fingerprint: str
    kinematics_fingerprint: str

    @field_validator("checks", "warnings")
    @classmethod
    def freeze_lists(cls, value: list[object]) -> list[object]:
        return freeze_sequence(value)


class PreparedMotion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_id: UUID
    start_state: JointState
    target_state: JointState
    duration_s: Annotated[
        float,
        Field(
            ge=MIN_MOTION_DURATION_S,
            le=MAX_EFFECTIVE_MOTION_DURATION_S,
            allow_inf_nan=False,
        ),
    ]
    preflight: MotionPreflight


class PreparedContinuousJog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_id: UUID
    start_state: JointState
    joint_id: str
    direction: Literal[-1, 1]
    speed_units_s: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    acceleration_units_s2: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    unit: DomainUnit
    minimum: Annotated[float, Field(allow_inf_nan=False)]
    maximum: Annotated[float, Field(allow_inf_nan=False)]
    preflight: MotionPreflight


class MotionCommandStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    command_id: UUID
    state: MotionCommandState
    progress: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    preflight: MotionPreflight
    error: str | None = None
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    hardware_accessed: bool = False


class MotionAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_id: UUID
    status: MotionCommandState
    preflight: MotionPreflight
