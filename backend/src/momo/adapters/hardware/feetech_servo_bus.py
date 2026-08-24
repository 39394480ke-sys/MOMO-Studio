"""Lazy optional Feetech ServoBus shell with pending SDK/license verification.

No third-party module is imported here.  The Legacy commit requested for SDK
provenance is not present in this repository's object database, so the production
package name, bridge API, and license remain deliberately unclaimed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from functools import partial
from importlib import import_module
from types import ModuleType
from typing import Protocol, TypeVar, cast

from momo.domain.errors import RobotApplicationError
from momo.domain.real_hardware import (
    ExplicitServoDevice,
    HardwareDependencyState,
    HardwareDependencyStatus,
    RealHardwareAccessGrant,
    RealHardwareAuthorizationPurpose,
    RealStopOutcome,
    RealStopResult,
    ServoPingResult,
    ServoWriteResult,
    explicit_device_fingerprint,
)


class FeetechAdapterPendingError(RobotApplicationError):
    code = "FEETECH_ADAPTER_VERIFICATION_PENDING"
    status_code = 503


class FeetechDependencyError(RobotApplicationError):
    code = "FEETECH_DEPENDENCY_UNAVAILABLE"
    status_code = 503


class _VerifiedFeetechBridge(Protocol):
    """Future reviewed shim; intentionally not claimed as an SDK's native API."""

    def open(self, device: str, protocol: str) -> None: ...

    def close(self) -> None: ...

    def ping(self, servo_id: int) -> bool: ...

    def read_present_position(self, servo_id: int) -> int: ...

    def read_operating_mode(self, servo_id: int) -> str: ...

    def read_torque_state(self, servo_id: int) -> bool: ...

    def write_goal_positions(self, goals: Mapping[int, int]) -> Mapping[int, bool]: ...


class _VerifiedFeetechModule(Protocol):
    def create_momo_servo_backend(self) -> _VerifiedFeetechBridge: ...


_T = TypeVar("_T")


async def _wait_task_terminal(task: asyncio.Task[_T]) -> asyncio.CancelledError | None:
    """Retain the first cancellation but observe the child through any repeats."""

    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            if cancellation is None:
                cancellation = error
        except Exception:
            # The terminal exception is retrieved by task.result() at the call site.
            pass
    return cancellation


async def _completion_observed_thread_call(call: Callable[[], _T], *, name: str) -> _T:
    """Do not let cancellation race bridge.close against an in-flight SDK call."""

    task = asyncio.create_task(asyncio.to_thread(call), name=name)
    cancellation = await _wait_task_terminal(task)
    try:
        result = task.result()
    except BaseException as error:
        if cancellation is not None and error is not cancellation:
            raise cancellation from error
        raise
    if cancellation is not None:
        raise cancellation
    return result


class FeetechServoBusFactory:
    """Import an explicitly configured optional bridge only after a full grant."""

    def __init__(
        self,
        *,
        verified_bridge_module: str | None = None,
        importer: Callable[[str], ModuleType] = import_module,
    ) -> None:
        self._module_name = verified_bridge_module
        self._importer = importer

    @property
    def dependency(self) -> HardwareDependencyStatus:
        return HardwareDependencyStatus(
            adapter_id="feetech-servo-bus-shell",
            state=HardwareDependencyState.PENDING_ADAPTER_VERIFICATION,
            package_name=self._module_name,
            license_status="UNVERIFIED",
            notice=(
                "Pending Adapter Verification: SDK package, license, register semantics, "
                "and physical Stop behavior are not yet proven from available Legacy evidence."
            ),
        )

    def create(self, authorization: RealHardwareAccessGrant) -> FeetechServoBus:
        _require_complete_grant(authorization)
        dependency = self.dependency
        if dependency.state is not HardwareDependencyState.AVAILABLE:
            raise FeetechAdapterPendingError(
                "Feetech SDK/license/adapter verification is still pending"
            )
        if authorization.adapter_id != dependency.adapter_id:
            raise FeetechAdapterPendingError(
                "Real hardware authorization was issued for a different adapter"
            )
        module_name = self._module_name
        if module_name is None:
            raise FeetechAdapterPendingError(
                "Feetech adapter package and license verification are pending"
            )
        try:
            module = cast(_VerifiedFeetechModule, self._importer(module_name))
        except Exception as error:
            raise FeetechDependencyError(
                "The explicitly configured Feetech bridge is unavailable"
            ) from error
        if not callable(getattr(module, "create_momo_servo_backend", None)):
            raise FeetechAdapterPendingError(
                "The configured module does not expose the reviewed MOMO bridge contract"
            )
        # The bridge object is not created until explicit open(). Factory/import
        # success therefore cannot open a port or instantiate an SDK PortHandler.
        return FeetechServoBus(module, authorization)


