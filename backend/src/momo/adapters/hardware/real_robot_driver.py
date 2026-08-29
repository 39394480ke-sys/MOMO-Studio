"""Profile-bound REAL robot driver over one explicitly authorized ServoBus."""

from __future__ import annotations

import asyncio
from uuid import UUID

from momo.domain.calibration import CalibrationDocument
from momo.domain.enums import RobotVariant
from momo.domain.hardware_mapping import goal_raw_to_logical
from momo.domain.real_hardware import RealStopOutcome
from momo.domain.robot import JointState, RobotId, RobotProfile
from momo.ports.servo_bus import ServoBus


class AuthorizedServoBusBinding:
    """Process-local binding published only by the reviewed lifecycle coordinator."""

    def __init__(self) -> None:
        self._bus: ServoBus | None = None
        self._session_id: UUID | None = None

    @property
    def session_id(self) -> UUID | None:
        return self._session_id

    @property
    def connected(self) -> bool:
        return self._bus is not None

    def bind(self, bus: ServoBus, *, session_id: UUID) -> None:
        if self._bus is not None:
            raise RuntimeError("an authorized ServoBus is already bound")
        self._bus = bus
        self._session_id = session_id

    def unbind(self) -> None:
        self._bus = None
        self._session_id = None

    def require_bus(self) -> ServoBus:
        bus = self._bus
        if bus is None:
            raise RuntimeError("no authorized REAL ServoBus is connected")
        return bus


class RealRobotDriver:
    """Unit-safe lifecycle/readback adapter; motion writes stay in RealMotionExecutor."""

    def __init__(
        self,
        robot_id: RobotId,
        profile: RobotProfile,
        calibration: CalibrationDocument,
        binding: AuthorizedServoBusBinding,
    ) -> None:
        if calibration.template:
            raise ValueError("template calibration cannot back a REAL robot driver")
        if (
            calibration.robot_variant is not profile.variant
            or calibration.profile_fingerprint != profile.fingerprint
            or tuple(joint.joint_id for joint in calibration.joints)
            != tuple(profile.enabled_joints)
        ):
            raise ValueError("REAL robot calibration does not match the active Profile")
        self._robot_id = robot_id
        self._profile = profile
        self._calibration = calibration
        self._binding = binding
        self._connected = False
        self._guard = asyncio.Lock()

    @property
    def robot_id(self) -> RobotId:
        return self._robot_id

    @property
    def variant(self) -> RobotVariant:
        return self._profile.variant

    @property
    def profile(self) -> RobotProfile:
        return self._profile

    @property
    def servo_ids(self) -> tuple[int, ...]:
        values: list[int] = []
        for joint_id in self._profile.enabled_joints:
            servo_id = self._profile.definitions_by_id[joint_id].servo_id
            if servo_id is None:
                raise ValueError(f"enabled joint {joint_id} has no explicit Servo ID")
            values.append(servo_id)
        return tuple(values)

    async def connect(self) -> None:
        async with self._guard:
            bus = self._binding.require_bus()
            await bus.read_present_positions(self.servo_ids)
            self._connected = True

    async def disconnect(self) -> None:
        async with self._guard:
            self._connected = False

    async def is_connected(self) -> bool:
        return self._connected and self._binding.connected

    async def read_joint_state(self) -> JointState:
        async with self._guard:
            if not self._connected:
                raise RuntimeError("REAL robot driver is not connected")
            raw = await self._binding.require_bus().read_present_positions(self.servo_ids)
            positions: dict[str, float] = {}
            units = {}
            for joint_id in self._profile.enabled_joints:
                definition = self._profile.definitions_by_id[joint_id]
                servo_id = definition.servo_id
                assert servo_id is not None
                positions[joint_id] = goal_raw_to_logical(
                    joint_id,
                    raw[servo_id],
                    self._profile,
                    self._calibration.joints_by_id[joint_id],
                )
                units[joint_id] = definition.domain_unit
            return JointState(positions=positions, units=units).validate_against(self._profile)

    async def move_to_joint_state(self, state: JointState) -> None:
        del state
        raise RuntimeError("REAL state writes must pass through RealMotionExecutor")

    async def stop(self) -> RealStopOutcome:
        return await self._binding.require_bus().stop_or_hold(self.servo_ids)


__all__ = ["AuthorizedServoBusBinding", "RealRobotDriver"]
