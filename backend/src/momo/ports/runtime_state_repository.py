"""Persistence boundary for safe Dry Run runtime snapshots."""

from typing import Protocol, runtime_checkable

from momo.domain.runtime import RuntimeState


@runtime_checkable
class RuntimeStateRepository(Protocol):
    def load(self, robot_id: str) -> RuntimeState | None: ...

    def save(self, state: RuntimeState) -> None: ...

    def reject_loaded_state(self, robot_id: str, reason: str) -> None: ...

    @property
    def path_description(self) -> str: ...

    @property
    def last_load_valid(self) -> bool: ...

    @property
    def last_diagnostic(self) -> str: ...

    @property
    def last_quarantined_file(self) -> str | None: ...
