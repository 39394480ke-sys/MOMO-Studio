"""Stage 3 API surface and hardware isolation contract tests."""

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
        version="0.1.0-rc1",
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
        "version": "0.1.0-rc1",
        "stage": 8,
        "control_mode": "DRY_RUN",
        "hardware_access_policy": "DISABLED",
        "real_motion_enabled": False,
    }


def test_meta_and_product_scope_apis() -> None:
    app = make_app()
    response = get(app, "/api/v1/meta")
    assert response.status_code == 200
    assert response.json()["supported_robot_variants"] == ["V1", "V2"]
    assert response.json()["active_robot_variant"] == "V2"
    assert response.json()["real_motion_enabled"] is False
    assert response.json()["release_status"] == "FIELD_ACCEPTANCE_REQUIRED"
    assert response.json()["dry_run_validated"] is True
    assert response.json()["real_hardware_field_acceptance"] == "PENDING"

    scope_response = get(app, "/api/v1/meta/product-scope")
    assert scope_response.status_code == 200
    scope = scope_response.json()
    assert scope["stage"] == 8
    assert "mesh-free FK and IK" in scope["stage_3_available"]
    assert "coherent FK-backed Pose capture" in scope["stage_4_available"]
    assert (
        "whole-plan preflight with immutable digest-bound prepared trajectories"
        in scope["stage_5_available"]
    )
    assert (
        "atomic recoverable MotionDraft autosave with revision conflicts"
        in scope["stage_6_available"]
    )
    assert (
        "lease-bound Dry Run Follow through the Motion Safety Gateway" in scope["stage_7_available"]
    )
    assert (
        "deny-by-default Real readiness and short-lived Operator Sessions"
        in scope["stage_8_available"]
    )
    assert scope["release"] == "first_version"
    assert "single active MOMO V1 or V2 robot" in scope["included_in_first_version"]
    assert "photo, video recording, or media management" in scope["excluded_from_first_version"]


