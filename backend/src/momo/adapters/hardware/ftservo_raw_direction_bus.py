"""Exact-device STS3215 adapter for the bounded Raw direction workflow only.

This adapter deliberately does not implement the production ``ServoBus``.  It can
open one configured port, address one allowlisted Servo at a time, execute an
already-prepared comparison step, and request a hold at the observed position.
There is no scanning, Home, arbitrary register API, Cartesian motion, or playback.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from importlib import import_module
from types import ModuleType
from typing import Literal, Protocol, cast
from uuid import UUID

from momo.domain.raw_direction import PreparedRawDirectionCommand
from momo.domain.real_hardware import RealStopOutcome, RealStopResult, ServoWriteResult
from momo.ports.servo_bus import CommissioningPositionReadback

BAUD_RATE = 1_000_000
SUPPORTED_PROTOCOL = "STS3215"
STS3215_MODEL_NUMBER = 777
TORQUE_ENABLE_ADDRESS = 40
COMM_SUCCESS = 0
RAW_SPEED_COUNTS_PER_SECOND = 400
RAW_ACCELERATION = 1
# Match the pinned Legacy V2 controller's proven field-settling policy.  Four
# counts was tighter than the mechanism's loaded repeatability and caused a
# completed small move to be reported as a failure.
SETTLE_TIMEOUT_S = 2.5
TARGET_TOLERANCE_COUNTS = 16
MIN_DIRECTIONAL_PROGRESS_RATIO = 0.75
SMALL_DIRECTION_STEP_MAX_COUNTS = 16
SMALL_DIRECTIONAL_PROGRESS_RATIO = 0.30


class RawDirectionSettleTimeout(TimeoutError):
    """The Servo kept responding but did not enter the accepted target band."""

    def __init__(
        self,
        *,
        target_raw: int,
        observed_raw: int,
        tolerance_counts: int,
        progress_counts: int,
        required_progress_counts: int,
    ) -> None:
        super().__init__(
            "STS3215 comparison step did not settle before timeout "
            f"(target_raw={target_raw}, observed_raw={observed_raw}, "
            f"tolerance_counts={tolerance_counts}, progress_counts={progress_counts}, "
            f"required_progress_counts={required_progress_counts})"
        )
        self.target_raw = target_raw
        self.observed_raw = observed_raw
        self.tolerance_counts = tolerance_counts
        self.progress_counts = progress_counts
        self.required_progress_counts = required_progress_counts


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

    def write1ByteTxRx(self, servo_id: int, address: int, value: int) -> tuple[int, int]: ...


class _Sdk(Protocol):
    def PortHandler(self, device: str) -> _Port: ...

    def sms_sts(self, port: _Port) -> _Packet: ...


def _encode_signed_position(value: int) -> int:
    magnitude = abs(value)
    if magnitude > 0x7FFF:
        raise ValueError("STS3215 signed position magnitude exceeds 15 bits")
    return magnitude | (0x8000 if value < 0 else 0)


class FtServoRawDirectionBus:
    """Lazily opened, single-joint physical adapter for Raw direction comparison."""

    adapter_id = "ftservo-raw-direction-bus"
    is_physical_adapter: Literal[True] = True

    def __init__(
        self,
        *,
        device: str,
        protocol: str,
        allowed_servo_ids: tuple[int, ...],
        importer: Callable[[str], ModuleType] = import_module,
        settle_timeout_s: float = SETTLE_TIMEOUT_S,
        target_tolerance_counts: int = TARGET_TOLERANCE_COUNTS,
        min_directional_progress_ratio: float = MIN_DIRECTIONAL_PROGRESS_RATIO,
    ) -> None:
        if not device.startswith("/dev/"):
            raise ValueError("Raw direction device must be one explicit /dev path")
        if protocol != SUPPORTED_PROTOCOL:
            raise ValueError(f"Raw direction adapter supports only {SUPPORTED_PROTOCOL}")
        if not allowed_servo_ids or len(allowed_servo_ids) != len(set(allowed_servo_ids)):
            raise ValueError("Raw direction adapter requires unique explicit Servo IDs")
        if any(isinstance(value, bool) or not 1 <= value <= 253 for value in allowed_servo_ids):
            raise ValueError("Raw direction Servo IDs must be integers from 1 through 253")
        if settle_timeout_s <= 0:
            raise ValueError("Raw direction settle timeout must be positive")
        if target_tolerance_counts < 0:
            raise ValueError("Raw direction target tolerance cannot be negative")
        if not 0 < min_directional_progress_ratio <= 1:
            raise ValueError("Raw direction minimum progress ratio must be in (0, 1]")
        self._device = device
        self._protocol = protocol
        self._allowed_ids = allowed_servo_ids
        self._importer = importer
        self._settle_timeout_s = float(settle_timeout_s)
        self._target_tolerance_counts = int(target_tolerance_counts)
        self._min_directional_progress_ratio = float(min_directional_progress_ratio)
        self._port: _Port | None = None
        self._packet: _Packet | None = None
        self._session_id: UUID | None = None
        self._torque_enabled: set[int] = set()
        self._guard = asyncio.Lock()

    async def reset_for_session(self, session_id: UUID) -> None:
        if not isinstance(session_id, UUID):
            raise TypeError("Raw direction session_id must be a UUID")
        async with self._guard:
            if self._packet is None:
                await asyncio.to_thread(self._open_and_verify)
            self._session_id = session_id

    async def read_present_position(self, servo_id: int) -> CommissioningPositionReadback:
        self._require_allowed(servo_id)
        async with self._guard:
            raw = await asyncio.to_thread(self._read_position, servo_id)
        return CommissioningPositionReadback(
            servo_id=servo_id,
            raw_position=raw,
            captured_at=datetime.now(UTC),
        )

    async def write_prepared_raw_direction_command(
        self,
        command: PreparedRawDirectionCommand,
    ) -> ServoWriteResult:
        if not isinstance(command, PreparedRawDirectionCommand):
            raise TypeError("Raw direction adapter accepts only a prepared command")
        self._require_allowed(command.servo_id)
        if command.session_id != self._session_id:
            raise PermissionError("Raw direction command belongs to another session")
        async with self._guard:
            await asyncio.to_thread(self._execute_step, command)
        return ServoWriteResult(
            requested_ids=(command.servo_id,),
            written_ids=(command.servo_id,),
            failed_ids=(),
            connected=True,
            complete=True,
            safety_state_known=True,
            detail="One backend-prepared STS3215 comparison step completed",
        )

    async def stop_or_hold(self, servo_id: int) -> RealStopOutcome:
        self._require_id_allowed(servo_id)
        async with self._guard:
            if self._packet is None:
                return RealStopOutcome(
                    result=RealStopResult.NOT_CONNECTED,
                    requested_ids=(servo_id,),
                    affected_ids=(),
                    connected=False,
                    safety_state_known=False,
                    detail="Raw direction adapter is not connected",
                )
            await asyncio.to_thread(self._request_hold, servo_id)
        return RealStopOutcome(
            result=RealStopResult.HOLD_REQUESTED,
            requested_ids=(servo_id,),
            affected_ids=(servo_id,),
            connected=True,
            safety_state_known=False,
            detail=(
                "Current position was written back as Goal_Position; "
                "physical E-stop remains authoritative"
            ),
        )

    async def close(self) -> None:
        async with self._guard:
            await asyncio.to_thread(self._close_sync)

    def _open_and_verify(self) -> None:
        if self._packet is not None or self._port is not None:
            raise RuntimeError("Raw direction adapter has an inconsistent open state")
        sdk = cast(_Sdk, self._importer("scservo_sdk"))
        port = sdk.PortHandler(self._device)
        packet = sdk.sms_sts(port)
        try:
            if port.setBaudRate(BAUD_RATE) is not True:
                raise RuntimeError("Could not open the explicit STS3215 port at 1 Mbps")
            for servo_id in self._allowed_ids:
                model, result, error = packet.ping(servo_id)
                self._require_success(result, error, operation=f"ping Servo {servo_id}")
                if model != STS3215_MODEL_NUMBER:
                    raise RuntimeError(
                        f"Servo {servo_id} model {model} is not STS3215 model "
                        f"{STS3215_MODEL_NUMBER}"
                    )
        except BaseException:
            port.closePort()
            raise
        self._port = port
        self._packet = packet

    def _execute_step(self, command: PreparedRawDirectionCommand) -> None:
        current = self._read_position(command.servo_id)
        if current != command.start_raw:
            raise RuntimeError("Servo moved after the backend prepared the Raw comparison step")
        # Set Goal to the observed position before enabling torque, preventing a
        # stale Goal register from pulling the mechanism when torque is engaged.
        self._write_position(command.servo_id, current)
        if command.servo_id not in self._torque_enabled:
            packet = self._require_packet()
            result, error = packet.write1ByteTxRx(
                command.servo_id,
                TORQUE_ENABLE_ADDRESS,
                1,
            )
            self._require_success(result, error, operation="enable torque")
            self._torque_enabled.add(command.servo_id)
        self._write_position(command.servo_id, command.target_raw)
        deadline = time.monotonic() + self._settle_timeout_s
        effective_tolerance = min(
            self._target_tolerance_counts,
            max(1, command.step_counts // 4),
        )
        # Direct-drive wrist joints have only about 11 encoder counts in a 1°
        # comparison step.  Applying the large-step 75% threshold to that
        # quantized motion rejects a clearly same-direction readback under
        # normal gear/load stiction.  Keep a multi-count noise margin while
        # accepting enough motion to let the operator judge the sign.
        progress_ratio = (
            SMALL_DIRECTIONAL_PROGRESS_RATIO
            if command.step_counts <= SMALL_DIRECTION_STEP_MAX_COUNTS
            else self._min_directional_progress_ratio
        )
        required_progress = max(1, math.ceil(command.step_counts * progress_ratio))
        while True:
            observed = self._read_position(command.servo_id)
            if abs(observed - command.target_raw) <= effective_tolerance:
                return
            if time.monotonic() >= deadline:
                signed_progress = (observed - command.start_raw) * command.direction.sign
                # This workflow characterizes direction, not positioning
                # accuracy.  A loaded mechanism may stop just outside the
                # exact target band while still providing an unambiguous sign.
                if signed_progress >= required_progress:
                    return
                raise RawDirectionSettleTimeout(
                    target_raw=command.target_raw,
                    observed_raw=observed,
                    tolerance_counts=effective_tolerance,
                    progress_counts=signed_progress,
                    required_progress_counts=required_progress,
                )
            time.sleep(0.02)

    def _request_hold(self, servo_id: int) -> None:
        current = self._read_position(servo_id)
        self._write_position(servo_id, current)

    def _write_position(self, servo_id: int, raw: int) -> None:
        result, error = self._require_packet().WritePosEx(
            servo_id,
            _encode_signed_position(raw),
            RAW_SPEED_COUNTS_PER_SECOND,
            RAW_ACCELERATION,
        )
        self._require_success(result, error, operation=f"write Goal_Position Servo {servo_id}")

    def _read_position(self, servo_id: int) -> int:
        value, result, error = self._require_packet().ReadPos(servo_id)
        self._require_success(result, error, operation=f"read Present_Position Servo {servo_id}")
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuntimeError("STS3215 position readback was not an integer")
        return value

    def _close_sync(self) -> None:
        packet = self._packet
        port = self._port
        if packet is not None:
            for servo_id in tuple(self._torque_enabled):
                try:
                    result, error = packet.write1ByteTxRx(
                        servo_id,
                        TORQUE_ENABLE_ADDRESS,
                        0,
                    )
                    self._require_success(result, error, operation="disable torque")
                except Exception:
                    # Close must still release the serial descriptor; the physical
                    # E-stop remains authoritative if a torque-disable write fails.
                    pass
        self._torque_enabled.clear()
        self._session_id = None
        self._packet = None
        self._port = None
        if port is not None:
            port.closePort()

    def _require_allowed(self, servo_id: int) -> None:
        self._require_id_allowed(servo_id)
        if self._packet is None:
            raise RuntimeError("Raw direction adapter is not connected")

    def _require_id_allowed(self, servo_id: int) -> None:
        if servo_id not in self._allowed_ids:
            raise PermissionError("Servo ID is outside the explicit Raw direction allowlist")

    def _require_packet(self) -> _Packet:
        if self._packet is None or self._port is None:
            raise RuntimeError("Raw direction adapter is not connected")
        return self._packet

    @staticmethod
    def _require_success(result: int, error: int, *, operation: str) -> None:
        if result != COMM_SUCCESS or error != 0:
            raise RuntimeError(f"{operation} failed: result={result}, error={error}")


__all__ = ["FtServoRawDirectionBus", "RawDirectionSettleTimeout"]
