"""Minimal explicit-ID ServoBus boundary for Stage 8 real-hardware work."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from momo.domain.commissioning import (
    PreparedCommissioningJogTarget,
    PreparedCommissioningTestCommand,
)
from momo.domain.raw_direction import PreparedRawDirectionCommand
from momo.domain.real_hardware import (
    HardwareDependencyStatus,
    RealHardwareAccessGrant,
    RealStopOutcome,
    ServoPingResult,
    ServoWriteResult,
)


@dataclass(frozen=True, slots=True)
class CommissioningPositionReadback:
    """One timestamped raw position captured from one explicit servo ID."""

    servo_id: int
    raw_position: int
    captured_at: datetime

    def __post_init__(self) -> None:
        if (
            isinstance(self.servo_id, bool)
            or not isinstance(self.servo_id, int)
            or not 1 <= self.servo_id <= 253
        ):
            raise ValueError("servo_id must be an integer from 1 through 253")
        if isinstance(self.raw_position, bool) or not isinstance(self.raw_position, int):
            raise TypeError("raw_position must be an integer")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("captured_at must include a timezone offset")


@runtime_checkable
class CommissioningMotionServoBus(Protocol):
    """Capability-minimal boundary for an authorized one-joint test.

    Deliberately absent: device discovery/opening, scans, multi-servo writes,
    arbitrary registers, operating-mode writes, torque writes, Home, Cartesian
    motion, playback, and every production-motion primitive.  The application
    service prepares the immutable command before it can reach this boundary.
    """

    async def read_present_position(
        self,
        servo_id: int,
    ) -> CommissioningPositionReadback: ...

    async def read_prepared_joint_state(
        self,
        servo_ids: tuple[int, ...],
    ) -> tuple[CommissioningPositionReadback, ...]: ...

    async def write_prepared_command(
        self,
        command: PreparedCommissioningTestCommand,
    ) -> ServoWriteResult: ...

    async def begin_prepared_motion(self, session_id: UUID) -> None: ...

    async def write_prepared_jog_target(
        self,
        command: PreparedCommissioningJogTarget,
    ) -> ServoWriteResult: ...

    async def stop_or_hold(self, servo_id: int) -> RealStopOutcome: ...

    async def stop_or_hold_at_prepared_jog_target(
        self,
        command: PreparedCommissioningJogTarget,
    ) -> RealStopOutcome: ...

    async def reset_for_session(self, session_id: UUID) -> None: ...

    async def close(self) -> None: ...


class CommissioningMotionServoBusFacade:
    """Private capability-narrowing facade with an immutable ID allowlist."""

    __slots__ = ("__allowed_servo_ids", "__bus")

    def __init__(
        self,
        bus: CommissioningMotionServoBus,
        *,
        allowed_servo_ids: tuple[int, ...],
    ) -> None:
        if not allowed_servo_ids:
            raise ValueError("at least one explicitly allowed servo ID is required")
        if len(allowed_servo_ids) != len(set(allowed_servo_ids)):
            raise ValueError("allowed servo IDs must be unique")
        for servo_id in allowed_servo_ids:
            self._validate_servo_id(servo_id)
        self.__bus = bus
        self.__allowed_servo_ids = frozenset(allowed_servo_ids)

    async def read_present_position(self, servo_id: int) -> CommissioningPositionReadback:
        self._require_allowed(servo_id)
        readback = await self.__bus.read_present_position(servo_id)
        if not isinstance(readback, CommissioningPositionReadback):
            raise TypeError("commissioning adapter returned an invalid position readback")
        if readback.servo_id != servo_id:
            raise RuntimeError("commissioning adapter returned a different servo ID")
        return readback

    async def read_prepared_joint_state(
        self,
        servo_ids: tuple[int, ...],
    ) -> tuple[CommissioningPositionReadback, ...]:
        if not servo_ids or len(servo_ids) != len(set(servo_ids)):
            raise ValueError("commissioning read requires unique explicit Servo IDs")
        for servo_id in servo_ids:
            self._require_allowed(servo_id)
        values = await self.__bus.read_prepared_joint_state(servo_ids)
        if not isinstance(values, tuple) or tuple(item.servo_id for item in values) != servo_ids:
            raise RuntimeError("commissioning adapter returned an invalid multi-ID readback")
        return values

    async def write_prepared_command(
        self,
        command: PreparedCommissioningTestCommand,
    ) -> ServoWriteResult:
        if not isinstance(command, PreparedCommissioningTestCommand):
            raise TypeError("only a prepared commissioning test command may be written")
        self._require_allowed(command.servo_id)
        result = await self.__bus.write_prepared_command(command)
        if not isinstance(result, ServoWriteResult):
            raise TypeError("commissioning adapter returned an invalid write result")
        if result.requested_ids != (command.servo_id,):
            raise RuntimeError("commissioning adapter write result escaped the single-ID grant")
        return result

    async def begin_prepared_motion(self, session_id: UUID) -> None:
        if not isinstance(session_id, UUID):
            raise TypeError("commissioning session_id must be a UUID")
        await self.__bus.begin_prepared_motion(session_id)

    async def write_prepared_jog_target(
        self,
        command: PreparedCommissioningJogTarget,
    ) -> ServoWriteResult:
        if not isinstance(command, PreparedCommissioningJogTarget):
            raise TypeError("only a prepared commissioning jog target may be written")
        self._require_allowed(command.servo_id)
        result = await self.__bus.write_prepared_jog_target(command)
        if not isinstance(result, ServoWriteResult):
            raise TypeError("commissioning adapter returned an invalid jog write result")
        if result.requested_ids != (command.servo_id,):
            raise RuntimeError("commissioning jog write escaped the single-ID grant")
        return result

    async def stop_or_hold(self, servo_id: int) -> RealStopOutcome:
        self._require_allowed(servo_id)
        outcome = await self.__bus.stop_or_hold(servo_id)
        if not isinstance(outcome, RealStopOutcome):
            raise TypeError("commissioning adapter returned an invalid Stop/Hold outcome")
        if outcome.requested_ids != (servo_id,):
            raise RuntimeError("commissioning adapter Stop result escaped the single-ID grant")
        return outcome

    async def stop_or_hold_at_prepared_jog_target(
        self,
        command: PreparedCommissioningJogTarget,
    ) -> RealStopOutcome:
        if not isinstance(command, PreparedCommissioningJogTarget):
            raise TypeError("only a prepared commissioning jog target may be retained")
        self._require_allowed(command.servo_id)
        outcome = await self.__bus.stop_or_hold_at_prepared_jog_target(command)
        if not isinstance(outcome, RealStopOutcome):
            raise TypeError("commissioning adapter returned an invalid bounded Stop outcome")
        if outcome.requested_ids != (command.servo_id,):
            raise RuntimeError("commissioning bounded Stop escaped the single-ID grant")
        return outcome

    async def reset_for_session(self, session_id: UUID) -> None:
        if not isinstance(session_id, UUID):
            raise TypeError("commissioning session_id must be a UUID")
        await self.__bus.reset_for_session(session_id)

    async def close(self) -> None:
        await self.__bus.close()

    def _require_allowed(self, servo_id: int) -> None:
        self._validate_servo_id(servo_id)
        if servo_id not in self.__allowed_servo_ids:
            raise PermissionError("servo ID is outside the commissioning allowlist")

    @staticmethod
    def _validate_servo_id(servo_id: int) -> None:
        if isinstance(servo_id, bool) or not isinstance(servo_id, int) or not 1 <= servo_id <= 253:
            raise ValueError("servo ID must be an integer from 1 through 253")


@runtime_checkable
class RawDirectionServoBus(Protocol):
    """Calibration-independent one-Servo boundary for Raw +/- characterization."""

    async def read_present_position(
        self,
        servo_id: int,
    ) -> CommissioningPositionReadback: ...

    async def write_prepared_raw_direction_command(
        self,
        command: PreparedRawDirectionCommand,
    ) -> ServoWriteResult: ...

    async def stop_or_hold(self, servo_id: int) -> RealStopOutcome: ...

    async def reset_for_session(self, session_id: UUID) -> None: ...

    async def close(self) -> None: ...


class RawDirectionServoBusFacade:
    """Keep Raw direction callers inside one immutable explicit-ID allowlist."""

    __slots__ = ("__allowed_servo_ids", "__bus")

    def __init__(self, bus: RawDirectionServoBus, *, allowed_servo_ids: tuple[int, ...]) -> None:
        if not allowed_servo_ids or len(allowed_servo_ids) != len(set(allowed_servo_ids)):
            raise ValueError("raw-direction bus requires unique explicit Servo IDs")
        for servo_id in allowed_servo_ids:
            self._validate_servo_id(servo_id)
        self.__bus = bus
        self.__allowed_servo_ids = frozenset(allowed_servo_ids)

    @property
    def is_physical_adapter(self) -> bool:
        return bool(getattr(self.__bus, "is_physical_adapter", False))

    async def read_present_position(self, servo_id: int) -> CommissioningPositionReadback:
        self._require_allowed(servo_id)
        readback = await self.__bus.read_present_position(servo_id)
        if not isinstance(readback, CommissioningPositionReadback):
            raise TypeError("raw-direction adapter returned an invalid position readback")
        if readback.servo_id != servo_id:
            raise RuntimeError("raw-direction adapter returned a different Servo ID")
        return readback

    async def write_prepared_raw_direction_command(
        self,
        command: PreparedRawDirectionCommand,
    ) -> ServoWriteResult:
        if not isinstance(command, PreparedRawDirectionCommand):
            raise TypeError("only a prepared raw-direction command may be written")
        self._require_allowed(command.servo_id)
        result = await self.__bus.write_prepared_raw_direction_command(command)
        if not isinstance(result, ServoWriteResult):
            raise TypeError("raw-direction adapter returned an invalid write result")
        if result.requested_ids != (command.servo_id,):
            raise RuntimeError("raw-direction write escaped the single-ID grant")
        return result

    async def stop_or_hold(self, servo_id: int) -> RealStopOutcome:
        self._require_allowed(servo_id)
        result = await self.__bus.stop_or_hold(servo_id)
        if not isinstance(result, RealStopOutcome):
            raise TypeError("raw-direction adapter returned an invalid Stop/Hold outcome")
        if result.requested_ids != (servo_id,):
            raise RuntimeError("raw-direction Stop escaped the single-ID grant")
        return result

    async def reset_for_session(self, session_id: UUID) -> None:
        if not isinstance(session_id, UUID):
            raise TypeError("raw-direction session_id must be a UUID")
        await self.__bus.reset_for_session(session_id)

    async def close(self) -> None:
        await self.__bus.close()

    def _require_allowed(self, servo_id: int) -> None:
        self._validate_servo_id(servo_id)
        if servo_id not in self.__allowed_servo_ids:
            raise PermissionError("Servo ID is outside the raw-direction allowlist")

    @staticmethod
    def _validate_servo_id(servo_id: int) -> None:
        if isinstance(servo_id, bool) or not isinstance(servo_id, int) or not 1 <= servo_id <= 253:
            raise ValueError("Servo ID must be an integer from 1 through 253")


@runtime_checkable
class ReadOnlyServoBus(Protocol):
    """Minimum explicit-ID capability used for commissioning.

    Deliberately absent: goal writes, Stop/Hold writes, torque writes, arbitrary
    register access, scanning, enumeration, Home, and every motion primitive.
    Application services that only diagnose or capture calibration data must
    depend on this protocol instead of ``ServoBus``.
    """

    async def open(self, device: str, protocol: str) -> None: ...

    async def close(self) -> None: ...

    async def ping_explicit_ids(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, ServoPingResult]: ...

    async def read_present_positions(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, int]: ...

    async def read_operating_modes(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, str]: ...

    async def read_torque_states(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, bool]: ...


class ReadOnlyServoBusFacade:
    """Capability-narrowing wrapper around a bus with read operations.

    The wrapped object is intentionally private and no escape hatch is exposed.
    Consequently, a commissioning caller receives an object whose public API has
    no hardware-write method even when the adapter behind it is a full bus.
    """

    __slots__ = ("__bus",)

    def __init__(self, bus: ReadOnlyServoBus) -> None:
        self.__bus = bus

    async def open(self, device: str, protocol: str) -> None:
        await self.__bus.open(device, protocol)

    async def close(self) -> None:
        await self.__bus.close()

    async def ping_explicit_ids(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, ServoPingResult]:
        return await self.__bus.ping_explicit_ids(servo_ids)

    async def read_present_positions(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, int]:
        return await self.__bus.read_present_positions(servo_ids)

    async def read_operating_modes(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, str]:
        return await self.__bus.read_operating_modes(servo_ids)

    async def read_torque_states(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, bool]:
        return await self.__bus.read_torque_states(servo_ids)


@runtime_checkable
class ServoBus(ReadOnlyServoBus, Protocol):
    """Full bounded bus used only by reviewed motion and emergency boundaries.

    No scan, arbitrary register, torque-enable, or raw SDK surface is exposed.
    """

    async def write_goal_positions(
        self,
        goal_positions: Mapping[int, int],
    ) -> ServoWriteResult: ...

    async def stop_or_hold(self, servo_ids: tuple[int, ...]) -> RealStopOutcome: ...


@runtime_checkable
class ServoBusFactory(Protocol):
    """A factory may resolve an optional SDK only after receiving a full grant."""

    @property
    def dependency(self) -> HardwareDependencyStatus: ...

    def create(self, authorization: RealHardwareAccessGrant) -> ServoBus: ...


__all__ = [
    "CommissioningMotionServoBus",
    "CommissioningMotionServoBusFacade",
    "CommissioningPositionReadback",
    "RawDirectionServoBus",
    "RawDirectionServoBusFacade",
    "ReadOnlyServoBus",
    "ReadOnlyServoBusFacade",
    "ServoBus",
    "ServoBusFactory",
]
