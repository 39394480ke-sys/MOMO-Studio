"""Bounded Studio draft summaries and compiler/save response envelopes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from momo.api.trajectory_schemas import TrajectoryPreflightResponse, TrajectoryPreviewResponse
from momo.domain.enums import RobotVariant
from momo.domain.motion import Motion
from momo.domain.motion_draft import MotionDraft


class MotionDraftSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    source_motion_id: UUID | None
    source_motion_revision: int | None
    name: str
    robot_variant: RobotVariant
    keyframe_count: Annotated[int, Field(strict=True, ge=0, le=1000)]
    created_at: datetime
    updated_at: datetime
    revision: Annotated[int, Field(strict=True, ge=1)]


class MotionDraftListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[MotionDraftSummary]
    page: int
    page_size: int
    total: int


class MotionDraftValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=80),
    ]
    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
    ]


class MotionDraftValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    draft_id: UUID
    draft_revision: Annotated[int, Field(strict=True, ge=1)]
    valid: bool
    issues: list[MotionDraftValidationIssue]


class MotionDraftCompileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    draft_id: UUID
    draft_revision: Annotated[int, Field(strict=True, ge=1)]
    preflight: TrajectoryPreflightResponse
    preview: TrajectoryPreviewResponse | None
    executable: Literal[False] = False


class MotionDraftSaveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    draft: MotionDraft
    motion: Motion
    preflight: TrajectoryPreflightResponse


class StudioCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
