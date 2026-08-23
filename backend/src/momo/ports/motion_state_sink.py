"""High-level state sink used only after the unified motion preflight."""

from typing import Protocol, runtime_checkable
from uuid import UUID

from momo.domain.robot import JointState


@runtime_checkable
class MotionStateSink(Protocol):
    async def apply_motion_state(self, command_id: UUID, state: JointState) -> int: ...

    async def flush_motion_state(self, command_id: UUID) -> None: ...

    async def mark_motion_fault(self, command_id: UUID, error: str) -> None: ...
