"""Local persistence boundary for immutable field-acceptance evidence."""

from typing import Protocol, runtime_checkable

from momo.domain.commissioning import FieldAcceptanceEvidence


@runtime_checkable
class FieldAcceptanceEvidenceRepository(Protocol):
    def list_evidence(self) -> tuple[FieldAcceptanceEvidence, ...]: ...

    def save(self, evidence: FieldAcceptanceEvidence) -> None: ...
