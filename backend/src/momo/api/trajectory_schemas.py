"""Bounded HTTP DTOs for compiled trajectory preflight, preview, and playback."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from momo.domain.enums import DomainUnit, MotionMode
from momo.domain.pose import Fingerprint
from momo.domain.trajectory import TrajectoryPreflightCheck, TrajectoryViolation


class TrajectoryPreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: Annotated[int, Field(strict=True, ge=1)]
    sample_rate_hz: Annotated[
        float,
        Field(strict=True, ge=5.0, le=50.0, allow_inf_nan=False),
    ] = 25.0


class TrajectoryPreflightResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    digest: Fingerprint | None
    motion_id: UUID
    motion_revision: Annotated[int, Field(strict=True, ge=1)]
    duration_s: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    sample_count: Annotated[int, Field(strict=True, ge=0, le=20000)]
    segment_count: Annotated[int, Field(strict=True, ge=0, le=2000)]
    sample_rate_hz: Annotated[
        float,
        Field(strict=True, gt=0, le=100, allow_inf_nan=False),
    ]
    violations: list[TrajectoryViolation]
    checks: list[TrajectoryPreflightCheck]
    prepared_at: datetime | None = None
    real_motion_ready: bool = False
    field_acceptance_ready: bool = False
    hardware_accessed: bool = False


class PlaybackStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: Annotated[int, Field(strict=True, ge=1)]
    trajectory_digest: Fingerprint
    loop: bool = False
    rate: Annotated[
        float,
        Field(strict=True, ge=0.25, le=2.0, allow_inf_nan=False),
    ] = 1.0


class PlaybackRateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate: Annotated[
        float,
        Field(strict=True, ge=0.25, le=2.0, allow_inf_nan=False),
    ]


class PlaybackLoopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loop: bool


class TrajectoryPreviewPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    time_s: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    value: Annotated[float, Field(strict=True, allow_inf_nan=False)]
    unit: DomainUnit


class TrajectoryTcpPreviewPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    time_s: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    x_mm: Annotated[float, Field(strict=True, allow_inf_nan=False)]
    y_mm: Annotated[float, Field(strict=True, allow_inf_nan=False)]
    z_mm: Annotated[float, Field(strict=True, allow_inf_nan=False)]


class TrajectorySegmentPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    segment_index: Annotated[int, Field(strict=True, ge=0)]
    motion_mode: MotionMode | Literal["HOLD"]
    start_time_s: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    end_time_s: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    sample_count: Annotated[int, Field(strict=True, ge=1)]
    start_keyframe_id: UUID | None
    end_keyframe_id: UUID | None


class TrajectoryKeyframeMarker(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    keyframe_id: UUID
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    time_s: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    sample_index: Annotated[int, Field(strict=True, ge=0)]


class TrajectoryPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    digest: Fingerprint
    motion_id: UUID
    duration_s: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
    sample_rate_hz: Annotated[
        float,
        Field(strict=True, gt=0, le=100, allow_inf_nan=False),
    ]
    sample_count: Annotated[int, Field(strict=True, ge=2, le=20000)]
    segments: list[TrajectorySegmentPreview]
    joint_series: dict[str, list[TrajectoryPreviewPoint]]
    tcp_path: list[TrajectoryTcpPreviewPoint]
    keyframe_markers: list[TrajectoryKeyframeMarker]
