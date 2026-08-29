"""Validated application inputs for Studio draft authoring workflows."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from momo.application.library_commands import ExpectedRevision, GotoPoseCommand, Tags
from momo.domain.enums import RobotVariant
from momo.domain.motion import MotionKeyframe, PlaybackDefaults
from momo.domain.motion_draft import MotionDraftEditorMetadata
from momo.domain.pose import Name

DraftKeyframes = Annotated[list[MotionKeyframe], Field(max_length=1000)]
SampleRate = Annotated[float, Field(strict=True, ge=5.0, le=50.0, allow_inf_nan=False)]


class MotionDraftCreateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    description: Annotated[str, StringConstraints(max_length=5000)] = ""
    robot_variant: RobotVariant
    keyframes: DraftKeyframes = Field(default_factory=list)
    playback_defaults: PlaybackDefaults = Field(default_factory=PlaybackDefaults)
    tags: Tags = Field(default_factory=list)
    editor_metadata: MotionDraftEditorMetadata = Field(default_factory=MotionDraftEditorMetadata)


class MotionDraftAutosaveCommand(BaseModel):
    """A complete editor snapshot written with compare-and-swap semantics."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: ExpectedRevision
    name: Name
    description: Annotated[str, StringConstraints(max_length=5000)]
    robot_variant: RobotVariant
    keyframes: DraftKeyframes
    playback_defaults: PlaybackDefaults
    tags: Tags
    editor_metadata: MotionDraftEditorMetadata


class MotionDraftRevisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: ExpectedRevision


class MotionDraftCompileCommand(MotionDraftRevisionCommand):
    sample_rate_hz: SampleRate = 25.0


class MotionDraftSaveCommand(MotionDraftCompileCommand):
    expected_source_revision: ExpectedRevision | None = None


class MotionDraftSaveAsCommand(MotionDraftCompileCommand):
    name: Name | None = None


class MotionDraftAbandonSaveIntentCommand(BaseModel):
    """Explicit operator acknowledgement for discarding one recovery marker."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: ExpectedRevision
    operation_id: UUID
    confirm: Literal["ABANDON_FORMAL_SAVE"]


class MotionDraftGotoCommand(GotoPoseCommand):
    """Operator intent to move to one persisted draft keyframe through the safety gateway."""
