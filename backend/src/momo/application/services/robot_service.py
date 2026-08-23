"""Serialized single-robot Dry Run lifecycle and diagnostics."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from typing import Any
from uuid import UUID

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
from momo.ports.clock import Clock
from momo.ports.robot_driver import RobotDriver
from momo.ports.runtime_state_repository import RuntimeStateRepository
from momo.settings import Settings

PRIMARY_ROBOT_ID = "primary"
STATE_OBSERVATION_TIMEOUT_S = 0.25
DriverFactory = Callable[[RobotId, RobotProfile, dict[str, float] | None], RobotDriver]


class RobotApplicationService:
    """The single-robot lifecycle and atomic Dry Run state application service."""

    def __init__(
        self,
        settings: Settings,
        profile_service: ProfileService,
        calibration_service: CalibrationService,
        runtime_repository: RuntimeStateRepository,
        *,
        driver_factory: DriverFactory,
        clock: Clock,
    ) -> None:
        self.settings = settings
        self.profile_service = profile_service
        self.calibration_service = calibration_service
        self.runtime_repository = runtime_repository
        self._driver_factory = driver_factory
        self.clock = clock
        self._command_lock = asyncio.Lock()
        self._pending_runtime_snapshot: RuntimeState | None = None
        self._persistence_worker_task: asyncio.Task[None] | None = None
        self._persistence_error: str | None = None

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
            updated_at=self.clock.now(),
            observed_monotonic=self.clock.monotonic(),
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
        runtime.updated_at = self.clock.now()
        runtime.observed_monotonic = self.clock.monotonic()
        runtime.last_error = error

    def _touch(self) -> None:
        runtime = self.manager.get_active()
        runtime.state_sequence += 1
        runtime.updated_at = self.clock.now()
        runtime.observed_monotonic = self.clock.monotonic()

    def _runtime_snapshot_unlocked(self) -> RuntimeState:
        runtime = self.manager.get_active()
        return RuntimeState(
            robot_id=runtime.robot_id.root,
            variant=runtime.profile.variant,
            profile_fingerprint=runtime.profile.fingerprint,
            positions=dict(runtime.positions),
            units=dict(runtime.units),
            connection_state=runtime.connection_state,
            updated_at=runtime.updated_at,
            state_sequence=runtime.state_sequence,
        )

    def _queue_save_unlocked(self) -> None:
        """Coalesce persistence to one in-flight write plus one latest snapshot."""

        self._pending_runtime_snapshot = self._runtime_snapshot_unlocked()
        task = self._persistence_worker_task
        if task is None or task.done():
            self._persistence_worker_task = asyncio.create_task(
                self._persistence_worker(),
                name="dry-run-runtime-persistence",
            )

    async def _persistence_worker(self) -> None:
        while self._pending_runtime_snapshot is not None:
            snapshot = self._pending_runtime_snapshot
            self._pending_runtime_snapshot = None
            try:
                await asyncio.to_thread(self.runtime_repository.save, snapshot)
                self._persistence_error = None
            except Exception as error:
                self._persistence_error = type(error).__name__

    async def drain_runtime_persistence(self, *, timeout_s: float = 1.0) -> None:
        """Drain the bounded worker during orderly shutdown or deterministic tests."""

        task = self._persistence_worker_task
        if task is None or task.done():
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout_s)
        except TimeoutError:
            self._persistence_error = "TimeoutError"
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _calibration_status(self, profile: RobotProfile) -> CalibrationStatusReport:
        return self.calibration_service.status(profile)

    def _status_unlocked(self) -> RobotStatus:
        runtime = self.manager.get_active()
        calibration = self._calibration_status(runtime.profile)
        state_age_s = self.clock.monotonic() - runtime.observed_monotonic
        stale = runtime.connection_state is RobotConnectionState.CONNECTED and (
            state_age_s < 0.0 or state_age_s > self.settings.robot_state_freshness_limit_s
        )
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
            stale=stale,
        )

    async def get_status(self) -> RobotStatus:
        async with self._command_lock:
            await self._refresh_observation_unlocked()
            return self._status_unlocked()

    async def get_motion_snapshot(self) -> tuple[RobotStatus, RobotProfile, JointState]:
        """Capture status/profile/joints under one short lifecycle lock."""

        async with self._command_lock:
            await self._refresh_observation_unlocked()
            runtime = self.manager.get_active()
            state = JointState(
                positions=dict(runtime.positions),
                units={
                    joint_id: runtime.profile.definitions_by_id[joint_id].domain_unit
                    for joint_id in runtime.profile.enabled_joints
                },
            ).validate_against(runtime.profile)
            return self._status_unlocked(), runtime.profile, state

    async def _refresh_observation_unlocked(self) -> None:
        """Refresh connected state through the high-level, unit-safe driver port.

        The Stage 3 composition always injects the in-memory Dry Run driver, so
        this operation cannot scan, connect, or touch hardware.  A failed or
        timed-out observation deliberately leaves both observation timestamps
        unchanged; monotonic age then makes status stale and preflight fails.
        """

        runtime = self.manager.get_active()
        if runtime.connection_state is not RobotConnectionState.CONNECTED:
            return
        try:
            observed = await asyncio.wait_for(
                runtime.driver.read_joint_state(),
                timeout=STATE_OBSERVATION_TIMEOUT_S,
            )
            if observed.units is None:
                raise ValueError("observed joint state omitted explicit units")
            validated = observed.validate_against(runtime.profile)
        except Exception:
            return

        positions = dict(validated.positions)
        units = {
            definition.joint_id: definition.domain_unit.value
            for definition in runtime.profile.joint_definitions
        }
        if positions != runtime.positions or units != runtime.units:
            runtime.positions = positions
            runtime.units = units
            self._touch()
            self._queue_save_unlocked()
            return
        runtime.updated_at = self.clock.now()
        runtime.observed_monotonic = self.clock.monotonic()

    async def apply_motion_state(self, command_id: UUID, state: JointState) -> int:
        """Short atomic Dry Run update used by the prepared-motion executor."""

        del command_id
        async with self._command_lock:
            runtime = self.manager.get_active()
            if runtime.connection_state is not RobotConnectionState.CONNECTED:
                raise RobotApplicationError("Dry Run robot disconnected during motion")
            validated = state.validate_against(runtime.profile)
            await runtime.driver.move_to_joint_state(validated)
            runtime.positions = dict(validated.positions)
            runtime.units = {
                definition.joint_id: definition.domain_unit.value
                for definition in runtime.profile.joint_definitions
            }
            self._touch()
            return runtime.state_sequence

    async def flush_motion_state(self, command_id: UUID) -> None:
        """Persist one terminal motion snapshot without blocking the event loop."""

        del command_id
        async with self._command_lock:
            self._queue_save_unlocked()

    async def mark_motion_fault(self, command_id: UUID, error: str) -> None:
        del command_id
        async with self._command_lock:
            self._transition(
                RobotConnectionState.FAULTED,
                error=f"Dry Run motion fault: {error[:160]}",
            )
            self._queue_save_unlocked()

    async def connect(self) -> RobotStatus:
        async with self._command_lock:
            runtime = self.manager.get_active()
            if self.settings.hardware_access_policy is not HardwareAccessPolicy.DISABLED:
                raise HardwareAccessDisabledError("Stage 3 hardware access must remain disabled")
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
                self._queue_save_unlocked()
            except Exception as error:
                self._transition(
                    RobotConnectionState.FAULTED,
                    error=f"Dry Run connect failed: {type(error).__name__}",
                )
                with suppress(OSError):
                    self._queue_save_unlocked()
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
                self._queue_save_unlocked()
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
                self._queue_save_unlocked()
                return StopResponse(
                    result=StopResult.NOT_CONNECTED.value,
                    status=self._status_unlocked(),
                    hardware_accessed=False,
                )
            if runtime.connection_state is RobotConnectionState.FAULTED:
                try:
                    await runtime.driver.stop()
                    await runtime.driver.disconnect()
                    self._transition(RobotConnectionState.DISCONNECTED)
                    self._queue_save_unlocked()
                    return StopResponse(
                        result=StopResult.STOPPED.value,
                        status=self._status_unlocked(),
                        hardware_accessed=False,
                    )
                except Exception as error:
                    self._transition(
                        RobotConnectionState.FAULTED,
                        error=f"Dry Run fault recovery failed: {type(error).__name__}",
                    )
                    self._queue_save_unlocked()
                    return StopResponse(
                        result=StopResult.FAILED.value,
                        status=self._status_unlocked(),
                        hardware_accessed=False,
                    )
            if runtime.connection_state is not RobotConnectionState.CONNECTED:
                raise RobotBusyError(f"Robot cannot stop while {runtime.connection_state.value}")
            try:
                await runtime.driver.stop()
                self._touch()
                self._queue_save_unlocked()
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
                self._queue_save_unlocked()
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
                updated_at=self.clock.now(),
                observed_monotonic=self.clock.monotonic(),
                state_sequence=sequence,
            )
            self.manager.replace_active(runtime)
            self._queue_save_unlocked()
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
                "stage_policy": "DRY_RUN_ONLY",
                "active_profile_fingerprint": runtime.profile.fingerprint,
                "robot_state_freshness_limit_s": self.settings.robot_state_freshness_limit_s,
                "runtime_persistence_error": self._persistence_error,
                "hardware_accessed": False,
            }