class FeetechServoBus:
    """Explicit bridge wrapper; construction and capability inspection are inert."""

    def __init__(
        self,
        module: _VerifiedFeetechModule,
        authorization: RealHardwareAccessGrant,
    ) -> None:
        self._module = module
        self._authorization = authorization
        self._bridge: _VerifiedFeetechBridge | None = None
        self._connected = False
        self._guard = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._connected

    async def open(self, device: str, protocol: str) -> None:
        _validate_device_protocol(device, protocol)
        candidate = ExplicitServoDevice(
            serial_port=device,
            protocol=protocol,
            servo_ids=self._authorization.session.allowed_servo_ids,
        )
        if explicit_device_fingerprint(candidate) != self._authorization.device_fingerprint:
            raise PermissionError("device and protocol must match the authorized grant")
        async with self._guard:
            if self._connected:
                return
            if self._bridge is not None:
                raise RuntimeError(
                    "A prior Feetech open has an uncertain cleanup state; close it first"
                )
            create_task = asyncio.create_task(
                asyncio.to_thread(self._module.create_momo_servo_backend),
                name="feetech-bridge-create",
            )
            create_cancellation = await _wait_task_terminal(create_task)
            try:
                bridge = create_task.result()
            except BaseException as error:
                if create_cancellation is not None and error is not create_cancellation:
                    raise create_cancellation from error
                raise
            if create_cancellation is not None:
                self._bridge = bridge
                cleanup_error = await self._attempt_bridge_close_unlocked(bridge)
                if cleanup_error is not None:
                    raise create_cancellation from cleanup_error
                raise create_cancellation
            self._bridge = bridge
            open_task = asyncio.create_task(
                asyncio.to_thread(bridge.open, device, protocol),
                name="feetech-bridge-open",
            )
            open_cancellation = await _wait_task_terminal(open_task)
            open_error: BaseException | None = None
            try:
                open_task.result()
            except BaseException as error:
                open_error = error
            if open_cancellation is not None or open_error is not None:
                cleanup_error = await self._attempt_bridge_close_unlocked(bridge)
                cause = cleanup_error or open_error
                if open_cancellation is not None:
                    if cause is not None and cause is not open_cancellation:
                        raise open_cancellation from cause
                    raise open_cancellation
                if open_error is not None:
                    if cleanup_error is not None:
                        raise open_error from cleanup_error
                    raise open_error
            self._connected = True

    async def close(self) -> None:
        async with self._guard:
            bridge = self._bridge
            if bridge is None:
                self._connected = False
                return
            error = await self._attempt_bridge_close_unlocked(bridge)
            if error is not None:
                raise error

    async def _attempt_bridge_close_unlocked(
        self,
        bridge: _VerifiedFeetechBridge,
    ) -> Exception | None:
        cleanup = asyncio.create_task(
            asyncio.to_thread(bridge.close),
            name="feetech-bridge-close",
        )
        cancellation = await _wait_task_terminal(cleanup)
        try:
            cleanup.result()
        except BaseException as error:
            # A failed close cannot discard the only handle. Conservatively keep
            # the bridge reachable so Device priority Stop/cleanup can retry.
            self._bridge = bridge
            self._connected = True
            if cancellation is not None and error is not cancellation:
                raise cancellation from error
            if isinstance(error, asyncio.CancelledError):
                raise
            if not isinstance(error, Exception):
                raise
            return error
        self._bridge = None
        self._connected = False
        if cancellation is not None:
            raise cancellation
        return None

    async def ping_explicit_ids(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, ServoPingResult]:
        async with self._guard:
            bridge = self._require_bridge(servo_ids)
            results: dict[int, ServoPingResult] = {}
            for servo_id in servo_ids:
                responded = await _completion_observed_thread_call(
                    partial(bridge.ping, servo_id),
                    name=f"feetech-ping-{servo_id}",
                )
                if not isinstance(responded, bool):
                    raise RuntimeError("Feetech bridge ping must return a boolean")
                results[servo_id] = ServoPingResult(
                    servo_id=servo_id,
                    responded=responded,
                    detail=("explicit servo responded" if responded else "explicit servo missing"),
                )
            return results

    async def read_present_positions(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, int]:
        async with self._guard:
            bridge = self._require_bridge(servo_ids)
            results: dict[int, int] = {}
            for servo_id in servo_ids:
                raw = await _completion_observed_thread_call(
                    partial(bridge.read_present_position, servo_id),
                    name=f"feetech-position-{servo_id}",
                )
                if isinstance(raw, bool) or not isinstance(raw, int):
                    raise RuntimeError("Feetech present position must be an integer")
                results[servo_id] = raw
            return results

    async def read_operating_modes(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, str]:
        async with self._guard:
            bridge = self._require_bridge(servo_ids)
            results: dict[int, str] = {}
            for servo_id in servo_ids:
                mode = await _completion_observed_thread_call(
                    partial(bridge.read_operating_mode, servo_id),
                    name=f"feetech-mode-{servo_id}",
                )
                if not isinstance(mode, str) or not mode or len(mode) > 64:
                    raise RuntimeError("Feetech operating mode must be a bounded string")
                results[servo_id] = mode
            return results

    async def read_torque_states(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, bool]:
        async with self._guard:
            bridge = self._require_bridge(servo_ids)
            results: dict[int, bool] = {}
            for servo_id in servo_ids:
                enabled = await _completion_observed_thread_call(
                    partial(bridge.read_torque_state, servo_id),
                    name=f"feetech-torque-{servo_id}",
                )
                if not isinstance(enabled, bool):
                    raise RuntimeError("Feetech torque state must be a boolean")
                results[servo_id] = enabled
            return results

    async def write_goal_positions(
        self,
        goal_positions: Mapping[int, int],
    ) -> ServoWriteResult:
        requested = tuple(goal_positions)
        self._require_bridge(requested)
        self._require_full_granted_ids(requested)
        self._require_goal_write_authorization()
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in goal_positions.values()
        ):
            raise TypeError("goal positions must be integer raw values")
        # A timed-out asyncio.to_thread call can continue mutating hardware after
        # the caller reports failure and sends Stop. Until the reviewed adapter
        # proves cancellable/bounded SDK semantics, this shell cannot write.
        raise FeetechAdapterPendingError(
            "Feetech goal writes are disabled pending bounded cancellation verification"
        )

    async def stop_or_hold(self, servo_ids: tuple[int, ...]) -> RealStopOutcome:
        _validate_explicit_ids(servo_ids)
        self._require_full_granted_ids(servo_ids)
        if not self._connected:
            return RealStopOutcome(
                result=RealStopResult.NOT_CONNECTED,
                requested_ids=servo_ids,
                affected_ids=(),
                connected=False,
                safety_state_known=False,
                detail="Feetech bridge is not connected",
            )
        # No Stop/hold/torque register semantics are guessed. Field verification
        # and a physical E-stop remain mandatory before this can claim success.
        return RealStopOutcome(
            result=RealStopResult.SAFETY_STATE_UNCERTAIN,
            requested_ids=servo_ids,
            affected_ids=(),
            connected=True,
            safety_state_known=False,
            detail=("Feetech physical Stop behavior is unverified; use the physical E-stop"),
        )

    def _require_bridge(self, servo_ids: tuple[int, ...]) -> _VerifiedFeetechBridge:
        _validate_explicit_ids(servo_ids)
        self._require_granted_read_ids(servo_ids)
        bridge = self._bridge
        if not self._connected or bridge is None:
            raise RuntimeError("Feetech ServoBus is not connected")
        return bridge

    def _require_granted_read_ids(self, servo_ids: tuple[int, ...]) -> None:
        if not set(servo_ids) <= set(self._authorization.session.allowed_servo_ids):
            raise PermissionError("read IDs must be a subset of the authorized allowlist")

    def _require_full_granted_ids(self, servo_ids: tuple[int, ...]) -> None:
        if servo_ids != self._authorization.session.allowed_servo_ids:
            raise PermissionError("write/Stop IDs must exactly match the authorized allowlist")

    def _require_goal_write_authorization(self) -> None:
        purpose = self._authorization.purpose
        if purpose is RealHardwareAuthorizationPurpose.DIAGNOSTICS:
            raise PermissionError("a read-only diagnostics grant cannot write goal positions")


