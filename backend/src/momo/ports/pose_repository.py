"""Persistence boundary for future UUID-named Pose JSON files."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from momo.domain.pose import Pose


@runtime_checkable
class PoseRepository(Protocol):
    async def get(self, pose_id: UUID) -> Pose | None: ...

    async def list(self) -> Sequence[Pose]: ...

    async def save(self, pose: Pose, *, expected_revision: int | None = None) -> None: ...

    async def delete(self, pose_id: UUID, *, expected_revision: int) -> bool: ...
