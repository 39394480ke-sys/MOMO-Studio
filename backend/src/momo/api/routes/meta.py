"""Read-only build and product-scope metadata endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from momo.api.dependencies import get_settings
from momo.api.schemas import MetaResponse, ProductScopeResponse
from momo.settings import Settings

router = APIRouter(prefix="/meta", tags=["meta"])
SettingsDependency = Annotated[Settings, Depends(get_settings)]


@router.get("", response_model=MetaResponse)
def metadata(settings: SettingsDependency) -> MetaResponse:
    return MetaResponse(
        product=settings.product_name,
        version=settings.version,
        active_robot_variant=settings.active_robot_variant,
        real_motion_enabled=False,
    )


@router.get("/product-scope", response_model=ProductScopeResponse)
def product_scope(settings: SettingsDependency) -> ProductScopeResponse:
    return ProductScopeResponse(
        product=settings.product_name,
        stage_1_available=[
            "health and product metadata",
            "versioned domain and port contracts",
            "robot profile, pose, and motion JSON schemas",
            "five-page frontend shell",
            "dry-run-only safety foundation",
        ],
        included_in_first_version=[
            "single active MOMO V1 or V2 robot",
            "joint and Cartesian control",
            "pose, keyframe, motion, and library workflows",
            "safe preflight and playback",
            "camera-based target selection and vision following",
            "device diagnostics and calibration status",
        ],
        excluded_from_first_version=[
            "AI, voice, gesture, or natural-language robot control",
            "photo, video recording, or media management",
            "gripper and teach mode",
            "community features",
            "multi-arm coordination product features",
            "PyQt or PyBullet product windows",
        ],
    )
