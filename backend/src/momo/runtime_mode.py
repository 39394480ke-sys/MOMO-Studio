"""Fixed-path local runtime-mode selection for the supervised server."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile

from momo.domain.enums import ControlMode, HardwareAccessPolicy
from momo.ports.runtime_mode_control import RuntimeModeControlSnapshot
from momo.settings import Settings, load_settings, repository_root

_DRY_OVERRIDES: dict[str, object] = {
    "control_mode": ControlMode.DRY_RUN,
    "hardware_access_policy": HardwareAccessPolicy.DISABLED,
    "hardware_startup_enabled": False,
    "hardware_local_config_enabled": False,
    "real_motion_enabled": False,
    "commissioning_motion_test_enabled": False,
    "raw_direction_test_enabled": False,
    "feetech_read_only_adapter_enabled": False,
    "feetech_raw_direction_adapter_enabled": False,
    "feetech_commissioning_motion_adapter_enabled": False,
    "feetech_production_motion_adapter_enabled": False,
}


class LocalRuntimeModeController:
    """Select one already-reviewed local composition without editing device data."""

    def __init__(
        self,
        local_config_path: Path,
        *,
        selection_path: Path | None = None,
    ) -> None:
        self.local_config_path = local_config_path.resolve(strict=True)
        self.selection_path = selection_path or (
            repository_root() / "data" / "runtime" / "control-mode-selection"
        )
        self._restart: Callable[[], None] | None = None
        self._restart_target: ControlMode | None = None

    @property
    def restart_requested(self) -> bool:
        return self._restart_target is not None

    def bind_restart(self, callback: Callable[[], None]) -> None:
        self._restart = callback

    def selected_mode(self) -> ControlMode:
        try:
            value = self.selection_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return self._configured_real_settings().control_mode
        try:
            return ControlMode(value)
        except ValueError as error:
            raise ValueError("runtime mode selection is invalid") from error

    def selected_settings(self) -> Settings:
        configured = self._configured_real_settings()
        if self.selected_mode() is ControlMode.REAL:
            if configured.control_mode is not ControlMode.REAL:
                raise ValueError("the explicit local config does not define a REAL workspace")
            return configured
        values = configured.model_dump(mode="python")
        values.update(_DRY_OVERRIDES)
        return Settings.model_validate(values)

    def snapshot(self, active_mode: ControlMode) -> RuntimeModeControlSnapshot:
        blockers: list[str] = []
        configured: Settings | None = None
        try:
            configured = self._configured_real_settings()
            if configured.control_mode is not ControlMode.REAL:
                blockers.append("LOCAL_REAL_WORKSPACE_NOT_CONFIGURED")
        except (OSError, ValueError):
            blockers.append("LOCAL_REAL_CONFIGURATION_INVALID")
        selected = self._restart_target or self.selected_mode()
        return RuntimeModeControlSnapshot(
            active_mode=active_mode,
            selected_mode=selected,
            switch_supported=self._restart is not None,
            restart_in_progress=self._restart_target is not None,
            real_config_available=not blockers,
            configured_real_policy=(
                configured.hardware_access_policy if configured is not None else None
            ),
            configured_real_motion_enabled=bool(
                configured is not None and configured.real_motion_enabled
            ),
            blocking_reasons=tuple(blockers),
        )

    def request_switch(self, target_mode: ControlMode) -> None:
        restart = self._restart
        if restart is None:
            raise RuntimeError("the backend was not started by the supervised local launcher")
        if target_mode is ControlMode.REAL:
            configured = self._configured_real_settings()
            if configured.control_mode is not ControlMode.REAL:
                raise ValueError("the explicit local config does not define a REAL workspace")
        self._write_selection(target_mode)
        self._restart_target = target_mode
        restart()

    def _configured_real_settings(self) -> Settings:
        return load_settings(local_config_path=self.local_config_path)

    def _write_selection(self, target_mode: ControlMode) -> None:
        destination = self.selection_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(f"{target_mode.value}\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()


__all__ = ["LocalRuntimeModeController"]
