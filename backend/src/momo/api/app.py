"""Side-effect-free FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from momo.api.error_handlers import install_error_handlers
from momo.api.routes.calibration import router as calibration_router
from momo.api.routes.health import router as health_router
from momo.api.routes.kinematics import router as kinematics_router
from momo.api.routes.meta import router as meta_router
from momo.api.routes.motion import router as motion_router
from momo.api.routes.robot import router as robot_router
from momo.api.routes.ws_robot import router as ws_robot_router
from momo.application.services.robot_service import RobotApplicationService
from momo.bootstrap import build_robot_service, build_stage3_services
from momo.settings import Settings, load_settings


def create_app(
    settings: Settings | None = None,
    robot_service: RobotApplicationService | None = None,
) -> FastAPI:
    """Build the API without connecting hardware or starting background workers."""

    resolved_settings = settings if settings is not None else load_settings()
    resolved_robot_service = (
        robot_service if robot_service is not None else build_robot_service(resolved_settings)
    )

    stage3 = build_stage3_services(resolved_settings, resolved_robot_service)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        yield
        await stage3.motion.shutdown()

    app = FastAPI(
        title=f"{resolved_settings.product_name} API",
        version=resolved_settings.version,
        description="Stage 3 Dry Run kinematics and unified safe motion API.",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.robot_service = resolved_robot_service
    app.state.kinematics_service = stage3.kinematics
    app.state.motion_service = stage3.motion
    app.state.jog_service = stage3.jog
    install_error_handlers(app)
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(meta_router, prefix="/api/v1")
    app.include_router(robot_router, prefix="/api/v1")
    app.include_router(calibration_router, prefix="/api/v1")
    app.include_router(kinematics_router, prefix="/api/v1")
    app.include_router(motion_router, prefix="/api/v1")
    app.include_router(ws_robot_router, prefix="/api/v1")
    return app
