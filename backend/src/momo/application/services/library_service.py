"""Pose/Motion persistence, capture, compatibility, and Goto orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError

from momo.application.library_commands import (
    DuplicateEntityCommand,
    GotoPoseCommand,
    MotionCreateCommand,
    MotionPatchCommand,
    PoseCaptureCommand,
    PoseCreateCommand,
    PosePatchCommand,
)
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.motion_service import MotionApplicationService
from momo.application.services.robot_service import RobotApplicationService
from momo.domain.enums import MotionCommandSource, MotionCommandType
from momo.domain.errors import (
    CaptureStateChangedError,
    EntityInvalidError,
    EntityNotFoundError,
    PoseIncompatibleError,
    RevisionConflictError,
)
from momo.domain.motion import LegacyImportMetadata, Motion, MotionKeyframe, PlaybackDefaults
from momo.domain.motion_command import JointMovePayload, MotionCommand
from momo.domain.motion_draft import legacy_snapshot_sha256
from momo.domain.motion_preflight import MotionAccepted
from momo.domain.pose import Pose, PoseSnapshot, SnapshotJointState
from momo.ports.clock import Clock
from momo.ports.motion_repository import MotionRepository
from momo.ports.pose_repository import PoseRepository

EntityT = TypeVar("EntityT", Pose, Motion)
EntityModelT = TypeVar("EntityModelT", bound=BaseModel)
CAPTURE_ATTEMPTS = 3
COPY_SUFFIX = " Copy"
TrustedLegacySnapshotDigests = frozenset[str]


class LibraryApplicationService:
    def __init__(
        self,
        poses: PoseRepository,
        motions: MotionRepository,
        robot: RobotApplicationService,
        kinematics: KinematicsService,
        motion: MotionApplicationService,
        clock: Clock,
    ) -> None:
        self.poses = poses
        self.motions = motions
        self.robot = robot
        self.kinematics = kinematics
        self.motion = motion
        self.clock = clock
        self._motion_mutation_lock = asyncio.Lock()

    async def list_poses(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
        tags: Sequence[str],
        sort: str,
        order: str,
    ) -> tuple[list[Pose], int]:
        return self._page(await self.poses.list(), page, page_size, search, tags, sort, order)

    async def list_motions(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
        tags: Sequence[str],
        sort: str,
        order: str,
    ) -> tuple[list[Motion], int]:
        return self._page(await self.motions.list(), page, page_size, search, tags, sort, order)

    @staticmethod
    def _page(
        entities: Sequence[EntityT],
        page: int,
        page_size: int,
        search: str | None,
        tags: Sequence[str],
        sort: str,
        order: str,
    ) -> tuple[list[EntityT], int]:
        query = search.strip().casefold() if search else ""
        tag_set = {tag.strip().casefold() for tag in tags if tag.strip()}
        filtered = [
            entity
            for entity in entities
            if (
                not query
                or query in str(entity.name).casefold()
                or query in str(entity.description).casefold()
                or any(query in str(tag).casefold() for tag in entity.tags)
            )
            and tag_set.issubset({str(tag).casefold() for tag in entity.tags})
        ]

        def key(entity: EntityT) -> tuple[object, str]:
            value: object = getattr(entity, sort)
            if sort == "name":
                value = str(value).casefold()
            return value, str(entity.id)

        filtered.sort(key=key, reverse=order == "desc")
        total = len(filtered)
        start = (page - 1) * page_size
        return filtered[start : start + page_size], total

    async def get_pose(self, pose_id: UUID) -> Pose:
        pose = await self.poses.get(pose_id)
        if pose is None:
            raise EntityNotFoundError("Pose was not found")
        return pose

    async def get_motion(self, motion_id: UUID) -> Motion:
        motion = await self.motions.get(motion_id)
        if motion is None:
            raise EntityNotFoundError("Motion was not found")
        return motion

    @asynccontextmanager
    async def motion_revision_lease(
        self,
        motion_id: UUID,
        expected_revision: int,
    ) -> AsyncIterator[Motion]:
        """Fence one revision read through an execution/preflight linearization point."""

        async with self._motion_mutation_lock:
            motion = await self.get_motion(motion_id)
            self._check_revision(motion.revision, expected_revision)
            yield motion

    async def create_pose(self, request: PoseCreateCommand) -> Pose:
        self._reject_client_owned_provenance((request.snapshot,))
        await self._validate_client_snapshot(request.snapshot)
        now = self.clock.now()
        pose = self._entity_from_request(
            Pose,
            {
                "name": request.name,
                "description": request.description,
                "tags": request.tags,
                "snapshot": request.snapshot,
                "created_at": now,
                "updated_at": now,
            },
            "pose",
        )
        await self.poses.save(pose)
        return pose

    async def capture_pose(self, request: PoseCaptureCommand) -> Pose:
        for _ in range(CAPTURE_ATTEMPTS):
            first_status, first_profile, first_state = await self.robot.get_motion_snapshot()
            if not first_status.connected or first_status.stale:
                raise CaptureStateChangedError(
                    "Robot must be connected with a fresh state for capture",
                    details={"reason": "ROBOT_NOT_READY"},
                )
            model = self.kinematics.model_for(first_profile)
            forward = await self.kinematics.forward(
                first_profile,
                first_state,
                state_sequence=first_status.state_sequence,
                robot_id=first_status.robot_id,
            )
            second_status, second_profile, second_state = await self.robot.get_motion_snapshot()
            coherent = (
                second_status.connected
                and not second_status.stale
                and second_status.robot_id == first_status.robot_id
                and second_status.variant is first_status.variant
                and second_status.state_sequence == first_status.state_sequence
                and second_profile.fingerprint == first_profile.fingerprint
                and second_profile.variant is first_profile.variant
                and second_state == first_state
                and forward.state_sequence == first_status.state_sequence
            )
            if not coherent:
                continue
            now = self.clock.now()
            snapshot = PoseSnapshot(
                robot_variant=first_profile.variant,
                joint_state=SnapshotJointState.model_validate(
                    first_state.model_dump(mode="python", round_trip=True)
                ),
                tcp_pose=forward.tcp_pose,
                profile_fingerprint=first_profile.fingerprint,
                kinematics_fingerprint=model.fingerprint,
                state_sequence=first_status.state_sequence,
                hardware_snapshot=None,
                calibration_fingerprint=None,
                captured_at=now,
            )
            pose = self._entity_from_request(
                Pose,
                {
                    "name": request.name,
                    "description": request.description,
                    "tags": request.tags,
                    "snapshot": snapshot,
                    "created_at": now,
                    "updated_at": now,
                },
                "pose",
            )
            await self.poses.save(pose)
            return pose
        raise CaptureStateChangedError(
            "Robot state changed during capture",
            details={"attempts": CAPTURE_ATTEMPTS},
        )

    async def update_pose(self, pose_id: UUID, request: PosePatchCommand) -> Pose:
        current = await self.get_pose(pose_id)
        self._check_revision(current.revision, request.expected_revision)
        data = current.model_dump(mode="python")
        for field in ("name", "description", "tags"):
            if field in request.model_fields_set:
                data[field] = getattr(request, field)
        data["revision"] = current.revision + 1
        data["updated_at"] = self.clock.now()
        updated = self._entity_from_request(Pose, data, "pose")
        await self.poses.save(updated, expected_revision=request.expected_revision)
        return updated

    async def duplicate_pose(self, pose_id: UUID, request: DuplicateEntityCommand) -> Pose:
        source = await self.get_pose(pose_id)
        self._check_revision(source.revision, request.expected_revision)
        now = self.clock.now()
        duplicate = self._entity_from_request(
            Pose,
            {
                "id": uuid4(),
                "name": request.name if request.name is not None else self._copy_name(source.name),
                "description": source.description,
                "tags": list(source.tags),
                "snapshot": PoseSnapshot.model_validate(source.snapshot.model_dump(mode="python")),
                "created_at": now,
                "updated_at": now,
                "revision": 1,
            },
            "pose",
        )
        await self.poses.save(duplicate)
        return duplicate

    async def delete_pose(self, pose_id: UUID, expected_revision: int) -> None:
        deleted = await self.poses.delete(pose_id, expected_revision=expected_revision)
        if not deleted:
            raise EntityNotFoundError("Pose was not found")

    async def goto_pose(self, pose_id: UUID, request: GotoPoseCommand) -> MotionAccepted:
        pose = await self.get_pose(pose_id)
        self._check_revision(pose.revision, request.expected_revision)
        status, profile, _ = await self.robot.get_motion_snapshot()
        snapshot = pose.snapshot
        model = self.kinematics.model_for(profile)
        incompatibilities: list[str] = []
        if snapshot.robot_variant is not profile.variant:
            incompatibilities.append("robot_variant")
        if set(snapshot.joint_state.positions) != set(profile.enabled_joints):
            incompatibilities.append("joint_set")
        if snapshot.profile_fingerprint != profile.fingerprint:
            incompatibilities.append("profile_fingerprint")
        if snapshot.kinematics_fingerprint != model.fingerprint:
            incompatibilities.append("kinematics_fingerprint")
        try:
            snapshot.validate_against(profile)
        except ValueError:
            incompatibilities.append("joint_state")
        if incompatibilities:
            raise PoseIncompatibleError(
                "Pose is incompatible with the active robot",
                details={"checks": sorted(set(incompatibilities))},
            )
        command = MotionCommand(
            robot_id=status.robot_id,
            source=MotionCommandSource.LIBRARY,
            expected_state_sequence=status.state_sequence,
            expected_profile_fingerprint=profile.fingerprint,
            expected_kinematics_fingerprint=model.fingerprint,
            command_type=MotionCommandType.MOVE_JOINTS,
            payload=JointMovePayload(
                joint_state=snapshot.joint_state,
                duration_s=request.duration_s,
            ),
            speed_scale=request.speed_scale,
            idempotency_key=request.idempotency_key,
        )
        return await self.motion.submit(command)

    async def create_motion(self, request: MotionCreateCommand) -> Motion:
        self._reject_client_owned_provenance(
            tuple(keyframe.pose_snapshot for keyframe in request.keyframes)
        )
        for keyframe in request.keyframes:
            await self._validate_client_snapshot(keyframe.pose_snapshot)
        now = self.clock.now()
        motion = self._entity_from_request(
            Motion,
            {
                "name": request.name,
                "description": request.description,
                "robot_variant": request.robot_variant,
                "keyframes": request.keyframes,
                "playback_defaults": request.playback_defaults,
                "tags": request.tags,
                "created_at": now,
                "updated_at": now,
            },
            "motion",
        )
        async with self._motion_mutation_lock:
            await self.motions.save(motion)
        return motion

    async def update_motion(self, motion_id: UUID, request: MotionPatchCommand) -> Motion:
        async with self._motion_mutation_lock:
            current = await self.get_motion(motion_id)
            self._check_revision(current.revision, request.expected_revision)
            if request.keyframes is not None:
                self._reject_client_owned_provenance(
                    tuple(keyframe.pose_snapshot for keyframe in request.keyframes)
                )
                for keyframe in request.keyframes:
                    await self._validate_client_snapshot(keyframe.pose_snapshot)
            data = current.model_dump(mode="python")
            editable = (
                "name",
                "description",
                "robot_variant",
                "keyframes",
                "playback_defaults",
                "tags",
            )
            for field in editable:
                if field in request.model_fields_set:
                    data[field] = getattr(request, field)
            data["revision"] = current.revision + 1
            data["updated_at"] = self.clock.now()
            updated = self._entity_from_request(Motion, data, "motion")
            await self.motions.save(updated, expected_revision=request.expected_revision)
            return updated

    async def duplicate_motion(self, motion_id: UUID, request: DuplicateEntityCommand) -> Motion:
        async with self._motion_mutation_lock:
            source = await self.get_motion(motion_id)
            self._check_revision(source.revision, request.expected_revision)
            now = self.clock.now()
            duplicate = self._entity_from_request(
                Motion,
                {
                    "id": uuid4(),
                    "name": (
                        request.name if request.name is not None else self._copy_name(source.name)
                    ),
                    "description": source.description,
                    "robot_variant": source.robot_variant,
                    "keyframes": [
                        MotionKeyframe.model_validate(item.model_dump(mode="python"))
                        for item in source.keyframes
                    ],
                    "playback_defaults": PlaybackDefaults.model_validate(
                        source.playback_defaults.model_dump(mode="python")
                    ),
                    "tags": list(source.tags),
                    "source_metadata": (
                        LegacyImportMetadata.model_validate(
                            source.source_metadata.model_dump(mode="python")
                        )
                        if source.source_metadata is not None
                        else None
                    ),
                    "created_at": now,
                    "updated_at": now,
                    "revision": 1,
                },
                "motion",
            )
            await self.motions.save(duplicate)
            return duplicate

    async def delete_motion(self, motion_id: UUID, expected_revision: int) -> None:
        async with self._motion_mutation_lock:
            deleted = await self.motions.delete(motion_id, expected_revision=expected_revision)
            if not deleted:
                raise EntityNotFoundError("Motion was not found")

    async def persist_motion_candidate(
        self,
        motion: Motion,
        *,
        expected_revision: int | None,
        trusted_legacy_snapshot_sha256: TrustedLegacySnapshotDigests = frozenset(),
    ) -> Motion:
        """Persist a compiler-validated Studio candidate under the playback revision fence.

        Studio performs its expensive compile before entering this shared lock. The
        revision is then resolved again here, so a concurrent playback lease or
        Library mutation cannot be bypassed by a raw repository write.
        """

        self._reject_client_owned_provenance(
            tuple(keyframe.pose_snapshot for keyframe in motion.keyframes)
        )
        for keyframe in motion.keyframes:
            await self._validate_client_snapshot(
                keyframe.pose_snapshot,
                trusted_legacy_snapshot_sha256=trusted_legacy_snapshot_sha256,
            )
        async with self._motion_mutation_lock:
            if expected_revision is None:
                if motion.revision != 1:
                    raise EntityInvalidError("New Motion candidates must begin at revision 1")
                await self.motions.save(motion)
                return motion
            current = await self.get_motion(motion.id)
            self._check_revision(current.revision, expected_revision)
            if motion.revision != expected_revision + 1:
                raise EntityInvalidError("Updated Motion revision must increment exactly once")
            await self.motions.save(motion, expected_revision=expected_revision)
            return motion

    @staticmethod
    def _check_revision(actual: int, expected: int) -> None:
        if actual != expected:
            raise RevisionConflictError(
                "Entity revision changed",
                details={"expected_revision": expected, "actual_revision": actual},
            )

    @staticmethod
    def _reject_client_owned_provenance(snapshots: Sequence[PoseSnapshot]) -> None:
        for snapshot in snapshots:
            checks: list[str] = []
            if snapshot.hardware_snapshot is not None:
                checks.append("hardware_snapshot_must_be_null")
            if snapshot.calibration_fingerprint is not None:
                checks.append("calibration_fingerprint_must_be_null")
            if checks:
                raise PoseIncompatibleError(
                    "Stage 4 clients cannot persist hardware or calibration provenance",
                    details={"checks": checks},
                )

    async def _validate_client_snapshot(
        self,
        snapshot: PoseSnapshot,
        *,
        trusted_legacy_snapshot_sha256: TrustedLegacySnapshotDigests = frozenset(),
    ) -> None:
        profile = self.robot.profile_service.get_profile(snapshot.robot_variant)
        model = self.kinematics.model_for(profile)
        checks: list[str] = []
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
                robot_id="library-validation",
            )
            if snapshot.tcp_pose != forward.tcp_pose:
                checks.append("tcp_pose")
        if checks:
            raise PoseIncompatibleError(
                "Snapshot is incompatible with its declared robot contract",
                details={"checks": sorted(set(checks))},
            )

    @staticmethod
    def _copy_name(source_name: str) -> str:
        prefix_limit = 200 - len(COPY_SUFFIX)
        return f"{str(source_name)[:prefix_limit].rstrip()}{COPY_SUFFIX}"

    @staticmethod
    def _entity_from_request(
        model: type[EntityModelT], data: object, entity_name: str
    ) -> EntityModelT:
        try:
            return model.model_validate(data)
        except ValidationError as error:
            raise EntityInvalidError(
                f"{entity_name.capitalize()} request violates entity invariants",
                details={"entity": entity_name},
            ) from error
