"""Bounded STS3215 adapter for one-joint commissioning control only."""

from __future__ import annotations

import asyncio
import math
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from importlib import import_module
from types import ModuleType
from typing import Literal, Protocol, TypeVar, cast
from uuid import UUID

from momo.domain.commissioning import (
    HARD_MAX_COMMISSIONING_RAW_SPEED,
    PreparedCommissioningJogTarget,
    PreparedCommissioningTestCommand,
)
from momo.domain.real_hardware import RealStopOutcome, RealStopResult, ServoWriteResult
from momo.ports.servo_bus import CommissioningPositionReadback

BAUD_RATE = 1_000_000
SUPPORTED_PROTOCOL = "STS3215"
STS3215_MODEL_NUMBER = 777
TORQUE_ENABLE_ADDRESS = 40
GOAL_POSITION_ADDRESS = 42
COMM_SUCCESS = 0
# Reuse the Legacy loaded-motor ceiling.  Legacy documents the STS3215
# no-load ceiling as about 3,400 raw/s and deliberately keeps 2,200 raw/s for
# loaded motion.
MAX_RAW_SPEED = HARD_MAX_COMMISSIONING_RAW_SPEED
RAW_ACCELERATION = 1
# Legacy manual control left the volatile motor profile at its power-on maximum.
# Use the explicit STS3215 ceiling instead of the ambiguous zero sentinel so a
# prior commissioning move cannot leave direct control at a residual low speed.
LEGACY_STREAM_SPEED = 3_400
LEGACY_STREAM_ACCELERATION = 0
SETTLE_TIMEOUT_S = 2.5
TARGET_TOLERANCE_COUNTS = 16
MIN_DIRECTIONAL_PROGRESS_RATIO = 0.75
SMALL_DIRECTION_STEP_MAX_COUNTS = 16
SMALL_DIRECTIONAL_PROGRESS_RATIO = 0.30


class CommissioningStepInterrupted(RuntimeError):
    """The priority Stop path interrupted an in-flight bounded step."""


class CommissioningStepSettleTimeout(TimeoutError):
    """The Servo responded but did not make enough same-direction progress."""


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

    def write2ByteTxRx(self, servo_id: int, address: int, value: int) -> tuple[int, int]: ...


class _Sdk(Protocol):
    def PortHandler(self, device: str) -> _Port: ...

    def sms_sts(self, port: _Port) -> _Packet: ...


_T = TypeVar("_T")


async def _completion_observed_thread_call(call: Callable[[], _T], *, name: str) -> _T:
    """Observe the SDK thread through cancellation before releasing the bus lock."""

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


