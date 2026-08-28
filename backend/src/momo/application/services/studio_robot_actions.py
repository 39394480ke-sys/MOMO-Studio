"""Studio capture and persisted-keyframe robot actions."""

from __future__ import annotations

from uuid import UUID

from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.motion_service import MotionApplicationService
from momo.application.services.robot_service import RobotApplicationService
from momo.application.studio_commands import MotionDraftGotoCommand
from momo.domain.enums import MotionCommandSource, MotionCommandType
from momo.domain.errors import (
    CaptureStateChangedError,
    EntityNotFoundError,
    PoseIncompatibleError,
    RevisionConflictError,
)
from momo.domain.motion_command import JointMovePayload, MotionCommand
from momo.domain.motion_draft import MotionDraft
from momo.domain.motion_preflight import MotionAccepted
from momo.domain.pose import PoseSnapshot, SnapshotJointState
from momo.ports.clock import Clock

CAPTURE_ATTEMPTS = 3


class StudioRobotActions:
    """Execute bounded Studio robot actions without owning application locks."""

    def __init__(
        self,
        robot: RobotApplicationService,
        kinematics: KinematicsService,
        motion: MotionApplicationService,
        clock: Clock,
    ) -> None:
        self.robot = robot
        self.kinematics = kinematics
        self.motion = motion
        self.clock = clock

    async def capture_snapshot(self) -> PoseSnapshot:
        """Capture one coherent Dry Run state without creating a Pose entity."""

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
            if (
                second_status.connected
                and not second_status.stale
                and second_status.robot_id == first_status.robot_id
                and second_status.variant is first_status.variant
                and second_status.state_sequence == first_status.state_sequence
                and second_profile.fingerprint == first_profile.fingerprint
                and second_state == first_state
                and forward.state_sequence == first_status.state_sequence
            ):
                return PoseSnapshot(
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
                    captured_at=self.clock.now(),
                )
        raise CaptureStateChangedError(
            "Robot state changed during capture",
            details={"attempts": CAPTURE_ATTEMPTS},
        )

    async def goto_keyframe(
        self,
        draft: MotionDraft,
        keyframe_id: UUID,
        request: MotionDraftGotoCommand,
    ) -> MotionAccepted:
        """Submit one persisted keyframe snapshot as a Studio motion intent."""

        if draft.revision != request.expected_revision:
            raise RevisionConflictError(
                "MotionDraft revision changed",
                details={
                    "entity": "MotionDraft",
                    "expected_revision": request.expected_revision,
                    "actual_revision": draft.revision,
                },
            )
        keyframe = next((item for item in draft.keyframes if item.id == keyframe_id), None)
        if keyframe is None:
            raise EntityNotFoundError("Motion draft keyframe was not found")

        status, profile, _ = await self.robot.get_motion_snapshot()
        snapshot = keyframe.pose_snapshot
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
                "Studio keyframe is incompatible with the active robot",
                details={"checks": sorted(set(incompatibilities))},
            )

        command = MotionCommand(
            robot_id=status.robot_id,
            source=MotionCommandSource.STUDIO,
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
