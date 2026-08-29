"""Bounded HTTP contracts for single-joint commissioning motion tests."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from momo.domain.commissioning import (
    CommissioningMotionTestState,
    PhysicalStopVerification,
)
from momo.domain.raw_direction import (
    RawDirection,
    RawDirectionCalibrationDraft,
    RawDirectionObservation,
    RawDirectionTestState,
    RawDirectionZeroSnapshot,
)


class CommissioningMotionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: CommissioningMotionTestState
    session_id: UUID | None
    active_joint_id: str | None
    command_count: int = Field(ge=0)
    session_expires_at: datetime | None
    deadman_expires_at: datetime | None
    last_evidence_id: UUID | None
    failure_reason: str | None
    physical_stop_verification: PhysicalStopVerification


class CommissioningRelativeTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    signed_delta: float
    requested_speed: float = Field(gt=0.0)
    requested_acceleration: float = Field(gt=0.0)
    command_duration_s: float = Field(gt=0.0)
    request_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
    ]


class CommissioningDirectStepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    signed_delta: float
    requested_speed: float = Field(gt=0.0)


class CommissioningDirectJogStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    direction: Literal[-1, 1]
    requested_speed: float = Field(gt=0.0)


class CommissioningDirectControlResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    running: bool
    mode: Literal["STEP", "CONTINUOUS", "IDLE"]
    joint_id: str | None
    direction: int | None
    requested_speed: float | None
    logical_position: float | None
    raw_position: int | None
    target_value: float | None
    message: str


class CommissioningDirectJointStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    positions: dict[str, float]
    units: dict[str, Literal["mm", "deg"]]
    raw_positions: dict[str, int]
    captured_at: datetime
    moving: bool
    message: str


class RawDirectionStepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: RawDirection


class RawDirectionAlignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matches_urdf: bool


class RawDirectionDraftConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_text: Annotated[
        str,
        StringConstraints(strip_whitespace=False, min_length=1, max_length=128),
    ]


class RawDirectionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: RawDirectionTestState
    session_id: UUID | None
    active_joint_id: str | None
    command_count: int = Field(ge=0)
    session_expires_at: datetime | None
    deadman_expires_at: datetime | None
    zero_snapshot: RawDirectionZeroSnapshot | None
    last_observation: RawDirectionObservation | None
    observations: tuple[RawDirectionObservation, ...]
    calibration_draft: RawDirectionCalibrationDraft | None
    failure_reason: str | None


__all__ = [
    "CommissioningDirectControlResponse",
    "CommissioningDirectJogStartRequest",
    "CommissioningDirectJointStateResponse",
    "CommissioningDirectStepRequest",
    "CommissioningMotionStatusResponse",
    "CommissioningRelativeTestRequest",
    "RawDirectionAlignmentRequest",
    "RawDirectionDraftConfirmationRequest",
    "RawDirectionStatusResponse",
    "RawDirectionStepRequest",
]
