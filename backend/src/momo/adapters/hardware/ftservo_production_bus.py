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
from momo.ports.servo_bus import ServoTorqueTransitionResult

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


class _SyncWriter(Protocol):
    def txPacket(self) -> int: ...

    def clearParam(self) -> None: ...


class _Packet(Protocol):
    groupSyncWrite: _SyncWriter

    def ping(self, servo_id: int) -> tuple[int, int, int]: ...

    def ReadPos(self, servo_id: int) -> tuple[int, int, int]: ...

    def WritePosEx(
        self,
        servo_id: int,
        position: int,
        speed: int,
        acceleration: int,
    ) -> tuple[int, int]: ...

    def SyncWritePosEx(
        self,
        servo_id: int,
        position: int,
        speed: int,
        acceleration: int,
    ) -> bool: ...

    def read1ByteTxRx(self, servo_id: int, address: int) -> tuple[int, int, int]: ...

    def read2ByteTxRx(self, servo_id: int, address: int) -> tuple[int, int, int]: ...

    def write1ByteTxRx(self, servo_id: int, address: int, value: int) -> tuple[int, int]: ...

    def write2ByteTxRx(self, servo_id: int, address: int, value: int) -> tuple[int, int]: ...


class _Sdk(Protocol):
    def PortHandler(self, device: str) -> _Port: ...

    def sms_sts(self, port: _Port) -> _Packet: ...


