"""Strict, device-independent contracts for Stage 7 vision workflows.

The values in this module describe captured frames and observations only.  They do
not open cameras, retain media, or authorize robot motion.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from math import ceil, floor, isfinite
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

MAX_FRAME_WIDTH_PX = 4096
MAX_FRAME_HEIGHT_PX = 4096
MAX_FRAME_PIXELS = 1920 * 1080
MAX_ENCODED_FRAME_BYTES = 8 * 1024 * 1024

FrameId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
SourceId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
ProviderId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
NormalizedCoordinate = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Confidence = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0.0, le=1.0)]
FrameWidth = Annotated[int, Field(strict=True, ge=1, le=MAX_FRAME_WIDTH_PX)]
FrameHeight = Annotated[int, Field(strict=True, ge=1, le=MAX_FRAME_HEIGHT_PX)]


class CameraAccessPolicy(StrEnum):
    """Independent camera gate; Stage 7 defaults never imply live access."""

    DISABLED = "DISABLED"
    SYNTHETIC_ONLY = "SYNTHETIC_ONLY"
    LIVE_CAMERA_ALLOWED = "LIVE_CAMERA_ALLOWED"


class VisionProviderKind(StrEnum):
    FRAME_SOURCE = "FRAME_SOURCE"
    TARGET_DETECTOR = "TARGET_DETECTOR"
    FACE_DETECTOR = "FACE_DETECTOR"
    TARGET_TRACKER = "TARGET_TRACKER"
    STREAM_ENCODER = "STREAM_ENCODER"


class VisionProviderStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


# Descriptive aliases keep API/application naming explicit without inventing a
# second status vocabulary.
ProviderCapabilityStatus = VisionProviderStatus
VisionCapabilityStatus = VisionProviderStatus


class VisionStatus(StrEnum):
    DISABLED = "DISABLED"
    READY = "READY"
    STREAMING = "STREAMING"
    DISCONNECTED = "DISCONNECTED"
    FAULTED = "FAULTED"
    CLOSED = "CLOSED"


class TargetKind(StrEnum):
    MANUAL = "MANUAL"
    PERSON = "PERSON"
    FACE = "FACE"


DetectionKind = TargetKind


class TrackingStatus(StrEnum):
    UNINITIALIZED = "UNINITIALIZED"
    LOCKED = "LOCKED"
    LOST = "LOST"
    STALE = "STALE"
    FAULTED = "FAULTED"


def _require_aware_timestamp(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return value


class FrameMetadata(BaseModel):
    """Identity, time, source, and explicit dimensions for one captured frame."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    frame_id: FrameId
    source_id: SourceId
    captured_at: datetime
    width_px: FrameWidth
    height_px: FrameHeight

    @field_validator("captured_at")
    @classmethod
    def captured_at_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware_timestamp(value, "captured_at")

    @model_validator(mode="after")
    def resolution_must_be_bounded(self) -> Self:
        if self.width_px * self.height_px > MAX_FRAME_PIXELS:
            raise ValueError(f"frame resolution exceeds {MAX_FRAME_PIXELS} pixels")
        return self


