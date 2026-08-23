"""Persistence boundary for future UUID-named Motion JSON files."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from momo.domain.motion import Motion


@runtime_checkable
class MotionRepository(Protocol):
    async def get(self, motion_id: UUID) -> Motion | None: ...

    async def list(self) -> Sequence[Motion]: ...

    async def save(self, motion: Motion) -> None: ...

    async def delete(self, motion_id: UUID) -> bool: ...
