"""Reviewed explicit-ID STS3215 bus for the product REAL motion runtime."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Mapping
from contextlib import suppress
from importlib import import_module
from importlib.util import find_spec
from types import ModuleType
from typing import Protocol, TypeVar, cast

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

SUPPORTED_PROTOCOL = "STS3215"
BAUD_RATE = 1_000_000
STS3215_MODEL_NUMBER = 777
COMM_SUCCESS = 0
MIN_ANGLE_LIMIT_ADDRESS = 9
MAX_ANGLE_LIMIT_ADDRESS = 11
OPERATING_MODE_ADDRESS = 33
TORQUE_ENABLE_ADDRESS = 40
GOAL_POSITION_ADDRESS = 42
LEGACY_STREAM_SPEED = 3_400
LEGACY_STREAM_ACCELERATION = 0
ADAPTER_ID = "ftservo-production-motion-bus"
PACKAGE = "ftservo-python-sdk==2.0.0"


class _Port(Protocol):
    def setBaudRate(self, baudrate: int) -> bool: ...

    def closePort(self) -> None: ...


class _Packet(Protocol):
    def ping(self, servo_id: int) -> tuple[int, int, int]: ...

    def ReadPos(self, servo_id: int) -> tuple[int, int, int]: ...

    def WritePosEx(
        self,
        servo_id: int,
        position: int,
        speed: int,
        acceleration: int,
    ) -> tuple[int, int]: ...

    def read1ByteTxRx(self, servo_id: int, address: int) -> tuple[int, int, int]: ...

    def read2ByteTxRx(self, servo_id: int, address: int) -> tuple[int, int, int]: ...

    def write1ByteTxRx(self, servo_id: int, address: int, value: int) -> tuple[int, int]: ...

    def write2ByteTxRx(self, servo_id: int, address: int, value: int) -> tuple[int, int]: ...


class _Sdk(Protocol):
    def PortHandler(self, device: str) -> _Port: ...

    def sms_sts(self, port: _Port) -> _Packet: ...


_T = TypeVar("_T")


async def _completion_observed_thread_call(call: Callable[[], _T], *, name: str) -> _T:
    """Do not release ownership while a non-cancellable SDK transaction is running."""

    task = asyncio.create_task(asyncio.to_thread(call), name=name)
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            if cancellation is None:
                cancellation = error
        except Exception:
            pass
    try:
        result = task.result()
    except BaseException as error:
        if cancellation is not None and error is not cancellation:
            raise cancellation from error
        raise
    if cancellation is not None:
        raise cancellation
    return result


def _encode_signed_position(value: int) -> int:
    magnitude = abs(value)
    if magnitude > 0x7FFF:
        raise ValueError("STS3215 signed position magnitude exceeds 15 bits")
    return magnitude | (0x8000 if value < 0 else 0)


class FtServoProductionBusFactory:
    """Construct an inert bus only after a complete REAL motion grant."""

    def __init__(
        self,
        *,
        importer: Callable[[str], ModuleType] = import_module,
        package_available: Callable[[str], bool] | None = None,
    ) -> None:
        self._importer = importer
        self._package_available = package_available or (lambda name: find_spec(name) is not None)

    @property
    def dependency(self) -> HardwareDependencyStatus:
        installed = self._package_available("scservo_sdk")
        return HardwareDependencyStatus(
            adapter_id=ADAPTER_ID,
            state=(
                HardwareDependencyState.AVAILABLE
                if installed
                else HardwareDependencyState.UNAVAILABLE
            ),
            package_name=PACKAGE,
            license_status="MIT_REVIEWED",
            notice=(
                "Explicit-ID STS3215 product motion adapter derived from pinned Legacy "
                "ff8bbda0; no scan, arbitrary register, Home, or calibration mutation surface."
            ),
        )

    def create(self, authorization: RealHardwareAccessGrant) -> FtServoProductionBus:
        if self.dependency.state is not HardwareDependencyState.AVAILABLE:
            raise RuntimeError("The reviewed ftservo-python-sdk dependency is unavailable")
        if authorization.adapter_id != ADAPTER_ID:
            raise PermissionError("REAL motion grant targets another adapter")
        if authorization.purpose not in {
            RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION,
            RealHardwareAuthorizationPurpose.REAL_PLAYBACK,
        }:
            raise PermissionError("The grant does not authorize product motion")
        evidence = authorization.session
        if not evidence.confirmed or not evidence.physical_estop_confirmed:
            raise PermissionError("REAL motion grant is incomplete")
        return FtServoProductionBus(authorization, importer=self._importer)


class FtServoProductionBus:
    """One lazy, serialized bus with exact-ID writes and truthful Hold semantics."""

    def __init__(
        self,
        authorization: RealHardwareAccessGrant,
        *,
        importer: Callable[[str], ModuleType] = import_module,
    ) -> None:
        self._authorization = authorization
        self._allowed_ids = authorization.session.allowed_servo_ids
        self._importer = importer
        self._port: _Port | None = None
        self._packet: _Packet | None = None
        self._device: str | None = None
        self._connected = False
        self._torque_enabled: set[int] = set()
        self._stream_configured: set[int] = set()
        self._guard = asyncio.Lock()
        self._stop_requested = threading.Event()

    async def open(self, device: str, protocol: str) -> None:
        if protocol != SUPPORTED_PROTOCOL or not device.startswith("/dev/"):
            raise ValueError("REAL motion requires one explicit STS3215 /dev path")
        candidate = ExplicitServoDevice(
            robot_unit_id=self._authorization.session.robot_unit_id,
            serial_port=device,
            protocol=protocol,
            servo_ids=self._allowed_ids,
        )
        if explicit_device_fingerprint(candidate) != self._authorization.device_fingerprint:
            raise PermissionError("device identity does not match the REAL motion grant")
        async with self._guard:
            if self._connected:
                return
            self._device = device
            try:
                await _completion_observed_thread_call(self._open_sync, name="ftservo-real-open")
                self._connected = True
            except BaseException:
                self._device = None
                raise

    async def close(self) -> None:
        self._stop_requested.set()
        async with self._guard:
            await _completion_observed_thread_call(self._close_sync, name="ftservo-real-close")
            self._connected = False

    async def ping_explicit_ids(self, servo_ids: tuple[int, ...]) -> Mapping[int, ServoPingResult]:
        self._require_read_ids(servo_ids)
        async with self._guard:
            values = await _completion_observed_thread_call(
                lambda: self._ping_sync(servo_ids),
                name="ftservo-real-ping",
            )
        return {
            servo_id: ServoPingResult(
                servo_id=servo_id,
                responded=model == STS3215_MODEL_NUMBER,
                detail=(
                    "explicit STS3215 responded"
                    if model == STS3215_MODEL_NUMBER
                    else "model mismatch"
                ),
            )
            for servo_id, model in values.items()
        }

    async def read_present_positions(self, servo_ids: tuple[int, ...]) -> Mapping[int, int]:
        self._require_read_ids(servo_ids)
        async with self._guard:
            return await _completion_observed_thread_call(
                lambda: {servo_id: self._read_position(servo_id) for servo_id in servo_ids},
                name="ftservo-real-read-positions",
            )

    async def read_operating_modes(self, servo_ids: tuple[int, ...]) -> Mapping[int, str]:
        self._require_read_ids(servo_ids)
        async with self._guard:
            return await _completion_observed_thread_call(
                lambda: {servo_id: self._read_mode(servo_id) for servo_id in servo_ids},
                name="ftservo-real-read-modes",
            )

    async def read_torque_states(self, servo_ids: tuple[int, ...]) -> Mapping[int, bool]:
        self._require_read_ids(servo_ids)
        async with self._guard:
            return await _completion_observed_thread_call(
                lambda: {
                    servo_id: self._read1(servo_id, TORQUE_ENABLE_ADDRESS, "torque") == 1
                    for servo_id in servo_ids
                },
                name="ftservo-real-read-torque",
            )

    async def write_goal_positions(self, goal_positions: Mapping[int, int]) -> ServoWriteResult:
        requested = tuple(goal_positions)
        self._require_write_ids(requested)
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in goal_positions.values()
        ):
            raise TypeError("REAL goal positions must be integer raw values")
        self._stop_requested.clear()
        written: tuple[int, ...] = ()
        try:
            async with self._guard:
                written = await _completion_observed_thread_call(
                    lambda: self._write_goals_sync(goal_positions),
                    name="ftservo-real-write-goals",
                )
        except Exception:
            failed = tuple(servo_id for servo_id in requested if servo_id not in written)
            return ServoWriteResult(
                requested_ids=requested,
                written_ids=written,
                failed_ids=failed,
                connected=self._connected,
                complete=False,
                safety_state_known=False,
                detail="STS3215 goal write failed or was interrupted",
            )
        return ServoWriteResult(
            requested_ids=requested,
            written_ids=written,
            failed_ids=(),
            connected=True,
            complete=True,
            safety_state_known=True,
            detail="Exact-ID STS3215 goals written and available for bounded readback",
        )

    async def stop_or_hold(self, servo_ids: tuple[int, ...]) -> RealStopOutcome:
        self._require_write_ids(servo_ids)
        self._stop_requested.set()
        async with self._guard:
            if not self._connected:
                return RealStopOutcome(
                    result=RealStopResult.NOT_CONNECTED,
                    requested_ids=servo_ids,
                    affected_ids=(),
                    connected=False,
                    safety_state_known=False,
                    detail="REAL ServoBus is not connected",
                )
            try:
                affected = await _completion_observed_thread_call(
                    lambda: self._hold_sync(servo_ids),
                    name="ftservo-real-hold",
                )
            except Exception:
                return RealStopOutcome(
                    result=RealStopResult.SAFETY_STATE_UNCERTAIN,
                    requested_ids=servo_ids,
                    affected_ids=(),
                    connected=True,
                    safety_state_known=False,
                    detail="Software Hold failed; use the physical E-stop",
                )
        return RealStopOutcome(
            result=RealStopResult.HOLD_REQUESTED,
            requested_ids=servo_ids,
            affected_ids=affected,
            connected=True,
            safety_state_known=False,
            detail="Present positions were written back as goals; physical stop is not claimed",
        )

    def _open_sync(self) -> None:
        if self._port is not None or self._packet is not None:
            raise RuntimeError("REAL ServoBus has an inconsistent open state")
        sdk = cast(_Sdk, self._importer("scservo_sdk"))
        device = self._device
        if device is None:
            raise RuntimeError("REAL ServoBus has no explicit device binding")
        port = sdk.PortHandler(device)
        packet = sdk.sms_sts(port)
        try:
            if port.setBaudRate(BAUD_RATE) is not True:
                raise RuntimeError("could not open the explicit STS3215 port at 1 Mbps")
        except BaseException:
            with suppress(Exception):
                port.closePort()
            raise
        self._port = port
        self._packet = packet

    def _close_sync(self) -> None:
        port = self._port
        try:
            packet = self._packet
            if packet is not None:
                for servo_id in tuple(self._torque_enabled):
                    result, error = packet.write1ByteTxRx(servo_id, TORQUE_ENABLE_ADDRESS, 0)
                    self._require_success(result, error, operation=f"disable torque {servo_id}")
        finally:
            self._torque_enabled.clear()
            self._stream_configured.clear()
            self._packet = None
            self._port = None
            self._device = None
            if port is not None:
                port.closePort()

    def _ping_sync(self, servo_ids: tuple[int, ...]) -> dict[int, int]:
        packet = self._require_packet()
        values: dict[int, int] = {}
        for servo_id in servo_ids:
            model, result, error = packet.ping(servo_id)
            self._require_success(result, error, operation=f"ping {servo_id}")
            values[servo_id] = model
        return values

    def _write_goals_sync(self, goals: Mapping[int, int]) -> tuple[int, ...]:
        packet = self._require_packet()
        written: list[int] = []
        for servo_id in goals:
            if self._stop_requested.is_set():
                raise RuntimeError("REAL goal write interrupted by priority Stop")
            if servo_id not in self._stream_configured:
                current = self._read_position(servo_id)
                result, error = packet.WritePosEx(
                    servo_id,
                    _encode_signed_position(current),
                    LEGACY_STREAM_SPEED,
                    LEGACY_STREAM_ACCELERATION,
                )
                self._require_success(result, error, operation=f"configure stream {servo_id}")
                self._stream_configured.add(servo_id)
            if servo_id not in self._torque_enabled:
                result, error = packet.write1ByteTxRx(servo_id, TORQUE_ENABLE_ADDRESS, 1)
                self._require_success(result, error, operation=f"enable torque {servo_id}")
                self._torque_enabled.add(servo_id)
            result, error = packet.write2ByteTxRx(
                servo_id,
                GOAL_POSITION_ADDRESS,
                _encode_signed_position(goals[servo_id]),
            )
            self._require_success(result, error, operation=f"write goal {servo_id}")
            written.append(servo_id)
        return tuple(written)

    def _hold_sync(self, servo_ids: tuple[int, ...]) -> tuple[int, ...]:
        packet = self._require_packet()
        positions = {servo_id: self._read_position(servo_id) for servo_id in servo_ids}
        affected: list[int] = []
        for servo_id, raw in positions.items():
            result, error = packet.write2ByteTxRx(
                servo_id,
                GOAL_POSITION_ADDRESS,
                _encode_signed_position(raw),
            )
            self._require_success(result, error, operation=f"hold {servo_id}")
            affected.append(servo_id)
        return tuple(affected)

    def _read_position(self, servo_id: int) -> int:
        value, result, error = self._require_packet().ReadPos(servo_id)
        self._require_success(result, error, operation=f"read position {servo_id}")
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuntimeError("STS3215 position was not an integer")
        return value

    def _read_mode(self, servo_id: int) -> str:
        mode = self._read1(servo_id, OPERATING_MODE_ADDRESS, "operating mode")
        if mode != 0:
            return {1: "VELOCITY_CLOSED_LOOP", 2: "VELOCITY_OPEN_LOOP", 3: "STEP"}.get(
                mode, f"UNKNOWN_{mode}"
            )
        minimum = self._read2(servo_id, MIN_ANGLE_LIMIT_ADDRESS, "minimum angle limit")
        maximum = self._read2(servo_id, MAX_ANGLE_LIMIT_ADDRESS, "maximum angle limit")
        return "MULTI_TURN" if (minimum, maximum) == (0, 0) else "SINGLE_TURN"

    def _read1(self, servo_id: int, address: int, operation: str) -> int:
        value, result, error = self._require_packet().read1ByteTxRx(servo_id, address)
        self._require_success(result, error, operation=f"{operation} {servo_id}")
        return value

    def _read2(self, servo_id: int, address: int, operation: str) -> int:
        value, result, error = self._require_packet().read2ByteTxRx(servo_id, address)
        self._require_success(result, error, operation=f"{operation} {servo_id}")
        return value

    def _require_packet(self) -> _Packet:
        if not self._connected or self._packet is None or self._port is None:
            raise RuntimeError("REAL ServoBus is not connected")
        return self._packet

    def _require_read_ids(self, servo_ids: tuple[int, ...]) -> None:
        if not servo_ids or len(servo_ids) != len(set(servo_ids)):
            raise ValueError("Servo reads require unique explicit IDs")
        if not set(servo_ids) <= set(self._allowed_ids):
            raise PermissionError("Servo read escaped the authorized ID allowlist")

    def _require_write_ids(self, servo_ids: tuple[int, ...]) -> None:
        if servo_ids != self._allowed_ids:
            raise PermissionError("Servo write/Stop must target the exact authorized ID order")

    @staticmethod
    def _require_success(result: int, error: int, *, operation: str) -> None:
        if result != COMM_SUCCESS or error != 0:
            raise RuntimeError(f"{operation} failed: result={result}, error={error}")


__all__ = ["FtServoProductionBus", "FtServoProductionBusFactory"]
