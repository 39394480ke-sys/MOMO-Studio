"""Strict Stage 7 Vision HTTP contracts.

The browser supplies only normalized selections and explicit operator intent.  It
never supplies pixels, raw camera identifiers, joint state, or motion commands.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from momo.domain.enums import ProfileVerificationStatus
from momo.domain.robot import JointId

FrameIdValue = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=96),
]


class NormalizedBoundingBoxDto(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    x: Annotated[float, Field(strict=True, ge=0.0, lt=1.0)]
    y: Annotated[float, Field(strict=True, ge=0.0, lt=1.0)]
    width: Annotated[float, Field(strict=True, gt=0.0, le=1.0)]
    height: Annotated[float, Field(strict=True, gt=0.0, le=1.0)]

    @model_validator(mode="after")
    def remain_inside_normalized_frame(self) -> Self:
        if self.x + self.width > 1.0:
            raise ValueError("x + width must be <= 1.0")
        if self.y + self.height > 1.0:
            raise ValueError("y + height must be <= 1.0")
        return self


class VisionSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_id: FrameIdValue
    bounding_box: NormalizedBoundingBoxDto


class VisionDetectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_id: FrameIdValue


class VisionProviderCapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str
    kind: str
    available: bool
    active: bool
    model_source: str
    notice: str
    reason: str | None


class VisionCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_access_policy: str
    source: VisionProviderCapabilityResponse
    trackers: list[VisionProviderCapabilityResponse]
    detectors: list[VisionProviderCapabilityResponse]
    stream: VisionProviderCapabilityResponse
    real_follow_allowed: Literal[False] = False
    real_follow_blocked_reason: str


class VisionFrameMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_id: str
    width_px: int
    height_px: int
    captured_at: datetime
    source_id: str
    age_ms: float


class VisionTargetSelectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_id: str
    bounding_box: NormalizedBoundingBoxDto


class VisionTrackingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_id: str
    source_id: str
    captured_at: datetime
    bounding_box: NormalizedBoundingBoxDto | None
    confidence: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
    status: Literal["LOCKED", "LOST", "STALE", "FAULTED"]
    error: str | None


class VisionDetectionResponseItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detection_id: str
    frame_id: str
    source_id: str
    captured_at: datetime
    bounding_box: NormalizedBoundingBoxDto
    confidence: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
    label: str


class VisionDetectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: VisionProviderCapabilityResponse
    detections: list[VisionDetectionResponseItem]


class VisionFollowStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool
    lease_id: UUID | None
    expires_at: datetime | None
    stop_reason: str | None
    error_x: float | None
    error_y: float | None
    ema_error_x: float | None
    ema_error_y: float | None
    last_command_id: UUID | None


class VisionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_access_policy: str
    source_state: str
    latest_frame: VisionFrameMetadataResponse | None
    selection: VisionTargetSelectionResponse | None
    tracking: VisionTrackingResponse | None
    follow: VisionFollowStatusResponse
    robot_state: str
    dry_run: Literal[True] = True
    real_follow_blocked_reason: str


class VisionFollowConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    dead_zone_x: Annotated[float, Field(strict=True, ge=0.0, le=0.45)] = 0.08
    dead_zone_y: Annotated[float, Field(strict=True, ge=0.0, le=0.45)] = 0.08
    ema_alpha: Annotated[float, Field(strict=True, gt=0.0, le=1.0)] = 0.35
    gain: Annotated[float, Field(strict=True, gt=0.0, le=100.0)] = 5.0
    max_step: Annotated[float, Field(strict=True, gt=0.0, le=15.0)] = 2.0
    max_rate: Annotated[float, Field(strict=True, ge=0.2, le=20.0)] = 5.0
    confidence_threshold: Annotated[float, Field(strict=True, ge=0.0, le=1.0)] = 0.5
    frame_freshness_limit_s: Annotated[float, Field(strict=True, gt=0.0, le=2.0)] = 0.5
    target_lost_limit_s: Annotated[float, Field(strict=True, gt=0.0, le=5.0)] = 0.75
    lease_ttl_s: Annotated[float, Field(strict=True, ge=0.25, le=2.0)] = 0.75

    @model_validator(mode="after")
    def fit_bounded_motion_duration(self) -> Self:
        if self.max_step / self.max_rate > 60.0:
            raise ValueError("max_step/max_rate must fit the bounded motion duration")
        return self


class VisionFollowMappingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pan_joint: JointId
    tilt_joint: JointId
    pan_sign: Literal[-1, 1]
    tilt_sign: Literal[-1, 1]
    verification_status: Literal[ProfileVerificationStatus.VERIFIED_FOR_DRY_RUN]

    @field_validator("pan_sign", "tilt_sign", mode="before")
    @classmethod
    def reject_boolean_signs(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("mapping signs must be numeric -1 or 1")
        return value

    @model_validator(mode="after")
    def require_distinct_joints(self) -> Self:
        if self.pan_joint == self.tilt_joint:
            raise ValueError("pan_joint and tilt_joint must be distinct")
        return self


class VisionFollowStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configuration: VisionFollowConfigurationRequest
    mapping: VisionFollowMappingRequest


class VisionFollowLeaseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: UUID
    expires_at: datetime
    status: VisionStatusResponse