_T = TypeVar("_T")


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
            RealHardwareAuthorizationPurpose.REAL_VISION_FOLLOW,
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
        self._torque_uncertain: set[int] = set()
        self._last_torque_result: ServoTorqueTransitionResult | None = None
        self._guard = asyncio.Lock()
        self._state_guard = threading.Lock()
        self._write_generation = 0
        self._writes_revoked = False
        self._torque_transition = False
        self._closing = False
        self._closed = False
        self._active_sdk_task: asyncio.Task[object] | None = None

    @property
    def last_torque_result(self) -> ServoTorqueTransitionResult | None:
        """Latest per-Servo torque evidence, including uncertain cleanup."""

        return self._last_torque_result

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
        with self._state_guard:
            if self._closed or self._closing:
                raise RuntimeError("a closed REAL ServoBus cannot be reopened")
        if self._connected:
            return
        self._device = device
        try:
            await self._serialized_sdk_call(self._open_sync, name="ftservo-real-open")
            self._connected = True
        except BaseException:
            self._device = None
            raise

    async def close(self) -> None:
        with self._state_guard:
            if self._closed:
                return
            self._write_generation += 1
            self._writes_revoked = True
            self._closing = True
        try:
            result = await self._serialized_sdk_call(
                self._close_sync,
                name="ftservo-real-close",
            )
            self._last_torque_result = result
            if not result.complete:
                raise RuntimeError("torque cleanup was incomplete; safety state is uncertain")
        finally:
            self._connected = False
            with self._state_guard:
                self._closed = True
                self._closing = False

    async def ping_explicit_ids(self, servo_ids: tuple[int, ...]) -> Mapping[int, ServoPingResult]:
        self._require_read_ids(servo_ids)
        values = await self._serialized_sdk_call(
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
        return await self._serialized_sdk_call(
            lambda: {servo_id: self._read_position(servo_id) for servo_id in servo_ids},
            name="ftservo-real-read-positions",
        )

    async def read_operating_modes(self, servo_ids: tuple[int, ...]) -> Mapping[int, str]:
        self._require_read_ids(servo_ids)
        return await self._serialized_sdk_call(
            lambda: {servo_id: self._read_mode(servo_id) for servo_id in servo_ids},
            name="ftservo-real-read-modes",
        )

    async def read_torque_states(self, servo_ids: tuple[int, ...]) -> Mapping[int, bool]:
        self._require_read_ids(servo_ids)
        return await self._serialized_sdk_call(
            lambda: {
                servo_id: self._read1(servo_id, TORQUE_ENABLE_ADDRESS, "torque") == 1
                for servo_id in servo_ids
            },
            name="ftservo-real-read-torque",
        )

    async def enable_torque_for_execution(
        self,
        servo_ids: tuple[int, ...],
    ) -> ServoTorqueTransitionResult:
        """Arm exactly one reviewed execution; never called during open/startup."""

        self._require_write_ids(servo_ids)
        generation = self._capture_write_generation(require_torque=False)
        result = await self._serialized_sdk_call(
            lambda: self._enable_torque_sync(servo_ids, generation),
            name="ftservo-real-enable-torque",
        )
        self._last_torque_result = result
        return result

    async def disable_torque_for_execution(
        self,
        servo_ids: tuple[int, ...],
    ) -> ServoTorqueTransitionResult:
        """Fence queued goals, then best-effort disable every authorized Servo."""

        self._require_write_ids(servo_ids)
        with self._state_guard:
            self._write_generation += 1
            self._torque_transition = True
        result = await self._serialized_sdk_call(
            lambda: self._disable_torque_sync(servo_ids),
            name="ftservo-real-disable-torque",
        )
        self._last_torque_result = result
        with self._state_guard:
            self._torque_transition = False
        return result

    async def write_goal_positions(self, goal_positions: Mapping[int, int]) -> ServoWriteResult:
        requested = tuple(goal_positions)
        self._require_write_ids(requested)
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in goal_positions.values()
        ):
            raise TypeError("REAL goal positions must be integer raw values")
        try:
            generation = self._capture_write_generation(require_torque=True)
        except RuntimeError as error:
            return ServoWriteResult(
                requested_ids=requested,
                written_ids=(),
                failed_ids=requested,
                connected=self._connected,
                complete=False,
                safety_state_known=False,
                detail=str(error),
            )
        written: tuple[int, ...] = ()
        try:
            written = await self._serialized_sdk_call(
                lambda: self._write_goals_sync(goal_positions, generation),
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
        with self._state_guard:
            self._write_generation += 1
            self._writes_revoked = True
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
            affected = await self._serialized_sdk_call(
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

    def _close_sync(self) -> ServoTorqueTransitionResult:
        port = self._port
        requested = self._allowed_ids
        result = ServoTorqueTransitionResult(
            requested_ids=requested,
            succeeded_ids=requested,
            failed_ids=(),
            torque_enabled=False,
            connected=self._connected,
            complete=self._connected,
            safety_state_known=self._connected,
            detail="No open packet required torque cleanup",
        )
        try:
            packet = self._packet
            if packet is not None:
                result = self._disable_torque_sync(requested)
        finally:
            self._packet = None
            self._port = None
            self._device = None
            if port is not None:
                port.closePort()
        return result

    def _ping_sync(self, servo_ids: tuple[int, ...]) -> dict[int, int]:
        packet = self._require_packet()
        values: dict[int, int] = {}
        for servo_id in servo_ids:
            model, result, error = packet.ping(servo_id)
            self._require_success(result, error, operation=f"ping {servo_id}")
            values[servo_id] = model
        return values

    def _write_goals_sync(
        self,
        goals: Mapping[int, int],
        generation: int,
    ) -> tuple[int, ...]:
        packet = self._require_packet()
        self._require_generation(generation, require_torque=True)
        if len(goals) > 1:
            self._sync_write_positions(goals, generation=generation)
            self._require_generation(generation, require_torque=True)
            return tuple(goals)
        written: list[int] = []
        for servo_id in goals:
            self._require_generation(generation, require_torque=True)
            result, error = packet.WritePosEx(
                servo_id,
                _encode_signed_position(goals[servo_id]),
                LEGACY_STREAM_SPEED,
                LEGACY_STREAM_ACCELERATION,
            )
            self._require_success(result, error, operation=f"write goal {servo_id}")
            written.append(servo_id)
            self._require_generation(generation, require_torque=True)
        return tuple(written)

    def _enable_torque_sync(
        self,
        servo_ids: tuple[int, ...],
        generation: int,
    ) -> ServoTorqueTransitionResult:
        packet = self._require_packet()
        succeeded: list[int] = []
        failed: list[int] = []
        for index, servo_id in enumerate(servo_ids):
            try:
                self._require_generation(generation, require_torque=False)
                if servo_id not in self._torque_enabled:
                    result, error = packet.write1ByteTxRx(
                        servo_id,
                        TORQUE_ENABLE_ADDRESS,
                        1,
                    )
                    self._require_success(result, error, operation=f"enable torque {servo_id}")
                    with self._state_guard:
                        self._torque_enabled.add(servo_id)
                succeeded.append(servo_id)
                self._require_generation(generation, require_torque=False)
            except Exception:
                failed.extend(
                    candidate for candidate in servo_ids[index:] if candidate not in succeeded
                )
                rollback = self._disable_torque_sync(servo_ids)
                if not rollback.complete:
                    with self._state_guard:
                        self._torque_uncertain.update(rollback.failed_ids)
                return ServoTorqueTransitionResult(
                    requested_ids=servo_ids,
                    succeeded_ids=tuple(succeeded),
                    failed_ids=tuple(failed),
                    torque_enabled=False,
                    connected=self._connected,
                    complete=False,
                    safety_state_known=False,
                    detail=(
                        "Torque enable failed; every Servo received best-effort rollback, "
                        f"rollback_failed={rollback.failed_ids}"
                    ),
                )
        return ServoTorqueTransitionResult(
            requested_ids=servo_ids,
            succeeded_ids=servo_ids,
            failed_ids=(),
            torque_enabled=True,
            connected=True,
            complete=True,
            safety_state_known=True,
            detail="Torque explicitly enabled for the reviewed execution only",
        )

    def _disable_torque_sync(
        self,
        servo_ids: tuple[int, ...],
    ) -> ServoTorqueTransitionResult:
        packet = self._require_packet()
        succeeded: list[int] = []
        failed: list[int] = []
        for servo_id in servo_ids:
            try:
                result, error = packet.write1ByteTxRx(
                    servo_id,
                    TORQUE_ENABLE_ADDRESS,
                    0,
                )
                self._require_success(result, error, operation=f"disable torque {servo_id}")
                succeeded.append(servo_id)
                with self._state_guard:
                    self._torque_enabled.discard(servo_id)
                    self._torque_uncertain.discard(servo_id)
            except Exception:
                failed.append(servo_id)
                with self._state_guard:
                    self._torque_uncertain.add(servo_id)
        complete = not failed
        return ServoTorqueTransitionResult(
            requested_ids=servo_ids,
            succeeded_ids=tuple(succeeded),
            failed_ids=tuple(failed),
            torque_enabled=False,
            connected=self._connected,
            complete=complete,
            safety_state_known=complete,
            detail=(
                "Torque disabled for every authorized Servo"
                if complete
                else "Torque disable was attempted for every Servo; safety state is uncertain"
            ),
        )

    def _hold_sync(self, servo_ids: tuple[int, ...]) -> tuple[int, ...]:
        positions = {servo_id: self._read_position(servo_id) for servo_id in servo_ids}
        if len(positions) > 1:
            self._sync_write_positions(positions)
            return tuple(positions)
        packet = self._require_packet()
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

    def _sync_write_positions(
        self,
        positions: Mapping[int, int],
        *,
        generation: int | None = None,
    ) -> None:
        """Broadcast one coherent STS3215 position frame for all enabled joints.

        Legacy used the SDK's group write when it was available.  Cartesian and
        grouped REAL motion must not serialize six independent Goal_Position
        writes because that makes each joint start at a different instant.
        """

        packet = self._require_packet()
        writer = packet.groupSyncWrite
        writer.clearParam()
        try:
            for servo_id, position in positions.items():
                added = packet.SyncWritePosEx(
                    servo_id,
                    _encode_signed_position(position),
                    LEGACY_STREAM_SPEED,
                    LEGACY_STREAM_ACCELERATION,
                )
                if added is not True:
                    raise RuntimeError(f"could not stage synchronized goal for Servo {servo_id}")
            if generation is not None:
                self._require_generation(generation, require_torque=True)
            result = writer.txPacket()
            if result != COMM_SUCCESS:
                raise RuntimeError(f"synchronized goal write failed with result {result}")
            if generation is not None:
                self._require_generation(generation, require_torque=True)
        finally:
            writer.clearParam()

    async def _serialized_sdk_call(
        self,
        call: Callable[[], _T],
        *,
        name: str,
    ) -> _T:
        """Serialize SDK ownership while allowing caller deadlines to be truthful.

        A cancelled waiter returns immediately, but the lock remains owned until
        the non-cancellable SDK thread actually terminates.  Thus a bounded caller
        can report uncertainty without allowing Stop/Close or a queued write to
        overlap the still-running transaction.
        """

        await self._guard.acquire()
        task: asyncio.Task[_T] = asyncio.create_task(asyncio.to_thread(call), name=name)
        self._active_sdk_task = cast(asyncio.Task[object], task)
        release_here = True
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            release_here = False
            task.add_done_callback(self._release_cancelled_sdk_ownership)
            raise
        finally:
            if release_here:
                self._active_sdk_task = None
                self._guard.release()

    def _release_cancelled_sdk_ownership(self, task: asyncio.Task[object]) -> None:
        with suppress(BaseException):
            task.exception()
        if self._active_sdk_task is task:
            self._active_sdk_task = None
            self._guard.release()

    def _capture_write_generation(self, *, require_torque: bool) -> int:
        with self._state_guard:
            generation = self._write_generation
            self._require_generation_unlocked(generation, require_torque=require_torque)
            return generation

    def _require_generation(self, generation: int, *, require_torque: bool) -> None:
        with self._state_guard:
            self._require_generation_unlocked(generation, require_torque=require_torque)

    def _require_generation_unlocked(self, generation: int, *, require_torque: bool) -> None:
        if generation != self._write_generation:
            raise RuntimeError("REAL write generation was fenced by Stop or cleanup")
        if self._writes_revoked or self._closing or self._closed or self._torque_transition:
            raise RuntimeError("REAL writes are revoked by Stop or lifecycle cleanup")
        if not self._connected:
            raise RuntimeError("REAL ServoBus is not connected")
        if require_torque and (
            set(self._allowed_ids) != self._torque_enabled or self._torque_uncertain
        ):
            raise RuntimeError("Torque is not explicitly armed for this execution")

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
