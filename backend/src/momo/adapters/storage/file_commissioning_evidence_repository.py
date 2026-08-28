"""Atomic UUID storage for device-local commissioning test evidence."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from momo.adapters.storage.file_entity_repository import AtomicJsonEntityRepository
from momo.domain.commissioning import CommissioningTestEvidence
from momo.ports.clock import Clock


class FileCommissioningTestEvidenceRepository:
    """Async facade over the shared atomic, schema-validating entity store."""

    def __init__(self, directory: Path, clock: Clock) -> None:
        self.directory = directory.resolve()
        self._entities = AtomicJsonEntityRepository(
            self.directory,
            CommissioningTestEvidence,
            clock,
        )

    async def get(self, evidence_id: UUID) -> CommissioningTestEvidence | None:
        return await self._entities.get(evidence_id)

    async def list_evidence(self) -> tuple[CommissioningTestEvidence, ...]:
        return tuple(await self._entities.list())

    def list_evidence_sync(self) -> tuple[CommissioningTestEvidence, ...]:
        """Side-effect-free bootstrap read using the repository's bounded scanner."""

        return self._entities._list_sync()

    async def save(self, evidence: CommissioningTestEvidence) -> None:
        await self._entities.save(evidence, expected_revision=None)


__all__ = ["FileCommissioningTestEvidenceRepository"]
