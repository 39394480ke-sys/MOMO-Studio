"""Atomic UUID-named MotionDraft repository for crash recovery."""

from pathlib import Path

from momo.adapters.storage.file_entity_repository import AtomicJsonEntityRepository
from momo.domain.motion_draft import MotionDraft, motion_draft_persisted_json_schema
from momo.ports.clock import Clock


class FileMotionDraftRepository(AtomicJsonEntityRepository[MotionDraft]):
    def __init__(self, directory: Path, clock: Clock) -> None:
        super().__init__(
            directory,
            MotionDraft,
            clock,
            json_schema=motion_draft_persisted_json_schema(),
        )
