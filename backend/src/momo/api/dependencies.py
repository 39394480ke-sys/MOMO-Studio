"""FastAPI dependencies sourced from app state, not process globals."""

from typing import Annotated, cast

from fastapi import Header, Request

from momo.application.services.device_diagnostics_service import DeviceDiagnosticsService
from momo.application.services.jog_service import JogLeaseService
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.library_service import LibraryApplicationService
from momo.application.services.motion_service import MotionApplicationService
from momo.application.services.operator_session_service import OperatorSessionTokenError
from momo.application.services.robot_service import RobotApplicationService
from momo.application.services.studio_service import StudioApplicationService
from momo.application.services.trajectory_service import TrajectoryApplicationService
from momo.application.services.vision_service import VisionApplicationService
from momo.domain.enums import ControlMode
from momo.domain.real_hardware import RealHardwareAuthorizationPurpose
from momo.settings import Settings


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_robot_service(request: Request) -> RobotApplicationService:
    return cast(RobotApplicationService, request.app.state.robot_service)


def get_kinematics_service(request: Request) -> KinematicsService:
    return cast(KinematicsService, request.app.state.kinematics_service)


def get_motion_service(request: Request) -> MotionApplicationService:
    return cast(MotionApplicationService, request.app.state.motion_service)


def get_jog_service(request: Request) -> JogLeaseService:
    return cast(JogLeaseService, request.app.state.jog_service)


def get_library_service(request: Request) -> LibraryApplicationService:
    return cast(LibraryApplicationService, request.app.state.library_service)


def get_trajectory_service(request: Request) -> TrajectoryApplicationService:
    return cast(TrajectoryApplicationService, request.app.state.trajectory_service)


def get_studio_service(request: Request) -> StudioApplicationService:
    return cast(StudioApplicationService, request.app.state.studio_service)


def get_vision_service(request: Request) -> VisionApplicationService:
    return cast(VisionApplicationService, request.app.state.vision_service)


OptionalOperatorToken = Annotated[
    str | None,
    Header(alias="X-MOMO-Operator-Session"),
]


async def _authorize_real_motion_request(
    request: Request,
    token: str | None,
    *,
    purpose: RealHardwareAuthorizationPurpose,
) -> None:
    device = cast(
        DeviceDiagnosticsService,
        request.app.state.device_diagnostics_service,
    )
    if device.context.control_mode is not ControlMode.REAL:
        return
    if token is None or not 20 <= len(token) <= 200:
        raise OperatorSessionTokenError(
            "A valid operator session token is required for Real motion"
        )
    await device.authorize_operator_purpose(token, purpose=purpose)


async def authorize_real_joint_motion_request(
    request: Request,
    token: OptionalOperatorToken = None,
) -> None:
    await _authorize_real_motion_request(
        request,
        token,
        purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
    )


async def authorize_real_cartesian_motion_request(
    request: Request,
    token: OptionalOperatorToken = None,
) -> None:
    await _authorize_real_motion_request(
        request,
        token,
        purpose=RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION,
    )


async def authorize_real_playback_request(
    request: Request,
    token: OptionalOperatorToken = None,
) -> None:
    await _authorize_real_motion_request(
        request,
        token,
        purpose=RealHardwareAuthorizationPurpose.REAL_PLAYBACK,
    )


async def authorize_real_vision_follow_request(
    request: Request,
    token: OptionalOperatorToken = None,
) -> None:
    await _authorize_real_motion_request(
        request,
        token,
        purpose=RealHardwareAuthorizationPurpose.REAL_VISION_FOLLOW,
    )
