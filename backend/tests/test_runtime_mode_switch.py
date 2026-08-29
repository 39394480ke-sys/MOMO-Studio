"""Supervised local DRY_RUN/REAL selection without hardware access."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import yaml

from momo.api.app import create_app
from momo.domain.enums import ControlMode, HardwareAccessPolicy
from momo.runtime_mode import LocalRuntimeModeController


def real_local_config(path: Path) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "control_mode": "REAL",
                "hardware_access": "READ_ONLY",
                "hardware_local_config_enabled": True,
                "hardware_startup_enabled": True,
                "feetech_read_only_adapter_enabled": True,
                "robot_unit_id": "MOMO-V2-TEST",
                "serial_port": "/dev/tty.test",
                "servo_protocol": "STS3215",
                "servo_ids": [10, 11, 12, 13, 14, 15],
                "runtime_state_directory": str(path.parent / "runtime"),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def test_controller_derives_dry_run_without_mutating_real_device_config(tmp_path: Path) -> None:
    local = real_local_config(tmp_path / "local.yaml")
    original = local.read_bytes()
    selection = tmp_path / "mode"
    controller = LocalRuntimeModeController(local, selection_path=selection)
    restarted: list[None] = []
    controller.bind_restart(lambda: restarted.append(None))

    assert controller.selected_settings().control_mode is ControlMode.REAL
    controller.request_switch(ControlMode.DRY_RUN)
    assert selection.read_text(encoding="utf-8") == "DRY_RUN\n"
    assert restarted == [None]
    assert local.read_bytes() == original

    dry = LocalRuntimeModeController(local, selection_path=selection).selected_settings()
    assert dry.control_mode is ControlMode.DRY_RUN
    assert dry.hardware_access_policy is HardwareAccessPolicy.DISABLED
    assert dry.hardware_local_config_enabled is False
    assert dry.hardware_startup_enabled is False
    assert dry.feetech_read_only_adapter_enabled is False


def test_local_mode_api_requires_confirmations_and_requests_restart(tmp_path: Path) -> None:
    local = real_local_config(tmp_path / "local.yaml")
    selection = tmp_path / "mode"
    selection.write_text("DRY_RUN\n", encoding="utf-8")
    controller = LocalRuntimeModeController(local, selection_path=selection)
    restarted: list[None] = []
    controller.bind_restart(lambda: restarted.append(None))
    app = create_app(
        settings=controller.selected_settings(),
        runtime_mode_control=controller,
    )

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            status = await client.get("/api/v1/runtime/mode")
            assert status.status_code == 200
            assert status.json()["active_mode"] == "DRY_RUN"
            assert status.json()["real_config_available"] is True

            missing = await client.post(
                "/api/v1/runtime/mode",
                json={
                    "target_mode": "REAL",
                    "confirm_robot_disconnected": True,
                    "confirm_physical_estop_ready": False,
                    "confirm_workspace_clear": True,
                },
            )
            assert missing.status_code == 409
            assert restarted == []

            accepted = await client.post(
                "/api/v1/runtime/mode",
                json={
                    "target_mode": "REAL",
                    "confirm_robot_disconnected": True,
                    "confirm_physical_estop_ready": True,
                    "confirm_workspace_clear": True,
                },
            )
            assert accepted.status_code == 200, accepted.text
            assert accepted.json() == {
                "accepted": True,
                "target_mode": "REAL",
                "restarting": True,
            }

    asyncio.run(scenario())
    assert restarted == [None]
    assert selection.read_text(encoding="utf-8") == "REAL\n"
