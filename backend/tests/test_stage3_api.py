"""Stage 3 REST and read-only WebSocket integration contracts."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient

import momo.api.routes.ws_robot as ws_robot_route
from momo.api.app import create_app
from momo.settings import Settings


def make_app(tmp_path: Path) -> FastAPI:
    return create_app(
        Settings(
            runtime_state_directory=str(tmp_path / "runtime"),
            calibration_directory=str(tmp_path / "no-calibration"),
        )
    )


async def request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json_data: object | None = None,
    content: bytes | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        if content is not None:
            return await client.request(
                method,
                path,
                content=content,
                headers={"content-type": "application/json"},
            )
        return await client.request(method, path, json=json_data)


def common_fields(status: dict[str, Any], fk: dict[str, Any], key: str) -> dict[str, Any]:
    return {
        "expected_state_sequence": status["state_sequence"],
        "expected_profile_fingerprint": status["profile_fingerprint"],
        "expected_kinematics_fingerprint": fk["kinematics_fingerprint"],
        "source": "CONTROL",
        "idempotency_key": key,
        "speed_scale": 1.0,
    }


def test_fk_ik_and_joint_motion_round_trip_use_explicit_contracts(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_app(tmp_path)
        connected = await request(app, "POST", "/api/v1/robot/connect")
        assert connected.status_code == 200
        status = connected.json()["status"]

        fk_response = await request(app, "GET", "/api/v1/robot/fk")
        assert fk_response.status_code == 200
        fk = fk_response.json()
        assert fk["hardware_accessed"] is False
        assert fk["tcp_pose"]["frame"] == "base"
        assert fk["state_sequence"] == status["state_sequence"]

        ik_response = await request(
            app,
            "POST",
            "/api/v1/kinematics/ik",
            json_data={
                "target_pose": fk["tcp_pose"],
                "position_unit": "mm",
                "orientation_unit": "quaternion_xyzw",
                "seed_joint_state": {
                    "positions": status["positions"],
                    "units": status["units"],
                },
                "position_only": False,
            },
        )
        assert ik_response.status_code == 200
        assert ik_response.json()["success"] is True
        assert ik_response.json()["position_error_mm"] == 0.0
        assert ik_response.json()["joint_state_optional"]["units"] == status["units"]
        assert ik_response.json()["best_joint_state"]["units"] == status["units"]

        target = dict(status["positions"])
        target["j11"] += 5.0
        body = {
            **common_fields(status, fk, "api-joint-move"),
            "joint_state": {"positions": target, "units": status["units"]},
            "duration_s": 1.0,
        }
        accepted = await request(app, "POST", "/api/v1/motion/joints", json_data=body)
        assert accepted.status_code == 202, accepted.text
        command_id = accepted.json()["command_id"]
        assert accepted.json()["preflight"]["accepted"] is True

        command = await request(app, "GET", f"/api/v1/motion/commands/{command_id}")
        assert command.status_code == 200
        assert command.json()["hardware_accessed"] is False
        stopped = await request(app, "POST", "/api/v1/motion/stop")
        assert stopped.status_code == 200
        assert stopped.json()["hardware_accessed"] is False

    asyncio.run(scenario())


def test_public_control_routes_reject_source_impersonation_and_require_home_confirmation(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = make_app(tmp_path)
        status = (await request(app, "POST", "/api/v1/robot/connect")).json()["status"]
        fk = (await request(app, "GET", "/api/v1/robot/fk")).json()
        target = dict(status["positions"])
        target["j11"] += 1.0
        impersonation = {
            **common_fields(status, fk, "impersonation"),
            "source": "LIBRARY",
            "joint_state": {"positions": target, "units": status["units"]},
            "duration_s": 1.0,
        }
        response = await request(app, "POST", "/api/v1/motion/joints", json_data=impersonation)
        assert response.status_code == 422

        invalid_home = {
            **common_fields(status, fk, "bad-home"),
            "confirm": "YES",
            "duration_s": 2.0,
        }
        response = await request(app, "POST", "/api/v1/motion/home", json_data=invalid_home)
        assert response.status_code == 422

    asyncio.run(scenario())


def test_cartesian_pose_and_ik_unit_markers_are_required(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_app(tmp_path)
        status = (await request(app, "POST", "/api/v1/robot/connect")).json()["status"]
        fk = (await request(app, "GET", "/api/v1/robot/fk")).json()
        common = common_fields(status, fk, "required-units")
        cases = (
            (
                "/api/v1/motion/joints",
                {
                    **common,
                    "joint_state": {"positions": status["positions"]},
                    "duration_s": 1.0,
                },
            ),
            (
                "/api/v1/motion/cartesian-jog",
                {
                    **common,
                    "delta_position_mm": {"x": 1.0, "y": 0.0, "z": 0.0},
                    "delta_rotation_deg": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "frame": "BASE",
                    "duration_s": 1.0,
                },
            ),
            (
                "/api/v1/motion/pose",
                {**common, "target_pose": fk["tcp_pose"], "duration_s": 1.0},
            ),
            (
                "/api/v1/kinematics/ik",
                {"target_pose": fk["tcp_pose"]},
            ),
            (
                "/api/v1/kinematics/ik",
                {
                    "target_pose": fk["tcp_pose"],
                    "position_unit": "mm",
                    "orientation_unit": "quaternion_xyzw",
                    "seed_joint_state": {"positions": status["positions"]},
                },
            ),
        )
        for path, body in cases:
            response = await request(app, "POST", path, json_data=body)
            assert response.status_code == 422, (path, response.text)

    asyncio.run(scenario())


def test_motion_http_dtos_reject_boolean_string_nonfinite_and_tiny_numeric_intent(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = make_app(tmp_path)
        status = (await request(app, "POST", "/api/v1/robot/connect")).json()["status"]
        fk = (await request(app, "GET", "/api/v1/robot/fk")).json()

        async def rejected(path: str, body: dict[str, Any]) -> None:
            response = await request(app, "POST", path, json_data=body)
            assert response.status_code == 422, (path, body, response.text)

        base = common_fields(status, fk, "strict")
        await rejected(
            "/api/v1/motion/jog/start",
            {
                **base,
                "direction": True,
                "joint_id": "j11",
                "speed_units_s": 10.0,
                "unit": "deg",
            },
        )
        await rejected(
            "/api/v1/motion/jog/start",
            {
                **base,
                "direction": 1,
                "joint_id": "j11",
                "speed_units_s": True,
                "unit": "deg",
            },
        )
        await rejected(
            "/api/v1/motion/jog-step",
            {
                **base,
                "joint_id": "j11",
                "delta": True,
                "unit": "deg",
                "duration_s": 1.0,
            },
        )
        await rejected(
            "/api/v1/motion/cartesian-jog",
            {
                **base,
                "delta_position_mm": {"x": True, "y": 0.0, "z": 0.0},
                "delta_rotation_deg": {"x": 0.0, "y": 0.0, "z": 0.0},
                "frame": "BASE",
                "translation_unit": "mm",
                "rotation_unit": "deg",
                "duration_s": 1.0,
            },
        )
        string_target = dict(status["positions"])
        string_target["j11"] = "1.2"
        await rejected(
            "/api/v1/motion/joints",
            {
                **base,
                "joint_state": {"positions": string_target, "units": status["units"]},
                "duration_s": 1.0,
            },
        )
        await rejected(
            "/api/v1/motion/home",
            {**base, "confirm": "HOME", "duration_s": True},
        )
        await rejected(
            "/api/v1/motion/home",
            {**base, "speed_scale": 0.000001, "confirm": "HOME", "duration_s": 2.0},
        )
        await rejected(
            "/api/v1/motion/home",
            {
                **base,
                "expected_state_sequence": True,
                "confirm": "HOME",
                "duration_s": 2.0,
            },
        )
        await rejected(
            "/api/v1/kinematics/ik",
            {
                "target_pose": fk["tcp_pose"],
                "position_unit": "mm",
                "orientation_unit": "quaternion_xyzw",
                "maximum_iterations": True,
            },
        )

        nan_body = {
            **base,
            "joint_id": "j11",
            "delta": float("nan"),
            "unit": "deg",
            "duration_s": 1.0,
        }
        nan_response = await request(
            app,
            "POST",
            "/api/v1/motion/jog-step",
            content=json.dumps(nan_body).encode(),
        )
        assert nan_response.status_code == 422

    asyncio.run(scenario())


def test_continuous_jog_rest_lifecycle_returns_202_and_stops_by_session(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_app(tmp_path)
        status = (await request(app, "POST", "/api/v1/robot/connect")).json()["status"]
        fk = (await request(app, "GET", "/api/v1/robot/fk")).json()
        start = await request(
            app,
            "POST",
            "/api/v1/motion/jog/start",
            json_data={
                **common_fields(status, fk, "api-hold-jog"),
                "joint_id": "j11",
                "direction": 1,
                "speed_units_s": 10.0,
                "unit": "deg",
            },
        )
        assert start.status_code == 202, start.text
        lease = start.json()
        assert 250 <= lease["lease_expires_in_ms"] <= 500

        heartbeat = await request(
            app,
            "POST",
            f"/api/v1/motion/jog/{lease['jog_session_id']}/heartbeat",
        )
        assert heartbeat.status_code == 200
        stopped = await request(
            app,
            "POST",
            f"/api/v1/motion/jog/{lease['jog_session_id']}/stop",
        )
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "CANCELLED"

    asyncio.run(scenario())


def test_global_stop_marks_jog_lease_stopped_and_disconnect_cancels_motion(tmp_path: Path) -> None:
    async def start_jog(app: FastAPI, key: str) -> dict[str, Any]:
        status = (await request(app, "GET", "/api/v1/robot")).json()
        fk = (await request(app, "GET", "/api/v1/robot/fk")).json()
        response = await request(
            app,
            "POST",
            "/api/v1/motion/jog/start",
            json_data={
                **common_fields(status, fk, key),
                "joint_id": "j11",
                "direction": 1,
                "speed_units_s": 10.0,
                "unit": "deg",
            },
        )
        assert response.status_code == 202, response.text
        return cast(dict[str, Any], response.json())

    async def scenario() -> None:
        app = make_app(tmp_path)
        await request(app, "POST", "/api/v1/robot/connect")
        first = await start_jog(app, "global-stop")
        stopped = await request(app, "POST", "/api/v1/robot/stop")
        assert stopped.status_code == 200
        first_status = await request(app, "GET", f"/api/v1/motion/commands/{first['command_id']}")
        assert first_status.json()["state"] == "CANCELLED"
        expired = await request(
            app,
            "POST",
            f"/api/v1/motion/jog/{first['jog_session_id']}/heartbeat",
        )
        assert expired.status_code == 409
        assert expired.json()["code"] == "JOG_LEASE_EXPIRED"

        second = await start_jog(app, "disconnect-stop")
        disconnected = await request(app, "POST", "/api/v1/robot/disconnect")
        assert disconnected.status_code == 200
        assert disconnected.json()["status"]["connection_state"] == "DISCONNECTED"
        second_status = await request(app, "GET", f"/api/v1/motion/commands/{second['command_id']}")
        assert second_status.json()["state"] == "CANCELLED"

    asyncio.run(scenario())


def test_every_long_running_rest_operation_declares_202(tmp_path: Path) -> None:
    schema = make_app(tmp_path).openapi()["paths"]
    for path in (
        "/api/v1/motion/joints",
        "/api/v1/motion/jog-step",
        "/api/v1/motion/cartesian-jog",
        "/api/v1/motion/pose",
        "/api/v1/motion/home",
        "/api/v1/motion/jog/start",
    ):
        assert "202" in schema[path]["post"]["responses"], path


def test_robot_websocket_is_read_only_and_contains_full_fk_status(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    with TestClient(app) as client:
        connected = client.post("/api/v1/robot/connect")
        assert connected.status_code == 200
        status = connected.json()["status"]
        fk = client.get("/api/v1/robot/fk").json()
        target = dict(status["positions"])
        target["j11"] += 5.0
        accepted = client.post(
            "/api/v1/motion/joints",
            json={
                **common_fields(status, fk, "ws-terminal"),
                "joint_state": {"positions": target, "units": status["units"]},
                "duration_s": 1.0,
            },
        )
        assert accepted.status_code == 202
        assert client.post("/api/v1/motion/stop").status_code == 200
        with client.websocket_connect(
            "/api/v1/ws/robot",
            headers={"origin": "http://127.0.0.1:8000"},
        ) as websocket:
            payload = websocket.receive_json()

    assert payload["hardware_accessed"] is False
    assert payload["robot_status"]["connection_state"] == "CONNECTED"
    assert payload["state_sequence"] == payload["robot_status"]["state_sequence"]
    assert payload["forward_kinematics"]["tcp_pose"] == payload["tcp_pose"]
    assert len(payload["forward_kinematics"]["profile_fingerprint"]) == 64
    assert len(payload["forward_kinematics"]["kinematics_fingerprint"]) == 64
    assert payload["command_status"]["command_id"] == accepted.json()["command_id"]
    assert payload["command_status"]["state"] == "CANCELLED"
    assert not any(
        forbidden in path.lower()
        for path in app.openapi()["paths"]
        for forbidden in ("raw-servo", "serial", "camera")
    )


def test_robot_websocket_rate_cap_and_disconnect_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DisconnectingWebSocket:
        def __init__(self, app: FastAPI) -> None:
            self.app = app
            self.headers = {"origin": "http://127.0.0.1:8000"}
            self.cookies: dict[str, str] = {}
            self.query_params: dict[str, str] = {}
            self.state = SimpleNamespace()
            self.accepted = False
            self.payloads: list[dict[str, Any]] = []

        async def accept(self) -> None:
            self.accepted = True

        async def send_json(self, payload: dict[str, Any]) -> None:
            self.payloads.append(payload)
            if len(self.payloads) == 3:
                raise WebSocketDisconnect(code=1001)

    async def scenario() -> None:
        app = make_app(tmp_path)
        await app.state.robot_service.connect()
        websocket = DisconnectingWebSocket(app)
        delays: list[float] = []

        async def record_rate_limit() -> None:
            delays.append(ws_robot_route.WS_UPDATE_INTERVAL_S)

        monkeypatch.setattr(ws_robot_route, "_wait_for_next_publish", record_rate_limit)
        await asyncio.wait_for(
            ws_robot_route.robot_state_socket(cast(WebSocket, websocket)),
            timeout=0.2,
        )

        assert websocket.accepted is True
        assert len(websocket.payloads) == 3
        assert delays == [0.1, 0.1]
        assert ws_robot_route.WS_UPDATE_HZ == 10.0

    asyncio.run(scenario())


def test_robot_websocket_slow_send_is_cancelled_without_queue_growth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowWebSocket:
        def __init__(self, app: FastAPI) -> None:
            self.app = app
            self.headers = {"origin": "http://127.0.0.1:8000"}
            self.cookies: dict[str, str] = {}
            self.query_params: dict[str, str] = {}
            self.state = SimpleNamespace()
            self.accepted = False
            self.in_flight = 0
            self.maximum_in_flight = 0
            self.cancelled = False

        async def accept(self) -> None:
            self.accepted = True

        async def send_json(self, payload: dict[str, Any]) -> None:
            del payload
            self.in_flight += 1
            self.maximum_in_flight = max(self.maximum_in_flight, self.in_flight)
            try:
                await asyncio.Event().wait()
            finally:
                self.in_flight -= 1
                self.cancelled = True

    async def scenario() -> None:
        app = make_app(tmp_path)
        await app.state.robot_service.connect()
        websocket = SlowWebSocket(app)
        monkeypatch.setattr(ws_robot_route, "WS_SEND_TIMEOUT_S", 0.01)
        await asyncio.wait_for(
            ws_robot_route.robot_state_socket(cast(WebSocket, websocket)),
            timeout=0.2,
        )

        assert websocket.accepted is True
        assert websocket.cancelled is True
        assert websocket.in_flight == 0
        assert websocket.maximum_in_flight == 1

    asyncio.run(scenario())
