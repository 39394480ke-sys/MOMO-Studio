"""Read-only health endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends

from momo.api.dependencies import get_settings
from momo.api.schemas import HealthResponse
from momo.settings import Settings

router = APIRouter(tags=["health"])
SettingsDependency = Annotated[Settings, Depends(get_settings)]


@router.get("/health", response_model=HealthResponse)
def health(settings: SettingsDependency) -> HealthResponse:
    return HealthResponse(
        product=settings.product_name,
        version=settings.version,
        control_mode=settings.control_mode,
        hardware_access_policy=settings.hardware_access_policy,
        real_motion_enabled=settings.real_motion_enabled,
    )
