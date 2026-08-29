"""Port for the local supervised runtime-mode selector."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from momo.domain.enums import ControlMode, HardwareAccessPolicy


@dataclass(frozen=True, slots=True)
class RuntimeModeControlSnapshot:
    active_mode: ControlMode
    selected_mode: ControlMode
    switch_supported: bool
    restart_in_progress: bool
    real_config_available: bool
    configured_real_policy: HardwareAccessPolicy | None
    configured_real_motion_enabled: bool
    blocking_reasons: tuple[str, ...]


class RuntimeModeControl(Protocol):
    def snapshot(self, active_mode: ControlMode) -> RuntimeModeControlSnapshot: ...

    def request_switch(self, target_mode: ControlMode) -> None: ...


__all__ = ["RuntimeModeControl", "RuntimeModeControlSnapshot"]
