"""Validated application inputs for Pose and Motion library use cases."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from momo.domain.enums import RobotVariant
from momo.domain.motion import MotionKeyframe, PlaybackDefaults
from momo.domain.motion_command import MAX_EFFECTIVE_MOTION_DURATION_S, MIN_MOTION_DURATION_S
from momo.domain.pose import Name, PoseSnapshot

ExpectedRevision = Annotated[int, Field(strict=True, ge=1)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


def _require_unique_tags(value: list[str]) -> list[str]:
    """Reject duplicates after the API's whitespace/case normalization."""

    normalized = [tag.strip() for tag in value]
    normalized_keys = [tag.casefold() for tag in normalized]
    if len(normalized_keys) != len(set(normalized_keys)):
        raise ValueError("tags must be unique after normalization")
    return normalized


Tags = Annotated[list[Tag], Field(max_length=32), AfterValidator(_require_unique_tags)]


class PoseCreateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    description: Annotated[str, StringConstraints(max_length=5000)] = ""
    tags: Tags = Field(default_factory=list)
    snapshot: PoseSnapshot


class PoseCaptureCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    description: Annotated[str, StringConstraints(max_length=5000)] = ""
    tags: Tags = Field(default_factory=list)


class PosePatchCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: ExpectedRevision
    name: Name | None = None
    description: Annotated[str, StringConstraints(max_length=5000)] | None = None
    tags: Tags | None = None

    @model_validator(mode="after")
    def require_change(self) -> Self:
        editable = {"name", "description", "tags"}
        changed = editable & self.model_fields_set
        if not changed:
            raise ValueError("PATCH must include at least one editable field")
        if any(getattr(self, field) is None for field in changed):
            raise ValueError("PATCH editable fields must not be null")
        return self


class DuplicateEntityCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: ExpectedRevision
    name: Name | None = None


class GotoPoseCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: ExpectedRevision
    duration_s: Annotated[
        float,
        Field(
            strict=True,
            ge=MIN_MOTION_DURATION_S,
            le=MAX_EFFECTIVE_MOTION_DURATION_S,
            allow_inf_nan=False,
        ),
    ] = 1.0
    speed_scale: Annotated[float, Field(strict=True, ge=0.05, le=1, allow_inf_nan=False)] = 1.0
    idempotency_key: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ]


class MotionCreateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    description: Annotated[str, StringConstraints(max_length=5000)] = ""
    robot_variant: RobotVariant
    keyframes: Annotated[list[MotionKeyframe], Field(min_length=2, max_length=1000)]
    playback_defaults: PlaybackDefaults = Field(default_factory=PlaybackDefaults)
    tags: Tags = Field(default_factory=list)


class MotionPatchCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: ExpectedRevision
    name: Name | None = None
    description: Annotated[str, StringConstraints(max_length=5000)] | None = None
    robot_variant: RobotVariant | None = None
    keyframes: Annotated[list[MotionKeyframe], Field(min_length=2, max_length=1000)] | None = None
    playback_defaults: PlaybackDefaults | None = None
    tags: Tags | None = None

    @model_validator(mode="after")
    def require_change(self) -> Self:
        editable = {
            "name",
            "description",
            "robot_variant",
            "keyframes",
            "playback_defaults",
            "tags",
        }
        changed = editable & self.model_fields_set
        if not changed:
            raise ValueError("PATCH must include at least one editable field")
        if any(getattr(self, field) is None for field in changed):
            raise ValueError("PATCH editable fields must not be null")
        return self
