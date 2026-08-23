"""Explicit single-active-robot registry owned by the composition root."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from momo.domain.enums import RobotConnectionState
from momo.domain.robot import RobotId, RobotProfile
from momo.ports.robot_driver import RobotDriver


@dataclass(slots=True)
class RobotRuntime:
    robot_id: RobotId
    profile: RobotProfile
    driver: RobotDriver
    connection_state: RobotConnectionState
    positions: dict[str, float]
    units: dict[str, str]
    updated_at: datetime
    observed_monotonic: float
    state_sequence: int = 0
    last_error: str | None = None


class RobotManager:
    """Small registry now; extensible core without exposing fleet product controls."""

    def __init__(self, runtime: RobotRuntime) -> None:
        self._runtimes = {runtime.robot_id.root: runtime}
        self._active_robot_id = runtime.robot_id.root

    def get_active(self) -> RobotRuntime:
        return self._runtimes[self._active_robot_id]

    def replace_active(self, runtime: RobotRuntime) -> None:
        self._runtimes = {runtime.robot_id.root: runtime}
        self._active_robot_id = runtime.robot_id.root

    def list_robot_ids(self) -> tuple[RobotId, ...]:
        return tuple(runtime.robot_id for runtime in self._runtimes.values())