def _require_complete_grant(authorization: RealHardwareAccessGrant) -> None:
    evidence = authorization.session
    if authorization.authorized_at >= evidence.expires_at:
        raise FeetechAdapterPendingError("Real hardware authorization is expired")
    if not evidence.confirmed or not evidence.physical_estop_confirmed:
        raise FeetechAdapterPendingError("Real hardware authorization is incomplete")
    purpose_ready = {
        RealHardwareAuthorizationPurpose.DIAGNOSTICS: (
            authorization.capabilities.real_joint_motion_ready
        ),
        RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION: (
            authorization.capabilities.real_joint_motion_ready
        ),
        RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION: (
            authorization.capabilities.real_cartesian_motion_ready
        ),
        RealHardwareAuthorizationPurpose.REAL_PLAYBACK: (
            authorization.capabilities.real_playback_ready
        ),
        RealHardwareAuthorizationPurpose.REAL_VISION_FOLLOW: (
            authorization.capabilities.real_vision_follow_ready
        ),
    }[authorization.purpose]
    if not purpose_ready:
        raise FeetechAdapterPendingError(
            "Real hardware authorization purpose is not capability-ready"
        )


def _validate_device_protocol(device: str, protocol: str) -> None:
    if not isinstance(device, str) or not device.strip() or len(device) > 256:
        raise ValueError("an explicit bounded device is required")
    if not isinstance(protocol, str) or not protocol.strip() or len(protocol) > 64:
        raise ValueError("an explicit bounded protocol is required")


def _validate_explicit_ids(servo_ids: tuple[int, ...]) -> None:
    if not isinstance(servo_ids, tuple) or not servo_ids:
        raise ValueError("an explicit servo ID tuple is required")
    if len(servo_ids) != len(set(servo_ids)):
        raise ValueError("explicit servo IDs must be unique")
    if any(
        isinstance(servo_id, bool)
        or not isinstance(servo_id, int)
        or servo_id < 1
        or servo_id > 253
        for servo_id in servo_ids
    ):
        raise ValueError("explicit servo IDs must be integers from 1 through 253")
