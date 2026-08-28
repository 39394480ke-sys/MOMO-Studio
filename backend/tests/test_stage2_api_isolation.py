"""Stage 2 HTTP contracts and proof that product startup has no hardware path."""

from __future__ import annotations

import ast
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI

from momo.api.app import create_app
from momo.application.services.robot_service import RobotApplicationService
from momo.domain.enums import RobotVariant
from momo.settings import Settings, repository_root


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
        if json_data is not None:
            return await client.request(method, path, json=json_data)
        return await client.request(method, path, content=content)


def make_app(tmp_path: Path) -> FastAPI:
    return create_app(Settings(runtime_state_directory=str(tmp_path / "runtime")))


def test_all_stage_two_read_endpoints_return_safe_backend_state(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    async def scenario() -> None:
        for path in (
            "/api/v1/health",
            "/api/v1/meta",
            "/api/v1/robot",
            "/api/v1/robot/profile",
            "/api/v1/robot/diagnostics",
            "/api/v1/calibration/status",
        ):
            response = await request(app, "GET", path)
            assert response.status_code == 200, (path, response.text)
            assert "Traceback" not in response.text

        status = (await request(app, "GET", "/api/v1/robot")).json()
        assert status["control_mode"] == "DRY_RUN"
        assert status["hardware_access_policy"] == "DISABLED"
        assert status["hardware_accessed"] is False
        assert status["units"]["j10"] == "mm"

        profile = (await request(app, "GET", "/api/v1/robot/profile")).json()
        assert profile["profile"]["variant"] == "V2"
        assert profile["real_eligible"] is False
        assert len(profile["fingerprint"]) == 64

        calibration = (await request(app, "GET", "/api/v1/calibration/status")).json()
        assert calibration["status"] == "TEMPLATE_ONLY"
        assert calibration["real_readiness"] == "BLOCKED_BY_STAGE_POLICY"

        diagnostics = (await request(app, "GET", "/api/v1/robot/diagnostics")).json()
        assert diagnostics["hardware_access_policy"] == "DISABLED"
        assert diagnostics["hardware_accessed"] is False
        assert not diagnostics["runtime_state_path"].startswith("/")
        assert str(tmp_path) not in diagnostics["runtime_state_path"]

    asyncio.run(scenario())


def test_lifecycle_endpoints_are_idempotent_and_never_claim_hardware_access(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)

    async def scenario() -> None:
        first_stop = await request(app, "POST", "/api/v1/robot/stop")
        second_stop = await request(app, "POST", "/api/v1/robot/stop")
        assert first_stop.json()["result"] == second_stop.json()["result"] == "NOT_CONNECTED"

        connected = await request(app, "POST", "/api/v1/robot/connect")
        assert connected.status_code == 200
        assert connected.json()["status"]["connection_state"] == "CONNECTED"
        assert connected.json()["hardware_accessed"] is False

        stopped = await request(app, "POST", "/api/v1/robot/stop")
        assert stopped.json()["result"] == "STOPPED"
        assert stopped.json()["hardware_accessed"] is False

        disconnected = await request(app, "POST", "/api/v1/robot/disconnect")
        repeated = await request(app, "POST", "/api/v1/robot/disconnect")
        assert disconnected.status_code == repeated.status_code == 200
        assert repeated.json()["status"]["connection_state"] == "DISCONNECTED"
        assert repeated.json()["hardware_accessed"] is False

    asyncio.run(scenario())


def test_variant_switch_and_invalid_variant_use_structured_contracts(tmp_path: Path) -> None:
    app = make_app(tmp_path)

    async def scenario() -> None:
        switched = await request(
            app,
            "PUT",
            "/api/v1/robot/variant",
            json_data={"variant": RobotVariant.V1.value},
        )
        assert switched.status_code == 200
        assert set(switched.json()["status"]["positions"]) == {
            "j11",
            "j12",
            "j13",
            "j14",
            "j15",
        }

        invalid = await request(
            app,
            "PUT",
            "/api/v1/robot/variant",
            json_data={"variant": "V3"},
        )
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "REQUEST_VALIDATION_ERROR"
        assert set(invalid.json()) == {"code", "message", "details", "request_id"}
        assert "Traceback" not in invalid.text

        await request(app, "POST", "/api/v1/robot/connect")
        blocked = await request(
            app,
            "PUT",
            "/api/v1/robot/variant",
            json_data={"variant": "V2"},
        )
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "VARIANT_SWITCH_WHILE_CONNECTED"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("path", "json_data", "content"),
    [
        ("/api/v1/robot/connect?mode=REAL", None, None),
        ("/api/v1/robot/connect", {"mode": "REAL"}, None),
        ("/api/v1/robot/connect", None, b"{}"),
    ],
)
def test_connect_rejects_every_client_request_for_a_mode(
    tmp_path: Path,
    path: str,
    json_data: object | None,
    content: bytes | None,
) -> None:
    response = asyncio.run(
        request(
            make_app(tmp_path),
            "POST",
            path,
            json_data=json_data,
            content=content,
        )
    )
    assert response.status_code == 422
    assert response.json()["code"] == "PROFILE_INVALID"
    assert "Traceback" not in response.text


