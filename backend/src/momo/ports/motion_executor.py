"""Prepared-motion executor boundary."""

from typing import Protocol, runtime_checkable
from uuid import UUID

from momo.domain.motion_preflight import (
    MotionCommandStatus,
    PreparedContinuousJog,
    PreparedMotion,
)


@runtime_checkable
class MotionExecutor(Protocol):
    @property
    def active_command_id(self) -> UUID | None: ...

    def get_status(self, command_id: UUID) -> MotionCommandStatus | None: ...

    def active_status(self) -> MotionCommandStatus | None: ...

    def latest_status(self) -> MotionCommandStatus | None: ...

    async def submit(self, prepared: PreparedMotion) -> MotionCommandStatus: ...

    async def submit_continuous_jog(
        self, prepared: PreparedContinuousJog
    ) -> MotionCommandStatus: ...

    async def cancel_active(self) -> MotionCommandStatus | None: ...

    async def cancel(self, command_id: UUID) -> MotionCommandStatus | None: ...

    async def shutdown(self) -> None: ...
