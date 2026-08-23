"""Lease/deadman contracts for continuous jog."""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from momo.domain.enums import MotionCommandState


class JogLeaseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    jog_session_id: UUID
    command_id: UUID
    lease_expires_in_ms: Annotated[int, Field(ge=0)]
    status: MotionCommandState


class JogStopResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    jog_session_id: UUID
    stopped: bool
    status: MotionCommandState
