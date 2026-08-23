"""Side-effect-free FastAPI application factory."""

from fastapi import FastAPI

from momo.api.routes.health import router as health_router
from momo.api.routes.meta import router as meta_router
from momo.settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API without connecting hardware or starting background workers."""

    resolved_settings = settings if settings is not None else load_settings()
    app = FastAPI(
        title=f"{resolved_settings.product_name} API",
        version=resolved_settings.version,
        description="Stage 1 metadata API; it exposes no hardware or motion commands.",
    )
    app.state.settings = resolved_settings
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(meta_router, prefix="/api/v1")
    return app
