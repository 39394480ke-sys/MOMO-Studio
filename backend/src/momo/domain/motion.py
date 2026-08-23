"""Self-contained motion/keyframe models and playback invariants."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from momo.domain.enums import Easing, MotionMode, RobotVariant
from momo.domain.immutable import freeze_sequence
from momo.domain.pose import Name, PoseSnapshot, _require_aware, utc_now
from momo.domain.profiles import profile_for_validation
from momo.domain.robot import SCHEMA_VERSION

FiniteNonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
FinitePositive = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class MotionTransition(BaseModel):
    """Movement from the previous keyframe into its owning keyframe."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    duration_s: FinitePositive
    motion_mode: MotionMode
    easing: Easing = Easing.SMOOTHSTEP


class MotionKeyframe(BaseModel):
    """A complete embedded snapshot plus its incoming transition metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    pose_snapshot: PoseSnapshot
    source_pose_id: UUID | None = None
    hold_s: FiniteNonNegative = 0.0
    incoming_transition: MotionTransition | None = None

    @field_validator("pose_snapshot", mode="before")
    @classmethod
    def detach_snapshot_from_source_pose(cls, value: object) -> object:
        # Pydantic may otherwise retain a nested model instance by reference. A keyframe
        # is deliberately a snapshot copy, never a live link to a Pose entity.
        if isinstance(value, PoseSnapshot):
            return value.model_dump(mode="python", round_trip=True)
        return value


class PlaybackDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    loop: bool = False
    speed_multiplier: FinitePositive = 1.0


class Motion(BaseModel):
    """A playable motion that never dereferences source Pose files at runtime."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    id: UUID = Field(default_factory=uuid4)
    name: Name
    description: str = ""
    robot_variant: RobotVariant
    keyframes: Annotated[list[MotionKeyframe], Field(min_length=2)]
    playback_defaults: PlaybackDefaults = Field(default_factory=PlaybackDefaults)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    revision: Annotated[int, Field(ge=1)] = 1

    @field_validator("schema_version")
    @classmethod
    def require_supported_schema_version(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(f"unsupported motion schema_version: {value}")
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_must_be_aware(cls, value: datetime, info: object) -> datetime:
        field_name = getattr(info, "field_name", "timestamp")
        return _require_aware(value, field_name)

    @field_validator("tags")
    @classmethod
    def tags_must_be_unique(cls, value: list[str]) -> list[str]:
        normalized = [tag.strip() for tag in value]
        if any(not tag for tag in normalized):
            raise ValueError("tags must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("tags must be unique")
        return freeze_sequence(normalized)

    @field_validator("keyframes")
    @classmethod
    def freeze_keyframes(cls, value: list[MotionKeyframe]) -> list[MotionKeyframe]:
        return freeze_sequence(value)

    @model_validator(mode="after")
    def validate_motion(self, info: ValidationInfo) -> Self:
        if len(self.keyframes) < 2:
            raise ValueError("a playable Motion requires at least two keyframes")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")

        ids = [keyframe.id for keyframe in self.keyframes]
        if len(ids) != len(set(ids)):
            raise ValueError("keyframe IDs must be unique")
        if self.keyframes[0].incoming_transition is not None:
            raise ValueError("the first keyframe must not have an incoming_transition")
        for index, keyframe in enumerate(self.keyframes[1:], start=1):
            if keyframe.incoming_transition is None:
                raise ValueError(f"keyframe {index} must have an incoming_transition")

        profile = profile_for_validation(self.robot_variant, info.context)
        for index, keyframe in enumerate(self.keyframes):
            snapshot = keyframe.pose_snapshot
            if snapshot.robot_variant is not self.robot_variant:
                raise ValueError(
                    f"keyframe {index} snapshot variant {snapshot.robot_variant.value} does not "
                    f"match Motion variant {self.robot_variant.value}"
                )
            try:
                snapshot.joint_state.validate_against(profile)
            except ValueError as error:
                raise ValueError(f"keyframe {index} joint state is invalid: {error}") from error
        return self
