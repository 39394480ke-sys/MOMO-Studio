"""Persistence boundary for immutable local Kinematics verification evidence."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from momo.domain.commissioning import KinematicsVerificationEvidence


@runtime_checkable
class KinematicsVerificationEvidenceRepository(Protocol):
    async def get(self, evidence_id: UUID) -> KinematicsVerificationEvidence | None: ...

    async def list_evidence(self) -> tuple[KinematicsVerificationEvidence, ...]: ...

    async def save(self, evidence: KinematicsVerificationEvidence) -> None: ...


__all__ = ["KinematicsVerificationEvidenceRepository"]
