"""Versioned Stage 3 motion API; routes never receive a driver dependency."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from momo.api.dependencies import get_jog_service, get_motion_service
from momo.api.motion_schemas import (
    CartesianJogRequest,
    ContinuousJogStartRequest,
    HomeRequest,
    JointJogStepRequest,
    MoveJointsRequest,
    MovePoseRequest,
)
from momo.application.services.jog_service import JogLeaseService
from momo.application.services.motion_service import MotionApplicationService
from momo.domain.jog import JogLeaseResponse, JogStopResponse
from momo.domain.motion_preflight import MotionAccepted, MotionCommandStatus
from momo.domain.runtime import StopResponse

router = APIRouter(prefix="/motion", tags=["motion"])
MotionServiceDependency = Annotated[MotionApplicationService, Depends(get_motion_service)]
JogServiceDependency = Annotated[JogLeaseService, Depends(get_jog_service)]


@router.post(
    "/joints",
    response_model=MotionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def move_joints(
    request: MoveJointsRequest,
    service: MotionServiceDependency,
) -> MotionAccepted:
    return await service.submit(request.command())


@router.post(
    "/jog-step",
    response_model=MotionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def joint_jog_step(
    request: JointJogStepRequest,
    service: MotionServiceDependency,
) -> MotionAccepted:
    return await service.submit(request.command())


@router.post(
    "/cartesian-jog",
    response_model=MotionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cartesian_jog(
    request: CartesianJogRequest,
    service: MotionServiceDependency,
) -> MotionAccepted:
    return await service.submit(request.command())


@router.post(
    "/pose",
    response_model=MotionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def move_pose(
    request: MovePoseRequest,
    service: MotionServiceDependency,
) -> MotionAccepted:
    return await service.submit(request.command())


@router.post(
    "/home",
    response_model=MotionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def home(
    request: HomeRequest,
    service: MotionServiceDependency,
) -> MotionAccepted:
    return await service.submit(request.command())


@router.post(
    "/jog/start",
    response_model=JogLeaseResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_continuous_jog(
    request: ContinuousJogStartRequest,
    service: JogServiceDependency,
) -> JogLeaseResponse:
    return await service.start(request.command())


@router.post("/jog/{session_id}/heartbeat", response_model=JogLeaseResponse)
async def heartbeat_continuous_jog(
    session_id: UUID,
    service: JogServiceDependency,
) -> JogLeaseResponse:
    return await service.heartbeat(session_id)


@router.post("/jog/{session_id}/stop", response_model=JogStopResponse)
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


@router.post("/stop", response_model=StopResponse)
async def stop_motion(service: MotionServiceDependency) -> StopResponse:
    return await service.stop()
