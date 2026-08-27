"""Reviewed, read-only STS3215 bridge for the official Feetech Python SDK.

The optional SDK is imported only from :meth:`open`, after MOMO's complete
operator/session/device grant has already been checked by ``FeetechServoBus``.
This module deliberately exposes no register-write implementation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import suppress
from importlib import import_module
from types import ModuleType
from typing import Protocol, cast

from momo.adapters.hardware.feetech_servo_bus import (
    FeetechAdapterPendingError,
    FeetechDependencyError,
)

SUPPORTED_PROTOCOL = "STS3215"
BAUD_RATE = 1_000_000
STS3215_MODEL_NUMBER = 777

# Official FTServo_Python ``sms_sts.py`` control-table addresses.
_MIN_ANGLE_LIMIT = 9
_MAX_ANGLE_LIMIT = 11
_OPERATING_MODE = 33
_TORQUE_ENABLE = 40
_PRESENT_POSITION = 56
_COMM_SUCCESS = 0


class _PortHandler(Protocol):
    def setBaudRate(self, baudrate: int) -> bool: ...

    def closePort(self) -> None: ...


class _PacketHandler(Protocol):
    def ping(self, servo_id: int) -> tuple[int, int, int]: ...

    def read1ByteTxRx(self, servo_id: int, address: int) -> tuple[int, int, int]: ...

    def read2ByteTxRx(self, servo_id: int, address: int) -> tuple[int, int, int]: ...

    def ReadPos(self, servo_id: int) -> tuple[int, int, int]: ...


class _SdkModule(Protocol):
    def PortHandler(self, device: str) -> _PortHandler: ...

    def sms_sts(self, port_handler: _PortHandler) -> _PacketHandler: ...


class FtServoReadOnlyBridge:
    """Small allowlisted adapter over only ping and bounded read calls."""

    def __init__(self, *, importer: Callable[[str], ModuleType] = import_module) -> None:
        self._importer = importer
        self._port: _PortHandler | None = None
        self._packet: _PacketHandler | None = None

    def open(self, device: str, protocol: str) -> None:
        if protocol != SUPPORTED_PROTOCOL:
            raise ValueError(f"only {SUPPORTED_PROTOCOL} is supported by this bridge")
        if self._port is not None or self._packet is not None:
            raise RuntimeError("Feetech read-only bridge is already open")
        try:
            sdk = cast(_SdkModule, self._importer("scservo_sdk"))
        except (ImportError, ModuleNotFoundError) as error:
            raise FeetechDependencyError(
                "The official ftservo-python-sdk package is not installed"
            ) from error
        port = sdk.PortHandler(device)
        packet = sdk.sms_sts(port)
        try:
            if port.setBaudRate(BAUD_RATE) is not True:
                raise FeetechDependencyError("Feetech SDK could not open the explicit port")
        except BaseException:
            # SDK construction can leave a partially initialized serial object.
            # Retain no handle after a best-effort close.
            with suppress(Exception):
                port.closePort()
            raise
        self._port = port
        self._packet = packet

    def close(self) -> None:
        port = self._port
        self._packet = None
        self._port = None
        if port is not None:
            port.closePort()

    def ping(self, servo_id: int) -> bool:
        model, result, error = self._require_packet().ping(servo_id)
        if result != _COMM_SUCCESS:
            return False
        self._require_no_servo_error(error, operation="ping", servo_id=servo_id)
        if model != STS3215_MODEL_NUMBER:
            raise RuntimeError(
                f"servo {servo_id} model {model} is not reviewed STS3215 model "
                f"{STS3215_MODEL_NUMBER}"
            )
        return True

    def read_present_position(self, servo_id: int) -> int:
        value, result, error = self._require_packet().ReadPos(servo_id)
        self._require_read_success(result, error, operation="position", servo_id=servo_id)
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuntimeError("STS3215 present position was not an integer")
        return value

    def read_operating_mode(self, servo_id: int) -> str:
        packet = self._require_packet()
        mode = self._read1(packet, servo_id, _OPERATING_MODE, "operating mode")
        if mode != 0:
            return {
                1: "VELOCITY_CLOSED_LOOP",
                2: "VELOCITY_OPEN_LOOP",
                3: "STEP",
            }.get(mode, f"UNKNOWN_{mode}")

        # MOMO's MULTI_TURN profile contract means Feetech position mode with
        # both position limits disabled. A bounded position window is SINGLE_TURN.
        minimum = self._read2(packet, servo_id, _MIN_ANGLE_LIMIT, "minimum angle limit")
        maximum = self._read2(packet, servo_id, _MAX_ANGLE_LIMIT, "maximum angle limit")
        return "MULTI_TURN" if (minimum, maximum) == (0, 0) else "SINGLE_TURN"

    def read_torque_state(self, servo_id: int) -> bool:
        value = self._read1(
            self._require_packet(),
            servo_id,
            _TORQUE_ENABLE,
            "torque state",
        )
        if value not in {0, 1}:
            raise RuntimeError(f"servo {servo_id} returned unsupported torque state {value}")
        return value == 1

    def write_goal_positions(self, goals: Mapping[int, int]) -> Mapping[int, bool]:
        del goals
        raise FeetechAdapterPendingError(
            "The reviewed Feetech bridge is read-only and exposes no register writes"
        )

    def _require_packet(self) -> _PacketHandler:
        packet = self._packet
        if packet is None or self._port is None:
            raise RuntimeError("Feetech read-only bridge is not open")
        return packet

    def _read1(
        self,
        packet: _PacketHandler,
        servo_id: int,
        address: int,
        operation: str,
    ) -> int:
        value, result, error = packet.read1ByteTxRx(servo_id, address)
        self._require_read_success(result, error, operation=operation, servo_id=servo_id)
        return value

    def _read2(
        self,
        packet: _PacketHandler,
        servo_id: int,
        address: int,
        operation: str,
    ) -> int:
        value, result, error = packet.read2ByteTxRx(servo_id, address)
        self._require_read_success(result, error, operation=operation, servo_id=servo_id)
        return value

    @staticmethod
    def _require_read_success(
        result: int,
        error: int,
        *,
        operation: str,
        servo_id: int,
    ) -> None:
        if result != _COMM_SUCCESS:
            raise RuntimeError(f"servo {servo_id} {operation} communication failed: {result}")
        FtServoReadOnlyBridge._require_no_servo_error(
            error,
            operation=operation,
            servo_id=servo_id,
        )

    @staticmethod
    def _require_no_servo_error(error: int, *, operation: str, servo_id: int) -> None:
        if error != 0:
            raise RuntimeError(f"servo {servo_id} {operation} reported status error {error}")


def create_momo_servo_backend() -> FtServoReadOnlyBridge:
    """Construct an inert bridge; SDK import and port access happen only in open()."""

    return FtServoReadOnlyBridge()
