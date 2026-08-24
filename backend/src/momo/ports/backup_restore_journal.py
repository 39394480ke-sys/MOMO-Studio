"""Durable intent port for process-crash atomic backup restore."""

from typing import Protocol

from momo.domain.backup import BackupRestoreTransaction


class RestoreJournalRemovalUncertainError(OSError):
    """The journal was unlinked, but its directory commit could not be proven."""

    def __init__(self, message: str, *, journal_unlinked: bool) -> None:
        super().__init__(message)
        self.journal_unlinked = journal_unlinked


class BackupRestoreJournal(Protocol):
    async def load(self) -> BackupRestoreTransaction | None:
        """Load a pending transaction or return ``None`` when the journal is clear."""

    async def begin(self, transaction: BackupRestoreTransaction) -> bool:
        """Publish intent and report cancellation observed after dispatch."""

    async def clear(self) -> None:
        """Durably remove intent only after commit or complete compensation."""
