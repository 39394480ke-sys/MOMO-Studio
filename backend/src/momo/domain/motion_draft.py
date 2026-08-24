"""Immutable, recoverable Studio drafts kept separate from playable Motion entities."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from itertools import pairwise
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from momo.domain.enums import Easing, MotionMode, RobotVariant
from momo.domain.immutable import freeze_sequence
from momo.domain.motion import (
    LegacyImportMetadata,
    MotionKeyframe,
    MotionTransition,
    PlaybackDefaults,
)
from momo.domain.pose import (
    Description,
    Fingerprint,
    Name,
    PoseSnapshot,
    Tag,
    _require_aware,
    utc_now,
)
from momo.domain.profiles import profile_for_validation

if TYPE_CHECKING:
    from momo.domain.robot import RobotProfile


MOTION_DRAFT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
EDITOR_DEFAULT_TRANSITION = MotionTransition(
    duration_s=1.0,
    motion_mode=MotionMode.JOINT,
    easing=Easing.SMOOTHSTEP,
)


def legacy_snapshot_sha256(snapshot: PoseSnapshot) -> str:
    """Digest every semantic snapshot field with deterministic object-key ordering."""

    canonical = json.dumps(
        snapshot.model_dump(mode="json", round_trip=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class MotionDraftDefaultEdge(BaseModel):
    """Recoverable UI provenance for an adjacency that still uses editor defaults."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    from_keyframe_id: UUID
    to_keyframe_id: UUID


class MotionDraftEditorMetadata(BaseModel):
    """Small, bounded view state that is safe to recover after a crash."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    selected_keyframe_id: UUID | None = None
    playhead_s: Annotated[float, Field(strict=True, ge=0, le=600, allow_inf_nan=False)] = 0.0
    timeline_zoom: Annotated[float, Field(strict=True, ge=0.25, le=8.0, allow_inf_nan=False)] = 1.0
    timeline_scroll_s: Annotated[float, Field(strict=True, ge=0, le=600, allow_inf_nan=False)] = 0.0
    default_edges: Annotated[list[MotionDraftDefaultEdge], Field(max_length=999)] = Field(
        default_factory=list
    )

    @field_validator("default_edges")
    @classmethod
    def freeze_default_edges(
        cls, value: list[MotionDraftDefaultEdge]
    ) -> list[MotionDraftDefaultEdge]:
        return freeze_sequence(value)


class MotionDraftSaveIntent(BaseModel):
    """Write-ahead marker used to reconcile a cross-repository formal save."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: UUID = Field(default_factory=uuid4)
    kind: Literal["SAVE", "SAVE_AS"]
    target_motion_id: UUID
    target_motion_revision: Annotated[int, Field(strict=True, ge=1)]
    expected_motion_revision: Annotated[int, Field(strict=True, ge=1)] | None = None
    target_name: Name
    target_motion_created_at: datetime
    started_at: datetime = Field(default_factory=utc_now)

    @field_validator("target_motion_created_at", "started_at")
    @classmethod
    def intent_timestamps_must_be_aware(cls, value: datetime, info: object) -> datetime:
        return _require_aware(value, getattr(info, "field_name", "transaction timestamp"))


