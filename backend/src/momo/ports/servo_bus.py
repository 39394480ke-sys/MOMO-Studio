"""Minimal explicit-ID ServoBus boundary for Stage 8 real-hardware work."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from momo.domain.real_hardware import (
    HardwareDependencyStatus,
    RealHardwareAccessGrant,
    RealStopOutcome,
    ServoPingResult,
    ServoWriteResult,
)


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
    "ReadOnlyServoBus",
    "ReadOnlyServoBusFacade",
    "ServoBus",
    "ServoBusFactory",
]
