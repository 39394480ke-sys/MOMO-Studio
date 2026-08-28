"""Application orchestration for reviewed Dry Run kinematics models."""

from __future__ import annotations

from math import degrees

from momo.domain.enums import CartesianFrame
from momo.domain.kinematics.model import KinematicsModel
from momo.domain.kinematics.results import ForwardKinematicsResult, InverseKinematicsResult
from momo.domain.pose import TcpPose
from momo.domain.robot import JointState, RobotProfile
from momo.ports.kinematics import (
    Kinematics,
    from_kinematics_joint_state,
    from_kinematics_tcp_pose,
    to_kinematics_joint_state,
    to_kinematics_tcp_pose,
)
from momo.ports.kinematics_model_repository import KinematicsModelRepository


class KinematicsService:
    def __init__(
        self,
        repository: KinematicsModelRepository,
        adapter: Kinematics,
    ) -> None:
        self.repository = repository
        self.adapter = adapter

    def model_for(self, profile: RobotProfile) -> KinematicsModel:
        return self.repository.get(profile.variant).validate_against_profile(profile)

    async def forward(
        self,
        profile: RobotProfile,
        state: JointState,
        *,
        state_sequence: int,
        robot_id: str = "primary",
    ) -> ForwardKinematicsResult:
        model = self.model_for(profile)
        adapter_pose = await self.adapter.forward(
            model,
            to_kinematics_joint_state(state, profile),
        )
        return ForwardKinematicsResult(
            robot_id=robot_id,
            variant=profile.variant,
            state_sequence=state_sequence,
            profile_fingerprint=profile.fingerprint,
            kinematics_fingerprint=model.fingerprint,
            tcp_pose=from_kinematics_tcp_pose(adapter_pose),
            hardware_accessed=False,
        )

    async def inverse(
        self,
        profile: RobotProfile,
        target: TcpPose,
        *,
        seed: JointState | None = None,
        position_only: bool = False,
        maximum_iterations: int = 200,
    ) -> InverseKinematicsResult:
        model = self.model_for(profile)
        result = await self.adapter.inverse(
            model,
            to_kinematics_tcp_pose(target),
            to_kinematics_joint_state(seed, profile) if seed is not None else None,
            position_only=position_only,
            maximum_iterations=maximum_iterations,
        )

        def canonical(value: object) -> JointState | None:
            if value is None:
                return None
            from momo.ports.kinematics import KinematicsJointState

            if not isinstance(value, KinematicsJointState):
                raise TypeError("kinematics adapter returned an invalid joint state")
            return from_kinematics_joint_state(value, profile)

        orientation_error = (
            degrees(result.orientation_error_rad)
            if result.orientation_error_rad is not None
            else None
        )
        return InverseKinematicsResult(
            success=result.success,
            joint_state_optional=canonical(result.solution),
            best_joint_state=canonical(result.best_solution),
            iterations=result.iterations,
            position_error_mm=result.position_error_m * 1000.0,
            orientation_error_deg=orientation_error,
            termination_reason=result.termination_reason,
            warnings=list(result.warnings),
            kinematics_fingerprint=model.fingerprint,
        )

    async def compose_delta(
        self,
        profile: RobotProfile,
        current: TcpPose,
        *,
        delta_position_mm: tuple[float, float, float],
        delta_rotation_deg: tuple[float, float, float],
        frame: CartesianFrame,
    ) -> TcpPose:
        from math import radians

        model = self.model_for(profile)
        target = self.adapter.compose_delta(
            to_kinematics_tcp_pose(current),
            (
                delta_position_mm[0] / 1000.0,
                delta_position_mm[1] / 1000.0,
                delta_position_mm[2] / 1000.0,
            ),
            (
                radians(delta_rotation_deg[0]),
                radians(delta_rotation_deg[1]),
                radians(delta_rotation_deg[2]),
            ),
            frame,
        )
        if target.frame != model.base_frame:
            raise ValueError("composed target frame does not match active kinematics model")
        return from_kinematics_tcp_pose(target)