def test_stage_eight_exposes_reviewed_api_and_read_only_websocket() -> None:
    app = create_app(Settings(control_mode=ControlMode.DRY_RUN, real_motion_enabled=False))
    api_paths = {path: frozenset(methods) for path, methods in app.openapi()["paths"].items()}
    assert api_paths == {
        "/api/v1/backup/export": frozenset({"post"}),
        "/api/v1/backup/import/preview": frozenset({"post"}),
        "/api/v1/backup/import/restore": frozenset({"post"}),
        "/api/v1/calibration/status": frozenset({"get"}),
        "/api/v1/device/connect": frozenset({"post"}),
        "/api/v1/device/calibration/rollback": frozenset({"post"}),
        "/api/v1/device/calibration/sessions": frozenset({"post"}),
        "/api/v1/device/calibration/sessions/{session_id}": frozenset({"get", "delete"}),
        "/api/v1/device/calibration/sessions/{session_id}/complete": frozenset({"post"}),
        "/api/v1/device/calibration/sessions/{session_id}/confirm": frozenset({"post"}),
        "/api/v1/device/calibration/sessions/{session_id}/preview": frozenset({"post"}),
        "/api/v1/device/calibration/sessions/{session_id}/read": frozenset({"post"}),
        "/api/v1/device/commissioning/joints/{joint_id}/arm": frozenset({"post"}),
        "/api/v1/device/commissioning/joints/{joint_id}/tests/start": frozenset({"post"}),
        "/api/v1/device/commissioning/session": frozenset({"post"}),
        "/api/v1/device/commissioning/status": frozenset({"get"}),
        "/api/v1/device/commissioning/tests/heartbeat": frozenset({"post"}),
        "/api/v1/device/commissioning/tests/stop": frozenset({"post"}),
        "/api/v1/device/diagnostics": frozenset({"post"}),
        "/api/v1/device/disconnect": frozenset({"post"}),
        "/api/v1/device/field-acceptance": frozenset({"get", "post"}),
        "/api/v1/device/field-acceptance/joint-motion": frozenset({"post"}),
        "/api/v1/device/field-acceptance/pre-motion-checks": frozenset({"post"}),
        "/api/v1/device/field-acceptance/progress": frozenset({"get"}),
        "/api/v1/device/operator-session": frozenset({"post", "delete"}),
        "/api/v1/device/readiness": frozenset({"get"}),
        "/api/v1/device/stop": frozenset({"post"}),
        "/api/v1/health": frozenset({"get"}),
        "/api/v1/kinematics/ik": frozenset({"post"}),
        "/api/v1/kinematics-verification": frozenset({"get"}),
        "/api/v1/kinematics-verification/draft": frozenset({"post"}),
        "/api/v1/kinematics-verification/draft/{draft_id}/commit": frozenset({"post"}),
        "/api/v1/kinematics-verification/draft/{draft_id}/measurement": frozenset({"post"}),
        "/api/v1/meta": frozenset({"get"}),
        "/api/v1/meta/product-scope": frozenset({"get"}),
        "/api/v1/motion/cartesian-jog": frozenset({"post"}),
        "/api/v1/motion/commands/{command_id}": frozenset({"get"}),
        "/api/v1/motion/home": frozenset({"post"}),
        "/api/v1/motion/jog-step": frozenset({"post"}),
        "/api/v1/motion/jog/start": frozenset({"post"}),
        "/api/v1/motion/jog/{session_id}/heartbeat": frozenset({"post"}),
        "/api/v1/motion/jog/{session_id}/stop": frozenset({"post"}),
        "/api/v1/motion/joints": frozenset({"post"}),
        "/api/v1/motion/pose": frozenset({"post"}),
        "/api/v1/motion/stop": frozenset({"post"}),
        "/api/v1/motions": frozenset({"get", "post"}),
        "/api/v1/motions/{motion_id}": frozenset({"get", "patch", "delete"}),
        "/api/v1/motions/{motion_id}/duplicate": frozenset({"post"}),
        "/api/v1/motions/{motion_id}/play": frozenset({"post"}),
        "/api/v1/motions/{motion_id}/preflight": frozenset({"post"}),
        "/api/v1/playback": frozenset({"get"}),
        "/api/v1/playback/loop": frozenset({"put"}),
        "/api/v1/playback/pause": frozenset({"post"}),
        "/api/v1/playback/rate": frozenset({"put"}),
        "/api/v1/playback/resume": frozenset({"post"}),
        "/api/v1/playback/stop": frozenset({"post"}),
        "/api/v1/poses": frozenset({"get", "post"}),
        "/api/v1/poses/capture": frozenset({"post"}),
        "/api/v1/poses/{pose_id}": frozenset({"get", "patch", "delete"}),
        "/api/v1/poses/{pose_id}/duplicate": frozenset({"post"}),
        "/api/v1/poses/{pose_id}/goto": frozenset({"post"}),
        "/api/v1/robot": frozenset({"get"}),
        "/api/v1/robot/connect": frozenset({"post"}),
        "/api/v1/robot/diagnostics": frozenset({"get"}),
        "/api/v1/robot/disconnect": frozenset({"post"}),
        "/api/v1/robot/fk": frozenset({"get"}),
        "/api/v1/robot/profile": frozenset({"get"}),
        "/api/v1/robot/stop": frozenset({"post"}),
        "/api/v1/robot/variant": frozenset({"put"}),
        "/api/v1/security/session": frozenset({"post", "delete"}),
        "/api/v1/studio/capture": frozenset({"post"}),
        "/api/v1/studio/drafts": frozenset({"get", "post"}),
        "/api/v1/studio/drafts/from-motion/{motion_id}": frozenset({"post"}),
        "/api/v1/studio/drafts/{draft_id}": frozenset({"get", "put", "delete"}),
        "/api/v1/studio/drafts/{draft_id}/compile": frozenset({"post"}),
        "/api/v1/studio/drafts/{draft_id}/fork": frozenset({"post"}),
        "/api/v1/studio/drafts/{draft_id}/keyframes/{keyframe_id}/goto": frozenset({"post"}),
        "/api/v1/studio/drafts/{draft_id}/save": frozenset({"post"}),
        "/api/v1/studio/drafts/{draft_id}/save-as": frozenset({"post"}),
        "/api/v1/studio/drafts/{draft_id}/save-intent/abandon": frozenset({"post"}),
        "/api/v1/studio/drafts/{draft_id}/validate": frozenset({"post"}),
        "/api/v1/trajectory/{digest}/preview": frozenset({"get"}),
        "/api/v1/vision/capabilities": frozenset({"get"}),
        "/api/v1/vision/detect/{detector}": frozenset({"post"}),
        "/api/v1/vision/follow/start": frozenset({"post"}),
        "/api/v1/vision/follow/{lease_id}/heartbeat": frozenset({"post"}),
        "/api/v1/vision/follow/{lease_id}/stop": frozenset({"post"}),
        "/api/v1/vision/frame": frozenset({"get"}),
        "/api/v1/vision/selection": frozenset({"post", "delete"}),
        "/api/v1/vision/status": frozenset({"get"}),
        "/api/v1/vision/stream": frozenset({"get"}),
        "/api/v1/vision/tracking/reset": frozenset({"post"}),
    }
    assert app.openapi()["paths"]["/api/v1/device/field-acceptance"]["post"]["deprecated"] is True

    route_tree = list(iter_route_tree(app.routes))
    websocket_routes = [route for route in route_tree if isinstance(route, WebSocketRoute)]
    assert len(websocket_routes) == 1
    assert websocket_routes[0].path == "/ws/robot"
    assert not any(isinstance(route, Mount) for route in route_tree)
    custom_http_routes = [route for route in route_tree if isinstance(route, APIRoute)]
    paths = {route.path.lower() for route in custom_http_routes}
    assert not any(token in path for path in paths for token in ("raw-servo", "serial", "camera"))
