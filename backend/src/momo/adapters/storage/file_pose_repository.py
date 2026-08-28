"""Atomic UUID-named Pose repository."""

from pathlib import Path

from momo.adapters.storage.file_entity_repository import (
    AtomicJsonEntityRepository,
    RepositoryMaintenanceGate,
)
from momo.domain.pose import Pose
from momo.ports.clock import Clock


class FilePoseRepository(AtomicJsonEntityRepository[Pose]):
    def __init__(
        self,
        directory: Path,
        clock: Clock,
        *,
        maintenance_gate: RepositoryMaintenanceGate | None = None,
    ) -> None:
        super().__init__(directory, Pose, clock, maintenance_gate=maintenance_gate)
