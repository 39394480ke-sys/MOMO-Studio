"""Stage 3 Dry Run lifecycle and read-only robot diagnostics."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from momo.api.dependencies import get_motion_service, get_robot_service
from momo.api.schemas import (
    DiagnosticsResponse,
    ProfileResponse,
    RobotCommandResponse,
    VariantSwitchRequest,
)
from momo.application.services.motion_service import MotionApplicationService
from momo.application.services.robot_service import RobotApplicationService
from momo.domain.errors import ProfileInvalidError
from momo.domain.runtime import RobotStatus, StopResponse

router = APIRouter(prefix="/robot", tags=["robot"])
RobotServiceDependency = Annotated[RobotApplicationService, Depends(get_robot_service)]
MotionServiceDependency = Annotated[MotionApplicationService, Depends(get_motion_service)]


@router.get("", response_model=RobotStatus)
async def robot_status(service: RobotServiceDependency) -> RobotStatus:
    return await service.get_status()


@router.get("/profile", response_model=ProfileResponse)
async def robot_profile(service: RobotServiceDependency) -> ProfileResponse:
    return ProfileResponse.model_validate(await service.get_profile())


@router.get("/diagnostics", response_model=DiagnosticsResponse)
async def robot_diagnostics(service: RobotServiceDependency) -> DiagnosticsResponse:
    return DiagnosticsResponse.model_validate(await service.diagnostics())


@router.post("/connect", response_model=RobotCommandResponse)
async def connect_robot(
    request: Request,
    service: RobotServiceDependency,
) -> RobotCommandResponse:
    if request.query_params or await request.body():
        raise ProfileInvalidError("Stage 3 Connect accepts no mode, body, or query parameters")
    return RobotCommandResponse(status=await service.connect(), hardware_accessed=False)


@router.post("/disconnect", response_model=RobotCommandResponse)
async def disconnect_robot(service: MotionServiceDependency) -> RobotCommandResponse:
    return RobotCommandResponse(status=await service.disconnect(), hardware_accessed=False)


@router.post("/stop", response_model=StopResponse)
async def stop_robot(service: MotionServiceDependency) -> StopResponse:
    return await service.stop()


@router.put("/variant", response_model=RobotCommandResponse)
async def switch_robot_variant(
    request: VariantSwitchRequest,
    service: RobotServiceDependency,
) -> RobotCommandResponse:
    return RobotCommandResponse(
        status=await service.switch_variant(request.variant),
        hardware_accessed=False,
    )
