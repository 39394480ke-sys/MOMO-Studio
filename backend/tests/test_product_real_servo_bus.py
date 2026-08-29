"""Production REAL bus contract tests using an inert synthetic SDK only."""

from __future__ import annotations

import asyncio
from types import ModuleType
from typing import cast

import pytest

from momo.adapters.hardware.ftservo_production_bus import (
    ADAPTER_ID,
    GOAL_POSITION_ADDRESS,
    LEGACY_STREAM_ACCELERATION,
    LEGACY_STREAM_SPEED,
    TORQUE_ENABLE_ADDRESS,
    FtServoProductionBusFactory,
)
from momo.application.services.operator_session_service import OperatorSessionService
from momo.application.services.real_hardware_authorization import RealHardwareAuthorization
from momo.domain.real_hardware import (
    REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
    ExplicitServoDevice,
    OperatorSessionPurpose,
    RealHardwareAccessGrant,
    RealHardwareAuthorizationPurpose,
    RealHardwareGateInput,
    RealStopResult,
)
from tests.stage3_helpers import FakeClock
from tests.stage8_hardware_helpers import real_context, real_profile

SYNTHETIC_DEVICE = "/dev/fake-product-real-never-opened"


async def _production_grant() -> RealHardwareAccessGrant:
    profile = real_profile()
    servo_ids = tuple(cast(int, definition.servo_id) for definition in profile.joint_definitions)
    device = ExplicitServoDevice(
        robot_unit_id="MOMO-V2-UNIT-SYNTHETIC",
        serial_port=SYNTHETIC_DEVICE,
        protocol="STS3215",
        servo_ids=servo_ids,
    )
    context = real_context(
        profile=profile,
        device=device,
        dependency_adapter_id=ADAPTER_ID,
    )
    clock = FakeClock()
    authorization = RealHardwareAuthorization()
    sessions = OperatorSessionService(clock, authorization, ttl_s=60.0)
    issued = await sessions.issue(
        context,
        purpose=OperatorSessionPurpose.REAL_MOTION,
        confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
        physical_estop_confirmed=True,
    )
    evidence = await sessions.authorize(
        issued.session_token.get_secret_value(),
        context,
        purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
    )
    return authorization.require_authorized(
        RealHardwareGateInput(
            context=context,
            evaluated_at=clock.now(),
            operator_session=evidence,
        ),
        purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
    )


class _FakePort:
    def __init__(self, device: str, calls: list[tuple[object, ...]]) -> None:
        self.device = device
        self.calls = calls

    def setBaudRate(self, baudrate: int) -> bool:
        self.calls.append(("baud", self.device, baudrate))
        return True

    def closePort(self) -> None:
        self.calls.append(("close", self.device))


class _FakeSyncWriter:
    def __init__(self, packet: _FakePacket) -> None:
        self.packet = packet

    def txPacket(self) -> int:
        self.packet.calls.append(("sync-tx", tuple(self.packet.staged)))
        self.packet.positions.update(self.packet.staged)
        return 0

    def clearParam(self) -> None:
        self.packet.calls.append(("sync-clear",))
        self.packet.staged.clear()


