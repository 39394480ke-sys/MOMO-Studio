"""FastAPI dependencies sourced from app state, not process globals."""

from typing import cast

from fastapi import Request

from momo.application.services.robot_service import RobotApplicationService
from momo.settings import Settings


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_robot_service(request: Request) -> RobotApplicationService:
    return cast(RobotApplicationService, request.app.state.robot_service)
