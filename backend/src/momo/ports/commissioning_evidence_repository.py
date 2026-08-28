"""Persistence boundary for immutable single-joint commissioning evidence."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from momo.domain.commissioning import CommissioningTestEvidence


@runtime_checkable
class CommissioningTestEvidenceRepository(Protocol):
    async def get(self, evidence_id: UUID) -> CommissioningTestEvidence | None: ...

    async def list_evidence(self) -> tuple[CommissioningTestEvidence, ...]: ...

    async def save(self, evidence: CommissioningTestEvidence) -> None: ...


__all__ = ["CommissioningTestEvidenceRepository"]
