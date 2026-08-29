"""Prepared-motion executor boundary."""

from typing import Protocol, runtime_checkable
from uuid import UUID

from momo.domain.motion_preflight import (
    MotionCommandStatus,
    PreparedContinuousJog,
    PreparedMotion,
)
from momo.domain.real_hardware import RealHardwareAuthorizationPurpose
from momo.domain.real_motion import RealExecutionAuthorization


@runtime_checkable
class MotionExecutor(Protocol):
    @property
    def active_command_id(self) -> UUID | None: ...

    def get_status(self, command_id: UUID) -> MotionCommandStatus | None: ...

    def active_status(self) -> MotionCommandStatus | None: ...

    def latest_status(self) -> MotionCommandStatus | None: ...

    async def submit(
        self,
        prepared: PreparedMotion,
        *,
        authorization: RealExecutionAuthorization | None = None,
        execution_purpose: RealHardwareAuthorizationPurpose | None = None,
    ) -> MotionCommandStatus: ...

    async def submit_continuous_jog(
        self,
        prepared: PreparedContinuousJog,
        *,
        authorization: RealExecutionAuthorization | None = None,
        execution_purpose: RealHardwareAuthorizationPurpose | None = None,
    ) -> MotionCommandStatus: ...

    async def cancel_active(self) -> MotionCommandStatus | None: ...

    async def cancel(self, command_id: UUID) -> MotionCommandStatus | None: ...

    async def shutdown(self) -> None: ...
