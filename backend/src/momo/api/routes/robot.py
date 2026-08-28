"""Stage 3 Dry Run lifecycle and read-only robot diagnostics."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from momo.api.dependencies import get_kinematics_service, get_motion_service, get_robot_service
from momo.api.schemas import (
    DiagnosticsResponse,
    ProfileResponse,
    RobotCommandResponse,
    VariantSwitchRequest,
)
from momo.api.security import authorize_control_request, authorize_priority_stop_request
from momo.application.services.device_diagnostics_service import DeviceDiagnosticsService
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.motion_service import MotionApplicationService
from momo.application.services.robot_service import RobotApplicationService
from momo.domain.errors import ProfileInvalidError
from momo.domain.robot import RobotProfile
from momo.domain.runtime import RobotStatus, StopResponse

router = APIRouter(prefix="/robot", tags=["robot"])
RobotServiceDependency = Annotated[RobotApplicationService, Depends(get_robot_service)]
MotionServiceDependency = Annotated[MotionApplicationService, Depends(get_motion_service)]
KinematicsServiceDependency = Annotated[KinematicsService, Depends(get_kinematics_service)]


def get_device_diagnostics_service(request: Request) -> DeviceDiagnosticsService:
    return cast(DeviceDiagnosticsService, request.app.state.device_diagnostics_service)


DeviceServiceDependency = Annotated[
    DeviceDiagnosticsService,
    Depends(get_device_diagnostics_service),
]


@router.get("", response_model=RobotStatus)
async def robot_status(service: RobotServiceDependency) -> RobotStatus:
    return await service.get_status()


@router.get("/profile", response_model=ProfileResponse)
async def robot_profile(
    service: RobotServiceDependency,
    kinematics: KinematicsServiceDependency,
) -> ProfileResponse:
    payload = await service.get_profile()
    profile = payload.get("profile")
    if not isinstance(profile, RobotProfile):  # pragma: no cover - internal contract
        raise TypeError("robot service returned an invalid profile")
    return ProfileResponse(
        profile=profile,
        fingerprint=profile.fingerprint,
        kinematics_fingerprint=kinematics.model_for(profile).fingerprint,
        real_eligible=False,
    )


@router.get("/diagnostics", response_model=DiagnosticsResponse)
async def robot_diagnostics(service: RobotServiceDependency) -> DiagnosticsResponse:
    return DiagnosticsResponse.model_validate(await service.diagnostics())


@router.post(
    "/connect",
    response_model=RobotCommandResponse,
    dependencies=[Depends(authorize_control_request)],
)
async def connect_robot(
    request: Request,
    service: RobotServiceDependency,
) -> RobotCommandResponse:
    if request.query_params or await request.body():
        raise ProfileInvalidError("Stage 3 Connect accepts no mode, body, or query parameters")
    return RobotCommandResponse(status=await service.connect(), hardware_accessed=False)


@router.post(
    "/disconnect",
    response_model=RobotCommandResponse,
    dependencies=[Depends(authorize_control_request)],
)
async def disconnect_robot(service: MotionServiceDependency) -> RobotCommandResponse:
    return RobotCommandResponse(status=await service.disconnect(), hardware_accessed=False)


@router.post(
    "/stop",
    response_model=StopResponse,
    dependencies=[Depends(authorize_priority_stop_request)],
)
async def stop_robot(service: MotionServiceDependency) -> StopResponse:
    return await service.stop()


@router.put(
    "/variant",
    response_model=RobotCommandResponse,
    dependencies=[Depends(authorize_control_request)],
)
async def switch_robot_variant(
    request: VariantSwitchRequest,
    service: RobotServiceDependency,
    device: DeviceServiceDependency,
) -> RobotCommandResponse:
    return RobotCommandResponse(
        status=await service.switch_variant(
            request.variant,
            before_switch=device.invalidate_profile_authorization,
        ),
        hardware_accessed=False,
    )
