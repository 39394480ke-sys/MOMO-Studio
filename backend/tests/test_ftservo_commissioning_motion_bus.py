"""Capability-narrow STS3215 commissioning adapter tests using only SDK doubles."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import ModuleType
from uuid import UUID, uuid4

import pytest

from momo.adapters.hardware.ftservo_commissioning_motion_bus import (
    BAUD_RATE,
    STS3215_MODEL_NUMBER,
    FtServoCommissioningMotionBus,
)
from momo.domain.commissioning import (
    CommissioningSafetyEnvelope,
    PreparedCommissioningJogTarget,
    PreparedCommissioningTestCommand,
)
from momo.domain.enums import DomainUnit
from momo.domain.real_hardware import RealStopResult


class FakePort:
    def __init__(self, device: str, events: list[tuple[str, object]]) -> None:
        self.device = device
        self.events = events

    def setBaudRate(self, baudrate: int) -> bool:
        self.events.append(("baud", baudrate))
        return True

    def closePort(self) -> None:
        self.events.append(("close", self.device))


class FakePacket:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.events = events
        self.positions = {10: 1000, 11: 2000}

    def ping(self, servo_id: int) -> tuple[int, int, int]:
        self.events.append(("ping", servo_id))
        return STS3215_MODEL_NUMBER, 0, 0

    def ReadPos(self, servo_id: int) -> tuple[int, int, int]:
        self.events.append(("read", servo_id))
        return self.positions[servo_id], 0, 0

    def WritePosEx(
        self,
        servo_id: int,
        position: int,
        speed: int,
        acceleration: int,
    ) -> tuple[int, int]:
        signed = -(position & 0x7FFF) if position & 0x8000 else position
        self.events.append(("goal", (servo_id, signed, speed, acceleration)))
        self.positions[servo_id] = signed
        return 0, 0

    def write1ByteTxRx(self, servo_id: int, address: int, value: int) -> tuple[int, int]:
        self.events.append(("write1", (servo_id, address, value)))
        return 0, 0

    def write2ByteTxRx(self, servo_id: int, address: int, value: int) -> tuple[int, int]:
        signed = -(value & 0x7FFF) if value & 0x8000 else value
        self.events.append(("write2", (servo_id, address, signed)))
        if address == 42:
            self.positions[servo_id] = signed
        return 0, 0


def fake_sdk(events: list[tuple[str, object]], packet: FakePacket) -> ModuleType:
    module = ModuleType("scservo_sdk")
    module.PortHandler = lambda device: FakePort(device, events)  # type: ignore[attr-defined]
    module.sms_sts = lambda port: packet  # type: ignore[attr-defined]
    return module


def prepared_command(
    *,
    session_id: UUID,
    servo_id: int = 10,
) -> PreparedCommissioningTestCommand:
    now = datetime.now(UTC)
    return PreparedCommissioningTestCommand(
        session_id=session_id,
        robot_unit_id="MOMO-V2-UNIT-TEST",
        joint_id="j10",
        servo_id=servo_id,
        unit=DomainUnit.MM,
        start_value=0.0,
        requested_delta=0.5,
        target_value=0.5,
        start_raw=1000,
        target_raw=1032,
        requested_speed=0.5,
        requested_acceleration=1.0,
        command_duration_s=2.0,
        prepared_at=now,
        readback_fresh_until=now + timedelta(seconds=1),
        envelope=CommissioningSafetyEnvelope(),
    )


def prepared_jog_target(
    *,
    session_id: UUID,
    target_raw: int = 1040,
) -> PreparedCommissioningJogTarget:
    return PreparedCommissioningJogTarget(
        session_id=session_id,
        robot_unit_id="MOMO-V2-UNIT-TEST",
        joint_id="j10",
        servo_id=10,
        unit=DomainUnit.MM,
        target_value=0.625,
        target_raw=target_raw,
        raw_speed=64,
        requested_speed=1.0,
        prepared_at=datetime.now(UTC),
        envelope=CommissioningSafetyEnvelope(),
    )


def test_adapter_is_lazy_and_writes_only_the_prepared_joint() -> None:
    async def scenario() -> None:
        events: list[tuple[str, object]] = []
        packet = FakePacket(events)
        bus = FtServoCommissioningMotionBus(
            device="/dev/explicit",
            protocol="STS3215",
            allowed_servo_ids=(10, 11),
            importer=lambda _: fake_sdk(events, packet),
        )
        assert events == []
        session_id = uuid4()
        await bus.reset_for_session(session_id)
        assert events == [("baud", BAUD_RATE), ("ping", 10), ("ping", 11)]

        result = await bus.write_prepared_command(prepared_command(session_id=session_id))
        assert result.complete is True
        writes = [event for event in events if event[0] in {"goal", "write1"}]
        assert writes[0][1] == (10, 1000, 1, 1)
        assert writes[1] == ("write1", (10, 40, 1))
        assert writes[2][1][0:2] == (10, 1032)  # type: ignore[index]
        assert not any(event[0] == "goal" and event[1][0] == 11 for event in events)  # type: ignore[index]

        hold = await bus.stop_or_hold(10)
        assert hold.result is RealStopResult.HOLD_REQUESTED
        await bus.close()
        assert ("write1", (10, 40, 0)) in events
        assert events[-1] == ("close", "/dev/explicit")

    asyncio.run(scenario())


def test_adapter_rejects_unknown_ids_and_cross_session_commands() -> None:
    async def scenario() -> None:
        events: list[tuple[str, object]] = []
        packet = FakePacket(events)
        bus = FtServoCommissioningMotionBus(
            device="/dev/explicit",
            protocol="STS3215",
            allowed_servo_ids=(10,),
            importer=lambda _: fake_sdk(events, packet),
        )
        session_id = uuid4()
        await bus.reset_for_session(session_id)
        with pytest.raises(PermissionError, match="allowlist"):
            await bus.read_present_position(11)
        with pytest.raises(PermissionError, match="another session"):
            await bus.write_prepared_command(prepared_command(session_id=uuid4()))
        assert not any(event[0] in {"goal", "write1"} for event in events)
        await bus.close()

    asyncio.run(scenario())


def test_adapter_streams_prepared_jog_targets_without_waiting_for_settle() -> None:
    async def scenario() -> None:
        events: list[tuple[str, object]] = []
        packet = FakePacket(events)
        bus = FtServoCommissioningMotionBus(
            device="/dev/explicit",
            protocol="STS3215",
            allowed_servo_ids=(10,),
            importer=lambda _: fake_sdk(events, packet),
        )
        session_id = uuid4()
        await bus.reset_for_session(session_id)
        await bus.begin_prepared_motion(session_id)

        result = await bus.write_prepared_jog_target(prepared_jog_target(session_id=session_id))

        assert result.complete is True
        goals = [event[1] for event in events if event[0] == "goal"]
        assert goals[-1] == (10, 1000, 3400, 0)
        assert ("write1", (10, 40, 1)) in events
        assert ("write2", (10, 42, 1040)) in events

        await bus.write_prepared_jog_target(
            prepared_jog_target(session_id=session_id, target_raw=1050)
        )
        goals = [event[1] for event in events if event[0] == "goal"]
        assert goals == [(10, 1000, 3400, 0)]
        assert ("write2", (10, 42, 1050)) in events
        await bus.stop_or_hold(10)
        assert events.count(("write2", (10, 42, 1050))) == 2
        await bus.close()

    asyncio.run(scenario())


def test_stop_on_an_unopened_adapter_is_safe_and_inert() -> None:
    async def scenario() -> None:
        events: list[tuple[str, object]] = []
        packet = FakePacket(events)
        bus = FtServoCommissioningMotionBus(
            device="/dev/explicit",
            protocol="STS3215",
            allowed_servo_ids=(10,),
            importer=lambda _: fake_sdk(events, packet),
        )
        outcome = await bus.stop_or_hold(10)
        assert outcome.result is RealStopResult.NOT_CONNECTED
        assert events == []

    asyncio.run(scenario())
