"""Versioned Stage 3 motion API; routes never receive a driver dependency."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from momo.api.dependencies import (
    authorize_real_cartesian_motion_request,
    authorize_real_joint_motion_request,
    get_jog_service,
    get_motion_service,
)
from momo.api.motion_schemas import (
    CartesianJogRequest,
    CartesianJogStartRequest,
    ContinuousJogStartRequest,
    HomeRequest,
    JointJogStepRequest,
    MoveJointsRequest,
    MovePoseRequest,
)
from momo.api.security import (
    authorize_control_keepalive_request,
    authorize_control_request,
    authorize_priority_stop_request,
)
from momo.application.services.jog_service import JogLeaseService
from momo.application.services.motion_service import MotionApplicationService
from momo.domain.jog import JogLeaseResponse, JogStopResponse
from momo.domain.motion_command import MotionCommand
from momo.domain.motion_preflight import MotionAccepted, MotionCommandStatus
from momo.domain.real_hardware import RealHardwareAuthorizationPurpose
from momo.domain.real_motion import RealExecutionAuthorization
from momo.domain.runtime import StopResponse

router = APIRouter(prefix="/motion", tags=["motion"])
MotionServiceDependency = Annotated[MotionApplicationService, Depends(get_motion_service)]
JogServiceDependency = Annotated[JogLeaseService, Depends(get_jog_service)]
RealJointAuthorization = Annotated[
    RealExecutionAuthorization | None,
    Depends(authorize_real_joint_motion_request),
]
RealCartesianAuthorization = Annotated[
    RealExecutionAuthorization | None,
    Depends(authorize_real_cartesian_motion_request),
]


def _set_motion_audit_context(
    http_request: Request,
    *,
    command_id: UUID,
    robot_id: str,
    preflight: str,
    real: bool = False,
) -> None:
    """Attach bounded motion evidence to the request-level structured audit."""

    http_request.state.command_id = str(command_id)
    http_request.state.robot_id = robot_id
    http_request.state.mode = "REAL" if real else "DRY_RUN"
    http_request.state.preflight = preflight


async def _submit_motion(
    http_request: Request,
    service: MotionApplicationService,
    command: MotionCommand,
    authorization: RealExecutionAuthorization | None = None,
    execution_purpose: RealHardwareAuthorizationPurpose | None = None,
) -> MotionAccepted:
    command_id = command.command_id
    robot_id = command.robot_id
    _set_motion_audit_context(
        http_request,
        command_id=command_id,
        robot_id=robot_id,
        preflight="PENDING",
        real=authorization is not None,
    )
    try:
        accepted = await service.submit(
            command,
            authorization=authorization,
            execution_purpose=execution_purpose,
        )
    except Exception:
        http_request.state.preflight = "REJECTED"
        raise
    http_request.state.command_id = str(accepted.command_id)
    http_request.state.preflight = "ACCEPTED" if accepted.preflight.accepted else "REJECTED"
    return accepted


@router.post(
    "/joints",
    response_model=MotionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(authorize_control_request),
    ],
)
async def move_joints(
    request: MoveJointsRequest,
    http_request: Request,
    service: MotionServiceDependency,
    authorization: RealJointAuthorization,
) -> MotionAccepted:
    return await _submit_motion(
        http_request,
        service,
        request.command(),
        authorization,
        (RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION if authorization is not None else None),
    )


@router.post(
    "/jog-step",
    response_model=MotionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(authorize_control_request),
    ],
)
async def joint_jog_step(
    request: JointJogStepRequest,
    http_request: Request,
    service: MotionServiceDependency,
    authorization: RealJointAuthorization,
) -> MotionAccepted:
    return await _submit_motion(
        http_request,
        service,
        request.command(),
        authorization,
        (RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION if authorization is not None else None),
    )


@router.post(
    "/cartesian-jog",
    response_model=MotionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(authorize_control_request),
    ],
)
async def cartesian_jog(
    request: CartesianJogRequest,
    http_request: Request,
    service: MotionServiceDependency,
    authorization: RealCartesianAuthorization,
) -> MotionAccepted:
    return await _submit_motion(
        http_request,
        service,
        request.command(),
        authorization,
        (
            RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION
            if authorization is not None
            else None
        ),
    )


@router.post(
    "/cartesian-jog/start",
    response_model=JogLeaseResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(authorize_control_request)],
)
async def start_continuous_cartesian_jog(
    request: CartesianJogStartRequest,
    http_request: Request,
    service: JogServiceDependency,
    authorization: RealCartesianAuthorization,
) -> JogLeaseResponse:
    command = request.command()
    _set_motion_audit_context(
        http_request,
        command_id=command.command_id,
        robot_id=command.robot_id,
        preflight="PENDING",
        real=authorization is not None,
    )
    try:
        response = await service.start(
            command,
            authorization=authorization,
            execution_purpose=(
                RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION
                if authorization is not None
                else None
            ),
        )
    except Exception:
        http_request.state.preflight = "REJECTED"
        raise
    http_request.state.command_id = str(response.command_id)
    http_request.state.preflight = "ACCEPTED"
    return response


@router.post(
    "/pose",
    response_model=MotionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(authorize_control_request),
    ],
)
async def move_pose(
    request: MovePoseRequest,
    http_request: Request,
    service: MotionServiceDependency,
    authorization: RealCartesianAuthorization,
) -> MotionAccepted:
    return await _submit_motion(
        http_request,
        service,
        request.command(),
        authorization,
        (
            RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION
            if authorization is not None
            else None
        ),
    )


@router.post(
    "/home",
    response_model=MotionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(authorize_control_request),
    ],
)
async def home(
    request: HomeRequest,
    http_request: Request,
    service: MotionServiceDependency,
    authorization: RealJointAuthorization,
) -> MotionAccepted:
    return await _submit_motion(
        http_request,
        service,
        request.command(),
        authorization,
        (RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION if authorization is not None else None),
    )


@router.post(
    "/jog/start",
    response_model=JogLeaseResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(authorize_control_request),
    ],
)
async def start_continuous_jog(
    request: ContinuousJogStartRequest,
    http_request: Request,
    service: JogServiceDependency,
    authorization: RealJointAuthorization,
) -> JogLeaseResponse:
    command = request.command()
    _set_motion_audit_context(
        http_request,
        command_id=command.command_id,
        robot_id=command.robot_id,
        preflight="PENDING",
        real=authorization is not None,
    )
    try:
        response = await service.start(
            command,
            authorization=authorization,
            execution_purpose=(
                RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION
                if authorization is not None
                else None
            ),
        )
    except Exception:
        http_request.state.preflight = "REJECTED"
        raise
    http_request.state.command_id = str(response.command_id)
    http_request.state.preflight = "ACCEPTED"
    return response


@router.post(
    "/jog/{session_id}/heartbeat",
    response_model=JogLeaseResponse,
    dependencies=[
        Depends(authorize_control_keepalive_request),
        Depends(authorize_real_joint_motion_request),
    ],
)
async def heartbeat_continuous_jog(
    session_id: UUID,
    service: JogServiceDependency,
) -> JogLeaseResponse:
    return await service.heartbeat(session_id)


@router.post(
    "/cartesian-jog/{session_id}/heartbeat",
    response_model=JogLeaseResponse,
    dependencies=[
        Depends(authorize_control_keepalive_request),
        Depends(authorize_real_cartesian_motion_request),
    ],
)
async def heartbeat_continuous_cartesian_jog(
    session_id: UUID,
    service: JogServiceDependency,
) -> JogLeaseResponse:
    return await service.heartbeat(session_id)


@router.post(
    "/jog/{session_id}/stop",
    response_model=JogStopResponse,
    dependencies=[Depends(authorize_priority_stop_request)],
)
async def stop_continuous_jog(
    session_id: UUID,
    service: JogServiceDependency,
) -> JogStopResponse:
    return await service.stop(session_id)


@router.get("/commands/{command_id}", response_model=MotionCommandStatus)
async def command_status(
    command_id: UUID,
    service: MotionServiceDependency,
) -> MotionCommandStatus:
    return service.get_status(command_id)


@router.post(
    "/stop",
    response_model=StopResponse,
    dependencies=[Depends(authorize_priority_stop_request)],
)
async def stop_motion(service: MotionServiceDependency) -> StopResponse:
    return await service.stop()
