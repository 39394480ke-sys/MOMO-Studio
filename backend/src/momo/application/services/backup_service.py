"""Deterministic export, dry-run import preview, and compensating restore."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import TypeAlias, cast
from uuid import UUID

from pydantic import JsonValue, ValidationError

from momo.domain.backup import (
    BACKUP_FORMAT_VERSION,
    MAX_BACKUP_DOCUMENTS,
    MAX_BACKUP_UPLOAD_BYTES,
    MAX_RESTORE_REVISION_STEPS,
    BackupCollisionError,
    BackupCollisionPolicy,
    BackupCommitUncertainError,
    BackupDocument,
    BackupEntityKind,
    BackupEnvelope,
    BackupError,
    BackupFormatError,
    BackupImportAction,
    BackupImportIssue,
    BackupImportItem,
    BackupImportPreview,
    BackupImportTotals,
    BackupPreviewRequiredError,
    BackupRestoreCalibrationTarget,
    BackupRestoreEntityTarget,
    BackupRestoreError,
    BackupRestoreResult,
    BackupRestoreTransaction,
    BackupRollbackError,
    BackupUnsafeContentError,
    canonical_json_bytes,
    safe_error_details,
)
from momo.domain.calibration import CALIBRATION_SCHEMA_VERSION, CalibrationDocument
from momo.domain.enums import RobotVariant
from momo.domain.errors import (
    AtomicImportCommittedError,
    EntityAlreadyExistsError,
    RevisionConflictError,
)
from momo.domain.motion import MOTION_SCHEMA_VERSION, Motion
from momo.domain.motion_draft import MOTION_DRAFT_SCHEMA_VERSION, MotionDraft
from momo.domain.pose import POSE_SCHEMA_VERSION, Pose
from momo.ports.backup_restore_journal import (
    BackupRestoreJournal,
    RestoreJournalRemovalUncertainError,
)
from momo.ports.calibration_repository import CalibrationRepository
from momo.ports.motion_draft_repository import MotionDraftRepository
from momo.ports.motion_repository import MotionRepository
from momo.ports.pose_repository import PoseRepository

MigrationPayload: TypeAlias = dict[str, JsonValue]
MigrationFunction: TypeAlias = Callable[[MigrationPayload], MigrationPayload]
CalibrationImporter: TypeAlias = Callable[[tuple[CalibrationDocument, ...]], Awaitable[None]]
CalibrationRollback: TypeAlias = Callable[
    [tuple[BackupRestoreCalibrationTarget, ...]], Awaitable[None]
]
RevisionedEntity: TypeAlias = Pose | Motion | MotionDraft

_CURRENT_SCHEMA_VERSIONS: dict[BackupEntityKind, str] = {
    BackupEntityKind.POSE: POSE_SCHEMA_VERSION,
    BackupEntityKind.MOTION: MOTION_SCHEMA_VERSION,
    BackupEntityKind.DRAFT: MOTION_DRAFT_SCHEMA_VERSION,
    BackupEntityKind.CALIBRATION: CALIBRATION_SCHEMA_VERSION,
}
_FORBIDDEN_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
        "accesstoken",
        "apikey",
        "accesskey",
        "privatekey",
        "secretkey",
        "lantoken",
        "sessiontoken",
        "serial",
        "serialnumber",
        "deviceserial",
        "serialport",
        "portname",
        "devicepath",
        "camerapath",
        "camerauri",
        "rtspuri",
        "logpath",
        "logdirectory",
        "runtimeconnection",
        "connectionstring",
        "path",
        "filepath",
        "directory",
        "localpath",
        "absolutepath",
        "camerafile",
        "logfile",
    }
)
_FORBIDDEN_CREDENTIAL_KEY_PARTS = (
    "authorization",
    "credential",
    "password",
    "secret",
    "sessiontoken",
    "refreshtoken",
    "accesstoken",
    "apikey",
    "accesskey",
    "privatekey",
    "secretkey",
)
_FORBIDDEN_KEY_TERMS = frozenset(
    {
        "authorization",
        "cookie",
        "credential",
        "password",
        "secret",
        "serial",
        "token",
    }
)
_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s,;\"']+")
_EMBEDDED_LOCAL_PATH = re.compile(r"(?<![A-Za-z0-9/])/(?:[^\s,;\"']+)")
_HTTP_URL = re.compile(r"https?://[^\s,;\"']+", re.IGNORECASE)
_MAX_PREVIEW_GRANTS = 128
_PREVIEW_GRANT_TTL_S = 300.0
_EMBEDDED_CREDENTIAL_VALUE = re.compile(
    r"(?<![A-Za-z0-9_])[\"'`]?(?:[A-Za-z][A-Za-z0-9_.-]{0,63})?"
    r"(?:access[_-]?token|authorization|cookie|credential|"
    r"password|refresh[_-]?token|session[_-]?token|secret|token|api[_-]?key|"
    r"access[_-]?key|private[_-]?key|secret[_-]?key)[\"'`]?\s*(?:=|:)\s*"
    r"(?:(?:Bearer|Basic)\s+)?(?:\"[^\"\r\n]{8,}\"|'[^'\r\n]{8,}'|"
    r"`[^`\r\n]{8,}`|[^\s,;}\]]{16,})",
    re.IGNORECASE,
)
_AUTH_CREDENTIAL = re.compile(
    r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/-]{16,}={0,2}",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _MigrationStep:
    destination_version: str
    migrate: MigrationFunction


@dataclass(frozen=True, slots=True)
class _PreparedDocument:
    document: BackupDocument
    entity: RevisionedEntity | CalibrationDocument
    migrated_from: str | None


class BackupMigrationRegistry:
    """Explicit, deterministic one-version-at-a-time migration registry."""

    def __init__(self) -> None:
        self._steps: dict[tuple[BackupEntityKind, str], _MigrationStep] = {}

    def register(
        self,
        *,
        kind: BackupEntityKind,
        source_version: str,
        destination_version: str,
        migrate: MigrationFunction,
    ) -> None:
        key = (kind, source_version)
        if not source_version or not destination_version or source_version == destination_version:
            raise ValueError("migration versions must be non-empty and different")
        if key in self._steps:
            raise ValueError("a migration is already registered for this kind/version")
        self._steps[key] = _MigrationStep(destination_version, migrate)

    def migrate(
        self,
        kind: BackupEntityKind,
        payload: MigrationPayload,
    ) -> tuple[MigrationPayload, str | None]:
        target = _CURRENT_SCHEMA_VERSIONS[kind]
        current = payload.get("schema_version")
        if not isinstance(current, str):
            raise BackupFormatError("Backup entity has no string schema_version")
        if current == target:
            return payload, None
        original_version = current
        original_id = payload.get("id")
        original_revision = payload.get("revision")
        migrated = payload
        visited: set[str] = set()
        for _ in range(8):
            if current == target:
                return migrated, original_version
            if current in visited:
                raise BackupFormatError("Backup migration registry contains a cycle")
            visited.add(current)
            step = self._steps.get((kind, current))
            if step is None:
                raise BackupFormatError(
                    f"No explicit {kind.value} migration exists from schema {current}"
                )
            detached = cast(MigrationPayload, json.loads(canonical_json_bytes(migrated)))
            candidate = step.migrate(detached)
            if not isinstance(candidate, dict):
                raise BackupFormatError("Backup migration did not return an object")
            if candidate.get("schema_version") != step.destination_version:
                raise BackupFormatError("Backup migration did not set its declared schema version")
            if candidate.get("id") != original_id or candidate.get("revision") != original_revision:
                raise BackupFormatError("Backup migration changed entity identity or revision")
            migrated = candidate
            current = step.destination_version
        raise BackupFormatError("Backup migration chain exceeds the supported length")


class BackupApplicationService:
    """Backup use cases over existing repository ports; never accepts a filesystem path."""

    def __init__(
        self,
        *,
        poses: PoseRepository,
        motions: MotionRepository,
        drafts: MotionDraftRepository,
        calibrations: CalibrationRepository | None = None,
        calibration_importer: CalibrationImporter | None = None,
        calibration_rollback: CalibrationRollback | None = None,
        restore_journal: BackupRestoreJournal | None = None,
        migrations: BackupMigrationRegistry | None = None,
        maintenance_lock: AbstractAsyncContextManager[None] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.poses = poses
        self.motions = motions
        self.drafts = drafts
        self.calibrations = calibrations
        self.calibration_importer = calibration_importer
        self.calibration_rollback = calibration_rollback
        self.restore_journal = restore_journal
        if (
            restore_journal is not None
            and calibration_importer is not None
            and calibration_rollback is None
        ):
            raise ValueError("A durable restore journal requires exact calibration rollback")
        self.migrations = migrations or BackupMigrationRegistry()
        self._maintenance_lock = maintenance_lock or asyncio.Lock()
        self._monotonic = monotonic
        self._preview_grants: OrderedDict[tuple[str, BackupCollisionPolicy, bool], float] = (
            OrderedDict()
        )
        self._preview_grant_lock = asyncio.Lock()

    async def recover_pending_restore(self) -> bool:
        """Compensate a durable write-ahead intent before serving application traffic."""

        if self.restore_journal is None:
            return False
        async with self._maintenance_lock:
            transaction = await self.restore_journal.load()
            if transaction is None:
                return False
            failures, _ = await self._rollback_targets_resilient(
                transaction.entities,
                transaction.calibrations,
            )
            if failures:
                raise BackupRollbackError(
                    "Pending restore recovery could not be completed",
                    details=safe_error_details(rollback_failures=failures),
                )
            await self._clear_journal_after_compensation(
                "Pending restore data was removed, but journal cleanup durability is uncertain"
            )
            return True

    async def export_bundle(self, *, include_calibration: bool = False) -> BackupEnvelope:
        pose_values, motion_values, draft_values = await asyncio.gather(
            self.poses.list(),
            self.motions.list(),
            self.drafts.list(),
        )
        documents: list[BackupDocument] = []
        for kind, values in (
            (BackupEntityKind.POSE, pose_values),
            (BackupEntityKind.MOTION, motion_values),
            (BackupEntityKind.DRAFT, draft_values),
        ):
            for revisioned_entity in values:
                payload = cast(MigrationPayload, revisioned_entity.model_dump(mode="json"))
                _require_backup_safe(payload)
                documents.append(BackupDocument.from_payload(kind=kind, payload=payload))
        if include_calibration:
            if self.calibrations is None:
                raise BackupFormatError("Calibration export is unavailable in this installation")
            calibration_values = tuple(
                document
                for variant in RobotVariant
                if (document := self.calibrations.get_for_variant(variant)) is not None
            )
            variants = [item.robot_variant for item in calibration_values]
            if len(variants) != len(set(variants)):
                raise BackupFormatError("Calibration export contains duplicate robot variants")
            for calibration_entity in calibration_values:
                payload = cast(MigrationPayload, calibration_entity.model_dump(mode="json"))
                _require_backup_safe(payload)
                documents.append(
                    BackupDocument.from_payload(
                        kind=BackupEntityKind.CALIBRATION,
                        payload=payload,
                    )
                )
        if len(documents) > MAX_BACKUP_DOCUMENTS:
            raise BackupFormatError("Backup contains too many documents")
        envelope = BackupEnvelope.build(documents)
        if len(envelope.to_bytes()) > MAX_BACKUP_UPLOAD_BYTES:
            raise BackupFormatError("Backup exceeds the maximum encoded size")
        return envelope

    async def preview_import(
        self,
        content: bytes,
        *,
        collision_policy: BackupCollisionPolicy = BackupCollisionPolicy.REJECT,
        allow_calibration: bool = False,
    ) -> BackupImportPreview:
        _, preview = await self._prepare(
            content,
            collision_policy=collision_policy,
            allow_calibration=allow_calibration,
        )
        if preview.valid:
            await self._register_preview_grant(
                preview.bundle_sha256,
                collision_policy,
                allow_calibration,
            )
        return preview

    async def restore_bundle(
        self,
        content: bytes,
        *,
        expected_bundle_sha256: str,
        confirmation: str,
        collision_policy: BackupCollisionPolicy = BackupCollisionPolicy.REJECT,
        allow_calibration: bool = False,
    ) -> BackupRestoreResult:
        if confirmation != "RESTORE":
            raise BackupPreviewRequiredError("Restore requires the exact RESTORE confirmation")
        await self._consume_preview_grant(
            expected_bundle_sha256,
            collision_policy,
            allow_calibration,
        )
        async with self._maintenance_lock:
            prepared, preview = await self._prepare(
                content,
                collision_policy=collision_policy,
                allow_calibration=allow_calibration,
            )
            if expected_bundle_sha256 != preview.bundle_sha256:
                raise BackupPreviewRequiredError(
                    "Backup digest differs from the previewed bundle",
                    details=safe_error_details(expected_bundle_sha256=expected_bundle_sha256),
                )
            if not preview.valid:
                if preview.totals.conflict:
                    raise BackupCollisionError(
                        "Backup has collisions under the selected policy",
                        details=safe_error_details(conflicts=preview.totals.conflict),
                    )
                raise BackupFormatError(
                    "Backup preview contains validation issues",
                    details=safe_error_details(issue_codes=[item.code for item in preview.issues]),
                )

            by_key = {(item.document.kind, item.document.id): item for item in prepared}
            entity_targets = [
                BackupRestoreEntityTarget(
                    kind=item.kind,
                    id=item.id,
                    revision=cast(int, item.source_revision),
                )
                for item in preview.items
                if item.action is BackupImportAction.CREATE
                and item.kind is not BackupEntityKind.CALIBRATION
            ]
            calibration_targets = [
                BackupRestoreCalibrationTarget(
                    variant=cast(
                        CalibrationDocument,
                        by_key[(item.kind, item.id)].entity,
                    ).robot_variant,
                    id=item.id,
                )
                for item in preview.items
                if item.action is BackupImportAction.CREATE
                and item.kind is BackupEntityKind.CALIBRATION
            ]
            transaction = (
                BackupRestoreTransaction(
                    bundle_sha256=preview.bundle_sha256,
                    entities=entity_targets,
                    calibrations=calibration_targets,
                )
                if entity_targets or calibration_targets
                else None
            )
            if transaction is not None and self.restore_journal is not None:
                journal_cancelled = await self.restore_journal.begin(transaction)
                if journal_cancelled:
                    rollback_failures, _ = await self._rollback_targets_resilient(
                        entity_targets,
                        calibration_targets,
                    )
                    if rollback_failures:
                        raise BackupRollbackError(
                            "Restore was cancelled and rollback could not be completed",
                            details=safe_error_details(rollback_failures=rollback_failures),
                        )
                    await self._clear_journal_after_compensation(
                        "Cancelled restore data was removed, but journal cleanup durability "
                        "is uncertain"
                    )
                    raise asyncio.CancelledError
            calibrations: list[CalibrationDocument] = []
            restored_counts = {kind: 0 for kind in BackupEntityKind}
            skipped_count = 0
            try:
                for item in preview.items:
                    if item.action is BackupImportAction.SKIP:
                        skipped_count += 1
                        continue
                    prepared_item = by_key[(item.kind, item.id)]
                    if item.kind is BackupEntityKind.CALIBRATION:
                        calibrations.append(cast(CalibrationDocument, prepared_item.entity))
                        continue
                    _, cancellation_requested, create_error = await self._create_revisioned(
                        item.kind, prepared_item.entity
                    )
                    if cancellation_requested:
                        # The atomic create was allowed to reach a known terminal
                        # result. Record it before propagating cancellation so the
                        # outer handler can compensate the exact committed revision.
                        raise asyncio.CancelledError
                    if create_error is not None:
                        # `os.replace` committed the exact bytes, but the directory
                        # fsync failed. Treat the entity as created so compensation
                        # removes it before the durability error is reported.
                        raise create_error
                    restored_counts[item.kind] += 1

                result = BackupRestoreResult(
                    bundle_sha256=preview.bundle_sha256,
                    restored_counts=restored_counts,
                    skipped_count=skipped_count,
                )
                if calibrations:
                    if self.calibration_importer is None:  # preview should make this unreachable
                        raise BackupFormatError("Calibration restore is unavailable")
                    await self.calibration_importer(tuple(calibrations))
                    restored_counts[BackupEntityKind.CALIBRATION] = len(calibrations)
                    result = BackupRestoreResult(
                        bundle_sha256=preview.bundle_sha256,
                        restored_counts=restored_counts,
                        skipped_count=skipped_count,
                    )
                if transaction is not None and self.restore_journal is not None:
                    await self._clear_journal_after_commit()
                return result
            except asyncio.CancelledError as error:
                rollback_failures, _ = await self._rollback_targets_resilient(
                    entity_targets,
                    calibration_targets,
                )
                if rollback_failures:
                    raise BackupRollbackError(
                        "Restore was cancelled and rollback could not be completed",
                        details=safe_error_details(rollback_failures=rollback_failures),
                    ) from error
                if transaction is not None and self.restore_journal is not None:
                    await self._clear_journal_after_compensation(
                        "Cancelled restore data was removed, but journal cleanup durability "
                        "is uncertain"
                    )
                raise
            except BackupCommitUncertainError:
                # WAL unlink is the commit point. If its directory fsync fails,
                # rollback could itself be interrupted after the journal has become
                # durably absent. Preserve the complete batch: a crash now yields
                # either all committed data or a reappearing WAL that startup rolls
                # back in full.
                raise
            except Exception as error:
                rollback_failures, rollback_cancelled = await self._rollback_targets_resilient(
                    entity_targets,
                    calibration_targets,
                )
                if rollback_failures:
                    raise BackupRollbackError(
                        "Restore failed and rollback could not be completed",
                        details=safe_error_details(rollback_failures=rollback_failures),
                    ) from error
                if rollback_cancelled:
                    raise asyncio.CancelledError from error
                if transaction is not None and self.restore_journal is not None:
                    await self._clear_journal_after_compensation(
                        "Failed restore data was removed, but journal cleanup durability "
                        "is uncertain"
                    )
                if isinstance(error, EntityAlreadyExistsError | RevisionConflictError):
                    raise BackupCollisionError(
                        "Repository state changed after preview; restore was rolled back"
                    ) from error
                if isinstance(error, BackupRollbackError):
                    raise
                raise BackupRestoreError(
                    "Restore failed and all created documents were rolled back"
                ) from error

    async def _clear_journal_after_commit(self) -> None:
        """Map the unlink commit point to a truthful product-facing outcome."""

        if self.restore_journal is None:  # pragma: no cover - guarded by callers
            return
        try:
            await self.restore_journal.clear()
        except RestoreJournalRemovalUncertainError as error:
            raise BackupCommitUncertainError(
                "Restore committed, but journal removal durability is uncertain"
            ) from error

    async def _clear_journal_after_compensation(self, message: str) -> None:
        """Report uncertain WAL cleanup without claiming a restore committed."""

        if self.restore_journal is None:  # pragma: no cover - guarded by callers
            return
        try:
            await self.restore_journal.clear()
        except RestoreJournalRemovalUncertainError as error:
            raise BackupRollbackError(message) from error

    async def _register_preview_grant(
        self,
        bundle_sha256: str,
        collision_policy: BackupCollisionPolicy,
        allow_calibration: bool,
    ) -> None:
        key = (bundle_sha256, collision_policy, allow_calibration)
        async with self._preview_grant_lock:
            self._prune_preview_grants()
            self._preview_grants[key] = self._monotonic() + _PREVIEW_GRANT_TTL_S
            self._preview_grants.move_to_end(key)
            while len(self._preview_grants) > _MAX_PREVIEW_GRANTS:
                self._preview_grants.popitem(last=False)

    async def _consume_preview_grant(
        self,
        bundle_sha256: str,
        collision_policy: BackupCollisionPolicy,
        allow_calibration: bool,
    ) -> None:
        key = (bundle_sha256, collision_policy, allow_calibration)
        async with self._preview_grant_lock:
            self._prune_preview_grants()
            expires_at = self._preview_grants.pop(key, None)
        if expires_at is None or expires_at <= self._monotonic():
            raise BackupPreviewRequiredError(
                "Run a successful import preview with the exact restore options first"
            )

    def _prune_preview_grants(self) -> None:
        now = self._monotonic()
        for key, expires_at in tuple(self._preview_grants.items()):
            if expires_at <= now:
                del self._preview_grants[key]

    async def _prepare(
        self,
        content: bytes,
        *,
        collision_policy: BackupCollisionPolicy,
        allow_calibration: bool,
    ) -> tuple[list[_PreparedDocument], BackupImportPreview]:
        envelope = _parse_envelope(content)
        prepared: list[_PreparedDocument] = []
        items: list[BackupImportItem] = []
        issues: list[BackupImportIssue] = []
        calibration_values = self._current_calibrations()
        incoming_calibration_variants: set[RobotVariant] = set()
        revision_steps = 0

        for document in envelope.documents:
            try:
                _require_backup_safe(document.payload)
                if document.kind is BackupEntityKind.CALIBRATION and not allow_calibration:
                    raise BackupFormatError(
                        "Calibration import requires an explicit allow_calibration decision"
                    )
                migrated, migrated_from = self.migrations.migrate(
                    document.kind,
                    dict(document.payload),
                )
                _require_backup_safe(migrated)
                entity = _validate_entity(document.kind, migrated)
                if document.kind is BackupEntityKind.CALIBRATION:
                    calibration = cast(CalibrationDocument, entity)
                    _require_importable_calibration(calibration)
                    if calibration.robot_variant in incoming_calibration_variants:
                        raise BackupFormatError(
                            "Backup contains more than one calibration for a robot variant"
                        )
                    incoming_calibration_variants.add(calibration.robot_variant)
                candidate = _PreparedDocument(document, entity, migrated_from)
                collision = await self._collision(candidate, calibration_values)
                if collision:
                    if collision_policy is BackupCollisionPolicy.SKIP:
                        action = BackupImportAction.SKIP
                        message = "Existing destination document will be left unchanged"
                    else:
                        action = BackupImportAction.CONFLICT
                        message = (
                            "Destination already contains this identity or calibration variant"
                        )
                        issues.append(
                            BackupImportIssue(
                                code="BACKUP_COLLISION",
                                message=message,
                                kind=document.kind,
                                entity_id=document.id,
                            )
                        )
                elif (
                    document.kind is BackupEntityKind.CALIBRATION
                    and self.calibration_importer is None
                ):
                    action = BackupImportAction.INVALID
                    message = "Calibration restore is unavailable in this installation"
                    issues.append(
                        BackupImportIssue(
                            code="CALIBRATION_RESTORE_UNAVAILABLE",
                            message=message,
                            kind=document.kind,
                            entity_id=document.id,
                        )
                    )
                else:
                    action = BackupImportAction.CREATE
                    message = None
                    if document.source_revision is not None:
                        revision_steps += document.source_revision
                prepared.append(candidate)
                items.append(
                    BackupImportItem(
                        kind=document.kind,
                        id=document.id,
                        source_revision=document.source_revision,
                        action=action,
                        migrated_from=migrated_from,
                        message=message,
                    )
                )
            except (
                BackupFormatError,
                BackupUnsafeContentError,
                ValidationError,
                ValueError,
            ) as error:
                message = _safe_validation_message(error)
                items.append(
                    BackupImportItem(
                        kind=document.kind,
                        id=document.id,
                        source_revision=document.source_revision,
                        action=BackupImportAction.INVALID,
                        message=message,
                    )
                )
                issues.append(
                    BackupImportIssue(
                        code=error.code if isinstance(error, BackupError) else "ENTITY_INVALID",
                        message=message,
                        kind=document.kind,
                        entity_id=document.id,
                    )
                )

        if revision_steps > MAX_RESTORE_REVISION_STEPS:
            issues.append(
                BackupImportIssue(
                    code="RESTORE_REVISION_BUDGET_EXCEEDED",
                    message="Backup revisions exceed the bounded restore work budget",
                )
            )
        totals = BackupImportTotals(
            documents=len(items),
            create=sum(item.action is BackupImportAction.CREATE for item in items),
            skip=sum(item.action is BackupImportAction.SKIP for item in items),
            conflict=sum(item.action is BackupImportAction.CONFLICT for item in items),
            invalid=sum(item.action is BackupImportAction.INVALID for item in items),
        )
        preview = BackupImportPreview(
            bundle_sha256=envelope.sha256,
            format_version=BACKUP_FORMAT_VERSION,
            valid=not issues and revision_steps <= MAX_RESTORE_REVISION_STEPS,
            contains_calibration=envelope.manifest.calibration_included,
            collision_policy=collision_policy,
            totals=totals,
            items=items,
            issues=issues,
        )
        return prepared, preview

    def _current_calibrations(self) -> tuple[CalibrationDocument, ...]:
        if self.calibrations is None:
            return ()
        return tuple(
            document
            for variant in RobotVariant
            if (document := self.calibrations.get_for_variant(variant)) is not None
        )

    async def _collision(
        self,
        item: _PreparedDocument,
        calibrations: Sequence[CalibrationDocument],
    ) -> bool:
        if item.document.kind is BackupEntityKind.POSE:
            return await self.poses.get(item.document.id) is not None
        if item.document.kind is BackupEntityKind.MOTION:
            return await self.motions.get(item.document.id) is not None
        if item.document.kind is BackupEntityKind.DRAFT:
            return await self.drafts.get(item.document.id) is not None
        calibration = cast(CalibrationDocument, item.entity)
        return any(
            current.id == calibration.id or current.robot_variant is calibration.robot_variant
            for current in calibrations
        )

    async def _create_revisioned(
        self,
        kind: BackupEntityKind,
        entity: RevisionedEntity | CalibrationDocument,
    ) -> tuple[int, bool, Exception | None]:
        revisioned = cast(RevisionedEntity, entity)
        try:
            if kind is BackupEntityKind.POSE:
                cancelled = await self.poses.import_exact(cast(Pose, revisioned))
            elif kind is BackupEntityKind.MOTION:
                cancelled = await self.motions.import_exact(cast(Motion, revisioned))
            elif kind is BackupEntityKind.DRAFT:
                cancelled = await self.drafts.import_exact(cast(MotionDraft, revisioned))
            else:  # pragma: no cover - caller routes calibration separately
                raise TypeError("calibration does not use revisioned entity storage")
        except AtomicImportCommittedError as error:
            return revisioned.revision, error.cancellation_requested, error
        return revisioned.revision, cancelled, None

    async def _rollback_targets_resilient(
        self,
        entities: Sequence[BackupRestoreEntityTarget],
        calibrations: Sequence[BackupRestoreCalibrationTarget],
    ) -> tuple[int, bool]:
        """Finish bounded compensation despite repeated caller cancellation."""

        cancellation_requested = False
        while True:
            try:
                return (
                    await self._rollback_targets(entities, calibrations),
                    cancellation_requested,
                )
            except asyncio.CancelledError:
                cancellation_requested = True

    async def _rollback_targets(
        self,
        entities: Sequence[BackupRestoreEntityTarget],
        calibrations: Sequence[BackupRestoreCalibrationTarget],
    ) -> int:
        failures = 0
        if calibrations:
            if self.calibration_rollback is None:
                if self.restore_journal is not None:
                    failures += 1
            else:
                try:
                    await self.calibration_rollback(tuple(calibrations))
                except Exception:
                    failures += 1
        for target in reversed(entities):
            try:
                await self._delete_exact(target.kind, target.id, target.revision)
            except Exception:
                failures += 1
        return failures

    async def _delete_exact(
        self,
        kind: BackupEntityKind,
        entity_id: UUID,
        expected_revision: int,
    ) -> None:
        """Compensate only the exact revision written by this restore.

        A concurrent edit advances the revision and must survive. In that case the
        repository compare-and-swap raises and restore reports an incomplete rollback
        instead of deleting someone else's data.
        """

        if kind is BackupEntityKind.POSE:
            await self.poses.delete(entity_id, expected_revision=expected_revision)
        elif kind is BackupEntityKind.MOTION:
            await self.motions.delete(entity_id, expected_revision=expected_revision)
        elif kind is BackupEntityKind.DRAFT:
            await self.drafts.delete(entity_id, expected_revision=expected_revision)


def _parse_envelope(content: bytes) -> BackupEnvelope:
    if not content or len(content) > MAX_BACKUP_UPLOAD_BYTES:
        raise BackupFormatError(
            "Backup body is empty or exceeds the upload limit",
            details=safe_error_details(maximum_bytes=MAX_BACKUP_UPLOAD_BYTES),
        )

    def reject_constant(value: str) -> None:
        raise ValueError(f"invalid JSON constant {value}")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("backup JSON contains a duplicate object key")
            result[key] = value
        return result

    try:
        raw = json.loads(
            content.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
        return BackupEnvelope.model_validate(raw)
    except (
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
        ValidationError,
        ValueError,
    ) as error:
        raise BackupFormatError("Backup envelope is invalid") from error


def _validate_entity(
    kind: BackupEntityKind,
    payload: MigrationPayload,
) -> RevisionedEntity | CalibrationDocument:
    if kind is BackupEntityKind.POSE:
        return Pose.model_validate(payload)
    if kind is BackupEntityKind.MOTION:
        return Motion.model_validate(payload)
    if kind is BackupEntityKind.DRAFT:
        return MotionDraft.model_validate(payload)
    return CalibrationDocument.model_validate(payload)


def _require_importable_calibration(calibration: CalibrationDocument) -> None:
    """Backups may restore only field-shaped, complete calibration artifacts."""

    if calibration.template:
        raise BackupFormatError("Template calibration cannot be restored as Real calibration")
    if not all(joint.complete for joint in calibration.joints):
        raise BackupFormatError("Incomplete calibration cannot be restored as Real calibration")


def _require_backup_safe(value: object) -> None:
    nodes = 0

    def visit(item: object, location: str, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 100_000 or depth > 20:
            raise BackupUnsafeContentError("Backup content exceeds the safety traversal bound")
        if isinstance(item, dict):
            for raw_key, child in item.items():
                key = str(raw_key)
                normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
                separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
                terms = {term for term in re.split(r"[^A-Za-z0-9]+", separated.casefold()) if term}
                forbidden_term = bool(terms & _FORBIDDEN_KEY_TERMS) or bool(
                    terms & {"path", "directory", "filename"}
                )
                if (
                    normalized in _FORBIDDEN_KEYS
                    or forbidden_term
                    or any(part in normalized for part in _FORBIDDEN_CREDENTIAL_KEY_PARTS)
                ):
                    raise BackupUnsafeContentError(
                        "Backup contains a forbidden device-local or credential field",
                        details=safe_error_details(field=f"{location}.{key}"),
                    )
                visit(child, f"{location}.{key}", depth + 1)
        elif isinstance(item, list | tuple):
            for index, child in enumerate(item):
                visit(child, f"{location}[{index}]", depth + 1)
        elif isinstance(item, str) and (
            _contains_local_path(item)
            or _EMBEDDED_CREDENTIAL_VALUE.search(item)
            or _AUTH_CREDENTIAL.search(item)
        ):
            raise BackupUnsafeContentError(
                "Backup contains a device-local path or credential value",
                details=safe_error_details(field=location),
            )

    visit(value, "$", 0)


def _contains_local_path(value: str) -> bool:
    """Reject local paths embedded in prose while permitting ordinary HTTP links."""

    without_http_urls = _HTTP_URL.sub("", value)
    return bool(
        without_http_urls.startswith("/")
        or without_http_urls.startswith("file://")
        or _WINDOWS_ABSOLUTE_PATH.search(without_http_urls)
        or _EMBEDDED_LOCAL_PATH.search(without_http_urls)
    )


def _safe_validation_message(error: Exception) -> str:
    if isinstance(error, BackupUnsafeContentError | BackupFormatError):
        return error.message
    if isinstance(error, ValidationError):
        return "Entity does not satisfy the current validated schema"
    return "Entity validation failed"
