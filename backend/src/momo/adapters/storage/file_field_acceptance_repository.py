"""Atomic UUID-named storage for ignored, device-local acceptance evidence."""

from pathlib import Path

from momo.adapters.storage.file_entity_repository import AtomicJsonEntityRepository
from momo.domain.real_hardware import FieldAcceptanceEvidence
from momo.ports.clock import Clock


class FileFieldAcceptanceEvidenceRepository:
    """Synchronous facade used during side-effect-free application composition.

    The underlying repository supplies schema validation, UUID-only filenames,
    bounded scans, corrupt-file quarantine, atomic replace, and directory fsync.
    """

    def __init__(self, directory: Path, clock: Clock) -> None:
        self.directory = directory.resolve()
        self._entities = AtomicJsonEntityRepository(
            self.directory,
            FieldAcceptanceEvidence,
            clock,
        )

    def list_evidence(self) -> tuple[FieldAcceptanceEvidence, ...]:
        return self._entities._list_sync()

    def save(self, evidence: FieldAcceptanceEvidence) -> None:
        self._entities._save_sync(evidence, expected_revision=None)


__all__ = ["FileFieldAcceptanceEvidenceRepository"]
