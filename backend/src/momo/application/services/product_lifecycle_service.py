"""Mode-aware lifecycle orchestration without exposing adapters to API routes."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from uuid import UUID

from momo.application.services.device_diagnostics_service import DeviceDiagnosticsService
from momo.application.services.motion_service import MotionApplicationService
from momo.application.services.operator_session_service import OperatorSessionTokenError
from momo.application.services.robot_service import RobotApplicationService
from momo.domain.enums import ControlMode
from momo.domain.real_hardware import RealHardwareAuthorizationPurpose
from momo.domain.runtime import RobotStatus
from momo.ports.servo_bus import ServoBus


class ProductLifecycleService:
    """Connect/disconnect one product Robot through the selected outer composition."""

    def __init__(
        self,
        *,
        robot: RobotApplicationService,
        motion: MotionApplicationService,
        device: DeviceDiagnosticsService,
        bind_real_bus: Callable[[ServoBus, UUID], None] | None = None,
        unbind_real_bus: Callable[[], None] | None = None,
    ) -> None:
        self.robot = robot
        self.motion = motion
        self.device = device
        self._bind_real_bus = bind_real_bus
        self._unbind_real_bus = unbind_real_bus

    @property
    def control_mode(self) -> ControlMode:
        return self.robot.settings.control_mode

    async def connect(self, token: str | None = None) -> RobotStatus:
        if self.control_mode is ControlMode.DRY_RUN:
            return await self.robot.connect()
        if token is None:
            raise OperatorSessionTokenError(
                "A valid REAL motion operator session is required to connect"
            )
        binder = self._bind_real_bus
        if binder is None:
            raise RuntimeError("REAL product composition has no authorized bus binding")
        try:
            bus, evidence, _ = await self.device.connect_for_product_motion(
                token,
                purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            )
            binder(bus, evidence.session_id)
            return await self.robot.connect()
        except BaseException:
            if self._unbind_real_bus is not None:
                self._unbind_real_bus()
            with suppress(Exception):
                await self.device.disconnect(token)
            raise

    async def disconnect(self, token: str | None = None) -> RobotStatus:
        if self.control_mode is ControlMode.DRY_RUN:
            return await self.motion.disconnect()
        if token is None:
            raise OperatorSessionTokenError(
                "The active REAL operator session is required to disconnect"
            )
        try:
            status = await self.motion.disconnect()
        finally:
            try:
                await self.device.disconnect(token)
            finally:
                if self._unbind_real_bus is not None:
                    self._unbind_real_bus()
        return status


__all__ = ["ProductLifecycleService"]
