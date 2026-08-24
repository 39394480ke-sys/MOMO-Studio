"""FastAPI dependencies sourced from app state, not process globals."""

from typing import cast

from fastapi import Request

from momo.application.services.jog_service import JogLeaseService
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.library_service import LibraryApplicationService
from momo.application.services.motion_service import MotionApplicationService
from momo.application.services.robot_service import RobotApplicationService
from momo.application.services.studio_service import StudioApplicationService
from momo.application.services.trajectory_service import TrajectoryApplicationService
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
