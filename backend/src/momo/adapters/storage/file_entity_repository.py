"""Atomic, schema-validated storage shared by Pose and Motion repositories."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import tempfile
import threading
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar, cast
from uuid import UUID

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ValidationError

from momo.domain.errors import (
    EntityAlreadyExistsError,
    EntityInvalidError,
    RepositoryCapacityError,
    RevisionConflictError,
)
from momo.ports.clock import Clock

EntityT = TypeVar("EntityT", bound=BaseModel)
MAX_ENTITY_BYTES = 4 * 1024 * 1024
MAX_REPOSITORY_ENTITY_FILES = 5000
MAX_REPOSITORY_SCAN_ENTRIES = 10000
MAX_REPOSITORY_AGGREGATE_BYTES = 64 * 1024 * 1024
QUARANTINE_DIGEST_BYTES = 64 * 1024


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


class _PersistedEntity(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def revision(self) -> int: ...

    @property
    def created_at(self) -> datetime: ...


class AtomicJsonEntityRepository(Generic[EntityT]):
    """UUID-only JSON files with CAS updates and corrupt-file isolation.

    File operations run on worker threads, but a repository-local lock makes the
    read/check/replace sequence indivisible for callers sharing this instance.
    Every document is checked against the exact generated JSON Schema and then
    reconstructed by its Pydantic domain model.
    """

    def __init__(
        self,
        directory: Path,
        model: type[EntityT],
        clock: Clock,
        *,
        json_schema: dict[str, Any] | None = None,
    ) -> None:
        self.directory = directory.resolve()
        self.quarantine_directory = self.directory / "quarantine"
        self.model = model
        schema = json_schema or model.model_json_schema(mode="serialization")
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)
        self.clock = clock
        self._lock = threading.RLock()

    async def get(self, entity_id: UUID) -> EntityT | None:
        return await asyncio.to_thread(self._get_sync, entity_id)

    async def list(self) -> Sequence[EntityT]:
        return await asyncio.to_thread(self._list_sync)

    async def save(self, entity: EntityT, *, expected_revision: int | None = None) -> None:
        await asyncio.to_thread(self._save_sync, entity, expected_revision)

    async def delete(self, entity_id: UUID, *, expected_revision: int) -> bool:
        return await asyncio.to_thread(self._delete_sync, entity_id, expected_revision)

    def _ensure_directory(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)

    def _entity_path(self, entity_id: UUID) -> Path:
        if not isinstance(entity_id, UUID):
            raise EntityInvalidError("Entity IDs must be UUIDs")
        candidate = self.directory / f"{entity_id}.json"
        if candidate.parent.resolve() != self.directory:
            raise EntityInvalidError("Entity ID is outside the repository")
        return candidate

    def _get_sync(self, entity_id: UUID) -> EntityT | None:
        with self._lock:
            path = self._entity_path(entity_id)
            if not os.path.lexists(path):
                return None
            return self._read_or_quarantine(path, expected_id=entity_id)

    def _list_sync(self) -> tuple[EntityT, ...]:
        with self._lock:
            if not self.directory.is_dir():
                return ()
            paths = self._repository_paths()
            self._require_aggregate_capacity(paths)
            entities: list[EntityT] = []
            for path in paths:
                try:
                    expected_id = UUID(path.stem)
                except ValueError:
                    self._quarantine(path)
                    continue
                entity = self._read_or_quarantine(path, expected_id=expected_id)
                if entity is not None:
                    entities.append(entity)
            return tuple(
                sorted(
                    entities,
                    key=lambda item: (
                        cast(_PersistedEntity, item).created_at,
                        str(cast(_PersistedEntity, item).id),
                    ),
                    reverse=True,
                )
            )

    def _repository_paths(self) -> tuple[Path, ...]:
        """Enumerate a repository under explicit scan and entity-count budgets."""

        if not self.directory.is_dir():
            return ()
        scanned = 0
        candidates: list[Path] = []
        with os.scandir(self.directory) as entries:
            for entry in entries:
                scanned += 1
                if scanned > MAX_REPOSITORY_SCAN_ENTRIES:
                    self._raise_capacity("directory_entries", MAX_REPOSITORY_SCAN_ENTRIES)
                if not entry.name.endswith(".json"):
                    continue
                candidates.append(Path(entry.path))
                if len(candidates) > MAX_REPOSITORY_ENTITY_FILES:
                    self._raise_capacity("entity_files", MAX_REPOSITORY_ENTITY_FILES)
        return tuple(sorted(candidates, key=lambda item: item.name))

    @staticmethod
    def _regular_file_size(path: Path) -> int:
        try:
            metadata = path.lstat()
        except OSError:
            return 0
        return metadata.st_size if stat.S_ISREG(metadata.st_mode) else 0

    def _require_aggregate_capacity(self, paths: Sequence[Path]) -> int:
        aggregate = 0
        for path in paths:
            aggregate += self._regular_file_size(path)
            if aggregate > MAX_REPOSITORY_AGGREGATE_BYTES:
                self._raise_capacity("aggregate_bytes", MAX_REPOSITORY_AGGREGATE_BYTES)
        return aggregate

    @staticmethod
    def _raise_capacity(resource: str, limit: int) -> None:
        raise RepositoryCapacityError(
            "Repository capacity limit exceeded",
            details={"resource": resource, "limit": limit},
        )

    def _read_or_quarantine(self, path: Path, *, expected_id: UUID) -> EntityT | None:
        try:
            raw_text = self._read_regular_file(path).decode("utf-8")
            raw = json.loads(
                raw_text,
                parse_constant=_reject_json_constant,
            )
            self._validate_schema(raw)
            entity = self.model.model_validate(raw)
            if getattr(entity, "id", None) != expected_id:
                raise ValueError("entity UUID does not match filename")
            return entity
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError, ValidationError):
            self._quarantine(path)
            return None

    @staticmethod
    def _read_regular_file(path: Path) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("only regular files are repository entities")
            if metadata.st_size > MAX_ENTITY_BYTES:
                raise ValueError("entity exceeds maximum size")
            chunks: list[bytes] = []
            remaining = MAX_ENTITY_BYTES + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            if len(payload) > MAX_ENTITY_BYTES:
                raise ValueError("entity exceeds maximum size")
            return payload
        finally:
            os.close(descriptor)

    def _validate_schema(self, value: object) -> None:
        try:
            self._validator.validate(value)
        except JsonSchemaValidationError as error:
            raise ValueError("entity does not satisfy its JSON Schema") from error

    def _save_sync(self, entity: EntityT, expected_revision: int | None) -> None:
        with self._lock:
            entity_id = getattr(entity, "id", None)
            revision = getattr(entity, "revision", None)
            if not isinstance(entity_id, UUID) or not isinstance(revision, int):
                raise EntityInvalidError("Persisted entity identity or revision is invalid")
            path = self._entity_path(entity_id)
            self._ensure_directory()

            existing: EntityT | None = None
            if os.path.lexists(path) and not stat.S_ISREG(path.lstat().st_mode):
                self._quarantine(path)
                raise EntityInvalidError("Only regular files are repository entities")
            if path.exists():
                existing = self._read_or_quarantine(path, expected_id=entity_id)
                if existing is None:
                    raise EntityInvalidError("Stored entity is corrupt and was quarantined")

            if expected_revision is None:
                if existing is not None:
                    raise EntityAlreadyExistsError("Entity UUID already exists")
                if revision != 1:
                    raise EntityInvalidError("New entities must begin at revision 1")
            else:
                if expected_revision < 1:
                    raise EntityInvalidError("expected_revision must be at least 1")
                if existing is None:
                    raise RevisionConflictError(
                        "Entity no longer exists",
                        details={"expected_revision": expected_revision, "actual_revision": None},
                    )
                actual_revision = cast(_PersistedEntity, existing).revision
                if actual_revision != expected_revision:
                    raise RevisionConflictError(
                        "Entity revision changed",
                        details={
                            "expected_revision": expected_revision,
                            "actual_revision": actual_revision,
                        },
                    )
                if revision != expected_revision + 1:
                    raise EntityInvalidError("Updated entity revision must increment exactly once")

            serialized = entity.model_dump(mode="json")
            self._validate_schema(serialized)
            payload = (
                json.dumps(
                    serialized,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
            if len(payload) > MAX_ENTITY_BYTES:
                raise EntityInvalidError("Entity exceeds the maximum persisted size")
            paths = self._repository_paths()
            if path not in paths and len(paths) >= MAX_REPOSITORY_ENTITY_FILES:
                self._raise_capacity("entity_files", MAX_REPOSITORY_ENTITY_FILES)
            aggregate = self._require_aggregate_capacity(paths)
            previous_size = self._regular_file_size(path) if path in paths else 0
            if aggregate - previous_size + len(payload) > MAX_REPOSITORY_AGGREGATE_BYTES:
                self._raise_capacity("aggregate_bytes", MAX_REPOSITORY_AGGREGATE_BYTES)
            self._atomic_replace(path, payload)

    def _delete_sync(self, entity_id: UUID, expected_revision: int) -> bool:
        with self._lock:
            path = self._entity_path(entity_id)
            if not os.path.lexists(path):
                return False
            existing = self._read_or_quarantine(path, expected_id=entity_id)
            if existing is None:
                return False
            actual_revision = cast(_PersistedEntity, existing).revision
            if actual_revision != expected_revision:
                raise RevisionConflictError(
                    "Entity revision changed",
                    details={
                        "expected_revision": expected_revision,
                        "actual_revision": actual_revision,
                    },
                )
            path.unlink()
            self._fsync_directory(self.directory)
            return True

    def _atomic_replace(self, destination: Path, payload: bytes) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.stem}.",
            suffix=".tmp",
            dir=self.directory,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            self._fsync_directory(self.directory)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _quarantine(self, path: Path) -> None:
        try:
            mode = path.lstat().st_mode
            if path.parent.resolve() != self.directory:
                return
            self.quarantine_directory.mkdir(parents=True, exist_ok=True)
            digest = "nonregular" if not stat.S_ISREG(mode) else self._bounded_digest(path)
            timestamp = self.clock.now().strftime("%Y%m%dT%H%M%S%fZ")
            destination = self.quarantine_directory / (
                f"{path.stem}.{timestamp}.{digest}.corrupt.json"
            )
            counter = 1
            while destination.exists():
                destination = self.quarantine_directory / (
                    f"{path.stem}.{timestamp}.{digest}.{counter}.corrupt.json"
                )
                counter += 1
            os.replace(path, destination)
            self._fsync_directory(self.quarantine_directory)
            self._fsync_directory(self.directory)
        except OSError:
            # Listing remains available even if a read-only volume prevents
            # quarantine. The invalid document is still omitted.
            return

    @staticmethod
    def _bounded_digest(path: Path) -> str:
        digest = hashlib.sha256()
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                return "nonregular"
            digest.update(str(metadata.st_size).encode("ascii"))
            digest.update(os.read(descriptor, QUARANTINE_DIGEST_BYTES))
            return digest.hexdigest()[:12]
        finally:
            os.close(descriptor)
