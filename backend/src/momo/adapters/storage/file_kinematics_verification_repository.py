"""Atomic UUID storage for local Kinematics verification evidence."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from momo.adapters.storage.file_entity_repository import AtomicJsonEntityRepository
from momo.domain.commissioning import KinematicsVerificationEvidence
from momo.ports.clock import Clock


class FileKinematicsVerificationEvidenceRepository:
    def __init__(self, directory: Path, clock: Clock) -> None:
        self.directory = directory.resolve()
        self._entities = AtomicJsonEntityRepository(
            self.directory,
            KinematicsVerificationEvidence,
            clock,
        )

    async def get(self, evidence_id: UUID) -> KinematicsVerificationEvidence | None:
        return await self._entities.get(evidence_id)

    async def list_evidence(self) -> tuple[KinematicsVerificationEvidence, ...]:
        return tuple(await self._entities.list())

    def list_evidence_sync(self) -> tuple[KinematicsVerificationEvidence, ...]:
        """Composition-time read; constructing the repository performs no I/O."""

        return self._entities._list_sync()

    async def save(self, evidence: KinematicsVerificationEvidence) -> None:
        await self._entities.save(evidence, expected_revision=None)


__all__ = ["FileKinematicsVerificationEvidenceRepository"]
