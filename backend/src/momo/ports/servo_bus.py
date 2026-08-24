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
class ServoBus(Protocol):
    """No scan, arbitrary register, torque-enable, or raw SDK surface is exposed."""

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