class FtServoCommissioningMotionBus:
    """Lazy exact-device adapter accepting only service-prepared single-joint commands."""

    adapter_id = "ftservo-commissioning-motion-bus"
    is_physical_adapter: Literal[True] = True
    physical_stop_verified: Literal[False] = False

    def __init__(
        self,
        *,
        device: str,
        protocol: str,
        allowed_servo_ids: tuple[int, ...],
        importer: Callable[[str], ModuleType] = import_module,
        settle_timeout_s: float = SETTLE_TIMEOUT_S,
    ) -> None:
        if not device.startswith("/dev/"):
            raise ValueError("Commissioning device must be one explicit /dev path")
        if protocol != SUPPORTED_PROTOCOL:
            raise ValueError(f"Commissioning adapter supports only {SUPPORTED_PROTOCOL}")
        if not allowed_servo_ids or len(allowed_servo_ids) != len(set(allowed_servo_ids)):
            raise ValueError("Commissioning adapter requires unique explicit Servo IDs")
        if any(isinstance(value, bool) or not 1 <= value <= 253 for value in allowed_servo_ids):
            raise ValueError("Commissioning Servo IDs must be integers from 1 through 253")
        if settle_timeout_s <= 0:
            raise ValueError("Commissioning settle timeout must be positive")
        self._device = device
        self._protocol = protocol
        self._allowed_ids = allowed_servo_ids
        self._importer = importer
        self._settle_timeout_s = float(settle_timeout_s)
        self._port: _Port | None = None
        self._packet: _Packet | None = None
        self._session_id: UUID | None = None
        self._torque_enabled: set[int] = set()
        self._legacy_stream_configured: set[int] = set()
        self._guard = asyncio.Lock()
        self._stop_requested = threading.Event()

    async def reset_for_session(self, session_id: UUID) -> None:
        if not isinstance(session_id, UUID):
            raise TypeError("commissioning session_id must be a UUID")
        self._stop_requested.set()
        async with self._guard:
            await _completion_observed_thread_call(
                self._reset_sync,
                name="ftservo-commissioning-session-reset",
            )
            self._session_id = session_id
            self._stop_requested.clear()

    async def read_present_position(self, servo_id: int) -> CommissioningPositionReadback:
        self._require_id_allowed(servo_id)
        async with self._guard:
            raw = await _completion_observed_thread_call(
                lambda: self._read_position(servo_id),
                name=f"ftservo-commissioning-read-{servo_id}",
            )
        return CommissioningPositionReadback(
            servo_id=servo_id,
            raw_position=raw,
            captured_at=datetime.now(UTC),
        )

    async def read_prepared_joint_state(
        self,
        servo_ids: tuple[int, ...],
    ) -> tuple[CommissioningPositionReadback, ...]:
        if not servo_ids or len(servo_ids) != len(set(servo_ids)):
            raise ValueError("position read requires unique explicit Servo IDs")
        for servo_id in servo_ids:
            self._require_id_allowed(servo_id)
        async with self._guard:
            values = await _completion_observed_thread_call(
                lambda: tuple((servo_id, self._read_position(servo_id)) for servo_id in servo_ids),
                name="ftservo-commissioning-read-all",
            )
        captured_at = datetime.now(UTC)
        return tuple(
            CommissioningPositionReadback(
                servo_id=servo_id,
                raw_position=raw,
                captured_at=captured_at,
            )
            for servo_id, raw in values
        )

    async def write_prepared_command(
        self,
        command: PreparedCommissioningTestCommand,
    ) -> ServoWriteResult:
        if not isinstance(command, PreparedCommissioningTestCommand):
            raise TypeError("only a prepared commissioning command may be written")
        self._require_id_allowed(command.servo_id)
        if command.session_id != self._session_id:
            raise PermissionError("commissioning command belongs to another session")
        self._stop_requested.clear()
        async with self._guard:
            await _completion_observed_thread_call(
                lambda: self._execute_step(command),
                name=f"ftservo-commissioning-step-{command.servo_id}",
            )
        return ServoWriteResult(
            requested_ids=(command.servo_id,),
            written_ids=(command.servo_id,),
            failed_ids=(),
            connected=True,
            complete=True,
            safety_state_known=True,
            detail="One backend-prepared low-speed STS3215 joint step completed",
        )

    async def begin_prepared_motion(self, session_id: UUID) -> None:
        """Clear a prior Stop fence only for the currently bound session."""

        if session_id != self._session_id:
            raise PermissionError("commissioning motion belongs to another session")
        async with self._guard:
            self._stop_requested.clear()

    async def write_prepared_jog_target(
        self,
        command: PreparedCommissioningJogTarget,
    ) -> ServoWriteResult:
        if not isinstance(command, PreparedCommissioningJogTarget):
            raise TypeError("only a prepared commissioning jog target may be written")
        self._require_id_allowed(command.servo_id)
        if command.session_id != self._session_id:
            raise PermissionError("commissioning jog target belongs to another session")
        async with self._guard:
            await _completion_observed_thread_call(
                lambda: self._execute_jog_target(command),
                name=f"ftservo-commissioning-jog-{command.servo_id}",
            )
        return ServoWriteResult(
            requested_ids=(command.servo_id,),
            written_ids=(command.servo_id,),
            failed_ids=(),
            connected=True,
            complete=True,
            safety_state_known=True,
            detail="One backend-prepared STS3215 jog target was written",
        )

    async def write_prepared_jog_targets(
        self,
        commands: tuple[PreparedCommissioningJogTarget, ...],
    ) -> ServoWriteResult:
        if not commands:
            raise ValueError("at least one prepared jog target is required")
        requested = tuple(command.servo_id for command in commands)
        if len(requested) != len(set(requested)):
            raise ValueError("prepared jog targets must use unique Servo IDs")
        for command in commands:
            if not isinstance(command, PreparedCommissioningJogTarget):
                raise TypeError("only prepared commissioning jog targets may be written")
            self._require_id_allowed(command.servo_id)
            if command.session_id != self._session_id:
                raise PermissionError("commissioning jog target belongs to another session")
        async with self._guard:
            await _completion_observed_thread_call(
                lambda: self._execute_jog_targets(commands),
                name="ftservo-commissioning-jog-multi",
            )
        return ServoWriteResult(
            requested_ids=requested,
            written_ids=requested,
            failed_ids=(),
            connected=True,
            complete=True,
            safety_state_known=True,
            detail="Backend-prepared STS3215 joint targets were written",
        )

    async def stop_or_hold(self, servo_id: int) -> RealStopOutcome:
        self._require_id_allowed(servo_id)
        self._stop_requested.set()
        async with self._guard:
            if self._packet is None:
                return RealStopOutcome(
                    result=RealStopResult.NOT_CONNECTED,
                    requested_ids=(servo_id,),
                    affected_ids=(),
                    connected=False,
                    safety_state_known=False,
                    detail="Commissioning adapter is not connected",
                )
            await _completion_observed_thread_call(
                lambda: self._request_hold(servo_id),
                name=f"ftservo-commissioning-hold-{servo_id}",
            )
        return RealStopOutcome(
            result=RealStopResult.HOLD_REQUESTED,
            requested_ids=(servo_id,),
            affected_ids=(servo_id,),
            connected=True,
            safety_state_known=False,
            detail="Current position was written back as Goal_Position",
        )

    async def stop_or_hold_many(self, servo_ids: tuple[int, ...]) -> RealStopOutcome:
        if not servo_ids or len(servo_ids) != len(set(servo_ids)):
            raise ValueError("Stop/Hold requires unique explicit Servo IDs")
        for servo_id in servo_ids:
            self._require_id_allowed(servo_id)
        self._stop_requested.set()
        async with self._guard:
            if self._packet is None:
                return RealStopOutcome(
                    result=RealStopResult.NOT_CONNECTED,
                    requested_ids=servo_ids,
                    affected_ids=(),
                    connected=False,
                    safety_state_known=False,
                    detail="Commissioning adapter is not connected",
                )
            await _completion_observed_thread_call(
                lambda: self._request_hold_many(servo_ids),
                name="ftservo-commissioning-hold-all",
            )
        return RealStopOutcome(
            result=RealStopResult.HOLD_REQUESTED,
            requested_ids=servo_ids,
            affected_ids=servo_ids,
            connected=True,
            safety_state_known=False,
            detail="Current positions were written back as Goal_Position",
        )

    async def close(self) -> None:
        self._stop_requested.set()
        async with self._guard:
            await _completion_observed_thread_call(
                self._close_sync,
                name="ftservo-commissioning-close",
            )

    def _reset_sync(self) -> None:
        if self._packet is None:
            self._open_and_verify()
        self._disable_torque_all()

    def _open_and_verify(self) -> None:
        if self._packet is not None or self._port is not None:
            raise RuntimeError("Commissioning adapter has an inconsistent open state")
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

    def _execute_step(self, command: PreparedCommissioningTestCommand) -> None:
        # Evidence motion deliberately uses its own low-speed profile. A later
        # direct-control target must restore the Legacy position-stream profile.
        self._legacy_stream_configured.discard(command.servo_id)
        current = self._read_position(command.servo_id)
        if current != command.start_raw:
            raise RuntimeError("Servo moved after the backend prepared the commissioning step")
        self._write_position(command.servo_id, current, speed=1)
        if command.servo_id not in self._torque_enabled:
            result, error = self._require_packet().write1ByteTxRx(
                command.servo_id,
                TORQUE_ENABLE_ADDRESS,
                1,
            )
            self._require_success(result, error, operation="enable torque")
            self._torque_enabled.add(command.servo_id)

        raw_distance = abs(command.target_raw - command.start_raw)
        raw_per_unit = raw_distance / abs(command.requested_delta)
        raw_speed = max(1, min(MAX_RAW_SPEED, round(raw_per_unit * command.requested_speed)))
        self._write_position(command.servo_id, command.target_raw, speed=raw_speed)
        deadline = time.monotonic() + min(
            self._settle_timeout_s,
            command.command_duration_s + 1.5,
        )
        dynamic_tolerance = min(TARGET_TOLERANCE_COUNTS, max(1, raw_distance // 4))
        progress_ratio = (
            SMALL_DIRECTIONAL_PROGRESS_RATIO
            if raw_distance <= SMALL_DIRECTION_STEP_MAX_COUNTS
            else MIN_DIRECTIONAL_PROGRESS_RATIO
        )
        required_progress = max(1, math.ceil(raw_distance * progress_ratio))
        raw_sign = 1 if command.target_raw > command.start_raw else -1
        while True:
            observed = self._read_position(command.servo_id)
            if self._stop_requested.is_set():
                self._write_position(command.servo_id, observed, speed=1)
                raise CommissioningStepInterrupted("commissioning step stopped by operator")
            if abs(observed - command.target_raw) <= dynamic_tolerance:
                return
            if time.monotonic() >= deadline:
                progress = (observed - command.start_raw) * raw_sign
                if progress >= required_progress:
                    return
                raise CommissioningStepSettleTimeout(
                    "STS3215 commissioning step did not make enough directional progress"
                )
            time.sleep(0.02)

    def _execute_jog_target(self, command: PreparedCommissioningJogTarget) -> None:
        if self._stop_requested.is_set():
            raise CommissioningStepInterrupted("commissioning jog stopped by operator")
        if command.servo_id not in self._legacy_stream_configured:
            current = self._read_position(command.servo_id)
            # Legacy manual control streamed only Goal_Position. Re-establish
            # its volatile STS3215 profile once, while targeting the already
            # observed position, then leave speed/acceleration untouched for
            # every 50 Hz target update.
            self._write_position(
                command.servo_id,
                current,
                speed=LEGACY_STREAM_SPEED,
                acceleration=LEGACY_STREAM_ACCELERATION,
            )
            self._legacy_stream_configured.add(command.servo_id)
        if command.servo_id not in self._torque_enabled:
            result, error = self._require_packet().write1ByteTxRx(
                command.servo_id,
                TORQUE_ENABLE_ADDRESS,
                1,
            )
            self._require_success(result, error, operation="enable torque")
            self._torque_enabled.add(command.servo_id)
        if self._stop_requested.is_set():
            raise CommissioningStepInterrupted("commissioning jog stopped by operator")
        self._write_goal_position(command.servo_id, command.target_raw)

    def _execute_jog_targets(
        self,
        commands: tuple[PreparedCommissioningJogTarget, ...],
    ) -> None:
        if self._stop_requested.is_set():
            raise CommissioningStepInterrupted("commissioning joint move stopped by operator")
        for command in commands:
            self._configure_stream_servo(command.servo_id)
        if self._stop_requested.is_set():
            raise CommissioningStepInterrupted("commissioning joint move stopped by operator")
        for command in commands:
            self._write_goal_position(command.servo_id, command.target_raw)

    def _configure_stream_servo(self, servo_id: int) -> None:
        if servo_id not in self._legacy_stream_configured:
            current = self._read_position(servo_id)
            self._write_position(
                servo_id,
                current,
                speed=LEGACY_STREAM_SPEED,
                acceleration=LEGACY_STREAM_ACCELERATION,
            )
            self._legacy_stream_configured.add(servo_id)
        if servo_id not in self._torque_enabled:
            result, error = self._require_packet().write1ByteTxRx(
                servo_id,
                TORQUE_ENABLE_ADDRESS,
                1,
            )
            self._require_success(result, error, operation="enable torque")
            self._torque_enabled.add(servo_id)

    def _request_hold(self, servo_id: int) -> None:
        current = self._read_position(servo_id)
        self._write_goal_position(servo_id, current)

    def _request_hold_many(self, servo_ids: tuple[int, ...]) -> None:
        positions = tuple((servo_id, self._read_position(servo_id)) for servo_id in servo_ids)
        for servo_id, current in positions:
            self._write_goal_position(servo_id, current)

    def _write_position(
        self,
        servo_id: int,
        raw: int,
        *,
        speed: int,
        acceleration: int = RAW_ACCELERATION,
    ) -> None:
        result, error = self._require_packet().WritePosEx(
            servo_id,
            _encode_signed_position(raw),
            speed,
            acceleration,
        )
        self._require_success(result, error, operation=f"write Goal_Position Servo {servo_id}")

    def _write_goal_position(self, servo_id: int, raw: int) -> None:
        result, error = self._require_packet().write2ByteTxRx(
            servo_id,
            GOAL_POSITION_ADDRESS,
            _encode_signed_position(raw),
        )
        self._require_success(
            result,
            error,
            operation=f"stream Goal_Position Servo {servo_id}",
        )

    def _read_position(self, servo_id: int) -> int:
        value, result, error = self._require_packet().ReadPos(servo_id)
        self._require_success(result, error, operation=f"read Present_Position Servo {servo_id}")
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuntimeError("STS3215 position readback was not an integer")
        return value

    def _disable_torque_all(self) -> None:
        packet = self._packet
        if packet is None:
            self._torque_enabled.clear()
            self._legacy_stream_configured.clear()
            return
        for servo_id in tuple(self._torque_enabled):
            result, error = packet.write1ByteTxRx(servo_id, TORQUE_ENABLE_ADDRESS, 0)
            self._require_success(result, error, operation=f"disable torque Servo {servo_id}")
        self._torque_enabled.clear()
        self._legacy_stream_configured.clear()

    def _close_sync(self) -> None:
        port = self._port
        try:
            self._disable_torque_all()
        finally:
            self._session_id = None
            self._packet = None
            self._port = None
            if port is not None:
                port.closePort()

    def _require_id_allowed(self, servo_id: int) -> None:
        if servo_id not in self._allowed_ids:
            raise PermissionError("Servo ID is outside the commissioning allowlist")

    def _require_packet(self) -> _Packet:
        if self._packet is None or self._port is None:
            raise RuntimeError("Commissioning adapter is not connected")
        return self._packet

    @staticmethod
    def _require_success(result: int, error: int, *, operation: str) -> None:
        if result != COMM_SUCCESS or error != 0:
            raise RuntimeError(f"{operation} failed: result={result}, error={error}")


__all__ = ["FtServoCommissioningMotionBus"]
