"""Studio draft persistence, coherent capture, validation, compilation, and save workflows."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from pydantic import ValidationError

from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.library_service import (
    LibraryApplicationService,
    TrustedLegacySnapshotDigests,
)
from momo.application.services.motion_service import MotionApplicationService
from momo.application.services.robot_service import RobotApplicationService
from momo.application.services.studio_formal_save_coordinator import (
    DraftSaveResult,
    StudioFormalSaveCoordinator,
    draft_from_data,
    revision_conflict_with_entity,
    trusted_legacy_snapshot_digests,
)
from momo.application.services.studio_robot_actions import StudioRobotActions
from momo.application.services.trajectory_compiler import TrajectoryCompiler
from momo.application.studio_commands import (
    MotionDraftAbandonSaveIntentCommand,
    MotionDraftAutosaveCommand,
    MotionDraftCompileCommand,
    MotionDraftCreateCommand,
    MotionDraftGotoCommand,
    MotionDraftRevisionCommand,
    MotionDraftSaveAsCommand,
    MotionDraftSaveCommand,
)
from momo.domain.enums import MotionCommandSource, RealReadiness
from momo.domain.errors import (
    EntityInvalidError,
    EntityNotFoundError,
    PoseIncompatibleError,
    RevisionConflictError,
)
from momo.domain.motion import LegacyImportMetadata, Motion, MotionKeyframe
from momo.domain.motion_draft import MotionDraft, legacy_snapshot_sha256
from momo.domain.motion_preflight import MotionAccepted
from momo.domain.pose import PoseSnapshot
from momo.domain.trajectory import TrajectoryCompileOutcome
from momo.ports.clock import Clock
from momo.ports.motion_draft_repository import MotionDraftRepository


@dataclass(frozen=True, slots=True)
class DraftValidationIssue:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class DraftValidationResult:
    draft: MotionDraft
    issues: tuple[DraftValidationIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


@dataclass(frozen=True, slots=True)
class DraftCompileResult:
    draft: MotionDraft
    candidate: Motion
    outcome: TrajectoryCompileOutcome


class StudioApplicationService:
    """Own draft state without admitting drafts to a motion executor or playback cache."""

    def __init__(
        self,
        drafts: MotionDraftRepository,
        library: LibraryApplicationService,
        robot: RobotApplicationService,
        kinematics: KinematicsService,
        compiler: TrajectoryCompiler,
        motion: MotionApplicationService,
        clock: Clock,
    ) -> None:
        self.drafts = drafts
        self.library = library
        self.robot = robot
        self.kinematics = kinematics
        self.compiler = compiler
        self.clock = clock
        self._mutation_lock = asyncio.Lock()
        self._compile_lock = asyncio.Lock()
        self._formal_save = StudioFormalSaveCoordinator(
            drafts,
            library,
            clock,
            self._compile,
            self._require_draft_unchanged,
        )
        self._robot_actions = StudioRobotActions(
            robot,
            kinematics,
            motion,
            clock,
        )

    async def list_drafts(self, *, page: int, page_size: int) -> tuple[list[MotionDraft], int]:
        async with self._mutation_lock:
            drafts = [
                await self._formal_save.recover_save_intent(item)
                for item in await self.drafts.list()
            ]
            drafts.sort(
                key=lambda item: (item.updated_at, str(item.id)),
                reverse=True,
            )
        total = len(drafts)
        start = (page - 1) * page_size
        return drafts[start : start + page_size], total

    async def get_draft(self, draft_id: UUID) -> MotionDraft:
        async with self._mutation_lock:
            return await self._formal_save.recover_save_intent(await self._get_draft(draft_id))

    async def _get_draft(self, draft_id: UUID) -> MotionDraft:
        draft = await self.drafts.get(draft_id)
        if draft is None:
            raise EntityNotFoundError("Motion draft was not found")
        return draft

    async def create_draft(self, request: MotionDraftCreateCommand) -> MotionDraft:
        trusted_legacy_snapshot_sha256 = await self._trusted_library_legacy_snapshots(
            request.keyframes,
            inherited=frozenset(),
        )
        await self._validate_client_keyframes(
            request.keyframes,
            trusted_legacy_snapshot_sha256=trusted_legacy_snapshot_sha256,
        )
        now = self.clock.now()
        draft = draft_from_data(
            {
                "name": request.name,
                "description": request.description,
                "robot_variant": request.robot_variant,
                "keyframes": request.keyframes,
                "playback_defaults": request.playback_defaults,
                "tags": request.tags,
                "trusted_legacy_snapshot_sha256": sorted(trusted_legacy_snapshot_sha256),
                "editor_metadata": request.editor_metadata,
                "created_at": now,
                "updated_at": now,
            }
        )
        async with self._mutation_lock:
            await self._formal_save.save_draft_entity(draft)
        return draft

    async def open_motion(self, motion_id: UUID, *, expected_revision: int) -> MotionDraft:
        async with self._mutation_lock:
            motion = await self._get_motion(motion_id)
            self._require_revision(motion.revision, expected_revision, entity="Motion")
            now = self.clock.now()
            draft = draft_from_data(
                {
                    "source_motion_id": motion.id,
                    "source_motion_revision": motion.revision,
                    "name": motion.name,
                    "description": motion.description,
                    "robot_variant": motion.robot_variant,
                    "keyframes": [
                        MotionKeyframe.model_validate(item.model_dump(mode="python"))
                        for item in motion.keyframes
                    ],
                    "playback_defaults": motion.playback_defaults,
                    "tags": list(motion.tags),
                    "source_metadata": motion.source_metadata,
                    "trusted_legacy_snapshot_sha256": sorted(
                        {
                            legacy_snapshot_sha256(item.pose_snapshot)
                            for item in motion.keyframes
                            if item.pose_snapshot.state_sequence is None
                        }
                    ),
                    "created_at": now,
                    "updated_at": now,
                }
            )
            await self._formal_save.save_draft_entity(draft)
            return draft

    async def autosave_draft(
        self,
        draft_id: UUID,
        request: MotionDraftAutosaveCommand,
    ) -> MotionDraft:
        async with self._mutation_lock:
            current = await self._formal_save.recover_save_intent(await self._get_draft(draft_id))
            self._require_revision(
                current.revision, request.expected_revision, entity="MotionDraft"
            )
            trusted_legacy_snapshot_sha256 = await self._trusted_library_legacy_snapshots(
                request.keyframes,
                inherited=trusted_legacy_snapshot_digests(current),
            )
            await self._validate_client_keyframes(
                request.keyframes,
                trusted_legacy_snapshot_sha256=trusted_legacy_snapshot_sha256,
            )
            updated = draft_from_data(
                {
                    "id": current.id,
                    "source_motion_id": current.source_motion_id,
                    "source_motion_revision": current.source_motion_revision,
                    "name": request.name,
                    "description": request.description,
                    "robot_variant": request.robot_variant,
                    "keyframes": request.keyframes,
                    "playback_defaults": request.playback_defaults,
                    "tags": request.tags,
                    "source_metadata": current.source_metadata,
                    "trusted_legacy_snapshot_sha256": sorted(trusted_legacy_snapshot_sha256),
                    "editor_metadata": request.editor_metadata,
                    "revision": current.revision + 1,
                    "created_at": current.created_at,
                    "updated_at": self.clock.now(),
                }
            )
            await self._formal_save.save_draft_entity(
                updated,
                expected_revision=request.expected_revision,
            )
            return updated

    async def fork_draft(
        self,
        draft_id: UUID,
        request: MotionDraftRevisionCommand,
    ) -> MotionDraft:
        """Clone authoritative state so local conflict content can be PUT safely afterward."""

        async with self._mutation_lock:
            current = await self._formal_save.recover_save_intent(await self._get_draft(draft_id))
            self._require_revision(
                current.revision,
                request.expected_revision,
                entity="MotionDraft",
            )
            now = self.clock.now()
            fork_data = current.model_dump(mode="python")
            fork_data.update(
                id=uuid4(),
                save_intent=None,
                revision=1,
                created_at=now,
                updated_at=now,
            )
            fork = draft_from_data(fork_data)
            await self._formal_save.save_draft_entity(fork)
            return fork

    async def delete_draft(self, draft_id: UUID, *, expected_revision: int) -> None:
        async with self._mutation_lock:
            current = await self._formal_save.recover_save_intent(await self._get_draft(draft_id))
            self._require_revision(current.revision, expected_revision, entity="MotionDraft")
            try:
                deleted = await self.drafts.delete(
                    draft_id,
                    expected_revision=expected_revision,
                )
            except RevisionConflictError as error:
                raise revision_conflict_with_entity(error, "MotionDraft") from error
            if not deleted:
                raise EntityNotFoundError("Motion draft was not found")

    async def abandon_save_intent(
        self,
        draft_id: UUID,
        request: MotionDraftAbandonSaveIntentCommand,
    ) -> MotionDraft:
        """Clear exactly one unresolved marker after an explicit operator acknowledgement."""

        async with self._mutation_lock:
            return await self._formal_save.abandon_save_intent(
                draft_id,
                expected_revision=request.expected_revision,
                operation_id=request.operation_id,
            )

    async def validate_draft(
        self, draft_id: UUID, *, expected_revision: int
    ) -> DraftValidationResult:
        draft = await self.get_draft(draft_id)
        self._require_revision(draft.revision, expected_revision, entity="MotionDraft")
        issues = self._conversion_issues(draft)
        if not issues:
            try:
                self._motion_from_draft(
                    draft,
                    motion_id=draft.id,
                    revision=draft.revision,
                    created_at=draft.created_at,
                    source_metadata=draft.source_metadata,
                )
            except EntityInvalidError:
                issues = (
                    DraftValidationIssue(
                        code="DRAFT_MOTION_INVALID",
                        message="Draft values do not satisfy formal Motion invariants",
                    ),
                )
        return DraftValidationResult(draft=draft, issues=issues)

    async def compile_draft(
        self,
        draft_id: UUID,
        request: MotionDraftCompileCommand,
    ) -> DraftCompileResult:
        draft = await self.get_draft(draft_id)
        async with self._compile_lock:
            current = await self._get_draft(draft_id)
            self._require_revision(current.revision, draft.revision, entity="MotionDraft")
            self._require_revision(draft.revision, request.expected_revision, entity="MotionDraft")
            self._require_convertible(draft)
            candidate = self._motion_from_draft(
                draft,
                motion_id=draft.id,
                revision=draft.revision,
                created_at=draft.created_at,
                source_metadata=draft.source_metadata,
            )
            outcome = await self._compile(candidate, sample_rate_hz=request.sample_rate_hz)
            await self._require_draft_unchanged(draft)
            return DraftCompileResult(draft=draft, candidate=candidate, outcome=outcome)

    async def save_draft(
        self,
        draft_id: UUID,
        request: MotionDraftSaveCommand,
    ) -> DraftSaveResult:
        async with self._mutation_lock, self._compile_lock:
            draft = await self._formal_save.recover_save_intent(await self._get_draft(draft_id))
            self._require_revision(draft.revision, request.expected_revision, entity="MotionDraft")
            self._require_convertible(draft)
            if draft.source_motion_id is None:
                if request.expected_source_revision is not None:
                    raise EntityInvalidError(
                        "A new draft cannot declare an expected source revision",
                        details={"reason": "UNEXPECTED_SOURCE_REVISION"},
                    )
                candidate = self._motion_from_draft(
                    draft,
                    motion_id=uuid4(),
                    revision=1,
                    created_at=self.clock.now(),
                    source_metadata=draft.source_metadata,
                )
                persisted_expected_revision: int | None = None
            else:
                if request.expected_source_revision is None:
                    raise EntityInvalidError(
                        "Saving an opened Motion requires expected_source_revision",
                        details={"reason": "EXPECTED_SOURCE_REVISION_REQUIRED"},
                    )
                if request.expected_source_revision != draft.source_motion_revision:
                    raise RevisionConflictError(
                        "Draft source Motion revision changed",
                        details={
                            "entity": "Motion",
                            "expected_revision": request.expected_source_revision,
                            "actual_revision": draft.source_motion_revision,
                        },
                    )
                source = await self._get_motion(draft.source_motion_id)
                self._require_revision(
                    source.revision,
                    request.expected_source_revision,
                    entity="Motion",
                )
                candidate = self._motion_from_draft(
                    draft,
                    motion_id=source.id,
                    revision=source.revision + 1,
                    created_at=source.created_at,
                    source_metadata=draft.source_metadata,
                )
                persisted_expected_revision = source.revision
            return await self._formal_save.compile_persist_and_rebind(
                draft,
                candidate,
                expected_motion_revision=persisted_expected_revision,
                sample_rate_hz=request.sample_rate_hz,
                save_kind="SAVE",
            )

    async def save_draft_as(
        self,
        draft_id: UUID,
        request: MotionDraftSaveAsCommand,
    ) -> DraftSaveResult:
        async with self._mutation_lock, self._compile_lock:
            draft = await self._formal_save.recover_save_intent(await self._get_draft(draft_id))
            self._require_revision(draft.revision, request.expected_revision, entity="MotionDraft")
            self._require_convertible(draft)
            data = draft.model_dump(mode="python")
            if request.name is not None:
                data["name"] = request.name
            candidate_draft = draft_from_data(data)
            candidate = self._motion_from_draft(
                candidate_draft,
                motion_id=uuid4(),
                revision=1,
                created_at=self.clock.now(),
                source_metadata=candidate_draft.source_metadata,
            )
            return await self._formal_save.compile_persist_and_rebind(
                draft,
                candidate,
                expected_motion_revision=None,
                sample_rate_hz=request.sample_rate_hz,
                save_kind="SAVE_AS",
            )

    async def capture_snapshot(self) -> PoseSnapshot:
        return await self._robot_actions.capture_snapshot()

    async def goto_keyframe(
        self,
        draft_id: UUID,
        keyframe_id: UUID,
        request: MotionDraftGotoCommand,
    ) -> MotionAccepted:
        async with self._mutation_lock:
            draft = await self._formal_save.recover_save_intent(await self._get_draft(draft_id))
            return await self._robot_actions.goto_keyframe(draft, keyframe_id, request)

    async def _compile(self, motion: Motion, *, sample_rate_hz: float) -> TrajectoryCompileOutcome:
        status, profile, start_state = await self.robot.get_motion_snapshot()
        model = self.kinematics.model_for(profile)
        calibration = self.robot.calibration_service.get_for_variant(profile.variant)
        return await self.compiler.compile(
            motion=motion,
            profile=profile,
            start_state=start_state,
            start_state_sequence=status.state_sequence,
            expected_motion_revision=motion.revision,
            expected_robot_variant=status.variant,
            expected_profile_fingerprint=status.profile_fingerprint,
            expected_kinematics_fingerprint=model.fingerprint,
            expected_state_sequence=status.state_sequence,
            connected=status.connected,
            state_fresh=not status.stale,
            hardware_access_policy=status.hardware_access_policy,
            sample_rate_hz=sample_rate_hz,
            calibration=calibration,
            control_mode=status.control_mode,
            stop_capable=True,
            source=MotionCommandSource.STUDIO,
            real_readiness=RealReadiness.BLOCKED_BY_STAGE_POLICY,
            field_acceptance_complete=False,
        )

    async def _require_draft_unchanged(self, draft: MotionDraft) -> None:
        current = await self._get_draft(draft.id)
        self._require_revision(current.revision, draft.revision, entity="MotionDraft")

    async def _get_motion(self, motion_id: UUID) -> Motion:
        return await self.library.get_motion(motion_id)

    @staticmethod
    def _conversion_issues(draft: MotionDraft) -> tuple[DraftValidationIssue, ...]:
        if len(draft.keyframes) < 2:
            return (
                DraftValidationIssue(
                    code="DRAFT_REQUIRES_TWO_KEYFRAMES",
                    message="A formal Motion requires at least two keyframes",
                ),
            )
        return ()

    def _require_convertible(self, draft: MotionDraft) -> None:
        issues = self._conversion_issues(draft)
        if issues:
            raise EntityInvalidError(
                "Motion draft cannot be converted to a formal Motion",
                details={"issues": [item.code for item in issues]},
            )

    def _motion_from_draft(
        self,
        draft: MotionDraft,
        *,
        motion_id: UUID,
        revision: int,
        created_at: object,
        source_metadata: LegacyImportMetadata | None,
    ) -> Motion:
        try:
            return Motion.model_validate(
                {
                    "id": motion_id,
                    "name": draft.name,
                    "description": draft.description,
                    "robot_variant": draft.robot_variant,
                    "keyframes": [item.model_dump(mode="python") for item in draft.keyframes],
                    "playback_defaults": draft.playback_defaults,
                    "tags": list(draft.tags),
                    "source_metadata": source_metadata,
                    "created_at": created_at,
                    "updated_at": self.clock.now(),
                    "revision": revision,
                }
            )
        except ValidationError as error:
            raise EntityInvalidError(
                "Motion draft violates formal Motion invariants",
                details={"entity": "motion_draft"},
            ) from error

    async def _validate_client_keyframes(
        self,
        keyframes: Sequence[MotionKeyframe],
        *,
        trusted_legacy_snapshot_sha256: TrustedLegacySnapshotDigests,
    ) -> None:
        for keyframe in keyframes:
            snapshot = keyframe.pose_snapshot
            checks: list[str] = []
            if snapshot.hardware_snapshot is not None:
                checks.append("hardware_snapshot_must_be_null")
            if snapshot.calibration_fingerprint is not None:
                checks.append("calibration_fingerprint_must_be_null")
            profile = self.robot.profile_service.get_profile(snapshot.robot_variant)
            model = self.kinematics.model_for(profile)
            trusted_null_sequence = (
                snapshot.state_sequence is None
                and legacy_snapshot_sha256(snapshot) in trusted_legacy_snapshot_sha256
            )
            if snapshot.state_sequence is None and not trusted_null_sequence:
                checks.append("state_sequence")
            if snapshot.profile_fingerprint != profile.fingerprint:
                checks.append("profile_fingerprint")
            if snapshot.kinematics_fingerprint != model.fingerprint:
                checks.append("kinematics_fingerprint")
            joint_state_valid = True
            try:
                snapshot.validate_against(profile)
            except ValueError:
                checks.append("joint_state")
                joint_state_valid = False
            if (snapshot.state_sequence is not None or trusted_null_sequence) and joint_state_valid:
                forward = await self.kinematics.forward(
                    profile,
                    snapshot.joint_state,
                    state_sequence=(
                        snapshot.state_sequence if snapshot.state_sequence is not None else 0
                    ),
                    robot_id="studio-validation",
                )
                if snapshot.tcp_pose != forward.tcp_pose:
                    checks.append("tcp_pose")
            if checks:
                raise PoseIncompatibleError(
                    "Draft snapshot is incompatible with its declared robot contract",
                    details={"checks": sorted(set(checks))},
                )

    async def _trusted_library_legacy_snapshots(
        self,
        keyframes: Sequence[MotionKeyframe],
        *,
        inherited: TrustedLegacySnapshotDigests,
    ) -> TrustedLegacySnapshotDigests:
        """Trust exact null-sequence snapshots already owned by the Legacy Pose library.

        A client cannot extend the registry directly. Recognition requires the keyframe's
        provenance UUID to resolve to a server-side Pose tagged by the reviewed importer,
        and the embedded immutable snapshot must remain byte-semantically identical.
        Runtime contract, joint, fingerprint, and recomputed-TCP checks still run below.
        """

        trusted = set(inherited)
        for keyframe in keyframes:
            snapshot = keyframe.pose_snapshot
            if snapshot.state_sequence is not None:
                continue
            digest = legacy_snapshot_sha256(snapshot)
            if digest in trusted or keyframe.source_pose_id is None:
                continue
            try:
                source_pose = await self.library.get_pose(keyframe.source_pose_id)
            except EntityNotFoundError:
                continue
            if "legacy-import" not in source_pose.tags or source_pose.snapshot != snapshot:
                continue
            trusted.add(digest)
        return frozenset(trusted)

    @staticmethod
    def _require_revision(
        actual: int,
        expected: int,
        *,
        entity: Literal["MotionDraft", "Motion"],
    ) -> None:
        if actual != expected:
            raise RevisionConflictError(
                f"{entity} revision changed",
                details={
                    "entity": entity,
                    "expected_revision": expected,
                    "actual_revision": actual,
                },
            )
