"""Profile-bound construction of one bounded Vision motion intent."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from momo.application.services.kinematics_service import KinematicsService
from momo.domain.enums import DomainUnit, JointType, MotionCommandSource, MotionCommandType
from momo.domain.errors import VisionFollowConflictError
from momo.domain.motion_command import JointMovePayload, MotionCommand
from momo.domain.robot import JointState, RobotProfile
from momo.domain.runtime import RobotStatus
from momo.domain.vision_follow import FollowConfiguration, clamp

_MIN_COMMAND_DURATION_S = 0.1
_MAX_COMMAND_DURATION_S = 60.0


@dataclass(frozen=True, slots=True)
class BuiltVisionCommand:
    command: MotionCommand | None
    pan_step: float
    tilt_step: float


class VisionFollowCommandFactory:
    """Bind controller output to current Profile/state without dispatching it."""

    def __init__(self, kinematics: KinematicsService) -> None:
        self.kinematics = kinematics

    @staticmethod
    def mapping_reasons(
        profile: RobotProfile,
        configuration: FollowConfiguration,
    ) -> tuple[str, ...]:
        mapping = configuration.mapping
        definitions = profile.definitions_by_id
        enabled = set(profile.enabled_joints)
        reasons: list[str] = []
        for axis, joint_id in (("PAN", mapping.pan_joint), ("TILT", mapping.tilt_joint)):
            if joint_id not in enabled:
                reasons.append(f"{axis}_JOINT_NOT_ENABLED")
                continue
            definition = definitions.get(joint_id)
            if definition is None:
                reasons.append(f"{axis}_JOINT_NOT_ENABLED")
            elif (
                definition.joint_type is not JointType.REVOLUTE
                or definition.domain_unit is not DomainUnit.DEG
            ):
                reasons.append(f"{axis}_JOINT_MUST_BE_REVOLUTE_DEG")
        return tuple(reasons)

    def build(
        self,
        *,
        robot_status: RobotStatus,
        profile: RobotProfile,
        current: JointState,
        configuration: FollowConfiguration,
        pan_step: float,
        tilt_step: float,
    ) -> BuiltVisionCommand:
        mapping = configuration.mapping
        definitions = profile.definitions_by_id
        reasons = self.mapping_reasons(profile, configuration)
        if reasons:
            raise VisionFollowConflictError(
                "Follow actuator mapping no longer matches the active Profile",
                details={"reasons": reasons},
            )

        pan_definition = definitions[mapping.pan_joint]
        tilt_definition = definitions[mapping.tilt_joint]
        positions = dict(current.positions)
        positions[mapping.pan_joint] = clamp(
            positions[mapping.pan_joint] + pan_step,
            pan_definition.minimum,
            pan_definition.maximum,
        )
        positions[mapping.tilt_joint] = clamp(
            positions[mapping.tilt_joint] + tilt_step,
            tilt_definition.minimum,
            tilt_definition.maximum,
        )
        actual_pan_step = positions[mapping.pan_joint] - current.positions[mapping.pan_joint]
        actual_tilt_step = positions[mapping.tilt_joint] - current.positions[mapping.tilt_joint]
        if abs(actual_pan_step) <= 1e-12 and abs(actual_tilt_step) <= 1e-12:
            return BuiltVisionCommand(None, actual_pan_step, actual_tilt_step)

        maximum_delta = max(abs(actual_pan_step), abs(actual_tilt_step))
        duration_s = max(_MIN_COMMAND_DURATION_S, maximum_delta / configuration.max_rate)
        duration_s = min(_MAX_COMMAND_DURATION_S, duration_s)
        command_id = uuid4()
        command = MotionCommand(
            command_id=command_id,
            robot_id=robot_status.robot_id,
            source=MotionCommandSource.VISION,
            expected_state_sequence=robot_status.state_sequence,
            expected_profile_fingerprint=profile.fingerprint,
            expected_kinematics_fingerprint=self.kinematics.model_for(profile).fingerprint,
            command_type=MotionCommandType.MOVE_JOINTS,
            payload=JointMovePayload(
                joint_state=JointState(
                    positions=positions,
                    units=dict(current.units or {}),
                ),
                duration_s=duration_s,
            ),
            idempotency_key=f"vision-follow:{command_id}",
        )
        return BuiltVisionCommand(command, actual_pan_step, actual_tilt_step)
