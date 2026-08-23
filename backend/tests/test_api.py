"""Read-only Stage 1 API contract tests (requirements 17, 18, and 20)."""

import asyncio
from collections.abc import Iterable, Iterator
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.routing import Mount, WebSocketRoute

from momo.api.app import create_app
from momo.domain.enums import ControlMode, RobotVariant
from momo.settings import Settings


def make_app() -> FastAPI:
    settings = Settings(
        product_name="MOMO Studio",
        version="0.1.0",
        control_mode=ControlMode.DRY_RUN,
        real_motion_enabled=False,
        active_robot_variant=RobotVariant.V2,
    )
    return create_app(settings)


def get(app: FastAPI, path: str) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    return asyncio.run(send())


def iter_route_tree(routes: Iterable[Any]) -> Iterator[Any]:
    for route in routes:
        yield route
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            yield from iter_route_tree(original_router.routes)
        nested_routes = getattr(route, "routes", None)
        if nested_routes is not None:
            yield from iter_route_tree(nested_routes)


def test_health_api_is_dry_run_and_real_motion_is_disabled() -> None:
    response = get(make_app(), "/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "product": "MOMO Studio",
        "version": "0.1.0",
        "control_mode": "DRY_RUN",
        "real_motion_enabled": False,
    }


def test_meta_and_product_scope_apis() -> None:
    app = make_app()
    response = get(app, "/api/v1/meta")
    assert response.status_code == 200
    assert response.json()["supported_robot_variants"] == ["V1", "V2"]
    assert response.json()["active_robot_variant"] == "V2"
    assert response.json()["real_motion_enabled"] is False

    scope_response = get(app, "/api/v1/meta/product-scope")
    assert scope_response.status_code == 200
    scope = scope_response.json()
    assert scope["stage"] == 1
    assert scope["release"] == "first_version"
    assert "single active MOMO V1 or V2 robot" in scope["included_in_first_version"]
    assert "photo, video recording, or media management" in scope["excluded_from_first_version"]


def test_stage_one_exposes_no_motion_or_hardware_command_api() -> None:
    app = create_app(Settings(control_mode=ControlMode.DRY_RUN, real_motion_enabled=False))
    api_paths = {path: frozenset(methods) for path, methods in app.openapi()["paths"].items()}
    assert api_paths == {
        "/api/v1/health": frozenset({"get"}),
        "/api/v1/meta": frozenset({"get"}),
        "/api/v1/meta/product-scope": frozenset({"get"}),
    }

    route_tree = list(iter_route_tree(app.routes))
    assert not any(isinstance(route, (Mount, WebSocketRoute)) for route in route_tree)
    custom_http_routes = [route for route in route_tree if isinstance(route, APIRoute)]
    assert {(route.path, frozenset(route.methods or set())) for route in custom_http_routes} == {
        ("/health", frozenset({"GET"})),
        ("/meta", frozenset({"GET"})),
        ("/meta/product-scope", frozenset({"GET"})),
    }
