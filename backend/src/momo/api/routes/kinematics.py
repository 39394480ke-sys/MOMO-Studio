"""Read-only FK and deterministic IK/reachability endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from momo.api.dependencies import get_kinematics_service, get_robot_service
from momo.api.motion_schemas import InverseKinematicsRequest
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.robot_service import RobotApplicationService
from momo.domain.kinematics.results import ForwardKinematicsResult, InverseKinematicsResult

router = APIRouter(tags=["kinematics"])
RobotServiceDependency = Annotated[RobotApplicationService, Depends(get_robot_service)]
KinematicsServiceDependency = Annotated[KinematicsService, Depends(get_kinematics_service)]


@router.get("/robot/fk", response_model=ForwardKinematicsResult)
async def current_fk(
    robot_service: RobotServiceDependency,
    kinematics: KinematicsServiceDependency,
) -> ForwardKinematicsResult:
    status, profile, state = await robot_service.get_motion_snapshot()
    return await kinematics.forward(
        profile,
        state,
        state_sequence=status.state_sequence,
        robot_id=status.robot_id,
    )


@router.post("/kinematics/ik", response_model=InverseKinematicsResult)
async def solve_ik(
    request: InverseKinematicsRequest,
    robot_service: RobotServiceDependency,
    kinematics: KinematicsServiceDependency,
) -> InverseKinematicsResult:
    _status, profile, current = await robot_service.get_motion_snapshot()
    seed = request.seed_joint_state if request.seed_joint_state is not None else current
    return await kinematics.inverse(
        profile,
        request.target_pose,
        seed=seed,
        position_only=request.position_only,
        maximum_iterations=request.maximum_iterations,
    )
