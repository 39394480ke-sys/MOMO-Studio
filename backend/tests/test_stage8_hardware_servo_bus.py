"""Stage 8 bounded ServoBus contract and lazy Feetech shell tests."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Mapping
from types import ModuleType

import pytest

from momo.adapters.hardware.fake_servo_bus import FakeServoBusFactory
from momo.adapters.hardware.feetech_servo_bus import (
    FeetechAdapterPendingError,
    FeetechServoBus,
    FeetechServoBusFactory,
)
from momo.application.services.operator_session_service import OperatorSessionService
from momo.application.services.real_hardware_authorization import RealHardwareAuthorization
from momo.domain.real_hardware import (
    REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
    HardwareDependencyState,
    RealHardwareAccessGrant,
    RealHardwareAuthorizationPurpose,
    RealHardwareGateInput,
    RealStopOutcome,
    RealStopResult,
    ServoWriteResult,
)
from momo.ports.servo_bus import ServoBus
from tests.stage3_helpers import FakeClock
from tests.stage8_hardware_helpers import fake_bus, real_context


async def authorized_grant(
    purpose: RealHardwareAuthorizationPurpose = RealHardwareAuthorizationPurpose.DIAGNOSTICS,
) -> RealHardwareAccessGrant:
    context = real_context()
    clock = FakeClock()
    authorization = RealHardwareAuthorization()
    sessions = OperatorSessionService(clock, authorization, ttl_s=60.0)
    issued = await sessions.issue(
        context,
        confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
        physical_estop_confirmed=True,
    )
    evidence = await sessions.authorize(
        issued.session_token.get_secret_value(),
        context,
        purpose=purpose,
    )
    return authorization.require_authorized(
        RealHardwareGateInput(
            context=context,
            evaluated_at=clock.now(),
            operator_session=evidence,
        ),
        purpose=purpose,
    )


def test_servo_bus_surface_is_bounded_and_fake_is_structural_implementation() -> None:
    context = real_context()
    bus = fake_bus(context)

    assert isinstance(bus, ServoBus)
    assert not hasattr(ServoBus, "scan")
    assert not hasattr(ServoBus, "read_register")
    assert not hasattr(ServoBus, "write_register")
    assert not hasattr(ServoBus, "enable_torque")


def test_typed_write_and_stop_results_refuse_false_success() -> None:
    with pytest.raises(ValueError, match="at least one requested ID"):
        ServoWriteResult(
            requested_ids=(),
            written_ids=(),
            failed_ids=(),
            connected=True,
            complete=True,
            safety_state_known=True,
            detail="empty false success",
        )
    with pytest.raises(ValueError, match="exactly partition"):
        ServoWriteResult(
            requested_ids=(1, 2),
            written_ids=(1,),
            failed_ids=(),
            connected=True,
            complete=False,
            safety_state_known=False,
            detail="invalid partition",
        )
    with pytest.raises(ValueError, match="all IDs verified"):
        RealStopOutcome(
            result=RealStopResult.STOPPED_AND_VERIFIED,
            requested_ids=(1, 2),
            affected_ids=(1,),
            connected=True,
            safety_state_known=True,
            detail="not actually complete",
        )
    with pytest.raises(ValueError, match="disconnected Stop"):
        RealStopOutcome(
            result=RealStopResult.FAILED,
            requested_ids=(1,),
            affected_ids=(1,),
            connected=False,
            safety_state_known=False,
            detail="cannot affect a disconnected bus",
        )


def test_fake_bus_uses_only_explicit_ids_and_reports_partial_write() -> None:
    async def scenario() -> None:
        context = real_context()
        assert context.device is not None
        failed_id = context.device.servo_ids[-1]
        bus = fake_bus(context, failed_write_ids=(failed_id,))
        await bus.open(context.device.serial_port, context.device.protocol)

        ping = await bus.ping_explicit_ids(context.device.servo_ids)
        assert tuple(ping) == context.device.servo_ids
        result = await bus.write_goal_positions(
            {servo_id: 10 for servo_id in context.device.servo_ids}
        )
        assert result.complete is False
        assert result.safety_state_known is False
        assert result.failed_ids == (failed_id,)
        assert set(result.written_ids) == set(context.device.servo_ids[:-1])
        assert all(event[0] != "scan" for event in bus.events)

        await bus.close()
        stopped = await bus.stop_or_hold(context.device.servo_ids)
        assert stopped.result is RealStopResult.NOT_CONNECTED
        assert stopped.safety_state_known is False

    asyncio.run(scenario())


class RecordingBridge:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def open(self, device: str, protocol: str) -> None:
        self.events.append(("open", (device, protocol)))

    def close(self) -> None:
        self.events.append(("close", None))

    def ping(self, servo_id: int) -> bool:
        self.events.append(("ping", servo_id))
        return True

    def read_present_position(self, servo_id: int) -> int:
        self.events.append(("position", servo_id))
        return 0

    def read_operating_mode(self, servo_id: int) -> str:
        self.events.append(("mode", servo_id))
        return "MULTI_TURN"

    def read_torque_state(self, servo_id: int) -> bool:
        self.events.append(("torque", servo_id))
        return False

    def write_goal_positions(self, goals: Mapping[int, int]) -> Mapping[int, bool]:
        self.events.append(("write", dict(goals)))
        return {servo_id: True for servo_id in goals}


def verified_module(bridge: RecordingBridge, create_calls: list[str]) -> ModuleType:
    module = ModuleType("synthetic_reviewed_feetech_bridge")

    def create_momo_servo_backend() -> RecordingBridge:
        create_calls.append("create")
        return bridge

    module.create_momo_servo_backend = create_momo_servo_backend  # type: ignore[attr-defined]
    return module


def test_pending_feetech_factory_never_imports_or_instantiates() -> None:
    async def scenario() -> None:
        grant = await authorized_grant()
        imports: list[str] = []
        creates: list[str] = []
        bridge = RecordingBridge()
        module = verified_module(bridge, creates)

        def importer(name: str) -> ModuleType:
            imports.append(name)
            return module

        factory = FeetechServoBusFactory(
            verified_bridge_module="synthetic_reviewed_feetech_bridge",
            importer=importer,
        )
        expired = grant.model_copy(update={"authorized_at": grant.session.expires_at})
        with pytest.raises(FeetechAdapterPendingError, match="expired"):
            factory.create(expired)
        assert imports == []
        assert creates == []

        with pytest.raises(FeetechAdapterPendingError, match="verification is still pending"):
            factory.create(grant)
        assert imports == []
        assert creates == []
        assert bridge.events == []

    asyncio.run(scenario())


def test_feetech_shell_is_explicit_read_only_and_stop_is_uncertain() -> None:
    async def scenario() -> None:
        grant = (await authorized_grant()).model_copy(
            update={"adapter_id": "feetech-servo-bus-shell"}
        )
        creates: list[str] = []
        bridge = RecordingBridge()
        module = verified_module(bridge, creates)
        bus = FeetechServoBus(module, grant)
        context = real_context()
        assert context.device is not None

        with pytest.raises(PermissionError, match="authorized grant"):
            await bus.open("/dev/not-authorized", context.device.protocol)
        assert creates == []
        await bus.open(context.device.serial_port, context.device.protocol)
        assert creates == ["create"]
        assert bridge.events == [("open", (context.device.serial_port, context.device.protocol))]
        allowed_ids = grant.session.allowed_servo_ids
        selected_ids = (allowed_ids[0],)
        assert await bus.read_present_positions(selected_ids) == {selected_ids[0]: 0}
        unallowed_id = next(servo_id for servo_id in range(1, 254) if servo_id not in allowed_ids)
        with pytest.raises(PermissionError, match="subset"):
            await bus.read_present_positions((unallowed_id,))
        with pytest.raises(PermissionError, match="exactly match"):
            await bus.stop_or_hold(selected_ids)
        with pytest.raises(PermissionError, match="read-only diagnostics"):
            await bus.write_goal_positions({servo_id: 0 for servo_id in allowed_ids})
        stop = await bus.stop_or_hold(allowed_ids)
        assert stop.result is RealStopResult.SAFETY_STATE_UNCERTAIN
        assert stop.safety_state_known is False
        assert all(event[0] not in {"scan", "stop", "hold"} for event in bridge.events)
        await bus.close()

    asyncio.run(scenario())


class BlockingOpenBridge(RecordingBridge):
    def __init__(self) -> None:
        super().__init__()
        self.open_started = threading.Event()
        self.release_open = threading.Event()

    def open(self, device: str, protocol: str) -> None:
        self.open_started.set()
        if not self.release_open.wait(timeout=2.0):
            raise TimeoutError("synthetic bridge open was not released")
        super().open(device, protocol)


class BlockingReadBridge(RecordingBridge):
    def __init__(self) -> None:
        super().__init__()
        self.read_started = threading.Event()
        self.release_read = threading.Event()

    def read_present_position(self, servo_id: int) -> int:
        self.events.append(("position-start", servo_id))
        self.read_started.set()
        if not self.release_read.wait(timeout=2.0):
            raise TimeoutError("synthetic bridge read was not released")
        self.events.append(("position-end", servo_id))
        return 0


def test_cancelled_feetech_open_waits_for_worker_and_closes_late_port() -> None:
    async def scenario() -> None:
        grant = (await authorized_grant()).model_copy(
            update={"adapter_id": "feetech-servo-bus-shell"}
        )
        bridge = BlockingOpenBridge()
        module = verified_module(bridge, [])
        bus = FeetechServoBus(module, grant)
        context = real_context()
        assert context.device is not None

        task = asyncio.create_task(bus.open(context.device.serial_port, context.device.protocol))
        while not bridge.open_started.is_set():
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert task.done() is False
        task.cancel()
        await asyncio.sleep(0)
        assert task.done() is False
        bridge.release_open.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1.0)

        assert [event[0] for event in bridge.events] == ["open", "close"]
        assert bus.connected is False

    asyncio.run(scenario())


def test_feetech_shell_never_starts_unverified_goal_write() -> None:
    async def scenario() -> None:
        grant = (
            await authorized_grant(RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION)
        ).model_copy(update={"adapter_id": "feetech-servo-bus-shell"})
        bridge = RecordingBridge()
        bus = FeetechServoBus(verified_module(bridge, []), grant)
        context = real_context()
        assert context.device is not None
        await bus.open(context.device.serial_port, context.device.protocol)

        with pytest.raises(FeetechAdapterPendingError, match="writes are disabled"):
            await bus.write_goal_positions({servo_id: 0 for servo_id in context.device.servo_ids})
        assert all(event[0] != "write" for event in bridge.events)
        await bus.close()

    asyncio.run(scenario())


def test_cancelled_feetech_read_finishes_before_bridge_can_close() -> None:
    async def scenario() -> None:
        grant = (await authorized_grant()).model_copy(
            update={"adapter_id": "feetech-servo-bus-shell"}
        )
        bridge = BlockingReadBridge()
        bus = FeetechServoBus(verified_module(bridge, []), grant)
        context = real_context()
        assert context.device is not None
        await bus.open(context.device.serial_port, context.device.protocol)
        servo_id = context.device.servo_ids[0]

        read_task = asyncio.create_task(bus.read_present_positions((servo_id,)))
        while not bridge.read_started.is_set():
            await asyncio.sleep(0)
        read_task.cancel()
        await asyncio.sleep(0)
        assert read_task.done() is False
        read_task.cancel()
        close_task = asyncio.create_task(bus.close())
        await asyncio.sleep(0)
        assert close_task.done() is False

        bridge.release_read.set()
        with pytest.raises(asyncio.CancelledError):
            await read_task
        await close_task
        assert [event[0] for event in bridge.events][-3:] == [
            "position-start",
            "position-end",
            "close",
        ]

    asyncio.run(scenario())


def test_fake_factory_and_bus_bind_exact_adapter_device_and_protocol() -> None:
    async def scenario() -> None:
        grant = await authorized_grant()
        context = real_context()
        bus = fake_bus(context)
        factory = FakeServoBusFactory(bus)
        bound = factory.create(grant)
        assert context.device is not None

        with pytest.raises(PermissionError, match="authorized grant"):
            await bound.open("/dev/not-authorized", context.device.protocol)
        with pytest.raises(PermissionError, match="authorized grant"):
            await bound.open(context.device.serial_port, "OTHER")
        assert bound.events == ()

        mismatched = grant.model_copy(update={"adapter_id": "another-adapter"})
        with pytest.raises(PermissionError, match="does not match"):
            factory.create(mismatched)

    asyncio.run(scenario())


def test_unverified_feetech_dependency_stays_pending_without_import() -> None:
    async def scenario() -> None:
        calls: list[str] = []

        def importer(name: str) -> ModuleType:
            calls.append(name)
            raise AssertionError("pending adapter must not import")

        factory = FeetechServoBusFactory(importer=importer)
        assert factory.dependency.state is HardwareDependencyState.PENDING_ADAPTER_VERIFICATION
        assert factory.dependency.package_name is None
        assert factory.dependency.license_status == "UNVERIFIED"
        with pytest.raises(FeetechAdapterPendingError):
            factory.create(await authorized_grant())
        assert calls == []

    asyncio.run(scenario())
