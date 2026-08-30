"""FastAPI dependencies sourced from app state, not process globals."""

from __future__ import annotations

import secrets
from typing import Annotated, cast

from fastapi import Depends, Header, Request

from momo.application.services.device_diagnostics_service import DeviceDiagnosticsService
from momo.application.services.jog_service import JogLeaseService
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.library_service import LibraryApplicationService
from momo.application.services.motion_service import MotionApplicationService
from momo.application.services.operator_session_service import OperatorSessionTokenError
from momo.application.services.product_lifecycle_service import ProductLifecycleService
from momo.application.services.robot_service import RobotApplicationService
from momo.application.services.studio_service import StudioApplicationService
from momo.application.services.trajectory_service import TrajectoryApplicationService
from momo.application.services.vision_service import VisionApplicationService
from momo.domain.enums import ControlMode
from momo.domain.real_hardware import RealHardwareAuthorizationPurpose
from momo.domain.real_motion import RealExecutionAuthorization
from momo.settings import Settings


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_robot_service(request: Request) -> RobotApplicationService:
    return cast(RobotApplicationService, request.app.state.robot_service)


def get_kinematics_service(request: Request) -> KinematicsService:
    return cast(KinematicsService, request.app.state.kinematics_service)


def get_motion_service(request: Request) -> MotionApplicationService:
    return cast(MotionApplicationService, request.app.state.motion_service)


def get_product_lifecycle_service(request: Request) -> ProductLifecycleService:
    return cast(ProductLifecycleService, request.app.state.product_lifecycle_service)


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


OPERATOR_SESSION_COOKIE = "momo_operator_session"


def get_optional_operator_session_token(
    request: Request,
    header_token: Annotated[
        str | None,
        Header(alias="X-MOMO-Operator-Session", min_length=20, max_length=200),
    ] = None,
) -> str | None:
    """Resolve an ephemeral operator session from HttpOnly cookie or legacy header.

    The header remains a bounded compatibility path for non-browser/local tooling.
    Supplying two different credentials is rejected instead of choosing one.
    """

    cookie_token = request.cookies.get(OPERATOR_SESSION_COOKIE)
    if cookie_token is not None and not 20 <= len(cookie_token) <= 200:
        raise OperatorSessionTokenError("The operator session cookie is malformed")
    if (
        cookie_token is not None
        and header_token is not None
        and not secrets.compare_digest(cookie_token, header_token)
    ):
        raise OperatorSessionTokenError("Conflicting operator session credentials were supplied")
    token = cookie_token or header_token
    return token


def get_operator_session_token(
    token: Annotated[str | None, Depends(get_optional_operator_session_token)],
) -> str:
    if token is None:
        raise OperatorSessionTokenError("A valid operator session token is required")
    return token


OperatorToken = Annotated[str, Depends(get_operator_session_token)]
OptionalOperatorToken = Annotated[
    str | None,
    Depends(get_optional_operator_session_token),
]


async def _authorize_real_motion_request(
    request: Request,
    token: str | None,
    *,
    purpose: RealHardwareAuthorizationPurpose,
) -> RealExecutionAuthorization | None:
    device = cast(
        DeviceDiagnosticsService,
        request.app.state.device_diagnostics_service,
    )
    if device.context.control_mode is not ControlMode.REAL:
        return None
    if token is None or not 20 <= len(token) <= 200:
        raise OperatorSessionTokenError(
            "A valid operator session token is required for Real motion"
        )
    return await device.authorize_real_execution(token, purpose=purpose)


async def authorize_real_joint_motion_request(
    request: Request,
    token: OptionalOperatorToken = None,
) -> RealExecutionAuthorization | None:
    return await _authorize_real_motion_request(
        request,
        token,
        purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
    )


async def authorize_real_cartesian_motion_request(
    request: Request,
    token: OptionalOperatorToken = None,
) -> RealExecutionAuthorization | None:
    return await _authorize_real_motion_request(
        request,
        token,
        purpose=RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION,
    )


async def authorize_real_playback_request(
    request: Request,
    token: OptionalOperatorToken = None,
) -> RealExecutionAuthorization | None:
    return await _authorize_real_motion_request(
        request,
        token,
        purpose=RealHardwareAuthorizationPurpose.REAL_PLAYBACK,
    )


async def authorize_real_vision_follow_request(
    request: Request,
    token: OptionalOperatorToken = None,
) -> RealExecutionAuthorization | None:
    return await _authorize_real_motion_request(
        request,
        token,
        purpose=RealHardwareAuthorizationPurpose.REAL_VISION_FOLLOW,
    )
