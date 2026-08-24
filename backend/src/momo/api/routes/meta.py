"""Read-only build and product-scope metadata endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from momo.api.dependencies import get_robot_service, get_settings
from momo.api.schemas import MetaResponse, ProductScopeResponse
from momo.application.services.robot_service import RobotApplicationService
from momo.domain.enums import ControlMode, HardwareAccessPolicy
from momo.settings import Settings

router = APIRouter(prefix="/meta", tags=["meta"])
SettingsDependency = Annotated[Settings, Depends(get_settings)]
RobotServiceDependency = Annotated[RobotApplicationService, Depends(get_robot_service)]


@router.get("", response_model=MetaResponse)
async def metadata(
    settings: SettingsDependency,
    robot_service: RobotServiceDependency,
) -> MetaResponse:
    status = await robot_service.get_status()
    return MetaResponse(
        product=settings.product_name,
        version=settings.version,
        active_robot_variant=status.variant,
        active_control_mode=ControlMode.DRY_RUN,
        hardware_access_policy=HardwareAccessPolicy.DISABLED,
        real_motion_enabled=False,
    )


@router.get("/product-scope", response_model=ProductScopeResponse)
def product_scope(settings: SettingsDependency) -> ProductScopeResponse:
    return ProductScopeResponse(
        product=settings.product_name,
        stage_3_available=[
            "single Active Robot Dry Run lifecycle",
            "V1 and V2 profile diagnostics",
            "calibration compatibility diagnostics",
            "atomic Dry Run runtime state",
            "mesh-free FK and IK",
            "unified safe Dry Run motion and jog leases",
            "read-only rate-limited robot state WebSocket",
        ],
        stage_4_available=[
            "atomic schema-validated Pose and Motion repositories",
            "coherent FK-backed Pose capture",
            "compatible Pose Goto through the Motion Safety Gateway",
            "bounded searchable Pose and Motion Library APIs",
            "explicit-path default-dry-run validated Legacy action import",
        ],
        stage_5_available=[
            "deterministic Joint and true Cartesian trajectory compilation",
            "whole-plan preflight with immutable digest-bound prepared trajectories",
            "bounded Dry Run playback with pause, resume, stop, loop, and rate",
            "read-only trajectory preview and real-time playback status",
        ],
        stage_6_available=[
            "atomic recoverable MotionDraft autosave with revision conflicts",
            "coherent Studio snapshot capture without Library side effects",
            "compiler-backed draft validation and bounded non-executable preview",
            "formal Motion Save and Save As after successful Dry Run preflight",
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
