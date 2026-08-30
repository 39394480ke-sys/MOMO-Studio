"""Physical Raw adapter contract tests with an in-memory SDK double only."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from types import ModuleType
from uuid import uuid4

import pytest

from momo.adapters.hardware.ftservo_raw_direction_bus import (
    BAUD_RATE,
    STS3215_MODEL_NUMBER,
    FtServoRawDirectionBus,
    RawDirectionCommandRevoked,
    RawDirectionSettleTimeout,
)
from momo.domain.raw_direction import (
    PreparedRawDirectionCommand,
    RawDirection,
    RawDirectionSafetyEnvelope,
)
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


def fake_sdk(events: list[tuple[str, object]], packet: FakePacket) -> ModuleType:
    module = ModuleType("scservo_sdk")
    module.PortHandler = lambda device: FakePort(device, events)  # type: ignore[attr-defined]
    module.sms_sts = lambda port: packet  # type: ignore[attr-defined]
    return module


def test_adapter_is_lazy_and_executes_only_one_prepared_allowlisted_step() -> None:
    async def scenario() -> None:
        events: list[tuple[str, object]] = []
        packet = FakePacket(events)
        bus = FtServoRawDirectionBus(
            device="/dev/explicit",
            protocol="STS3215",
            allowed_servo_ids=(10, 11),
            importer=lambda _: fake_sdk(events, packet),
        )
        assert events == []
        session_id = uuid4()
        await bus.reset_for_session(session_id)
        assert events == [("baud", BAUD_RATE), ("ping", 10), ("ping", 11)]

        now = datetime.now(UTC)
        command = PreparedRawDirectionCommand(
            session_id=session_id,
            robot_unit_id="MOMO-V2-UNIT-TEST",
            joint_id="j10",
            servo_id=10,
            direction=RawDirection.RAW_PLUS,
            step_counts=32,
            zero_raw=1000,
            start_raw=1000,
            target_raw=1032,
            prepared_at=now,
            readback_fresh_until=now + timedelta(seconds=1),
            envelope=RawDirectionSafetyEnvelope(),
        )
        result = await bus.write_prepared_raw_direction_command(command)
        assert result.complete is True
        writes = [event for event in events if event[0] in {"goal", "write1"}]
        assert writes[0][0] == "goal"
        assert writes[0][1][1] == 1000  # type: ignore[index]
        assert writes[1] == ("write1", (10, 40, 1))
        assert writes[2][0] == "goal"
        assert writes[2][1][1] == 1032  # type: ignore[index]

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
        bus = FtServoRawDirectionBus(
            device="/dev/explicit",
            protocol="STS3215",
            allowed_servo_ids=(10,),
            importer=lambda _: fake_sdk(events, packet),
        )
        session_id = uuid4()
        await bus.reset_for_session(session_id)
        with pytest.raises(PermissionError, match="allowlist"):
            await bus.read_present_position(11)
        now = datetime.now(UTC)
        command = PreparedRawDirectionCommand(
            session_id=uuid4(),
            robot_unit_id="MOMO-V2-UNIT-TEST",
            joint_id="j10",
            servo_id=10,
            direction=RawDirection.RAW_MINUS,
            step_counts=8,
            zero_raw=1000,
            start_raw=1000,
            target_raw=992,
            prepared_at=now,
            readback_fresh_until=now + timedelta(seconds=1),
            envelope=RawDirectionSafetyEnvelope(),
        )
        with pytest.raises(PermissionError, match="another session"):
            await bus.write_prepared_raw_direction_command(command)
        assert not any(event[0] in {"goal", "write1"} for event in events)
        await bus.close()

    asyncio.run(scenario())


def test_adapter_reports_last_raw_when_a_step_does_not_settle() -> None:
    async def scenario() -> None:
        events: list[tuple[str, object]] = []
        packet = FakePacket(events)

        def do_not_move(
            servo_id: int,
            position: int,
            speed: int,
            acceleration: int,
        ) -> tuple[int, int]:
            signed = -(position & 0x7FFF) if position & 0x8000 else position
            events.append(("goal", (servo_id, signed, speed, acceleration)))
            return 0, 0

        packet.WritePosEx = do_not_move  # type: ignore[method-assign]
        bus = FtServoRawDirectionBus(
            device="/dev/explicit",
            protocol="STS3215",
            allowed_servo_ids=(10,),
            importer=lambda _: fake_sdk(events, packet),
            settle_timeout_s=0.001,
            target_tolerance_counts=4,
        )
        session_id = uuid4()
        await bus.reset_for_session(session_id)
        now = datetime.now(UTC)
        command = PreparedRawDirectionCommand(
            session_id=session_id,
            robot_unit_id="MOMO-V2-UNIT-TEST",
            joint_id="j10",
            servo_id=10,
            direction=RawDirection.RAW_PLUS,
            step_counts=32,
            zero_raw=1000,
            start_raw=1000,
            target_raw=1032,
            prepared_at=now,
            readback_fresh_until=now + timedelta(seconds=1),
            envelope=RawDirectionSafetyEnvelope(),
        )
        with pytest.raises(RawDirectionSettleTimeout) as captured:
            await bus.write_prepared_raw_direction_command(command)
        assert captured.value.target_raw == 1032
        assert captured.value.observed_raw == 1000
        assert captured.value.tolerance_counts == 4
        assert captured.value.progress_counts == 0
        assert captured.value.required_progress_counts == 24
        await bus.close()

    asyncio.run(scenario())


def test_adapter_accepts_sufficient_directional_progress_for_sign_characterization() -> None:
    async def scenario() -> None:
        events: list[tuple[str, object]] = []
        packet = FakePacket(events)

        def move_most_of_the_step(
            servo_id: int,
            position: int,
            speed: int,
            acceleration: int,
        ) -> tuple[int, int]:
            signed = -(position & 0x7FFF) if position & 0x8000 else position
            events.append(("goal", (servo_id, signed, speed, acceleration)))
            packet.positions[servo_id] = 1025 if signed == 1032 else signed
            return 0, 0

        packet.WritePosEx = move_most_of_the_step  # type: ignore[method-assign]
        bus = FtServoRawDirectionBus(
            device="/dev/explicit",
            protocol="STS3215",
            allowed_servo_ids=(10,),
            importer=lambda _: fake_sdk(events, packet),
            settle_timeout_s=0.001,
            target_tolerance_counts=4,
        )
        session_id = uuid4()
        await bus.reset_for_session(session_id)
        now = datetime.now(UTC)
        command = PreparedRawDirectionCommand(
            session_id=session_id,
            robot_unit_id="MOMO-V2-UNIT-TEST",
            joint_id="j10",
            servo_id=10,
            direction=RawDirection.RAW_PLUS,
            step_counts=32,
            zero_raw=1000,
            start_raw=1000,
            target_raw=1032,
            prepared_at=now,
            readback_fresh_until=now + timedelta(seconds=1),
            envelope=RawDirectionSafetyEnvelope(),
        )
        result = await bus.write_prepared_raw_direction_command(command)
        assert result.complete is True
        assert packet.positions[10] == 1025
        await bus.close()

    asyncio.run(scenario())


def test_adapter_accepts_quantized_small_step_direction_progress() -> None:
    async def scenario() -> None:
        events: list[tuple[str, object]] = []
        packet = FakePacket(events)

        def move_five_counts(
            servo_id: int,
            position: int,
            speed: int,
            acceleration: int,
        ) -> tuple[int, int]:
            signed = -(position & 0x7FFF) if position & 0x8000 else position
            events.append(("goal", (servo_id, signed, speed, acceleration)))
            packet.positions[servo_id] = 1000 if signed == 1000 else 1005
            return 0, 0

        packet.WritePosEx = move_five_counts  # type: ignore[method-assign]
        bus = FtServoRawDirectionBus(
            device="/dev/explicit",
            protocol="STS3215",
            allowed_servo_ids=(10,),
            importer=lambda _: fake_sdk(events, packet),
            settle_timeout_s=0.001,
            target_tolerance_counts=2,
        )
        session_id = uuid4()
        await bus.reset_for_session(session_id)
        now = datetime.now(UTC)
        command = PreparedRawDirectionCommand(
            session_id=session_id,
            robot_unit_id="MOMO-V2-UNIT-TEST",
            joint_id="j14",
            servo_id=10,
            direction=RawDirection.RAW_PLUS,
            step_counts=11,
            zero_raw=1000,
            start_raw=1000,
            target_raw=1011,
            prepared_at=now,
            readback_fresh_until=now + timedelta(seconds=1),
            envelope=RawDirectionSafetyEnvelope(),
        )
        result = await bus.write_prepared_raw_direction_command(command)
        assert result.complete is True
        assert packet.positions[10] == 1005
        await bus.close()

    asyncio.run(scenario())


def test_adapter_rejects_small_step_progress_within_noise_margin() -> None:
    async def scenario() -> None:
        events: list[tuple[str, object]] = []
        packet = FakePacket(events)

        def move_three_counts(
            servo_id: int,
            position: int,
            speed: int,
            acceleration: int,
        ) -> tuple[int, int]:
            signed = -(position & 0x7FFF) if position & 0x8000 else position
            events.append(("goal", (servo_id, signed, speed, acceleration)))
            packet.positions[servo_id] = 1000 if signed == 1000 else 1003
            return 0, 0

        packet.WritePosEx = move_three_counts  # type: ignore[method-assign]
        bus = FtServoRawDirectionBus(
            device="/dev/explicit",
            protocol="STS3215",
            allowed_servo_ids=(10,),
            importer=lambda _: fake_sdk(events, packet),
            settle_timeout_s=0.001,
            target_tolerance_counts=2,
        )
        session_id = uuid4()
        await bus.reset_for_session(session_id)
        now = datetime.now(UTC)
        command = PreparedRawDirectionCommand(
            session_id=session_id,
            robot_unit_id="MOMO-V2-UNIT-TEST",
            joint_id="j14",
            servo_id=10,
            direction=RawDirection.RAW_PLUS,
            step_counts=11,
            zero_raw=1000,
            start_raw=1000,
            target_raw=1011,
            prepared_at=now,
            readback_fresh_until=now + timedelta(seconds=1),
            envelope=RawDirectionSafetyEnvelope(),
        )
        with pytest.raises(RawDirectionSettleTimeout) as captured:
            await bus.write_prepared_raw_direction_command(command)
        assert captured.value.progress_counts == 3
        assert captured.value.required_progress_counts == 4
        await bus.close()

    asyncio.run(scenario())


def test_stop_fences_a_step_blocked_in_the_sdk_before_requesting_hold() -> None:
    async def scenario() -> None:
        events: list[tuple[str, object]] = []
        packet = FakePacket(events)
        poll_entered = threading.Event()
        release_poll = threading.Event()
        read_count = 0

        original_read = packet.ReadPos

        def blocking_settle_read(servo_id: int) -> tuple[int, int, int]:
            nonlocal read_count
            read_count += 1
            # Read 1 prepares the command. Read 2 is the first settle poll,
            # after the target write has already returned.
            if read_count == 2:
                poll_entered.set()
                assert release_poll.wait(timeout=2)
            return original_read(servo_id)

        packet.ReadPos = blocking_settle_read  # type: ignore[method-assign]
        bus = FtServoRawDirectionBus(
            device="/dev/explicit",
            protocol="STS3215",
            allowed_servo_ids=(10,),
            importer=lambda _: fake_sdk(events, packet),
        )
        session_id = uuid4()
        await bus.reset_for_session(session_id)
        now = datetime.now(UTC)
        command = PreparedRawDirectionCommand(
            session_id=session_id,
            robot_unit_id="MOMO-V2-UNIT-TEST",
            joint_id="j10",
            servo_id=10,
            direction=RawDirection.RAW_PLUS,
            step_counts=32,
            zero_raw=1000,
            start_raw=1000,
            target_raw=1032,
            prepared_at=now,
            readback_fresh_until=now + timedelta(seconds=1),
            envelope=RawDirectionSafetyEnvelope(),
        )

        step_task = asyncio.create_task(bus.write_prepared_raw_direction_command(command))
        assert await asyncio.to_thread(poll_entered.wait, 2)
        stop_task = asyncio.create_task(bus.stop_or_hold(10))
        await asyncio.sleep(0)
        assert not stop_task.done()

        release_poll.set()
        stop = await asyncio.wait_for(stop_task, timeout=2)
        assert stop.result is RealStopResult.HOLD_REQUESTED
        with pytest.raises(RawDirectionCommandRevoked):
            await step_task

        event_count_after_stop = len(events)
        await asyncio.sleep(0.02)
        assert len(events) == event_count_after_stop
        # Stop revokes all writes until an explicit session reset.
        with pytest.raises(RawDirectionCommandRevoked):
            await bus.write_prepared_raw_direction_command(command)
        await bus.close()

    asyncio.run(scenario())
