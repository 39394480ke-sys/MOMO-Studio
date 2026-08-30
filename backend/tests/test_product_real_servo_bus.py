"""Production REAL bus contract tests using an inert synthetic SDK only."""

from __future__ import annotations

import asyncio
import threading
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
        self.packet.calls.append(("sync-tx", tuple(self.packet.staged.items())))
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


class _BlockingSyncWriter(_FakeSyncWriter):
    def __init__(self, packet: _FakePacket) -> None:
        super().__init__(packet)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block_once = True

    def txPacket(self) -> int:
        if self.block_once:
            self.block_once = False
            self.entered.set()
            self.release.wait()
        return super().txPacket()


class _BlockingFakeSdk(_FakeSdk):
    def __init__(self, calls: list[tuple[object, ...]]) -> None:
        super().__init__(calls)
        self.packet.groupSyncWrite = _BlockingSyncWriter(self.packet)


class _TorqueFailurePacket(_FakePacket):
    def __init__(
        self,
        calls: list[tuple[object, ...]],
        *,
        enable_failure: int,
        disable_failures: frozenset[int],
    ) -> None:
        super().__init__(calls)
        self.enable_failure = enable_failure
        self.disable_failures = disable_failures

    def write1ByteTxRx(self, servo_id: int, address: int, value: int) -> tuple[int, int]:
        self.calls.append(("write1", servo_id, address, value))
        if address == TORQUE_ENABLE_ADDRESS:
            if value == 1 and servo_id == self.enable_failure:
                return 1, 0
            if value == 0 and servo_id in self.disable_failures:
                return 1, 0
        return 0, 0


class _TorqueFailureSdk(_FakeSdk):
    def __init__(
        self,
        calls: list[tuple[object, ...]],
        *,
        enable_failure: int,
        disable_failures: frozenset[int],
    ) -> None:
        super().__init__(calls)
        self.packet = _TorqueFailurePacket(
            calls,
            enable_failure=enable_failure,
            disable_failures=disable_failures,
        )


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
        unarmed = await bus.write_goal_positions(goals)
        assert unarmed.complete is False
        assert unarmed.safety_state_known is False
        assert not [call for call in calls if call[:1] in {("sync-stage",), ("sync-tx",)}]

        armed = await bus.enable_torque_for_execution(servo_ids)
        assert armed.complete is True
        assert armed.succeeded_ids == servo_ids
        result = await bus.write_goal_positions(goals)
        assert result.complete is True
        assert result.written_ids == servo_ids
        assert not [call for call in calls if call[0] == "configure"]
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


def test_priority_stop_fences_blocked_and_queued_goal_writes() -> None:
    async def scenario() -> None:
        grant = await _production_grant()
        calls: list[tuple[object, ...]] = []
        sdk = _BlockingFakeSdk(calls)
        factory = FtServoProductionBusFactory(
            importer=lambda _name: cast(ModuleType, sdk),
            package_available=lambda name: name == "scservo_sdk",
        )
        bus = factory.create(grant)
        servo_ids = grant.session.allowed_servo_ids
        await bus.open(SYNTHETIC_DEVICE, "STS3215")
        assert (await bus.enable_torque_for_execution(servo_ids)).complete

        first = asyncio.create_task(
            bus.write_goal_positions({servo_id: 100 for servo_id in servo_ids})
        )
        writer = cast(_BlockingSyncWriter, sdk.packet.groupSyncWrite)
        assert await asyncio.wait_for(asyncio.to_thread(writer.entered.wait), timeout=1.0)

        stop = asyncio.create_task(bus.stop_or_hold(servo_ids))
        await asyncio.sleep(0)
        assert not stop.done()
        queued = await bus.write_goal_positions({servo_id: 200 for servo_id in servo_ids})
        assert queued.complete is False
        assert queued.safety_state_known is False
        assert not stop.done()

        writer.release.set()
        stale = await asyncio.wait_for(first, timeout=1.0)
        stopped = await asyncio.wait_for(stop, timeout=1.0)
        assert stale.complete is False
        assert stale.safety_state_known is False
        assert stopped.result is RealStopResult.HOLD_REQUESTED

        post_stop = await bus.write_goal_positions({servo_id: 300 for servo_id in servo_ids})
        assert post_stop.complete is False
        tx_payloads = [call[1] for call in calls if call[:1] == ("sync-tx",)]
        assert len(tx_payloads) == 2
        assert dict(cast(tuple[tuple[int, int], ...], tx_payloads[0])) == {
            servo_id: 100 for servo_id in servo_ids
        }
        assert dict(cast(tuple[tuple[int, int], ...], tx_payloads[1])) == {
            servo_id: 100 for servo_id in servo_ids
        }
        await bus.close()

    asyncio.run(scenario())


