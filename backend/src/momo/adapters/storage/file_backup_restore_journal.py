"""Bounded write-ahead journal for process-crash atomic backup restore."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import tempfile
import threading
from pathlib import Path

from pydantic import ValidationError

from momo.adapters.storage.durable_directory import ensure_directory_durable
from momo.domain.backup import (
    BackupRestoreTransaction,
    BackupRollbackError,
)
from momo.ports.backup_restore_journal import RestoreJournalRemovalUncertainError

MAX_RESTORE_JOURNAL_BYTES = 2 * 1024 * 1024
_JOURNAL_NAME = "restore-transaction.json"


class FileBackupRestoreJournal:
    """Persist one bounded restore intent; all async calls reach a terminal fs state."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self.path = self.directory / _JOURNAL_NAME
        self._lock = threading.RLock()
        self._directory_durable = False

    async def load(self) -> BackupRestoreTransaction | None:
        worker = asyncio.create_task(
            asyncio.to_thread(self._load_sync),
            name="backup-restore-journal-load",
        )
        while True:
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue

    async def begin(self, transaction: BackupRestoreTransaction) -> bool:
        worker = asyncio.create_task(
            asyncio.to_thread(self._begin_sync, transaction),
            name="backup-restore-journal-begin",
        )
        cancellation_requested = False
        while True:
            try:
                await asyncio.shield(worker)
                return cancellation_requested
            except asyncio.CancelledError:
                cancellation_requested = True

    async def clear(self) -> None:
        worker = asyncio.create_task(
            asyncio.to_thread(self._clear_sync),
            name="backup-restore-journal-clear",
        )
        while True:
            try:
                await asyncio.shield(worker)
                return
            except asyncio.CancelledError:
                continue

    def _load_sync(self) -> BackupRestoreTransaction | None:
        with self._lock:
            if not os.path.lexists(self.path):
                return None
            try:
                payload = self._read_regular_file(self.path)
                return BackupRestoreTransaction.model_validate_json(payload)
            except (OSError, ValueError, ValidationError) as error:
                raise BackupRollbackError(
                    "Pending restore journal is invalid; startup recovery is blocked"
                ) from error

    def _begin_sync(self, transaction: BackupRestoreTransaction) -> None:
        payload = (
            json.dumps(
                transaction.model_dump(mode="json"),
                sort_keys=True,
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        if len(payload) > MAX_RESTORE_JOURNAL_BYTES:
            raise BackupRollbackError("Restore journal exceeds its bounded size")
        with self._lock:
            self._ensure_directory()
            if os.path.lexists(self.path):
                raise BackupRollbackError(
                    "A pending restore journal must be recovered before another restore"
                )
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".restore-transaction.",
                suffix=".tmp",
                dir=self.directory,
            )
            temporary = Path(temporary_name)
            replaced = False
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                replaced = True
                self._fsync_directory(self.directory)
            except BaseException as error:
                temporary.unlink(missing_ok=True)
                message = (
                    "Restore intent was published but journal durability is uncertain"
                    if replaced
                    else "Restore intent could not be published"
                )
                raise BackupRollbackError(message) from error

    def _clear_sync(self) -> None:
        with self._lock:
            if not self.directory.exists():
                return
            self._ensure_directory()
            unlinked = False
            if os.path.lexists(self.path):
                metadata = self.path.lstat()
                if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                    raise BackupRollbackError("Restore journal path is not a regular file")
                self.path.unlink()
                unlinked = True
            try:
                self._fsync_directory(self.directory)
            except OSError as error:
                if unlinked:
                    raise RestoreJournalRemovalUncertainError(
                        "Restore journal was unlinked, but removal durability is uncertain",
                        journal_unlinked=True,
                    ) from error
                raise BackupRollbackError(
                    "Restore journal removal could not be made durable"
                ) from error

    @staticmethod
    def _read_regular_file(path: Path) -> bytes:
        path_metadata = path.lstat()
        if not stat.S_ISREG(path_metadata.st_mode) or stat.S_ISLNK(path_metadata.st_mode):
            raise ValueError("restore journal is not a regular file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_RESTORE_JOURNAL_BYTES:
                raise ValueError("restore journal is not a bounded regular file")
            chunks: list[bytes] = []
            remaining = MAX_RESTORE_JOURNAL_BYTES + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            if len(payload) > MAX_RESTORE_JOURNAL_BYTES:
                raise ValueError("restore journal exceeds its bounded size")
            return payload
        finally:
            os.close(descriptor)

    def _ensure_directory(self) -> None:
        if self._directory_durable and self.directory.is_dir():
            return
        ensure_directory_durable(
            self.directory,
            fsync_directory=self._fsync_directory,
            mode=0o700,
        )
        self._directory_durable = True

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


__all__ = ["FileBackupRestoreJournal"]
