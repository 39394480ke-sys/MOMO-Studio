"""Local-only supervised DRY_RUN/REAL runtime selection."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Request

from momo.api.schemas import (
    RuntimeModeStatusResponse,
    RuntimeModeSwitchRequest,
    RuntimeModeSwitchResponse,
)
from momo.domain.enums import ControlMode
from momo.domain.errors import RuntimeModeSwitchError
from momo.ports.runtime_mode_control import RuntimeModeControl, RuntimeModeControlSnapshot

router = APIRouter(prefix="/runtime/mode", tags=["runtime-mode"])


def _controller(request: Request) -> RuntimeModeControl | None:
    return cast(RuntimeModeControl | None, request.app.state.runtime_mode_control)


def _response(snapshot: RuntimeModeControlSnapshot) -> RuntimeModeStatusResponse:
    return RuntimeModeStatusResponse(
        active_mode=snapshot.active_mode,
        selected_mode=snapshot.selected_mode,
        switch_supported=snapshot.switch_supported,
        restart_in_progress=snapshot.restart_in_progress,
        real_config_available=snapshot.real_config_available,
        configured_real_policy=snapshot.configured_real_policy,
        configured_real_motion_enabled=snapshot.configured_real_motion_enabled,
        blocking_reasons=list(snapshot.blocking_reasons),
    )


@router.get("", response_model=RuntimeModeStatusResponse)
def runtime_mode_status(request: Request) -> RuntimeModeStatusResponse:
    settings = request.app.state.settings
    controller = _controller(request)
    if controller is None:
        return RuntimeModeStatusResponse(
            active_mode=settings.control_mode,
            selected_mode=settings.control_mode,
            switch_supported=False,
            restart_in_progress=False,
            real_config_available=False,
            blocking_reasons=["SUPERVISED_LOCAL_LAUNCHER_REQUIRED"],
        )
    return _response(controller.snapshot(settings.control_mode))


@router.post("", response_model=RuntimeModeSwitchResponse)
async def switch_runtime_mode(
    payload: RuntimeModeSwitchRequest,
    request: Request,
) -> RuntimeModeSwitchResponse:
    client = request.client
    if client is None or client.host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise RuntimeModeSwitchError("Runtime mode switching is available only on loopback")
    controller = _controller(request)
    if controller is None:
        raise RuntimeModeSwitchError("Start MOMO Studio with the supervised local launcher")
    robot = await request.app.state.robot_service.get_status()
    if robot.connected or not payload.confirm_robot_disconnected:
        raise RuntimeModeSwitchError("Disconnect the robot before changing runtime mode")
    if payload.target_mode is ControlMode.REAL and (
        not payload.confirm_physical_estop_ready or not payload.confirm_workspace_clear
    ):
        raise RuntimeModeSwitchError(
            "REAL mode requires physical E-stop and clear-workspace confirmation"
        )
    snapshot = controller.snapshot(request.app.state.settings.control_mode)
    if payload.target_mode is ControlMode.REAL and not snapshot.real_config_available:
        raise RuntimeModeSwitchError(
            "The reviewed local REAL workspace is unavailable",
            details={"blocking_reasons": list(snapshot.blocking_reasons)},
        )
    if payload.target_mode is request.app.state.settings.control_mode:
        raise RuntimeModeSwitchError("The requested runtime mode is already active")
    try:
        controller.request_switch(payload.target_mode)
    except (OSError, RuntimeError, ValueError) as error:
        raise RuntimeModeSwitchError("Runtime mode selection could not be saved") from error
    return RuntimeModeSwitchResponse(target_mode=payload.target_mode)


__all__ = ["router"]
