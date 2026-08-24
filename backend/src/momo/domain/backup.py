"""Deterministic, configuration-free backup envelope contracts."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from momo.domain.enums import RobotVariant
from momo.domain.errors import RobotApplicationError

BACKUP_FORMAT: Literal["momo-studio-backup"] = "momo-studio-backup"
BACKUP_FORMAT_VERSION: Literal["1.0.0"] = "1.0.0"
MAX_BACKUP_UPLOAD_BYTES = 32 * 1024 * 1024
MAX_BACKUP_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_BACKUP_DOCUMENTS = 5000
MAX_RESTORE_REVISION_STEPS = 50_000
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class BackupEntityKind(StrEnum):
    POSE = "pose"
    MOTION = "motion"
    DRAFT = "draft"
    CALIBRATION = "calibration"


class BackupCollisionPolicy(StrEnum):
    REJECT = "reject"
    SKIP = "skip"


class BackupImportAction(StrEnum):
    CREATE = "create"
    SKIP = "skip"
    CONFLICT = "conflict"
    INVALID = "invalid"


class BackupRestoreEntityTarget(BaseModel):
    """Exact create target recorded before a multi-repository restore starts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: BackupEntityKind
    id: UUID
    revision: Annotated[int, Field(strict=True, ge=1, le=MAX_RESTORE_REVISION_STEPS)]

    @model_validator(mode="after")
    def reject_calibration_kind(self) -> Self:
        if self.kind is BackupEntityKind.CALIBRATION:
            raise ValueError("calibration uses a variant-bound restore target")
        return self


class BackupRestoreCalibrationTarget(BaseModel):
    """Exact absent calibration identity recorded for crash compensation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    variant: RobotVariant
    id: UUID


class BackupRestoreTransaction(BaseModel):
    """Bounded write-ahead intent for process-crash atomic restore."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    transaction_id: UUID = Field(default_factory=uuid4)
    bundle_sha256: Sha256
    entities: Annotated[list[BackupRestoreEntityTarget], Field(max_length=MAX_BACKUP_DOCUMENTS)]
    calibrations: Annotated[
        list[BackupRestoreCalibrationTarget],
        Field(max_length=2),
    ] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_unique_nonempty_targets(self) -> Self:
        entity_keys = [(item.kind, item.id) for item in self.entities]
        calibration_keys = [(item.variant, item.id) for item in self.calibrations]
        if not entity_keys and not calibration_keys:
            raise ValueError("restore transaction requires at least one target")
        if len(entity_keys) != len(set(entity_keys)):
            raise ValueError("restore transaction repeats an entity target")
        if len(calibration_keys) != len(set(calibration_keys)):
            raise ValueError("restore transaction repeats a calibration target")
        if len({item.variant for item in self.calibrations}) != len(self.calibrations):
            raise ValueError("restore transaction repeats a calibration variant")
        return self


class BackupError(RobotApplicationError):
    code = "BACKUP_ERROR"
    status_code = 422


class BackupFormatError(BackupError):
    code = "BACKUP_FORMAT_INVALID"


class BackupUnsafeContentError(BackupError):
    code = "BACKUP_UNSAFE_CONTENT"


class BackupPreviewRequiredError(BackupError):
    code = "BACKUP_PREVIEW_REQUIRED"
    status_code = 409


class BackupCollisionError(BackupError):
    code = "BACKUP_COLLISION"
    status_code = 409


class BackupRestoreError(BackupError):
    code = "BACKUP_RESTORE_FAILED"
    status_code = 500


class BackupCommitUncertainError(BackupRestoreError):
    """All documents committed; durability of the WAL commit marker is uncertain."""

    code = "BACKUP_COMMIT_DURABILITY_UNCERTAIN"


class BackupRollbackError(BackupRestoreError):
    code = "BACKUP_ROLLBACK_FAILED"