class NormalizedBoundingBox(BaseModel):
    """A frame-bound box using finite ``x/y/width/height`` values in ``[0, 1]``.

    Box identity is deliberately self-contained.  A client cannot submit four
    coordinates detached from the source frame, timestamp, or pixel dimensions that
    gave those coordinates meaning.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    x: NormalizedCoordinate
    y: NormalizedCoordinate
    width: NormalizedCoordinate
    height: NormalizedCoordinate
    frame_id: FrameId
    source_id: SourceId
    captured_at: datetime
    frame_width_px: FrameWidth
    frame_height_px: FrameHeight

    @field_validator("captured_at")
    @classmethod
    def captured_at_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware_timestamp(value, "captured_at")

    @model_validator(mode="after")
    def validate_box(self) -> Self:
        coordinates = (self.x, self.y, self.width, self.height)
        if not all(isfinite(value) for value in coordinates):
            raise ValueError("bounding-box coordinates must be finite")
        if self.x < 0.0 or self.y < 0.0:
            raise ValueError("bounding-box origin must be within the normalized frame")
        if self.width <= 0.0 or self.height <= 0.0:
            raise ValueError("bounding-box width and height must be greater than zero")
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise ValueError("bounding box must not extend outside the normalized frame")
        if self.frame_width_px * self.frame_height_px > MAX_FRAME_PIXELS:
            raise ValueError(f"frame resolution exceeds {MAX_FRAME_PIXELS} pixels")
        return self

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2.0

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2.0

    @property
    def metadata(self) -> FrameMetadata:
        return FrameMetadata(
            frame_id=self.frame_id,
            source_id=self.source_id,
            captured_at=self.captured_at,
            width_px=self.frame_width_px,
            height_px=self.frame_height_px,
        )

    @classmethod
    def from_metadata(
        cls,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        metadata: FrameMetadata,
    ) -> Self:
        return cls(
            x=x,
            y=y,
            width=width,
            height=height,
            frame_id=metadata.frame_id,
            source_id=metadata.source_id,
            captured_at=metadata.captured_at,
            frame_width_px=metadata.width_px,
            frame_height_px=metadata.height_px,
        )

    @classmethod
    def from_pixels(
        cls,
        *,
        x_px: int,
        y_px: int,
        width_px: int,
        height_px: int,
        metadata: FrameMetadata,
    ) -> Self:
        values = (x_px, y_px, width_px, height_px)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise TypeError("pixel bounding-box coordinates must be integers")
        if x_px < 0 or y_px < 0 or width_px <= 0 or height_px <= 0:
            raise ValueError("pixel bounding box must have a non-negative origin and positive size")
        if x_px + width_px > metadata.width_px or y_px + height_px > metadata.height_px:
            raise ValueError("pixel bounding box must not extend outside the frame")
        return cls.from_metadata(
            x=x_px / metadata.width_px,
            y=y_px / metadata.height_px,
            width=width_px / metadata.width_px,
            height=height_px / metadata.height_px,
            metadata=metadata,
        )

    def to_pixels(self) -> tuple[int, int, int, int]:
        """Return an enclosing integer ``x/y/width/height`` pixel rectangle."""

        # The tiny tolerance prevents binary representations such as
        # ``(0.2 + 0.4) * 360 == 216.00000000000003`` from adding a phantom pixel.
        left = floor(self.x * self.frame_width_px + 1e-12)
        top = floor(self.y * self.frame_height_px + 1e-12)
        right = ceil((self.x + self.width) * self.frame_width_px - 1e-12)
        bottom = ceil((self.y + self.height) * self.frame_height_px - 1e-12)
        return left, top, right - left, bottom - top


class VisionFrame(BaseModel):
    """One bounded encoded frame; consumers may retain only their latest value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: FrameMetadata
    content: Annotated[bytes, Field(strict=True, max_length=MAX_ENCODED_FRAME_BYTES)]
    media_type: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
    ]

    @property
    def frame_id(self) -> str:
        return self.metadata.frame_id

    @property
    def source_id(self) -> str:
        return self.metadata.source_id

    @property
    def captured_at(self) -> datetime:
        return self.metadata.captured_at

    @property
    def width_px(self) -> int:
        return self.metadata.width_px

    @property
    def height_px(self) -> int:
        return self.metadata.height_px


class TargetSelection(BaseModel):
    """Manual target selection bound to the exact frame the operator saw."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bounding_box: NormalizedBoundingBox
    target_kind: TargetKind = TargetKind.MANUAL


class Detection(BaseModel):
    """One honest provider observation; an empty result is represented by no value."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    target_kind: TargetKind
    bounding_box: NormalizedBoundingBox
    confidence: Confidence
    provider_id: ProviderId

    @model_validator(mode="after")
    def detector_cannot_claim_manual_selection(self) -> Self:
        if self.target_kind is TargetKind.MANUAL:
            raise ValueError("detectors cannot emit MANUAL target observations")
        return self

    @property
    def metadata(self) -> FrameMetadata:
        return self.bounding_box.metadata


class TrackingResult(BaseModel):
    """Fail-closed tracker output for one exact frame."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    metadata: FrameMetadata
    status: TrackingStatus
    bounding_box: NormalizedBoundingBox | None = None
    confidence: Confidence = 0.0
    detail: Annotated[str, StringConstraints(max_length=500)] = ""

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.status is TrackingStatus.LOCKED:
            if self.bounding_box is None:
                raise ValueError("LOCKED tracking requires a bounding box")
            if self.confidence <= 0.0:
                raise ValueError("LOCKED tracking requires positive confidence")
            if self.bounding_box.metadata != self.metadata:
                raise ValueError("tracking box metadata must match result metadata")
        else:
            if self.bounding_box is not None:
                raise ValueError("non-LOCKED tracking must not reuse a bounding box")
            if self.confidence != 0.0:
                raise ValueError("non-LOCKED tracking confidence must be zero")
        return self


class VisionProviderCapability(BaseModel):
    """User-visible truth about one source, detector, tracker, or encoder."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: ProviderId
    kind: VisionProviderKind
    status: VisionProviderStatus
    display_name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ]
    model_source: Annotated[str, StringConstraints(max_length=500)] | None = None
    notice: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
    ]
    detail: Annotated[str, StringConstraints(max_length=500)] = ""

    @property
    def available(self) -> bool:
        return self.status is VisionProviderStatus.AVAILABLE


def box_matches_metadata(box: NormalizedBoundingBox, metadata: FrameMetadata) -> bool:
    """Exact identity check used at selection/tracker boundaries."""

    return box.metadata == metadata
