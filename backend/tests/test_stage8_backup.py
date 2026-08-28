"""Stage 8 deterministic, path-free backup and migration contracts."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from momo.adapters.storage.file_backup_restore_journal import FileBackupRestoreJournal
from momo.adapters.storage.file_calibration_workflow_repository import (
    FileCalibrationWorkflowRepository,
)
from momo.adapters.storage.file_entity_repository import RepositoryMaintenanceGate
from momo.adapters.storage.file_motion_draft_repository import FileMotionDraftRepository
from momo.adapters.storage.file_motion_repository import FileMotionRepository
from momo.adapters.storage.file_pose_repository import FilePoseRepository
from momo.api.app import create_app
from momo.api.backup_schemas import BACKUP_MEDIA_TYPE
from momo.api.error_handlers import install_error_handlers
from momo.api.routes.backup import router as backup_router
from momo.application.services.backup_service import (
    BackupApplicationService,
    BackupMigrationRegistry,
    CalibrationImporter,
    MigrationPayload,
)
from momo.application.services.security_service import SecurityService
from momo.domain.backup import (
    BackupCollisionPolicy,
    BackupCommitUncertainError,
    BackupDocument,
    BackupEntityKind,
    BackupEnvelope,
    BackupFormatError,
    BackupImportAction,
    BackupPreviewRequiredError,
    BackupRestoreCalibrationTarget,
    BackupRestoreEntityTarget,
    BackupRestoreError,
    BackupRestoreTransaction,
    BackupRollbackError,
    BackupUnsafeContentError,
)
from momo.domain.calibration import CalibrationDocument, CalibrationJoint
from momo.domain.enums import CalibrationOperatingMode, RobotVariant
from momo.domain.motion_draft import MotionDraft
from momo.domain.pose import POSE_SCHEMA_VERSION, Pose, PoseSnapshot
from momo.domain.security import NetworkSecurityPolicy
from momo.ports.pose_repository import PoseRepository
from momo.release_bootstrap import commit_calibration_import
from momo.settings import Settings
from tests.factories import make_motion, make_snapshot
from tests.stage3_helpers import FakeClock
from tests.stage8_hardware_helpers import real_calibration, real_profile


class MemoryCalibrationRepository:
    def __init__(self, *documents: CalibrationDocument) -> None:
        self.documents = {item.robot_variant: item for item in documents}

    def get_for_variant(self, variant: RobotVariant) -> CalibrationDocument | None:
        return self.documents.get(variant)


class FailingPoseRepository:
    def __init__(
        self,
        inner: FilePoseRepository,
        before_failure: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.inner = inner
        self.before_failure = before_failure

    async def get(self, pose_id: UUID) -> Pose | None:
        return await self.inner.get(pose_id)

    async def list(self) -> Sequence[Pose]:
        return await self.inner.list()

    async def save(self, pose: Pose, *, expected_revision: int | None = None) -> None:
        del pose, expected_revision
        if self.before_failure is not None:
            await self.before_failure()
        raise OSError("synthetic restore failure")

    async def import_exact(self, pose: Pose) -> bool:
        await self.save(pose)
        return False

    async def delete(self, pose_id: UUID, *, expected_revision: int) -> bool:
        return await self.inner.delete(pose_id, expected_revision=expected_revision)


def repositories(
    root: Path,
) -> tuple[FilePoseRepository, FileMotionRepository, FileMotionDraftRepository]:
    clock = FakeClock()
    return (
        FilePoseRepository(root / "poses", clock),
        FileMotionRepository(root / "motions", clock),
        FileMotionDraftRepository(root / "drafts", clock),
    )


def backup_service(
    root: Path,
    *,
    poses: PoseRepository | None = None,
    calibrations: MemoryCalibrationRepository | None = None,
    calibration_importer: CalibrationImporter | None = None,
    migrations: BackupMigrationRegistry | None = None,
) -> BackupApplicationService:
    default_poses, motions, drafts = repositories(root)
    return BackupApplicationService(
        poses=poses or default_poses,
        motions=motions,
        drafts=drafts,
        calibrations=calibrations,
        calibration_importer=calibration_importer,
        migrations=migrations,
    )


def make_calibration() -> CalibrationDocument:
    return CalibrationDocument(
        robot_variant=RobotVariant.V2,
        profile_fingerprint="a" * 64,
        template=False,
        joints=[
            CalibrationJoint(
                joint_id="j1",
                servo_id=1,
                operating_mode=CalibrationOperatingMode.SINGLE_TURN,
                direction=1,
                home_present_raw=2048,
                raw_bounds=(0, 4095),
            )
        ],
    )


def test_export_is_deterministic_config_free_and_document_digests_are_enforced(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        poses, motions, drafts = repositories(tmp_path / "source")
        pose = Pose(name="Backup pose", snapshot=make_snapshot())
        motion = make_motion()
        draft = MotionDraft(name="Draft", robot_variant=RobotVariant.V2)
        await poses.save(pose)
        await motions.save(motion)
        await drafts.save(draft)
        service = BackupApplicationService(poses=poses, motions=motions, drafts=drafts)

        first = await service.export_bundle()
        second = await service.export_bundle()
        assert first.to_bytes() == second.to_bytes()
        assert first.sha256 == second.sha256
        assert [item.kind.value for item in first.documents] == ["draft", "motion", "pose"]
        assert first.manifest.document_count == 3
        assert first.manifest.calibration_included is False
        rendered = first.to_bytes().decode("utf-8")
        assert "runtime_connection" not in rendered
        assert "camera_path" not in rendered
        assert "lan_token" not in rendered

        corrupted = json.loads(rendered)
        corrupted["documents"][0]["payload"]["name"] = "digest mismatch"
        with pytest.raises(BackupFormatError):
            await service.preview_import(
                json.dumps(corrupted).encode("utf-8"),
                collision_policy=BackupCollisionPolicy.REJECT,
            )

    asyncio.run(scenario())


def test_preview_restore_preserves_revisions_and_handles_collisions_without_overwrite(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        source_poses, source_motions, source_drafts = repositories(tmp_path / "source")
        original = Pose(name="Revision one", snapshot=make_snapshot())
        await source_poses.save(original)
        revision_two = Pose.model_validate(
            {**original.model_dump(mode="python"), "name": "Revision two", "revision": 2}
        )
        await source_poses.save(revision_two, expected_revision=1)
        revision_three = Pose.model_validate(
            {**revision_two.model_dump(mode="python"), "name": "Revision three", "revision": 3}
        )
        await source_poses.save(revision_three, expected_revision=2)
        source = BackupApplicationService(
            poses=source_poses,
            motions=source_motions,
            drafts=source_drafts,
        )
        envelope = await source.export_bundle()

        destination_poses, destination_motions, destination_drafts = repositories(
            tmp_path / "destination"
        )
        destination = BackupApplicationService(
            poses=destination_poses,
            motions=destination_motions,
            drafts=destination_drafts,
        )
        preview = await destination.preview_import(envelope.to_bytes())
        assert preview.valid is True
        assert preview.totals.create == 1
        result = await destination.restore_bundle(
            envelope.to_bytes(),
            expected_bundle_sha256=preview.bundle_sha256,
            confirmation="RESTORE",
        )
        assert result.restored_counts[BackupEntityKind.POSE] == 1
        assert await destination_poses.get(original.id) == revision_three

        rejected = await destination.preview_import(
            envelope.to_bytes(),
            collision_policy=BackupCollisionPolicy.REJECT,
        )
        assert rejected.valid is False
        assert rejected.items[0].action is BackupImportAction.CONFLICT
        skipped = await destination.preview_import(
            envelope.to_bytes(),
            collision_policy=BackupCollisionPolicy.SKIP,
        )
        assert skipped.valid is True
        assert skipped.items[0].action is BackupImportAction.SKIP
        skip_result = await destination.restore_bundle(
            envelope.to_bytes(),
            expected_bundle_sha256=skipped.bundle_sha256,
            confirmation="RESTORE",
            collision_policy=BackupCollisionPolicy.SKIP,
        )
        assert skip_result.skipped_count == 1
        assert await destination_poses.get(original.id) == revision_three

    asyncio.run(scenario())


def test_restore_requires_one_fresh_preview_bound_to_exact_options(tmp_path: Path) -> None:
    async def scenario() -> None:
        pose = Pose(name="Preview-bound", snapshot=make_snapshot())
        envelope = BackupEnvelope.build(
            [
                BackupDocument.from_payload(
                    kind=BackupEntityKind.POSE,
                    payload=cast(MigrationPayload, pose.model_dump(mode="json")),
                )
            ]
        )
        poses, motions, drafts = repositories(tmp_path / "destination")
        service = BackupApplicationService(poses=poses, motions=motions, drafts=drafts)

        with pytest.raises(BackupPreviewRequiredError, match="successful import preview"):
            await service.restore_bundle(
                envelope.to_bytes(),
                expected_bundle_sha256=envelope.sha256,
                confirmation="RESTORE",
            )

        preview = await service.preview_import(envelope.to_bytes())
        with pytest.raises(BackupPreviewRequiredError, match="exact restore options"):
            await service.restore_bundle(
                envelope.to_bytes(),
                expected_bundle_sha256=preview.bundle_sha256,
                confirmation="RESTORE",
                collision_policy=BackupCollisionPolicy.SKIP,
            )

        await service.restore_bundle(
            envelope.to_bytes(),
            expected_bundle_sha256=preview.bundle_sha256,
            confirmation="RESTORE",
        )
        assert await poses.get(pose.id) == pose
        with pytest.raises(BackupPreviewRequiredError, match="successful import preview"):
            await service.restore_bundle(
                envelope.to_bytes(),
                expected_bundle_sha256=preview.bundle_sha256,
                confirmation="RESTORE",
            )

    asyncio.run(scenario())


def test_exact_revision_import_performs_one_atomic_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        pose = Pose(name="High revision", snapshot=make_snapshot()).model_copy(
            update={"revision": 50_000}
        )
        envelope = BackupEnvelope.build(
            [
                BackupDocument.from_payload(
                    kind=BackupEntityKind.POSE,
                    payload=cast(MigrationPayload, pose.model_dump(mode="json")),
                )
            ]
        )
        poses, motions, drafts = repositories(tmp_path / "destination")
        replacements = 0
        original_replace = poses._atomic_replace

        def count_replace(destination: Path, payload: bytes) -> None:
            nonlocal replacements
            replacements += 1
            original_replace(destination, payload)

        monkeypatch.setattr(poses, "_atomic_replace", count_replace)
        service = BackupApplicationService(poses=poses, motions=motions, drafts=drafts)
        preview = await service.preview_import(envelope.to_bytes())
        assert preview.valid is True
        await service.restore_bundle(
            envelope.to_bytes(),
            expected_bundle_sha256=preview.bundle_sha256,
            confirmation="RESTORE",
        )
        assert replacements == 1
        assert await poses.get(pose.id) == pose

    asyncio.run(scenario())


def test_restore_cancellation_waits_for_atomic_create_then_rolls_it_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        pose = Pose(name="Cancellation race", snapshot=make_snapshot())
        envelope = BackupEnvelope.build(
            [
                BackupDocument.from_payload(
                    kind=BackupEntityKind.POSE,
                    payload=cast(MigrationPayload, pose.model_dump(mode="json")),
                )
            ]
        )
        poses, motions, drafts = repositories(tmp_path / "destination")
        entered_replace = threading.Event()
        release_replace = threading.Event()
        original_replace = poses._atomic_replace

        def blocking_replace(destination: Path, payload: bytes) -> None:
            entered_replace.set()
            if not release_replace.wait(timeout=5):
                raise TimeoutError("test did not release the atomic replace")
            original_replace(destination, payload)

        monkeypatch.setattr(poses, "_atomic_replace", blocking_replace)
        service = BackupApplicationService(poses=poses, motions=motions, drafts=drafts)
        preview = await service.preview_import(envelope.to_bytes())
        restore = asyncio.create_task(
            service.restore_bundle(
                envelope.to_bytes(),
                expected_bundle_sha256=preview.bundle_sha256,
                confirmation="RESTORE",
            )
        )
        assert await asyncio.to_thread(entered_replace.wait, 5)
        restore.cancel()
        await asyncio.sleep(0)
        assert not restore.done()
        release_replace.set()
        with pytest.raises(asyncio.CancelledError):
            await restore
        assert await poses.get(pose.id) is None

    asyncio.run(scenario())


def test_post_replace_directory_fsync_failure_compensates_committed_entity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        pose = Pose(name="Post-replace failure", snapshot=make_snapshot())
        envelope = BackupEnvelope.build(
            [
                BackupDocument.from_payload(
                    kind=BackupEntityKind.POSE,
                    payload=cast(MigrationPayload, pose.model_dump(mode="json")),
                )
            ]
        )
        poses, motions, drafts = repositories(tmp_path / "destination")
        poses._ensure_directory()
        original_fsync = poses._fsync_directory
        calls = 0

        def fail_first_directory_fsync(directory: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("synthetic post-replace directory fsync failure")
            original_fsync(directory)

        monkeypatch.setattr(poses, "_fsync_directory", fail_first_directory_fsync)
        service = BackupApplicationService(poses=poses, motions=motions, drafts=drafts)
        preview = await service.preview_import(envelope.to_bytes())
        with pytest.raises(BackupRestoreError, match="rolled back"):
            await service.restore_bundle(
                envelope.to_bytes(),
                expected_bundle_sha256=preview.bundle_sha256,
                confirmation="RESTORE",
            )
        assert calls >= 2
        assert await poses.get(pose.id) is None

    asyncio.run(scenario())


def test_cancellation_during_post_replace_fsync_still_compensates_entity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        pose = Pose(name="Combined failure", snapshot=make_snapshot())
        envelope = BackupEnvelope.build(
            [
                BackupDocument.from_payload(
                    kind=BackupEntityKind.POSE,
                    payload=cast(MigrationPayload, pose.model_dump(mode="json")),
                )
            ]
        )
        poses, motions, drafts = repositories(tmp_path / "destination")
        poses._ensure_directory()
        entered_fsync = threading.Event()
        release_fsync = threading.Event()
        original_fsync = poses._fsync_directory
        calls = 0

        def block_then_fail_first_fsync(directory: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                entered_fsync.set()
                if not release_fsync.wait(timeout=5):
                    raise TimeoutError("test did not release directory fsync")
                raise OSError("synthetic combined fsync failure")
            original_fsync(directory)

        monkeypatch.setattr(poses, "_fsync_directory", block_then_fail_first_fsync)
        service = BackupApplicationService(poses=poses, motions=motions, drafts=drafts)
        preview = await service.preview_import(envelope.to_bytes())
        restore = asyncio.create_task(
            service.restore_bundle(
                envelope.to_bytes(),
                expected_bundle_sha256=preview.bundle_sha256,
                confirmation="RESTORE",
            )
        )
        assert await asyncio.to_thread(entered_fsync.wait, 5)
        restore.cancel()
        release_fsync.set()
        with pytest.raises(asyncio.CancelledError):
            await restore
        assert await poses.get(pose.id) is None

    asyncio.run(scenario())


def test_restore_reenters_shared_maintenance_gate_without_child_task_deadlock(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        gate = RepositoryMaintenanceGate()
        clock = FakeClock()
        root = tmp_path / "destination"
        poses = FilePoseRepository(root / "poses", clock, maintenance_gate=gate)
        motions = FileMotionRepository(root / "motions", clock, maintenance_gate=gate)
        drafts = FileMotionDraftRepository(root / "drafts", clock, maintenance_gate=gate)
        pose = Pose(name="Shared maintenance gate", snapshot=make_snapshot())
        envelope = BackupEnvelope.build(
            [
                BackupDocument.from_payload(
                    kind=BackupEntityKind.POSE,
                    payload=cast(MigrationPayload, pose.model_dump(mode="json")),
                )
            ]
        )
        service = BackupApplicationService(
            poses=poses,
            motions=motions,
            drafts=drafts,
            maintenance_lock=gate,
        )
        preview = await service.preview_import(envelope.to_bytes())
        await asyncio.wait_for(
            service.restore_bundle(
                envelope.to_bytes(),
                expected_bundle_sha256=preview.bundle_sha256,
                confirmation="RESTORE",
            ),
            timeout=1,
        )
        assert await poses.get(pose.id) == pose

    asyncio.run(scenario())


def test_repeated_cancellation_during_calibration_import_commits_whole_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        pose = Pose(name="Cross-type commit", snapshot=make_snapshot())
        calibration = make_calibration()
        envelope = BackupEnvelope.build(
            [
                BackupDocument.from_payload(
                    kind=BackupEntityKind.POSE,
                    payload=cast(MigrationPayload, pose.model_dump(mode="json")),
                ),
                BackupDocument.from_payload(
                    kind=BackupEntityKind.CALIBRATION,
                    payload=cast(MigrationPayload, calibration.model_dump(mode="json")),
                ),
            ]
        )
        poses, motions, drafts = repositories(tmp_path / "destination")
        calibration_repository = FileCalibrationWorkflowRepository(
            tmp_path / "destination" / "calibrations"
        )
        entered_replace = threading.Event()
        release_replace = threading.Event()
        original_replace = calibration_repository._atomic_replace

        def blocking_replace(destination: Path, payload: bytes) -> None:
            entered_replace.set()
            if not release_replace.wait(timeout=5):
                raise TimeoutError("test did not release calibration replace")
            original_replace(destination, payload)

        monkeypatch.setattr(calibration_repository, "_atomic_replace", blocking_replace)
        clock = FakeClock()

        async def importer(values: tuple[CalibrationDocument, ...]) -> None:
            await commit_calibration_import(
                calibration_repository,
                values,
                created_at=clock.now(),
            )

        service = BackupApplicationService(
            poses=poses,
            motions=motions,
            drafts=drafts,
            calibrations=calibration_repository,
            calibration_importer=importer,
        )
        preview = await service.preview_import(
            envelope.to_bytes(),
            allow_calibration=True,
        )
        restore = asyncio.create_task(
            service.restore_bundle(
                envelope.to_bytes(),
                expected_bundle_sha256=preview.bundle_sha256,
                confirmation="RESTORE",
                allow_calibration=True,
            )
        )
        assert await asyncio.to_thread(entered_replace.wait, 5)
        restore.cancel()
        await asyncio.sleep(0)
        restore.cancel()
        await asyncio.sleep(0)
        assert not restore.done()
        release_replace.set()
        result = await restore
        assert result.restored_counts[BackupEntityKind.POSE] == 1
        assert result.restored_counts[BackupEntityKind.CALIBRATION] == 1
        assert await poses.get(pose.id) == pose
        assert calibration_repository.get_for_variant(RobotVariant.V2) == calibration

    asyncio.run(scenario())


def test_restore_failure_rolls_back_documents_created_earlier_in_the_batch(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        source_poses, source_motions, source_drafts = repositories(tmp_path / "source")
        await source_motions.save(make_motion())
        await source_poses.save(Pose(name="Fails later", snapshot=make_snapshot()))
        source = BackupApplicationService(
            poses=source_poses,
            motions=source_motions,
            drafts=source_drafts,
        )
        envelope = await source.export_bundle()

        clock = FakeClock()
        destination_poses = FailingPoseRepository(
            FilePoseRepository(tmp_path / "destination" / "poses", clock)
        )
        destination_motions = FileMotionRepository(tmp_path / "destination" / "motions", clock)
        destination_drafts = FileMotionDraftRepository(tmp_path / "destination" / "drafts", clock)
        destination = BackupApplicationService(
            poses=destination_poses,
            motions=destination_motions,
            drafts=destination_drafts,
        )
        preview = await destination.preview_import(envelope.to_bytes())
        assert preview.valid is True
        with pytest.raises(BackupRestoreError, match="rolled back"):
            await destination.restore_bundle(
                envelope.to_bytes(),
                expected_bundle_sha256=preview.bundle_sha256,
                confirmation="RESTORE",
            )
        assert await destination_motions.list() == ()
        assert await destination_poses.list() == ()

    asyncio.run(scenario())


def test_restore_rollback_never_deletes_a_concurrent_edit(tmp_path: Path) -> None:
    async def scenario() -> None:
        source_poses, source_motions, source_drafts = repositories(tmp_path / "source")
        motion = make_motion()
        await source_motions.save(motion)
        await source_poses.save(Pose(name="Fails after concurrent edit", snapshot=make_snapshot()))
        envelope = await BackupApplicationService(
            poses=source_poses,
            motions=source_motions,
            drafts=source_drafts,
        ).export_bundle()

        clock = FakeClock()
        destination_motions = FileMotionRepository(tmp_path / "destination" / "motions", clock)
        destination_drafts = FileMotionDraftRepository(
            tmp_path / "destination" / "drafts",
            clock,
        )

        async def edit_created_motion() -> None:
            created = await destination_motions.get(motion.id)
            assert created is not None
            edited = created.model_copy(update={"name": "Concurrent operator edit", "revision": 2})
            await destination_motions.save(edited, expected_revision=1)

        destination_poses = FailingPoseRepository(
            FilePoseRepository(tmp_path / "destination" / "poses", clock),
            edit_created_motion,
        )
        destination = BackupApplicationService(
            poses=destination_poses,
            motions=destination_motions,
            drafts=destination_drafts,
        )
        preview = await destination.preview_import(envelope.to_bytes())
        with pytest.raises(BackupRollbackError, match="rollback could not be completed"):
            await destination.restore_bundle(
                envelope.to_bytes(),
                expected_bundle_sha256=preview.bundle_sha256,
                confirmation="RESTORE",
            )
        preserved = await destination_motions.get(motion.id)
        assert preserved is not None
        assert preserved.name == "Concurrent operator edit"
        assert preserved.revision == 2

    asyncio.run(scenario())


def test_schema_migration_must_be_explicit_and_preserve_identity_and_revision(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        pose = Pose(name="Migrated", snapshot=make_snapshot())
        payload = pose.model_dump(mode="json")
        payload["schema_version"] = "1.9.0"
        document = BackupDocument.from_payload(
            kind=BackupEntityKind.POSE,
            payload=cast(MigrationPayload, payload),
        )
        envelope = BackupEnvelope.build([document])

        poses, motions, drafts = repositories(tmp_path / "destination")
        without_migration = BackupApplicationService(
            poses=poses,
            motions=motions,
            drafts=drafts,
        )
        rejected = await without_migration.preview_import(envelope.to_bytes())
        assert rejected.valid is False
        assert rejected.items[0].action is BackupImportAction.INVALID

        registry = BackupMigrationRegistry()

        def migrate_pose(value: MigrationPayload) -> MigrationPayload:
            return {**value, "schema_version": POSE_SCHEMA_VERSION}

        registry.register(
            kind=BackupEntityKind.POSE,
            source_version="1.9.0",
            destination_version=POSE_SCHEMA_VERSION,
            migrate=migrate_pose,
        )
        service = BackupApplicationService(
            poses=poses,
            motions=motions,
            drafts=drafts,
            migrations=registry,
        )
        preview = await service.preview_import(envelope.to_bytes())
        assert preview.valid is True
        assert preview.items[0].migrated_from == "1.9.0"
        await service.restore_bundle(
            envelope.to_bytes(),
            expected_bundle_sha256=preview.bundle_sha256,
            confirmation="RESTORE",
        )
        assert await poses.get(pose.id) == pose

    asyncio.run(scenario())


def test_device_local_data_is_rejected_and_calibration_requires_explicit_opt_in(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        poses, motions, drafts = repositories(tmp_path / "source")
        snapshot_data = make_snapshot().model_dump(mode="python")
        snapshot_data["hardware_snapshot"] = {"serial_port": "/dev/cu.usbserial-SECRET"}
        unsafe_pose = Pose(
            name="Unsafe",
            snapshot=PoseSnapshot.model_validate(snapshot_data),
        )
        await poses.save(unsafe_pose)
        unsafe_service = BackupApplicationService(poses=poses, motions=motions, drafts=drafts)
        with pytest.raises(BackupUnsafeContentError):
            await unsafe_service.export_bundle()

        secret_snapshot = make_snapshot().model_dump(mode="python")
        secret_snapshot["hardware_snapshot"] = {
            "nested": {
                "refresh_token": "credential-must-not-export",
                "oauth_token": "also-must-not-export",
                "api_key": "api-key-must-not-export",
                "access_key": "access-key-must-not-export",
                "private_key": "private-key-must-not-export",
            }
        }
        secret_pose = Pose(
            name="Nested secret",
            snapshot=PoseSnapshot.model_validate(secret_snapshot),
        )
        secret_poses, secret_motions, secret_drafts = repositories(tmp_path / "secret")
        await secret_poses.save(secret_pose)
        with pytest.raises(BackupUnsafeContentError):
            await BackupApplicationService(
                poses=secret_poses,
                motions=secret_motions,
                drafts=secret_drafts,
            ).export_bundle()

        for index, unsafe_value in enumerate(
            (
                "camera source /srv/camera/live",
                "failure path:/srv/momo/secret.db",
                r"stored at C:\Operators\MOMO\secret.json",
                "token=super-secret-long-lived-value-1234567890",
                "token='abcdefghijklmnopabcdefghijklmnop'",
                'token="abcdefghijklmnopabcdefghijklmnop"',
                '{"token":"abcdefghijklmnopabcdefghijklmnop"}',
                "api_key: 'abcdefghijklmnopabcdefghijklmnop'",
                "password=`abcdefghijklmnopabcdefghijklmnop`",
                "client_secret=abcdefghijklmnopabcdefghijklmnop",
                "db.password=abcdefghijklmnopabcdefghijklmnop",
                "github-token=abcdefghijklmnopabcdefghijklmnop",
                "oauth_access_token=abcdefghijklmnopabcdefghijklmnop",
                "clientSecret=abcdefghijklmnopabcdefghijklmnop",
                "Authorization: Basic YWJjZGVmZ2hpamtsbW5vcA==",
            )
        ):
            embedded_snapshot = make_snapshot().model_dump(mode="python")
            embedded_snapshot["hardware_snapshot"] = {
                "diagnostic_note": unsafe_value,
            }
            embedded_pose = Pose(
                name=f"Embedded unsafe value {index}",
                snapshot=PoseSnapshot.model_validate(embedded_snapshot),
            )
            embedded_poses, embedded_motions, embedded_drafts = repositories(
                tmp_path / f"embedded-{index}"
            )
            await embedded_poses.save(embedded_pose)
            with pytest.raises(BackupUnsafeContentError):
                await BackupApplicationService(
                    poses=embedded_poses,
                    motions=embedded_motions,
                    drafts=embedded_drafts,
                ).export_bundle()

        clean_poses, clean_motions, clean_drafts = repositories(tmp_path / "clean")
        calibration = make_calibration()
        source = BackupApplicationService(
            poses=clean_poses,
            motions=clean_motions,
            drafts=clean_drafts,
            calibrations=MemoryCalibrationRepository(calibration),
        )
        default_export = await source.export_bundle()
        assert default_export.manifest.calibration_included is False
        explicit_export = await source.export_bundle(include_calibration=True)
        assert explicit_export.manifest.calibration_included is True

        restored_calibrations: list[CalibrationDocument] = []

        async def import_calibrations(values: tuple[CalibrationDocument, ...]) -> None:
            restored_calibrations.extend(values)

        destination = backup_service(
            tmp_path / "calibration-destination",
            calibration_importer=import_calibrations,
        )
        denied = await destination.preview_import(explicit_export.to_bytes())
        assert denied.valid is False
        allowed = await destination.preview_import(
            explicit_export.to_bytes(),
            allow_calibration=True,
        )
        assert allowed.valid is True
        await destination.restore_bundle(
            explicit_export.to_bytes(),
            expected_bundle_sha256=allowed.bundle_sha256,
            confirmation="RESTORE",
            allow_calibration=True,
        )
        assert restored_calibrations == [calibration]

    asyncio.run(scenario())


def test_calibration_restore_rejects_duplicate_template_and_incomplete_documents(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async def importer(values: tuple[CalibrationDocument, ...]) -> None:
            pytest.fail(f"invalid calibration reached importer: {values!r}")

        destination = backup_service(
            tmp_path / "destination",
            calibration_importer=importer,
        )
        complete = make_calibration()
        duplicate = complete.model_copy(update={"id": uuid4()})
        duplicate_envelope = BackupEnvelope.build(
            [
                BackupDocument.from_payload(
                    kind=BackupEntityKind.CALIBRATION,
                    payload=cast(MigrationPayload, complete.model_dump(mode="json")),
                ),
                BackupDocument.from_payload(
                    kind=BackupEntityKind.CALIBRATION,
                    payload=cast(MigrationPayload, duplicate.model_dump(mode="json")),
                ),
            ]
        )
        duplicate_preview = await destination.preview_import(
            duplicate_envelope.to_bytes(),
            allow_calibration=True,
        )
        assert duplicate_preview.valid is False
        assert duplicate_preview.totals.invalid == 1

        incomplete_joint = complete.joints[0].model_copy(update={"home_present_raw": None})
        for invalid in (
            complete.model_copy(update={"template": True}),
            complete.model_copy(update={"id": uuid4(), "joints": [incomplete_joint]}),
        ):
            envelope = BackupEnvelope.build(
                [
                    BackupDocument.from_payload(
                        kind=BackupEntityKind.CALIBRATION,
                        payload=cast(MigrationPayload, invalid.model_dump(mode="json")),
                    )
                ]
            )
            preview = await destination.preview_import(
                envelope.to_bytes(),
                allow_calibration=True,
            )
            assert preview.valid is False
            assert preview.items[0].action is BackupImportAction.INVALID

    asyncio.run(scenario())


def test_backup_http_api_uses_raw_bounded_bytes_and_never_accepts_a_server_path(
    tmp_path: Path,
) -> None:
    poses, motions, drafts = repositories(tmp_path)
    service = BackupApplicationService(poses=poses, motions=motions, drafts=drafts)
    security = SecurityService(
        NetworkSecurityPolicy(),
        lan_token=None,
        monotonic=lambda: 0.0,
    )
    app = FastAPI()
    app.state.backup_service = service
    app.state.security_service = security
    install_error_handlers(app)
    app.include_router(backup_router, prefix="/api/v1")

    with TestClient(app) as client:
        exported = client.post("/api/v1/backup/export", json={"include_calibration": False})
        assert exported.status_code == 200
        assert exported.headers["content-type"].startswith(BACKUP_MEDIA_TYPE)
        digest = exported.headers["x-momo-backup-sha256"]
        assert len(digest) == 64

        preview = client.post(
            "/api/v1/backup/import/preview",
            content=exported.content,
            headers={"Content-Type": BACKUP_MEDIA_TYPE},
        )
        assert preview.status_code == 200
        assert preview.json()["bundle_sha256"] == digest
        assert "path" not in preview.json()

        rejected_media = client.post(
            "/api/v1/backup/import/preview",
            json={"server_path": "/tmp/backup.json"},
        )
        assert rejected_media.status_code == 415


def test_startup_recovers_durable_restore_intent_across_entities_and_calibration(
    tmp_path: Path,
) -> None:
    pose = Pose(name="Crash-pending", snapshot=make_snapshot())
    calibration = real_calibration(real_profile())
    pose_directory = tmp_path / "poses"
    real_calibration_directory = tmp_path / "real-calibration"
    journal_directory = tmp_path / "restore-journal"
    pose_repository = FilePoseRepository(pose_directory, FakeClock())
    calibration_repository = FileCalibrationWorkflowRepository(real_calibration_directory)
    journal = FileBackupRestoreJournal(journal_directory)
    transaction = BackupRestoreTransaction(
        bundle_sha256="a" * 64,
        entities=[
            BackupRestoreEntityTarget(
                kind=BackupEntityKind.POSE,
                id=pose.id,
                revision=pose.revision,
            )
        ],
        calibrations=[
            BackupRestoreCalibrationTarget(
                variant=calibration.robot_variant,
                id=calibration.id,
            )
        ],
    )

    async def seed_interrupted_transaction() -> None:
        await journal.begin(transaction)
        assert await journal.load() == transaction
        await pose_repository.import_exact(pose)
        calibration_repository.import_new_bundle(
            (calibration,),
            created_at=FakeClock().now(),
        )

    asyncio.run(seed_interrupted_transaction())
    assert (pose_directory / f"{pose.id}.json").is_file()
    assert (real_calibration_directory / "v2.current.json").is_file()

    settings = Settings(
        runtime_state_directory=str(tmp_path / "runtime"),
        calibration_directory=str(tmp_path / "dry-calibration"),
        real_calibration_directory=str(real_calibration_directory),
        pose_directory=str(pose_directory),
        motion_library_directory=str(tmp_path / "motions"),
        motion_draft_directory=str(tmp_path / "drafts"),
        backup_restore_journal_directory=str(journal_directory),
        audit_directory=str(tmp_path / "audit"),
        hardware_local_config_enabled=True,
    )
    app = create_app(settings=settings)
    device = app.state.device_diagnostics_service
    assert device.context.calibration is not None
    assert device.context.calibration.id == calibration.id
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200

    assert not (pose_directory / f"{pose.id}.json").exists()
    assert not (real_calibration_directory / "v2.current.json").exists()
    assert asyncio.run(journal.load()) is None
    assert device.context.calibration is None


def test_cancellation_during_journal_begin_aborts_without_restoring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        pose = Pose(name="Cancel WAL", snapshot=make_snapshot())
        envelope = BackupEnvelope.build(
            [
                BackupDocument.from_payload(
                    kind=BackupEntityKind.POSE,
                    payload=cast(MigrationPayload, pose.model_dump(mode="json")),
                )
            ]
        )
        poses, motions, drafts = repositories(tmp_path / "destination")
        journal = FileBackupRestoreJournal(tmp_path / "journal")
        service = BackupApplicationService(
            poses=poses,
            motions=motions,
            drafts=drafts,
            restore_journal=journal,
        )
        preview = await service.preview_import(envelope.to_bytes())
        started = threading.Event()
        release = threading.Event()
        original_begin = journal._begin_sync

        def blocking_begin(transaction: BackupRestoreTransaction) -> None:
            started.set()
            if not release.wait(timeout=2):
                raise TimeoutError("journal begin test was not released")
            original_begin(transaction)

        monkeypatch.setattr(journal, "_begin_sync", blocking_begin)
        restore = asyncio.create_task(
            service.restore_bundle(
                envelope.to_bytes(),
                expected_bundle_sha256=preview.bundle_sha256,
                confirmation="RESTORE",
            )
        )
        assert await asyncio.to_thread(started.wait, 2)
        restore.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await restore
        assert await poses.get(pose.id) is None
        assert await journal.load() is None

    asyncio.run(scenario())


def test_recovery_retries_directory_fsync_before_clearing_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        pose = Pose(name="Durable absence", snapshot=make_snapshot())
        poses, motions, drafts = repositories(tmp_path / "destination")
        journal = FileBackupRestoreJournal(tmp_path / "journal")
        transaction = BackupRestoreTransaction(
            bundle_sha256="b" * 64,
            entities=[
                BackupRestoreEntityTarget(
                    kind=BackupEntityKind.POSE,
                    id=pose.id,
                    revision=pose.revision,
                )
            ],
        )
        await journal.begin(transaction)
        await poses.import_exact(pose)
        service = BackupApplicationService(
            poses=poses,
            motions=motions,
            drafts=drafts,
            restore_journal=journal,
        )
        original_fsync = poses._fsync_directory
        fsync_calls = 0

        def fail_first_fsync(directory: Path) -> None:
            nonlocal fsync_calls
            fsync_calls += 1
            if fsync_calls == 1:
                raise OSError("synthetic directory fsync failure")
            original_fsync(directory)

        monkeypatch.setattr(poses, "_fsync_directory", fail_first_fsync)
        with pytest.raises(BackupRollbackError):
            await service.recover_pending_restore()
        assert await poses.get(pose.id) is None
        assert await journal.load() == transaction

        assert await service.recover_pending_restore() is True
        assert fsync_calls == 2
        assert await journal.load() is None

    asyncio.run(scenario())


def test_first_restore_durably_fsyncs_new_wal_and_target_parent_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        pose = Pose(name="Durable directories", snapshot=make_snapshot())
        calibration = make_calibration()
        pose_directory = tmp_path / "new" / "entities" / "poses"
        calibration_directory = tmp_path / "new" / "calibration"
        journal_directory = tmp_path / "new" / "transactions" / "restore"
        poses = FilePoseRepository(pose_directory, FakeClock())
        calibrations = FileCalibrationWorkflowRepository(calibration_directory)
        journal = FileBackupRestoreJournal(journal_directory)
        journal_fsyncs: list[Path] = []
        pose_fsyncs: list[Path] = []
        calibration_fsyncs: list[Path] = []
        original_journal_fsync = journal._fsync_directory
        original_pose_fsync = poses._fsync_directory
        original_calibration_fsync = calibrations._fsync_directory

        def journal_fsync(directory: Path) -> None:
            journal_fsyncs.append(directory)
            original_journal_fsync(directory)

        def pose_fsync(directory: Path) -> None:
            pose_fsyncs.append(directory)
            original_pose_fsync(directory)

        def calibration_fsync(directory: Path) -> None:
            calibration_fsyncs.append(directory)
            original_calibration_fsync(directory)

        monkeypatch.setattr(journal, "_fsync_directory", journal_fsync)
        monkeypatch.setattr(poses, "_fsync_directory", pose_fsync)
        monkeypatch.setattr(calibrations, "_fsync_directory", calibration_fsync)
        transaction = BackupRestoreTransaction(
            bundle_sha256="c" * 64,
            entities=[
                BackupRestoreEntityTarget(
                    kind=BackupEntityKind.POSE,
                    id=pose.id,
                    revision=pose.revision,
                )
            ],
            calibrations=[
                BackupRestoreCalibrationTarget(
                    variant=calibration.robot_variant,
                    id=calibration.id,
                )
            ],
        )
        await journal.begin(transaction)
        await poses.import_exact(pose)
        calibrations.import_new_bundle(
            (calibration,),
            created_at=FakeClock().now(),
        )

        assert journal_directory in journal_fsyncs
        assert journal_directory.parent in journal_fsyncs
        assert pose_directory in pose_fsyncs
        assert pose_directory.parent in pose_fsyncs
        assert calibration_directory in calibration_fsyncs
        assert calibration_directory.parent in calibration_fsyncs

    asyncio.run(scenario())


def test_wal_unlink_fsync_failure_is_commit_uncertain_and_never_partially_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        first = Pose(name="Commit one", snapshot=make_snapshot())
        second = Pose(name="Commit two", snapshot=make_snapshot())
        envelope = BackupEnvelope.build(
            [
                BackupDocument.from_payload(
                    kind=BackupEntityKind.POSE,
                    payload=cast(MigrationPayload, item.model_dump(mode="json")),
                )
                for item in (first, second)
            ]
        )
        poses, motions, drafts = repositories(tmp_path / "destination")
        journal = FileBackupRestoreJournal(tmp_path / "journal")
        journal._ensure_directory()
        service = BackupApplicationService(
            poses=poses,
            motions=motions,
            drafts=drafts,
            restore_journal=journal,
        )
        preview = await service.preview_import(envelope.to_bytes())
        original_fsync = journal._fsync_directory
        journal_directory_fsyncs = 0

        def fail_commit_marker_fsync(directory: Path) -> None:
            nonlocal journal_directory_fsyncs
            if directory == journal.directory:
                journal_directory_fsyncs += 1
                if journal_directory_fsyncs == 2:
                    raise OSError("synthetic WAL commit-marker fsync failure")
            original_fsync(directory)

        monkeypatch.setattr(journal, "_fsync_directory", fail_commit_marker_fsync)
        with pytest.raises(BackupCommitUncertainError):
            await service.restore_bundle(
                envelope.to_bytes(),
                expected_bundle_sha256=preview.bundle_sha256,
                confirmation="RESTORE",
            )

        assert journal_directory_fsyncs == 2
        assert await poses.get(first.id) == first
        assert await poses.get(second.id) == second
        assert await journal.load() is None

    asyncio.run(scenario())


def test_wal_unlink_fsync_failure_after_rollback_never_claims_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        source_poses, source_motions, source_drafts = repositories(tmp_path / "source")
        motion = make_motion()
        await source_motions.save(motion)
        await source_poses.save(Pose(name="Fails after Motion", snapshot=make_snapshot()))
        envelope = await BackupApplicationService(
            poses=source_poses,
            motions=source_motions,
            drafts=source_drafts,
        ).export_bundle()

        clock = FakeClock()
        poses = FailingPoseRepository(FilePoseRepository(tmp_path / "target" / "poses", clock))
        motions = FileMotionRepository(tmp_path / "target" / "motions", clock)
        drafts = FileMotionDraftRepository(tmp_path / "target" / "drafts", clock)
        journal = FileBackupRestoreJournal(tmp_path / "journal")
        journal._ensure_directory()
        service = BackupApplicationService(
            poses=poses,
            motions=motions,
            drafts=drafts,
            restore_journal=journal,
        )
        preview = await service.preview_import(envelope.to_bytes())
        original_fsync = journal._fsync_directory
        journal_directory_fsyncs = 0

        def fail_rollback_marker_fsync(directory: Path) -> None:
            nonlocal journal_directory_fsyncs
            if directory == journal.directory:
                journal_directory_fsyncs += 1
                if journal_directory_fsyncs == 2:
                    raise OSError("synthetic rollback-marker fsync failure")
            original_fsync(directory)

        monkeypatch.setattr(journal, "_fsync_directory", fail_rollback_marker_fsync)
        with pytest.raises(
            BackupRollbackError,
            match="Failed restore data was removed",
        ):
            await service.restore_bundle(
                envelope.to_bytes(),
                expected_bundle_sha256=preview.bundle_sha256,
                confirmation="RESTORE",
            )

        assert await motions.get(motion.id) is None
        assert await journal.load() is None

    asyncio.run(scenario())
