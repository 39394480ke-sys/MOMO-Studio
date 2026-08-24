"""Persistence boundary for recoverable Studio MotionDraft entities."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from momo.domain.motion_draft import MotionDraft


@runtime_checkable
class MotionDraftRepository(Protocol):
    async def get(self, draft_id: UUID) -> MotionDraft | None: ...

    async def list(self) -> Sequence[MotionDraft]: ...

    async def save(self, draft: MotionDraft, *, expected_revision: int | None = None) -> None: ...

    async def delete(self, draft_id: UUID, *, expected_revision: int) -> bool: ...