class MotionDraft(BaseModel):
    """Autosaved authoring state; unlike Motion, zero or one keyframe is valid.

    Drafts retain every non-cardinality Motion invariant so a two-or-more-frame
    draft has an unambiguous conversion boundary. They are not accepted by any
    playback port or executor.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1.0.0"] = MOTION_DRAFT_SCHEMA_VERSION
    id: UUID = Field(default_factory=uuid4)
    source_motion_id: UUID | None = None
    source_motion_revision: Annotated[int, Field(strict=True, ge=1)] | None = None
    name: Name
    description: Description = ""
    robot_variant: RobotVariant
    keyframes: Annotated[list[MotionKeyframe], Field(max_length=1000)] = Field(default_factory=list)
    playback_defaults: PlaybackDefaults = Field(default_factory=PlaybackDefaults)
    tags: Annotated[list[Tag], Field(max_length=32)] = Field(default_factory=list)
    source_metadata: LegacyImportMetadata | None = None
    trusted_legacy_snapshot_sha256: Annotated[list[Fingerprint], Field(max_length=1000)] = Field(
        default_factory=list
    )
    editor_metadata: MotionDraftEditorMetadata = Field(default_factory=MotionDraftEditorMetadata)
    save_intent: MotionDraftSaveIntent | None = None
    revision: Annotated[int, Field(strict=True, ge=1)] = 1
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("schema_version")
    @classmethod
    def require_supported_schema_version(cls, value: str) -> str:
        if value != MOTION_DRAFT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported motion draft schema_version: {value}; explicit migration is required"
            )
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_must_be_aware(cls, value: datetime, info: object) -> datetime:
        return _require_aware(value, getattr(info, "field_name", "timestamp"))

    @field_validator("keyframes")
    @classmethod
    def freeze_keyframes(cls, value: list[MotionKeyframe]) -> list[MotionKeyframe]:
        return freeze_sequence(value)

    @field_validator("tags")
    @classmethod
    def normalize_and_freeze_tags(cls, value: list[str]) -> list[str]:
        normalized = [tag.strip() for tag in value]
        if any(not tag for tag in normalized):
            raise ValueError("tags must not be blank")
        keys = [tag.casefold() for tag in normalized]
        if len(keys) != len(set(keys)):
            raise ValueError("tags must be unique after normalization")
        return freeze_sequence(normalized)

    @field_validator("trusted_legacy_snapshot_sha256")
    @classmethod
    def freeze_unique_trusted_legacy_snapshot_sha256(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("trusted_legacy_snapshot_sha256 must be unique")
        return freeze_sequence(value)

    @model_validator(mode="after")
    def validate_draft(self, info: ValidationInfo) -> Self:
        if (self.source_motion_id is None) != (self.source_motion_revision is None):
            raise ValueError("source_motion_id and source_motion_revision must be set together")
        if self.source_metadata is not None and self.source_motion_id is None:
            raise ValueError("source_metadata requires a coherent source Motion identity")
        if self.trusted_legacy_snapshot_sha256 and self.source_metadata is None:
            raise ValueError("trusted Legacy snapshots require typed source_metadata")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")

        ids = [keyframe.id for keyframe in self.keyframes]
        if len(ids) != len(set(ids)):
            raise ValueError("keyframe IDs must be unique")
        if self.keyframes and self.keyframes[0].incoming_transition is not None:
            raise ValueError("the first keyframe must not have an incoming_transition")
        for index, keyframe in enumerate(self.keyframes[1:], start=1):
            if keyframe.incoming_transition is None:
                raise ValueError(f"keyframe {index} must have an incoming_transition")
        selected = self.editor_metadata.selected_keyframe_id
        if selected is not None and selected not in set(ids):
            raise ValueError("selected_keyframe_id must identify a draft keyframe")
        adjacent_pairs = set(pairwise(ids))
        default_pairs = [
            (edge.from_keyframe_id, edge.to_keyframe_id)
            for edge in self.editor_metadata.default_edges
        ]
        if len(default_pairs) != len(set(default_pairs)):
            raise ValueError("default_edges must be unique")
        if any(pair not in adjacent_pairs for pair in default_pairs):
            raise ValueError("default_edges must identify current directed adjacencies")
        frame_by_id = {keyframe.id: keyframe for keyframe in self.keyframes}
        if any(
            frame_by_id[to_id].incoming_transition != EDITOR_DEFAULT_TRANSITION
            for _, to_id in default_pairs
        ):
            raise ValueError("default_edges may mark only the exact editor default transition")

        intent = self.save_intent
        if intent is not None:
            if intent.kind == "SAVE_AS":
                if (
                    intent.expected_motion_revision is not None
                    or intent.target_motion_revision != 1
                ):
                    raise ValueError("a Save As intent must target a new Motion at revision 1")
                if intent.target_motion_id == self.source_motion_id:
                    raise ValueError("a Save As intent must not overwrite the source Motion")
            elif self.source_motion_id is None:
                if (
                    intent.expected_motion_revision is not None
                    or intent.target_motion_revision != 1
                ):
                    raise ValueError("a new Save intent must target a new Motion at revision 1")
            else:
                source_revision = self.source_motion_revision
                if (
                    source_revision is None
                    or intent.target_motion_id != self.source_motion_id
                    or intent.expected_motion_revision != source_revision
                    or intent.target_motion_revision != source_revision + 1
                ):
                    raise ValueError(
                        "a source save intent must target its recorded Motion revision"
                    )

        if not self.keyframes:
            return self
        profile = profile_for_validation(self.robot_variant, info.context)
        profile_fingerprint = self.keyframes[0].pose_snapshot.profile_fingerprint
        kinematics_fingerprint = self.keyframes[0].pose_snapshot.kinematics_fingerprint
        for index, keyframe in enumerate(self.keyframes):
            snapshot = keyframe.pose_snapshot
            if (
                snapshot.state_sequence is None
                and legacy_snapshot_sha256(snapshot) not in self.trusted_legacy_snapshot_sha256
            ):
                raise ValueError(
                    f"keyframe {index} null state_sequence is not a trusted Legacy snapshot"
                )
            if snapshot.robot_variant is not self.robot_variant:
                raise ValueError(
                    f"keyframe {index} snapshot variant {snapshot.robot_variant.value} does not "
                    f"match MotionDraft variant {self.robot_variant.value}"
                )
            if snapshot.profile_fingerprint != profile_fingerprint:
                raise ValueError(f"keyframe {index} profile_fingerprint does not match the draft")
            if snapshot.kinematics_fingerprint != kinematics_fingerprint:
                raise ValueError(
                    f"keyframe {index} kinematics_fingerprint does not match the draft"
                )
            try:
                if profile is not None:
                    snapshot.joint_state.validate_against(profile)
                else:
                    snapshot.joint_state.validate_structure_for_variant(self.robot_variant)
            except ValueError as error:
                raise ValueError(f"keyframe {index} joint state is invalid: {error}") from error
        return self

    def validate_against(self, profile: RobotProfile) -> Self:
        """Apply an explicit runtime profile without any constructor singleton."""

        if profile.variant is not self.robot_variant:
            raise ValueError(
                f"profile {profile.variant.value} does not match MotionDraft variant "
                f"{self.robot_variant.value}"
            )
        for index, keyframe in enumerate(self.keyframes):
            try:
                keyframe.pose_snapshot.validate_against(profile)
            except ValueError as error:
                raise ValueError(f"keyframe {index} joint state is invalid: {error}") from error
        return self


def motion_draft_persisted_json_schema() -> dict[str, Any]:
    """Return the on-disk schema, where every serialized recovery field is explicit."""

    schema = MotionDraft.model_json_schema(mode="serialization")

    def require_serialized_fields(value: object) -> None:
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict):
                value["required"] = list(properties)
            for nested in value.values():
                require_serialized_fields(nested)
        elif isinstance(value, list):
            for nested in value:
                require_serialized_fields(nested)

    require_serialized_fields(schema)
    return schema