class BackupDocument(BaseModel):
    """One entity payload plus independently verifiable identity and revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: BackupEntityKind
    id: UUID
    schema_version: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    source_revision: Annotated[int, Field(strict=True, ge=1, le=MAX_RESTORE_REVISION_STEPS)] | None
    payload_sha256: Sha256
    payload: dict[str, JsonValue]

    @model_validator(mode="after")
    def verify_descriptor(self) -> Self:
        payload_id = self.payload.get("id")
        payload_version = self.payload.get("schema_version")
        if payload_id != str(self.id):
            raise ValueError("backup payload ID does not match its descriptor")
        if payload_version != self.schema_version:
            raise ValueError("backup payload schema_version does not match its descriptor")
        if self.kind is BackupEntityKind.CALIBRATION:
            if self.source_revision is not None:
                raise ValueError("calibration documents do not have a revision")
        else:
            payload_revision = self.payload.get("revision")
            if self.source_revision is None or payload_revision != self.source_revision:
                raise ValueError("backup payload revision does not match its descriptor")
        encoded = canonical_json_bytes(self.payload)
        if len(encoded) > MAX_BACKUP_DOCUMENT_BYTES:
            raise ValueError("backup document exceeds its encoded size limit")
        if hashlib.sha256(encoded).hexdigest() != self.payload_sha256:
            raise ValueError("backup document digest does not match its payload")
        return self

    def descriptor(self) -> dict[str, JsonValue]:
        return {
            "kind": self.kind.value,
            "id": str(self.id),
            "schema_version": self.schema_version,
            "source_revision": self.source_revision,
            "payload_sha256": self.payload_sha256,
        }

    @classmethod
    def from_payload(
        cls,
        *,
        kind: BackupEntityKind,
        payload: dict[str, JsonValue],
    ) -> BackupDocument:
        entity_id = UUID(str(payload.get("id")))
        schema_version = str(payload.get("schema_version"))
        raw_revision = payload.get("revision")
        if kind is BackupEntityKind.CALIBRATION:
            source_revision = None
        elif not isinstance(raw_revision, int) or isinstance(raw_revision, bool):
            raise ValueError("revisioned backup payload requires an integer revision")
        else:
            source_revision = raw_revision
        return cls(
            kind=kind,
            id=entity_id,
            schema_version=schema_version,
            source_revision=source_revision,
            payload_sha256=sha256_json(payload),
            payload=payload,
        )


class BackupManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Literal["momo-studio-backup"] = BACKUP_FORMAT
    format_version: Literal["1.0.0"] = BACKUP_FORMAT_VERSION
    document_count: Annotated[int, Field(strict=True, ge=0, le=MAX_BACKUP_DOCUMENTS)]
    calibration_included: bool
    documents_sha256: Sha256
    manifest_sha256: Sha256

    @classmethod
    def build(cls, documents: list[BackupDocument]) -> BackupManifest:
        descriptors = [item.descriptor() for item in documents]
        calibration_included = any(item.kind is BackupEntityKind.CALIBRATION for item in documents)
        documents_sha256 = sha256_json(descriptors)
        core: dict[str, JsonValue] = {
            "format": BACKUP_FORMAT,
            "format_version": BACKUP_FORMAT_VERSION,
            "document_count": len(documents),
            "calibration_included": calibration_included,
            "documents_sha256": documents_sha256,
        }
        return cls(
            document_count=len(documents),
            calibration_included=calibration_included,
            documents_sha256=documents_sha256,
            manifest_sha256=sha256_json(core),
        )

    def verify(self, documents: list[BackupDocument]) -> None:
        expected = self.build(documents)
        if self != expected:
            raise ValueError("backup manifest does not match its documents")


class BackupEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: BackupManifest
    documents: Annotated[list[BackupDocument], Field(max_length=MAX_BACKUP_DOCUMENTS)]

    @model_validator(mode="after")
    def verify_manifest_and_order(self) -> Self:
        keys = [(item.kind.value, str(item.id)) for item in self.documents]
        if keys != sorted(keys):
            raise ValueError("backup documents must use deterministic kind/UUID ordering")
        if len(keys) != len(set(keys)):
            raise ValueError("backup documents must not repeat an entity")
        self.manifest.verify(self.documents)
        return self

    @classmethod
    def build(cls, documents: list[BackupDocument]) -> BackupEnvelope:
        ordered = sorted(documents, key=lambda item: (item.kind.value, str(item.id)))
        return cls(manifest=BackupManifest.build(ordered), documents=ordered)

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json"))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()


class BackupImportIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    message: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    kind: BackupEntityKind | None = None
    entity_id: UUID | None = None


class BackupImportItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: BackupEntityKind
    id: UUID
    source_revision: int | None
    action: BackupImportAction
    migrated_from: Annotated[str, StringConstraints(min_length=1, max_length=32)] | None = None
    message: Annotated[str, StringConstraints(max_length=500)] | None = None


class BackupImportTotals(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    documents: Annotated[int, Field(strict=True, ge=0, le=MAX_BACKUP_DOCUMENTS)]
    create: Annotated[int, Field(strict=True, ge=0, le=MAX_BACKUP_DOCUMENTS)]
    skip: Annotated[int, Field(strict=True, ge=0, le=MAX_BACKUP_DOCUMENTS)]
    conflict: Annotated[int, Field(strict=True, ge=0, le=MAX_BACKUP_DOCUMENTS)]
    invalid: Annotated[int, Field(strict=True, ge=0, le=MAX_BACKUP_DOCUMENTS)]


class BackupImportPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_sha256: Sha256
    format_version: Literal["1.0.0"] = BACKUP_FORMAT_VERSION
    valid: bool
    contains_calibration: bool
    collision_policy: BackupCollisionPolicy
    totals: BackupImportTotals
    items: list[BackupImportItem]
    issues: list[BackupImportIssue]


class BackupRestoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_sha256: Sha256
    outcome: Literal["restored"] = "restored"
    restored_counts: dict[BackupEntityKind, int]
    skipped_count: Annotated[int, Field(strict=True, ge=0, le=MAX_BACKUP_DOCUMENTS)]


def safe_error_details(**values: Any) -> dict[str, Any]:
    """Keep backup failures structured without ever attaching raw uploaded data."""

    return values
