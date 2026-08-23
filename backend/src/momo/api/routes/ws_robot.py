"""Rate-limited, read-only robot state WebSocket."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.motion_service import MotionApplicationService
from momo.application.services.robot_service import RobotApplicationService

router = APIRouter(tags=["robot-state"])
WS_UPDATE_HZ = 10.0
WS_UPDATE_INTERVAL_S = 1.0 / WS_UPDATE_HZ
WS_SEND_TIMEOUT_S = 1.0


async def _wait_for_next_publish() -> None:
    await asyncio.sleep(WS_UPDATE_INTERVAL_S)


@router.websocket("/ws/robot")
async def robot_state_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    robot_service: RobotApplicationService = websocket.app.state.robot_service
    kinematics: KinematicsService = websocket.app.state.kinematics_service
    motion: MotionApplicationService = websocket.app.state.motion_service
    try:
        while True:
            status, profile, state = await robot_service.get_motion_snapshot()
            fk = await kinematics.forward(
                profile,
                state,
                state_sequence=status.state_sequence,
                robot_id=status.robot_id,
            )
            latest_command = motion.latest_status()
            payload = {
                "robot_status": status.model_dump(mode="json"),
                "tcp_pose": fk.tcp_pose.model_dump(mode="json"),
                "forward_kinematics": fk.model_dump(mode="json"),
                "command_status": (
                    latest_command.model_dump(mode="json") if latest_command is not None else None
                ),
                "state_sequence": status.state_sequence,
                "hardware_accessed": False,
            }
            # No application queue exists: a slow client can block only its own
            # sender, and is removed after the bounded send timeout.
            await asyncio.wait_for(
                websocket.send_json(payload),
                timeout=WS_SEND_TIMEOUT_S,
            )
            await _wait_for_next_publish()
    except (WebSocketDisconnect, TimeoutError, RuntimeError):
        return
