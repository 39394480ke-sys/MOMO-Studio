"""Atomic, revisioned calibration storage with durable backups and rollback."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from momo.adapters.storage.durable_directory import ensure_directory_durable
from momo.domain.backup import BackupRestoreCalibrationTarget
from momo.domain.calibration import CalibrationDocument
from momo.domain.calibration_workflow import (
    CalibrationRevisionRecord,
    CalibrationWorkflowError,
    CalibrationWorkflowSource,
    calibration_document_fingerprint,
)
from momo.domain.enums import RobotVariant

MAX_CALIBRATION_REVISION_BYTES = 1024 * 1024


class CalibrationReplaceCommittedError(OSError):
    """Calibration bytes were replaced but directory durability is uncertain."""


class FileCalibrationWorkflowRepository:
    """Store one current revision per variant; every replacement backs up the old bytes."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self.backup_directory = self.directory / ".backups"
        self._lock = threading.RLock()
        self._directory_durable = False
        self._durable_backup_directories: set[Path] = set()

    def get_for_variant(self, variant: RobotVariant) -> CalibrationDocument | None:
        record = self.get_revision(variant)
        return record.calibration if record is not None else None

    def get_revision(self, variant: RobotVariant) -> CalibrationRevisionRecord | None:
        with self._lock:
            path = self._current_path(variant)
            if not path.exists():
                return None
            return self._read_record(path)

    def save_new(
        self,
        calibration: CalibrationDocument,
        *,
        expected_revision: int | None,
        source: CalibrationWorkflowSource,
        created_at: datetime,
    ) -> CalibrationRevisionRecord:
        """Atomically install a new forward revision after backing up current bytes."""

        if calibration.template:
            raise CalibrationWorkflowError(
                "TEMPLATE_CALIBRATION_FORBIDDEN",
                "Template/example calibration cannot be saved as a Real calibration revision",
            )
        with self._lock:
            self._ensure_directory()
            path = self._current_path(calibration.robot_variant)
            current: CalibrationRevisionRecord | None = None
            current_payload: bytes | None = None
            if path.exists():
                current_payload = self._read_regular_bytes(path)
                current = self._parse_record(current_payload, path)
            actual_revision = current.revision if current is not None else None
            if actual_revision != expected_revision:
                raise CalibrationWorkflowError(
                    "CALIBRATION_REVISION_CONFLICT",
                    "Calibration revision changed",
                    details={
                        "expected_revision": expected_revision,
                        "actual_revision": actual_revision,
                    },
                )
            fingerprint = calibration_document_fingerprint(calibration)
            if current is not None and fingerprint == current.calibration_fingerprint:
                raise CalibrationWorkflowError(
                    "CALIBRATION_UNCHANGED",
                    "A new calibration revision must have a new fingerprint",
                )
            record = CalibrationRevisionRecord(
                revision=1 if current is None else current.revision + 1,
                calibration_fingerprint=fingerprint,
                previous_calibration_fingerprint=(
                    current.calibration_fingerprint if current is not None else None
                ),
                source=source,
                calibration=calibration,
                created_at=created_at,
            )
            if current is not None and current_payload is not None:
                self._write_backup(current, current_payload)
            self._atomic_replace(path, self._serialize(record))
            return record

    def import_new_bundle(
        self,
        calibrations: Sequence[CalibrationDocument],
        *,
        created_at: datetime,
    ) -> tuple[CalibrationRevisionRecord, ...]:
        """Install an absent, validated V1/V2 calibration set as one bounded batch.

        Collision preview never permits replacement. All payloads and destination
        absence are checked before the first replace; any write failure removes only
        files created by this batch while the repository lock excludes workflow saves.
        """

        values = tuple(calibrations)
        if not values or len(values) > len(RobotVariant):
            raise CalibrationWorkflowError(
                "CALIBRATION_IMPORT_BATCH_INVALID",
                "Calibration import must contain one or two explicit variants",
            )
        variants = tuple(item.robot_variant for item in values)
        identities = tuple(item.id for item in values)
        if len(variants) != len(set(variants)) or len(identities) != len(set(identities)):
            raise CalibrationWorkflowError(
                "CALIBRATION_IMPORT_BATCH_INVALID",
                "Calibration import variants and identities must be unique",
            )
        records: list[CalibrationRevisionRecord] = []
        for calibration in values:
            if calibration.template or not all(joint.complete for joint in calibration.joints):
                raise CalibrationWorkflowError(
                    "CALIBRATION_IMPORT_INVALID",
                    "Imported calibration must be complete and non-template",
                )
            fingerprint = calibration_document_fingerprint(calibration)
            records.append(
                CalibrationRevisionRecord(
                    revision=1,
                    calibration_fingerprint=fingerprint,
                    previous_calibration_fingerprint=None,
                    source=CalibrationWorkflowSource.EXISTING_REAL,
                    calibration=calibration,
                    created_at=created_at,
                )
            )

        with self._lock:
            self._ensure_directory()
            destinations = tuple(
                self._current_path(record.calibration.robot_variant) for record in records
            )
            if any(os.path.lexists(path) for path in destinations):
                raise CalibrationWorkflowError(
                    "CALIBRATION_REVISION_CONFLICT",
                    "A calibration destination changed after import preview",
                )
            payloads = tuple(self._serialize(record) for record in records)
            created: list[Path] = []
            try:
                for destination, payload in zip(destinations, payloads, strict=True):
                    try:
                        self._atomic_replace(destination, payload)
                    except CalibrationReplaceCommittedError:
                        # The destination is visible in this process even though
                        # directory durability is uncertain. Include it in the exact
                        # batch compensation set before propagating the failure.
                        created.append(destination)
                        raise
                    else:
                        created.append(destination)
            except BaseException as error:
                cleanup_failed = False
                for destination in reversed(created):
                    try:
                        destination.unlink(missing_ok=True)
                    except OSError:
                        cleanup_failed = True
                try:
                    self._fsync_directory(self.directory)
                except OSError:
                    cleanup_failed = True
                if cleanup_failed:
                    raise CalibrationWorkflowError(
                        "CALIBRATION_IMPORT_ROLLBACK_FAILED",
                        "Calibration import failed and cleanup was incomplete",
                    ) from error
                raise
        return tuple(records)

    def remove_imported_bundle_exact(
        self,
        targets: Sequence[BackupRestoreCalibrationTarget],
    ) -> None:
        """Compensate only revision-one calibration identities named by restore WAL."""

        values = tuple(targets)
        if len(values) > len(RobotVariant):
            raise CalibrationWorkflowError(
                "CALIBRATION_IMPORT_ROLLBACK_INVALID",
                "Calibration restore rollback exceeds the variant bound",
            )
        if len({item.variant for item in values}) != len(values):
            raise CalibrationWorkflowError(
                "CALIBRATION_IMPORT_ROLLBACK_INVALID",
                "Calibration restore rollback repeats a variant",
            )
        with self._lock:
            removable: list[Path] = []
            for target in values:
                path = self._current_path(target.variant)
                if not os.path.lexists(path):
                    continue
                record = self._read_record(path)
                if (
                    record.revision != 1
                    or record.source is not CalibrationWorkflowSource.EXISTING_REAL
                    or record.calibration.id != target.id
                    or record.calibration.robot_variant is not target.variant
                ):
                    raise CalibrationWorkflowError(
                        "CALIBRATION_IMPORT_ROLLBACK_CONFLICT",
                        "Calibration changed after restore intent and was not removed",
                    )
                removable.append(path)
            for path in removable:
                path.unlink()
            if self.directory.exists():
                self._fsync_directory(self.directory)

    def rollback(
        self,
        variant: RobotVariant,
        *,
        target_revision: int,
        expected_revision: int,
        created_at: datetime,
    ) -> CalibrationRevisionRecord:
        """Restore old content as a new monotonic revision; never rewind history."""

        with self._lock:
            current = self.get_revision(variant)
            if current is None:
                raise CalibrationWorkflowError(
                    "CALIBRATION_NOT_CONFIGURED",
                    "Cannot roll back an unconfigured calibration",
                )
            if current.revision != expected_revision:
                raise CalibrationWorkflowError(
                    "CALIBRATION_REVISION_CONFLICT",
                    "Calibration revision changed before rollback",
                    details={
                        "expected_revision": expected_revision,
                        "actual_revision": current.revision,
                    },
                )
            if target_revision >= current.revision or target_revision < 1:
                raise CalibrationWorkflowError(
                    "INVALID_ROLLBACK_TARGET",
                    "Rollback target must be an earlier positive revision",
                )
            target = self._find_backup(variant, target_revision)
            restored = target.calibration.model_copy(
                update={
                    "id": uuid4(),
                    "generated_at": created_at,
                    "notes": f"Rollback from revision {current.revision} to {target_revision}",
                }
            )
            return self.save_new(
                restored,
                expected_revision=current.revision,
                source=CalibrationWorkflowSource.EXISTING_REAL,
                created_at=created_at,
            )

    def _find_backup(
        self,
        variant: RobotVariant,
        revision: int,
    ) -> CalibrationRevisionRecord:
        directory = self._variant_backup_directory(variant)
        matches = tuple(directory.glob(f"{revision:08d}-*.json")) if directory.is_dir() else ()
        if len(matches) != 1:
            raise CalibrationWorkflowError(
                "CALIBRATION_BACKUP_NOT_FOUND",
                f"Calibration backup revision {revision} was not found uniquely",
            )
        record = self._read_record(matches[0])
        if record.revision != revision or record.calibration.robot_variant is not variant:
            raise CalibrationWorkflowError(
                "CALIBRATION_BACKUP_INVALID",
                "Calibration backup identity does not match its requested revision",
            )
        return record

    def _write_backup(self, record: CalibrationRevisionRecord, payload: bytes) -> None:
        directory = self._variant_backup_directory(record.calibration.robot_variant)
        self._ensure_backup_directory(directory)
        destination = directory / (f"{record.revision:08d}-{record.calibration_fingerprint}.json")
        if destination.exists():
            if self._read_regular_bytes(destination) != payload:
                raise CalibrationWorkflowError(
                    "CALIBRATION_BACKUP_CONFLICT",
                    "Existing calibration backup does not match current revision bytes",
                )
            return
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            self._fsync_directory(directory)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise

    def _read_record(self, path: Path) -> CalibrationRevisionRecord:
        return self._parse_record(self._read_regular_bytes(path), path)

    def _parse_record(self, payload: bytes, path: Path) -> CalibrationRevisionRecord:
        try:
            return CalibrationRevisionRecord.model_validate_json(payload)
        except (ValueError, ValidationError) as error:
            raise CalibrationWorkflowError(
                "CALIBRATION_REVISION_INVALID",
                f"Calibration revision {path.name!r} is invalid",
            ) from error

    @staticmethod
    def _serialize(record: CalibrationRevisionRecord) -> bytes:
        payload = (
            json.dumps(
                record.model_dump(mode="json"),
                sort_keys=True,
                ensure_ascii=True,
                allow_nan=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        if len(payload) > MAX_CALIBRATION_REVISION_BYTES:
            raise CalibrationWorkflowError(
                "CALIBRATION_REVISION_TOO_LARGE",
                "Calibration revision exceeds the one-MiB storage limit",
            )
        return payload

    @staticmethod
    def _read_regular_bytes(path: Path) -> bytes:
        if path.is_symlink() or not path.is_file():
            raise CalibrationWorkflowError(
                "CALIBRATION_PATH_INVALID",
                "Calibration path must be a regular non-symlink file",
            )
        try:
            size = path.stat().st_size
            if size > MAX_CALIBRATION_REVISION_BYTES:
                raise CalibrationWorkflowError(
                    "CALIBRATION_REVISION_TOO_LARGE",
                    "Calibration revision exceeds the one-MiB storage limit",
                )
            return path.read_bytes()
        except OSError as error:
            raise CalibrationWorkflowError(
                "CALIBRATION_STORAGE_ERROR",
                "Calibration revision could not be read",
            ) from error

    def _atomic_replace(self, destination: Path, payload: bytes) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.stem}.",
            suffix=".tmp",
            dir=self.directory,
        )
        temporary = Path(temporary_name)
        replaced = False
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            replaced = True
            self._fsync_directory(self.directory)
        except BaseException as error:
            temporary.unlink(missing_ok=True)
            if replaced:
                raise CalibrationReplaceCommittedError(
                    "Calibration bytes were replaced but directory durability is uncertain"
                ) from error
            raise

    def _ensure_directory(self) -> None:
        if self._directory_durable and self.directory.is_dir():
            return
        ensure_directory_durable(
            self.directory,
            fsync_directory=self._fsync_directory,
            mode=0o700,
        )
        self._directory_durable = True

    def _ensure_backup_directory(self, directory: Path) -> None:
        if directory in self._durable_backup_directories and directory.is_dir():
            return
        ensure_directory_durable(
            directory,
            fsync_directory=self._fsync_directory,
            mode=0o700,
        )
        self._durable_backup_directories.add(directory)

    def _current_path(self, variant: RobotVariant) -> Path:
        return self.directory / f"{variant.value.lower()}.current.json"

    def _variant_backup_directory(self, variant: RobotVariant) -> Path:
        return self.backup_directory / variant.value.lower()

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


__all__ = ["FileCalibrationWorkflowRepository"]
