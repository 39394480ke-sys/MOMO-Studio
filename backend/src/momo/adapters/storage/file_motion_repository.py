"""Atomic UUID-named Motion repository."""

from pathlib import Path

from momo.adapters.storage.file_entity_repository import AtomicJsonEntityRepository
from momo.domain.motion import Motion
from momo.ports.clock import Clock


class FileMotionRepository(AtomicJsonEntityRepository[Motion]):
    def __init__(self, directory: Path, clock: Clock) -> None:
        super().__init__(directory, Motion, clock)
