"""Side-effect-free FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from pydantic import SecretStr

from momo.api.error_handlers import install_error_handlers
from momo.api.routes.backup import router as backup_router
from momo.api.routes.calibration import router as calibration_router
from momo.api.routes.device import router as device_router
from momo.api.routes.device_calibration import router as device_calibration_router
from momo.api.routes.health import router as health_router
from momo.api.routes.kinematics import router as kinematics_router
from momo.api.routes.library import router as library_router
from momo.api.routes.meta import router as meta_router
from momo.api.routes.motion import router as motion_router
from momo.api.routes.playback import router as playback_router
from momo.api.routes.robot import router as robot_router
from momo.api.routes.security import router as security_router
from momo.api.routes.studio import router as studio_router
from momo.api.routes.vision import router as vision_router
from momo.api.routes.ws_robot import router as ws_robot_router
from momo.api.security import (
    BodySizeLimitMiddleware,
    StrictOriginMiddleware,
    StructuredRequestAuditMiddleware,
    authorize_rest_request,
    authorize_vision_request,
)
from momo.api.static_spa import SpaStaticFiles
from momo.application.services.robot_service import RobotApplicationService
from momo.bootstrap import build_application_services, build_robot_service
from momo.release_bootstrap import build_release_services
from momo.settings import Settings, load_settings, repository_root


def create_app(
    settings: Settings | None = None,
    robot_service: RobotApplicationService | None = None,
) -> FastAPI:
    """Build the API without connecting hardware or starting background workers."""

    resolved_settings = settings if settings is not None else load_settings()
    runtime_settings = resolved_settings.model_copy(update={"lan_auth_token": SecretStr("")})
    resolved_robot_service = (
        robot_service if robot_service is not None else build_robot_service(runtime_settings)
    )

    services = build_application_services(runtime_settings, resolved_robot_service)
    release = build_release_services(resolved_settings, resolved_robot_service, services)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        await release.backup.recover_pending_restore()
        yield
        try:
            await release.calibration.shutdown()
        finally:
            try:
                await release.device.shutdown()
            finally:
                try:
                    await services.vision.shutdown()
                finally:
                    await services.motion.shutdown()

    app = FastAPI(
        title=f"{runtime_settings.product_name} API",
        version=runtime_settings.version,
        description="MOMO Studio 0.1.0-rc1 API with field-gated Real hardware boundaries.",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = runtime_settings
    app.state.robot_service = resolved_robot_service
    app.state.kinematics_service = services.kinematics
    app.state.motion_service = services.motion
    app.state.jog_service = services.jog
    app.state.library_service = services.library
    app.state.trajectory_service = services.trajectory
    app.state.studio_service = services.studio
    app.state.vision_service = services.vision
    app.state.playback_service = services.playback
    app.state.playback_observer = services.playback_observer
    app.state.security_service = release.security
    app.state.backup_service = release.backup
    app.state.device_diagnostics_service = release.device
    app.state.calibration_workflow_coordinator = release.calibration
    app.state.real_calibration_repository = release.real_calibrations
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_body_bytes=release.security.policy.max_request_body_bytes,
    )
    app.add_middleware(StrictOriginMiddleware, service=release.security)
    app.add_middleware(StructuredRequestAuditMiddleware, service=release.security)
    install_error_handlers(app)
    rest_dependencies = [Depends(authorize_rest_request)]
    vision_dependencies = [Depends(authorize_vision_request)]
    app.include_router(security_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1", dependencies=rest_dependencies)
    app.include_router(meta_router, prefix="/api/v1", dependencies=rest_dependencies)
    app.include_router(robot_router, prefix="/api/v1", dependencies=rest_dependencies)
    app.include_router(calibration_router, prefix="/api/v1", dependencies=rest_dependencies)
    app.include_router(kinematics_router, prefix="/api/v1", dependencies=rest_dependencies)
    app.include_router(motion_router, prefix="/api/v1", dependencies=rest_dependencies)
    app.include_router(library_router, prefix="/api/v1", dependencies=rest_dependencies)
    app.include_router(playback_router, prefix="/api/v1", dependencies=rest_dependencies)
    app.include_router(studio_router, prefix="/api/v1", dependencies=rest_dependencies)
    app.include_router(vision_router, prefix="/api/v1", dependencies=vision_dependencies)
    app.include_router(device_router, prefix="/api/v1", dependencies=rest_dependencies)
    app.include_router(
        device_calibration_router,
        prefix="/api/v1",
        dependencies=rest_dependencies,
    )
    app.include_router(backup_router, prefix="/api/v1")
    app.include_router(ws_robot_router, prefix="/api/v1")
    if runtime_settings.serve_frontend_static:
        configured = Path(runtime_settings.frontend_dist_directory)
        distribution = (
            configured.resolve()
            if configured.is_absolute()
            else (repository_root() / configured).resolve()
        )
        app.mount("/", SpaStaticFiles(distribution), name="frontend")
    return app