class ExplodingRobotService:
    async def get_status(self) -> None:
        raise RuntimeError("sensitive internal detail")


def test_unexpected_backend_errors_do_not_leak_tracebacks(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    app.state.robot_service = cast(RobotApplicationService, ExplodingRobotService())
    response = asyncio.run(request(app, "GET", "/api/v1/robot"))
    assert response.status_code == 500
    assert response.json() == {
        "code": "INTERNAL_ERROR",
        "message": "An internal error occurred",
        "details": {},
        "request_id": None,
    }
    assert "sensitive internal detail" not in response.text
    assert "Traceback" not in response.text


def test_backend_source_has_no_serial_feetech_or_camera_imports() -> None:
    forbidden_roots = {
        "cv2",
        "feetech",
        "picamera",
        "picamera2",
        "pyrealsense2",
        "scservo_sdk",
        "serial",
        "serial_asyncio",
        "sts",
    }
    source_root = repository_root() / "backend" / "src" / "momo"
    observed: set[str] = set()
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                observed.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                observed.add(node.module.split(".", 1)[0])
    assert observed.isdisjoint(forbidden_roots)


def test_application_layer_never_imports_concrete_adapters() -> None:
    application_root = repository_root() / "backend" / "src" / "momo" / "application"
    violations: list[str] = []
    for path in application_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports = [node.module]
            else:
                continue
            if any(name.startswith("momo.adapters") for name in imports):
                violations.append(str(path.relative_to(application_root)))
    assert violations == []


def test_fresh_api_startup_succeeds_with_hardware_imports_blocked(tmp_path: Path) -> None:
    script = """
import sys
class HardwareImportBlocker:
    def find_spec(self, fullname, path=None, target=None):
        forbidden = {
            'cv2', 'serial', 'serial_asyncio', 'feetech', 'picamera',
            'picamera2', 'pyrealsense2', 'scservo_sdk', 'sts'
        }
        if fullname.split('.', 1)[0] in forbidden:
            raise RuntimeError(f'forbidden hardware import: {fullname}')
        return None
sys.meta_path.insert(0, HardwareImportBlocker())
from momo.api.app import create_app
from momo.settings import Settings
app = create_app(Settings(runtime_state_directory=sys.argv[1]))
paths = app.openapi()['paths']
assert '/api/v1/motion/joints' in paths
assert '/api/v1/kinematics/ik' in paths
assert all(
    'raw-servo' not in path and 'serial' not in path
    for path in paths
)
assert {path for path in paths if 'camera' in path} == {
    '/api/v1/vision/camera/close',
    '/api/v1/vision/camera/open',
}
print('hardware-isolated-startup-ok')
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository_root() / "backend" / "src")
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "runtime")],
        cwd=repository_root(),
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "hardware-isolated-startup-ok"