def test_blocking_sdk_timeout_is_uncertain_and_close_waits_for_thread_ownership() -> None:
    async def scenario() -> None:
        grant = await _production_grant()
        calls: list[tuple[object, ...]] = []
        sdk = _BlockingFakeSdk(calls)
        factory = FtServoProductionBusFactory(
            importer=lambda _name: cast(ModuleType, sdk),
            package_available=lambda name: name == "scservo_sdk",
        )
        bus = factory.create(grant)
        servo_ids = grant.session.allowed_servo_ids
        await bus.open(SYNTHETIC_DEVICE, "STS3215")
        assert (await bus.enable_torque_for_execution(servo_ids)).complete

        writer = cast(_BlockingSyncWriter, sdk.packet.groupSyncWrite)
        write = asyncio.create_task(
            bus.write_goal_positions({servo_id: 123 for servo_id in servo_ids})
        )
        assert await asyncio.wait_for(asyncio.to_thread(writer.entered.wait), timeout=1.0)
        close = asyncio.create_task(bus.close())
        await asyncio.sleep(0)
        assert not close.done()

        late = await bus.write_goal_positions({servo_id: 456 for servo_id in servo_ids})
        assert late.complete is False
        assert late.safety_state_known is False
        writer.release.set()
        stale = await asyncio.wait_for(write, timeout=1.0)
        assert stale.complete is False
        await asyncio.wait_for(close, timeout=1.0)

        tx_count_after_close = len([call for call in calls if call[:1] == ("sync-tx",)])
        await asyncio.sleep(0)
        assert len([call for call in calls if call[:1] == ("sync-tx",)]) == tx_count_after_close
        assert calls[-1] == ("close", SYNTHETIC_DEVICE)

    asyncio.run(scenario())


def test_partial_torque_enable_rolls_back_and_cleanup_attempts_every_servo() -> None:
    async def scenario() -> None:
        grant = await _production_grant()
        servo_ids = grant.session.allowed_servo_ids
        calls: list[tuple[object, ...]] = []
        sdk = _TorqueFailureSdk(
            calls,
            enable_failure=servo_ids[2],
            disable_failures=frozenset({servo_ids[1], servo_ids[-1]}),
        )
        factory = FtServoProductionBusFactory(
            importer=lambda _name: cast(ModuleType, sdk),
            package_available=lambda name: name == "scservo_sdk",
        )
        bus = factory.create(grant)
        await bus.open(SYNTHETIC_DEVICE, "STS3215")

        result = await bus.enable_torque_for_execution(servo_ids)
        assert result.complete is False
        assert result.safety_state_known is False
        assert result.succeeded_ids == servo_ids[:2]
        assert result.failed_ids == servo_ids[2:]
        rollback_ids = [
            cast(int, call[1])
            for call in calls
            if call[0] == "write1" and call[2:] == (TORQUE_ENABLE_ADDRESS, 0)
        ]
        assert rollback_ids == list(servo_ids)

        write = await bus.write_goal_positions({servo_id: 100 for servo_id in servo_ids})
        assert write.complete is False
        assert write.safety_state_known is False

        with pytest.raises(RuntimeError, match="safety state is uncertain"):
            await bus.close()
        all_disable_attempts = [
            cast(int, call[1])
            for call in calls
            if call[0] == "write1" and call[2:] == (TORQUE_ENABLE_ADDRESS, 0)
        ]
        assert all_disable_attempts == [*servo_ids, *servo_ids]
        assert bus.last_torque_result is not None
        assert bus.last_torque_result.failed_ids == (servo_ids[1], servo_ids[-1])

    asyncio.run(scenario())
