"""Bounded HTTP contracts for single-joint commissioning motion tests."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from momo.domain.commissioning import (
    CommissioningMotionTestState,
    PhysicalStopVerification,
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


__all__ = ["CommissioningMotionStatusResponse", "CommissioningRelativeTestRequest"]
