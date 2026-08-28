"""Immutable playback state, operator intent, and publication contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from momo.domain.enums import (
    ControlMode,
    HardwareAccessPolicy,
    MotionCommandSource,
    RobotVariant,
)
from momo.domain.pose import Fingerprint, _require_aware, utc_now

MAX_PLAYBACK_LOOPS = 100
MIN_PLAYBACK_RATE = 0.25
MAX_PLAYBACK_RATE = 2.0


class PlaybackState(StrEnum):
    """Complete lifecycle for the one bounded playback session."""

    IDLE = "IDLE"
    PREFLIGHTING = "PREFLIGHTING"
    READY = "READY"
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"
    FAULTED = "FAULTED"


class PlaybackEventKind(StrEnum):
    STATE = "STATE"
    PROGRESS = "PROGRESS"


class PlaybackOperatorIntent(BaseModel):
    """Explicit user intent bound to one already-preflighted immutable plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent_id: UUID = Field(default_factory=uuid4)
    motion_id: UUID
    motion_revision: Annotated[int, Field(strict=True, ge=1)]
    trajectory_digest: Fingerprint
    confirmed: Literal[True]
    source: Literal[MotionCommandSource.PLAYBACK] = MotionCommandSource.PLAYBACK
    issued_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def require_aware_timestamp(self) -> PlaybackOperatorIntent:
        _require_aware(self.issued_at, "issued_at")
        return self


class PlaybackExecutionSnapshot(BaseModel):
    """Fresh evidence returned by the reviewed playback validation adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operator_intent_id: UUID
    motion_id: UUID
    motion_revision: Annotated[int, Field(strict=True, ge=1)]
    robot_variant: RobotVariant
    state_sequence: Annotated[int, Field(strict=True, ge=0)]
    profile_fingerprint: Fingerprint
    kinematics_fingerprint: Fingerprint
    connected: bool
    stale: bool
    stop_capable: bool
    control_mode: ControlMode
    hardware_access_policy: HardwareAccessPolicy
    safety_gateway_validated: Literal[True]
    hardware_accessed: Literal[False] = False


class PlaybackStatus(BaseModel):
    """Latest bounded session status suitable for HTTP and WebSocket DTOs."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    session_id: UUID | None = None
    state: PlaybackState = PlaybackState.IDLE
    motion_id: UUID | None = None
    motion_revision: Annotated[int, Field(strict=True, ge=1)] | None = None
    trajectory_digest: Fingerprint | None = None
    progress: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    elapsed_s: Annotated[float, Field(ge=0.0)] = 0.0
    duration_s: Annotated[float, Field(ge=0.0)] = 0.0
    current_keyframe_id: UUID | None = None
    current_segment_index: Annotated[int, Field(ge=0)] | None = None
    current_sample_index: Annotated[int, Field(ge=0)] | None = None
    loop: bool = False
    loop_count: Annotated[int, Field(strict=True, ge=1, le=MAX_PLAYBACK_LOOPS)] = 1
    completed_loops: Annotated[int, Field(strict=True, ge=0, le=MAX_PLAYBACK_LOOPS)] = 0
    rate: Annotated[float, Field(ge=MIN_PLAYBACK_RATE, le=MAX_PLAYBACK_RATE)] = 1.0
    error: Annotated[str, Field(max_length=240)] | None = None
    operator_intent_id: UUID | None = None
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    hardware_accessed: Literal[False] = False

    @model_validator(mode="after")
    def timestamps_are_aware(self) -> PlaybackStatus:
        _require_aware(self.updated_at, "updated_at")
        if self.started_at is not None:
            _require_aware(self.started_at, "started_at")
        if self.finished_at is not None:
            _require_aware(self.finished_at, "finished_at")
        return self


class PlaybackEvent(BaseModel):
    """Typed latest-value event; observers must not build an unbounded queue."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: Annotated[int, Field(strict=True, ge=1)]
    kind: PlaybackEventKind
    status: PlaybackStatus
    emitted_at: datetime

    @model_validator(mode="after")
    def emitted_at_is_aware(self) -> PlaybackEvent:
        _require_aware(self.emitted_at, "emitted_at")
        return self
