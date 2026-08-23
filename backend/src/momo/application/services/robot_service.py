"""Serialized single-robot Dry Run lifecycle and diagnostics."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from momo.application.robot_manager import RobotManager, RobotRuntime
from momo.application.services.calibration_service import CalibrationService
from momo.application.services.profile_service import ProfileService
from momo.domain.calibration import CalibrationStatusReport
from momo.domain.enums import (
    ControlMode,
    HardwareAccessPolicy,
    RobotConnectionState,
    RobotVariant,
    StopResult,
)
from momo.domain.errors import (
    HardwareAccessDisabledError,
    RobotAlreadyConnectedError,
    RobotApplicationError,
    RobotBusyError,
    VariantSwitchWhileConnectedError,
)
from momo.domain.robot import JointState, RobotId, RobotProfile
from momo.domain.runtime import RobotStatus, RuntimeState, StopResponse
from momo.ports.robot_driver import RobotDriver
from momo.ports.runtime_state_repository import RuntimeStateRepository
from momo.settings import Settings

PRIMARY_ROBOT_ID = "primary"
DriverFactory = Callable[[RobotId, RobotProfile, dict[str, float] | None], RobotDriver]


def _now() -> datetime:
    return datetime.now(UTC)


class RobotApplicationService:
    """The only Stage 2 entry point for lifecycle commands."""

    def __init__(
        self,
        settings: Settings,
        profile_service: ProfileService,
        calibration_service: CalibrationService,
        runtime_repository: RuntimeStateRepository,
        *,
        driver_factory: DriverFactory,
    ) -> None:
        self.settings = settings
        self.profile_service = profile_service
        self.calibration_service = calibration_service
        self.runtime_repository = runtime_repository
        self._driver_factory = driver_factory
        self._command_lock = asyncio.Lock()

        profile = profile_service.get_profile(settings.active_robot_variant)
        positions, units, sequence = self._restore_or_home(profile)
        robot_id = RobotId(PRIMARY_ROBOT_ID)
        runtime = RobotRuntime(
            robot_id=robot_id,
            profile=profile,
            driver=self._driver_factory(robot_id, profile, positions),
            connection_state=RobotConnectionState.DISCONNECTED,
            positions=positions,
            units=units,
            updated_at=_now(),
            state_sequence=sequence,
        )
        self.manager = RobotManager(runtime)

    def _home_state(self, profile: RobotProfile) -> tuple[dict[str, float], dict[str, str]]:
        return (
            {definition.joint_id: definition.home for definition in profile.joint_definitions},
            {
                definition.joint_id: definition.domain_unit.value
                for definition in profile.joint_definitions
            },
        )

    def _restore_or_home(
        self,
        profile: RobotProfile,
    ) -> tuple[dict[str, float], dict[str, str], int]:
        homes, units = self._home_state(profile)
        state = self.runtime_repository.load(PRIMARY_ROBOT_ID)
        if state is None:
            return homes, units, 0

        reason = self._runtime_mismatch_reason(state, profile, units)
        if reason is not None:
            self.runtime_repository.reject_loaded_state(PRIMARY_ROBOT_ID, reason)
            return homes, units, 0
        try:
            JointState.model_validate(
                {"positions": state.positions, "units": state.units}
            ).validate_against(profile)
        except ValueError as error:
            self.runtime_repository.reject_loaded_state(
                PRIMARY_ROBOT_ID,
                f"Runtime state joint values are invalid: {error}",
            )
            return homes, units, 0
        return dict(state.positions), dict(state.units), state.state_sequence

    @staticmethod
    def _runtime_mismatch_reason(
        state: RuntimeState,
        profile: RobotProfile,
        units: dict[str, str],
    ) -> str | None:
        if state.robot_id != PRIMARY_ROBOT_ID:
            return "Runtime state robot_id does not match primary"
        if state.variant is not profile.variant:
            return "Runtime state variant does not match the active profile"
        if state.profile_fingerprint != profile.fingerprint:
            return "Runtime state profile fingerprint does not match"
        expected = set(profile.enabled_joints)
        if set(state.positions) != expected:
            return "Runtime state positions do not exactly match enabled_joints"
        if set(state.units) != expected or dict(state.units) != units:
            return "Runtime state units do not match the active profile"
        return None

    def _transition(self, state: RobotConnectionState, *, error: str | None = None) -> None:
        runtime = self.manager.get_active()
        runtime.connection_state = state
        runtime.state_sequence += 1
        runtime.updated_at = _now()
        runtime.last_error = error

    def _touch(self) -> None:
        runtime = self.manager.get_active()
        runtime.state_sequence += 1
        runtime.updated_at = _now()

    def _save(self) -> None:
        runtime = self.manager.get_active()
        self.runtime_repository.save(
            RuntimeState(
                robot_id=runtime.robot_id.root,
                variant=runtime.profile.variant,
                profile_fingerprint=runtime.profile.fingerprint,
                positions=dict(runtime.positions),
                units=dict(runtime.units),
                connection_state=runtime.connection_state,
                updated_at=runtime.updated_at,
                state_sequence=runtime.state_sequence,
            )
        )

    def _calibration_status(self, profile: RobotProfile) -> CalibrationStatusReport:
        return self.calibration_service.status(profile)

    def _status_unlocked(self) -> RobotStatus:
        runtime = self.manager.get_active()
        calibration = self._calibration_status(runtime.profile)
        return RobotStatus(
            robot_id=runtime.robot_id.root,
            variant=runtime.profile.variant,
            control_mode=ControlMode.DRY_RUN,
            hardware_access_policy=HardwareAccessPolicy.DISABLED,
            connection_state=runtime.connection_state,
            connected=runtime.connection_state is RobotConnectionState.CONNECTED,
            profile_fingerprint=runtime.profile.fingerprint,
            profile_verification_status=runtime.profile.verification_status,
            calibration_status=calibration.status,
            positions=dict(runtime.positions),
            units=dict(runtime.units),
            raw_positions=None,
            last_error=runtime.last_error,
            updated_at=runtime.updated_at,
            state_sequence=runtime.state_sequence,
            hardware_accessed=False,
        )

    async def get_status(self) -> RobotStatus:
        async with self._command_lock:
            return self._status_unlocked()

    async def connect(self) -> RobotStatus:
        async with self._command_lock:
            runtime = self.manager.get_active()
            if self.settings.hardware_access_policy is not HardwareAccessPolicy.DISABLED:
                raise HardwareAccessDisabledError("Stage 2 hardware access must remain disabled")
            if runtime.connection_state is RobotConnectionState.CONNECTED:
                raise RobotAlreadyConnectedError("The active Dry Run robot is already connected")
            if runtime.connection_state is not RobotConnectionState.DISCONNECTED:
                raise RobotBusyError(f"Robot cannot connect while {runtime.connection_state.value}")

            self._transition(RobotConnectionState.CONNECTING)
            try:
                await runtime.driver.connect()
                state = await runtime.driver.read_joint_state()
                runtime.positions = dict(state.positions)
                runtime.units = {
                    joint_id: unit.value for joint_id, unit in (state.units or {}).items()
                }
                self._transition(RobotConnectionState.CONNECTED)
                self._save()
            except Exception as error:
                self._transition(
                    RobotConnectionState.FAULTED,
                    error=f"Dry Run connect failed: {type(error).__name__}",
                )
                with suppress(OSError):
                    self._save()
                raise RobotApplicationError("Dry Run robot connection failed") from error
            return self._status_unlocked()

    async def disconnect(self) -> RobotStatus:
        async with self._command_lock:
            runtime = self.manager.get_active()
            if runtime.connection_state is RobotConnectionState.DISCONNECTED:
                return self._status_unlocked()
            if runtime.connection_state in {
                RobotConnectionState.CONNECTING,
                RobotConnectionState.DISCONNECTING,
            }:
                raise RobotBusyError(
                    f"Robot cannot disconnect while {runtime.connection_state.value}"
                )
            self._transition(RobotConnectionState.DISCONNECTING)
            try:
                await runtime.driver.disconnect()
                self._transition(RobotConnectionState.DISCONNECTED)
                self._save()
            except Exception as error:
                self._transition(
                    RobotConnectionState.FAULTED,
                    error=f"Dry Run disconnect failed: {type(error).__name__}",
                )
                raise RobotApplicationError("Dry Run robot disconnection failed") from error
            return self._status_unlocked()

    async def stop(self) -> StopResponse:
        async with self._command_lock:
            runtime = self.manager.get_active()
            if runtime.connection_state is RobotConnectionState.DISCONNECTED:
                self._touch()
                self._save()
                return StopResponse(
                    result=StopResult.NOT_CONNECTED.value,
                    status=self._status_unlocked(),
                    hardware_accessed=False,
                )
            if runtime.connection_state is not RobotConnectionState.CONNECTED:
                raise RobotBusyError(f"Robot cannot stop while {runtime.connection_state.value}")
            try:
                await runtime.driver.stop()
                self._touch()
                self._save()
                return StopResponse(
                    result=StopResult.STOPPED.value,
                    status=self._status_unlocked(),
                    hardware_accessed=False,
                )
            except Exception as error:
                self._transition(
                    RobotConnectionState.FAULTED,
                    error=f"Dry Run stop failed: {type(error).__name__}",
                )
                self._save()
                return StopResponse(
                    result=StopResult.FAILED.value,
                    status=self._status_unlocked(),
                    hardware_accessed=False,
                )

    async def switch_variant(self, variant: RobotVariant) -> RobotStatus:
        async with self._command_lock:
            current = self.manager.get_active()
            if current.connection_state is not RobotConnectionState.DISCONNECTED:
                raise VariantSwitchWhileConnectedError(
                    "Robot variant can only change while disconnected"
                )
            if variant is current.profile.variant:
                return self._status_unlocked()

            profile = self.profile_service.get_profile(variant)
            positions, units, restored_sequence = self._restore_or_home(profile)
            sequence = max(current.state_sequence, restored_sequence) + 1
            runtime = RobotRuntime(
                robot_id=current.robot_id,
                profile=profile,
                driver=self._driver_factory(current.robot_id, profile, positions),
                connection_state=RobotConnectionState.DISCONNECTED,
                positions=positions,
                units=units,
                updated_at=_now(),
                state_sequence=sequence,
            )
            self.manager.replace_active(runtime)
            self._save()
            return self._status_unlocked()

    async def get_profile(self) -> dict[str, Any]:
        async with self._command_lock:
            profile = self.manager.get_active().profile
            return {
                "profile": profile,
                "fingerprint": profile.fingerprint,
                "real_eligible": False,
            }

    async def get_calibration_status(self) -> CalibrationStatusReport:
        async with self._command_lock:
            return self._calibration_status(self.manager.get_active().profile)

    async def diagnostics(self) -> dict[str, Any]:
        async with self._command_lock:
            runtime = self.manager.get_active()
            return {
                "hardware_access_policy": HardwareAccessPolicy.DISABLED.value,
                "runtime_state_path": self.runtime_repository.path_description,
                "runtime_state_valid": self.runtime_repository.last_load_valid,
                "runtime_state_diagnostic": self.runtime_repository.last_diagnostic,
                "quarantined_runtime_file": self.runtime_repository.last_quarantined_file,
                "backend_version": self.settings.version,
                "legacy_source_commit": "ff8bbda0c2222cb57951c7913f7f12f5777b98fa",
                "stage_policy": "STAGE_2_DRY_RUN_ONLY",
                "active_profile_fingerprint": runtime.profile.fingerprint,
                "hardware_accessed": False,
            }
