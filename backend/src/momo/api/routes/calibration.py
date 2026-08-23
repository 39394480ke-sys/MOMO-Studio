"""Read-only calibration status; Stage 2 exposes no calibration writes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from momo.api.dependencies import get_robot_service
from momo.api.schemas import CalibrationStatusResponse
from momo.application.services.robot_service import RobotApplicationService

router = APIRouter(prefix="/calibration", tags=["calibration"])
RobotServiceDependency = Annotated[RobotApplicationService, Depends(get_robot_service)]


@router.get("/status", response_model=CalibrationStatusResponse)
async def calibration_status(
    service: RobotServiceDependency,
) -> CalibrationStatusResponse:
    return await service.get_calibration_status()
