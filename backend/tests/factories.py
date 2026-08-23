"""Small typed factories that keep invariant-focused tests readable."""

from momo.domain.enums import Easing, MotionMode, RobotVariant
from momo.domain.motion import Motion, MotionKeyframe, MotionTransition
from momo.domain.pose import PoseSnapshot, QuaternionXYZW, TcpPose, Vector3
from momo.domain.profiles import canonical_robot_profile
from momo.domain.robot import JointState


def make_joint_state(variant: RobotVariant = RobotVariant.V2) -> JointState:
    profile = canonical_robot_profile(variant)
    return JointState(
        positions={definition.joint_id: definition.home for definition in profile.joint_definitions}
    )


def make_snapshot(variant: RobotVariant = RobotVariant.V2) -> PoseSnapshot:
    return PoseSnapshot(
        robot_variant=variant,
        joint_state=make_joint_state(variant),
        tcp_pose=TcpPose(
            frame="base",
            position_mm=Vector3(x=100.0, y=20.0, z=350.0),
            orientation_quaternion_xyzw=QuaternionXYZW(x=0.0, y=0.0, z=0.0, w=1.0),
        ),
    )


def make_transition(duration_s: float = 1.5) -> MotionTransition:
    return MotionTransition(
        duration_s=duration_s,
        motion_mode=MotionMode.JOINT,
        easing=Easing.SMOOTHSTEP,
    )


def make_motion(variant: RobotVariant = RobotVariant.V2) -> Motion:
    return Motion(
        name="Two-point move",
        robot_variant=variant,
        keyframes=[
            MotionKeyframe(label="Start", pose_snapshot=make_snapshot(variant)),
            MotionKeyframe(
                label="End",
                pose_snapshot=make_snapshot(variant),
                incoming_transition=make_transition(),
            ),
        ],
    )
