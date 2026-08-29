"""Narrow structural boundaries used by the Stage 5 playback engine."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable
from uuid import UUID

from momo.domain.enums import DomainUnit, RobotVariant
from momo.domain.playback import (
    PlaybackEvent,
    PlaybackExecutionSnapshot,
    PlaybackOperatorIntent,
    PlaybackStatus,
)
from momo.domain.real_motion import RealExecutionAuthorization
from momo.domain.robot import JointState


class TrajectoryDigestView(Protocol):
    @property
    def sha256(self) -> str: ...


class TrajectorySampleView(Protocol):
    @property
    def time_s(self) -> float: ...

    @property
    def positions(self) -> Mapping[str, float]: ...

    @property
    def units(self) -> Mapping[str, DomainUnit]: ...

    @property
    def keyframe_id(self) -> UUID: ...

    @property
    def segment_index(self) -> int: ...

    @property
    def sample_index(self) -> int: ...


class TrajectoryPlanView(Protocol):
    @property
    def motion_id(self) -> UUID: ...

    @property
    def motion_revision(self) -> int: ...

    @property
    def robot_variant(self) -> RobotVariant: ...

    @property
    def profile_fingerprint(self) -> str: ...

    @property
    def kinematics_fingerprint(self) -> str: ...

    @property
    def start_state_sequence(self) -> int: ...

    @property
    def sample_rate_hz(self) -> float: ...

    @property
    def duration_s(self) -> float: ...

    @property
    def samples(self) -> Sequence[TrajectorySampleView]: ...

    @property
    def digest(self) -> TrajectoryDigestView: ...


class TrajectoryPreflightView(Protocol):
    @property
    def accepted(self) -> bool: ...


class PreparedTrajectoryView(Protocol):
    """Structural view implemented by ``momo.domain.trajectory.PreparedTrajectory``."""

    @property
    def plan(self) -> TrajectoryPlanView: ...

    @property
    def preflight(self) -> TrajectoryPreflightView: ...


@runtime_checkable
class PlaybackExecutionValidator(Protocol):
    """Adapter that must call the reviewed safety gateway before execution."""

    def validate_playback_execution(
        self,
        prepared: PreparedTrajectoryView,
        intent: PlaybackOperatorIntent,
    ) -> AbstractAsyncContextManager[PlaybackExecutionSnapshot]: ...


@runtime_checkable
class PlaybackStateSink(Protocol):
    """High-level domain-unit state sink; never a raw-servo boundary."""

    async def apply_motion_state(self, command_id: UUID, state: JointState) -> int: ...

    async def flush_motion_state(self, command_id: UUID) -> None: ...

    async def mark_motion_fault(self, command_id: UUID, error: str) -> None: ...


@runtime_checkable
class PlaybackObserver(Protocol):
    """Non-blocking latest-value publication port for WebSocket integration."""

    def publish_playback_event(self, event: PlaybackEvent) -> None: ...


@runtime_checkable
class PlaybackController(Protocol):
    """Mode-specific execution engine behind shared trajectory orchestration."""

    @property
    def motion_active(self) -> bool: ...

    def get_status(self) -> PlaybackStatus: ...

    async def begin_preflight(self, motion_id: UUID, motion_revision: int) -> PlaybackStatus: ...

    async def preflight_failed(self, reason: str = "") -> PlaybackStatus: ...

    async def clear_ready(self) -> PlaybackStatus: ...

    async def set_ready(self, prepared: PreparedTrajectoryView) -> PlaybackStatus: ...

    async def play(
        self,
        prepared: PreparedTrajectoryView,
        intent: PlaybackOperatorIntent,
        *,
        rate: float = 1.0,
        loop: bool = False,
        loop_count: int = 2,
        authorization: RealExecutionAuthorization | None = None,
    ) -> PlaybackStatus: ...

    async def pause(self) -> PlaybackStatus: ...

    async def resume(self) -> PlaybackStatus: ...

    async def stop(self) -> PlaybackStatus: ...

    async def set_rate(self, rate: float) -> PlaybackStatus: ...

    async def set_loop(self, enabled: bool, *, loop_count: int = 2) -> PlaybackStatus: ...

    async def shutdown(self) -> None: ...