class _FakePacket:
    def __init__(self, calls: list[tuple[object, ...]]) -> None:
        self.calls = calls
        self.positions: dict[int, int] = {}
        self.staged: dict[int, int] = {}
        self.groupSyncWrite = _FakeSyncWriter(self)

    def ping(self, servo_id: int) -> tuple[int, int, int]:
        self.calls.append(("ping", servo_id))
        return 777, 0, 0

    def ReadPos(self, servo_id: int) -> tuple[int, int, int]:
        self.calls.append(("read-position", servo_id))
        return self.positions.get(servo_id, 0), 0, 0

    def WritePosEx(
        self,
        servo_id: int,
        position: int,
        speed: int,
        acceleration: int,
    ) -> tuple[int, int]:
        self.calls.append(("configure", servo_id, position, speed, acceleration))
        return 0, 0

    def SyncWritePosEx(
        self,
        servo_id: int,
        position: int,
        speed: int,
        acceleration: int,
    ) -> bool:
        self.calls.append(("sync-stage", servo_id, position, speed, acceleration))
        if servo_id in self.staged:
            return False
        self.staged[servo_id] = position
        return True

    def read1ByteTxRx(self, servo_id: int, address: int) -> tuple[int, int, int]:
        value = 1 if address == TORQUE_ENABLE_ADDRESS else 0
        return value, 0, 0

    def read2ByteTxRx(self, servo_id: int, address: int) -> tuple[int, int, int]:
        del servo_id, address
        return 0, 0, 0

    def write1ByteTxRx(self, servo_id: int, address: int, value: int) -> tuple[int, int]:
        self.calls.append(("write1", servo_id, address, value))
        return 0, 0

    def write2ByteTxRx(self, servo_id: int, address: int, value: int) -> tuple[int, int]:
        self.calls.append(("write2", servo_id, address, value))
        if address == GOAL_POSITION_ADDRESS:
            self.positions[servo_id] = value
        return 0, 0


class _FakeSdk:
    def __init__(self, calls: list[tuple[object, ...]]) -> None:
        self.calls = calls
        self.packet = _FakePacket(calls)

    def PortHandler(self, device: str) -> _FakePort:
        self.calls.append(("port", device))
        return _FakePort(device, self.calls)

    def sms_sts(self, port: _FakePort) -> _FakePacket:
        self.calls.append(("packet", port.device))
        return self.packet


def test_production_bus_is_inert_until_authorized_open_and_uses_exact_ids() -> None:
    async def scenario() -> None:
        grant = await _production_grant()
        calls: list[tuple[object, ...]] = []
        sdk = _FakeSdk(calls)
        imported: list[str] = []

        def importer(name: str) -> ModuleType:
            imported.append(name)
            return cast(ModuleType, sdk)

        factory = FtServoProductionBusFactory(
            importer=importer,
            package_available=lambda name: name == "scservo_sdk",
        )
        bus = factory.create(grant)
        assert imported == []
        assert calls == []

        await bus.open(SYNTHETIC_DEVICE, "STS3215")
        assert imported == ["scservo_sdk"]
        servo_ids = grant.session.allowed_servo_ids
        goals = {servo_id: index * 100 for index, servo_id in enumerate(servo_ids)}
        result = await bus.write_goal_positions(goals)
        assert result.complete is True
        assert result.written_ids == servo_ids
        assert [call[1] for call in calls if call[0] == "configure"] == list(servo_ids)
        assert all(
            call[3:] == (LEGACY_STREAM_SPEED, LEGACY_STREAM_ACCELERATION)
            for call in calls
            if call[0] == "configure"
        )
        staged = [call for call in calls if call[:1] == ("sync-stage",)]
        assert [call[1] for call in staged] == list(servo_ids)
        assert all(call[3:] == (LEGACY_STREAM_SPEED, LEGACY_STREAM_ACCELERATION) for call in staged)
        assert len([call for call in calls if call[:1] == ("sync-tx",)]) == 1
        assert not [call for call in calls if call[:1] == ("write2",)]

        with pytest.raises(PermissionError, match="exact authorized ID order"):
            await bus.write_goal_positions({servo_ids[0]: 0})

        stopped = await bus.stop_or_hold(servo_ids)
        assert stopped.result is RealStopResult.HOLD_REQUESTED
        assert stopped.safety_state_known is False
        assert len([call for call in calls if call[:1] == ("sync-tx",)]) == 2
        await bus.close()
        torque_off = [
            call
            for call in calls
            if call[0] == "write1" and call[2] == TORQUE_ENABLE_ADDRESS and call[3] == 0
        ]
        assert {call[1] for call in torque_off} == set(servo_ids)

    asyncio.run(scenario())
