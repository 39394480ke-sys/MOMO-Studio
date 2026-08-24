"""Stage 8 explicit device workflow, cleanup, concurrency, and REST tests."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Mapping
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from momo.adapters.hardware.fake_servo_bus import FakeServoBus, FakeServoBusFactory
from momo.adapters.hardware.feetech_servo_bus import FeetechServoBusFactory
from momo.api.error_handlers import install_error_handlers
from momo.api.routes.device import router as device_router
from momo.application.services.device_diagnostics_service import (
    DeviceAlreadyConnectedError,
    DeviceConnectionError,
    DeviceDiagnosticsService,
    DeviceNotConnectedError,
)
from momo.application.services.operator_session_service import (
    OperatorSessionPrerequisiteError,
    OperatorSessionService,
    OperatorSessionTokenError,
)
from momo.application.services.real_hardware_authorization import RealHardwareAuthorization
from momo.application.services.security_service import SecurityService
from momo.domain.enums import KinematicsVerificationStatus
from momo.domain.real_hardware import (
    REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
    DeviceDiagnosticsSnapshot,
    RealHardwareAccessGrant,
    RealHardwareBlocker,
    RealHardwareContext,
    RealStopResult,
    ServoDiagnosticRecord,
    ServoPingResult,
)
from momo.domain.security import NetworkSecurityPolicy
from tests.stage3_helpers import FakeClock
from tests.stage8_hardware_helpers import device_service, fake_bus, real_context


async def issue_token(service: DeviceDiagnosticsService) -> str:
    issued = await service.issue_operator_session(
        confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
        physical_estop_confirmed=True,
    )
    return issued.session_token.get_secret_value()


def isolated_app(service: DeviceDiagnosticsService) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.state.device_diagnostics_service = service
    app.state.security_service = SecurityService(
        NetworkSecurityPolicy(),
        lan_token=None,
        monotonic=time.monotonic,
    )
    app.include_router(device_router, prefix="/api/v1")
    return app


async def request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json_data: object | None = None,
    token: str | None = None,
) -> httpx.Response:
    headers = {"X-MOMO-Operator-Session": token} if token is not None else None
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, json=json_data, headers=headers)


def assert_no_key(value: object, forbidden: str) -> None:
    if isinstance(value, dict):
        assert forbidden not in value
        for item in value.values():
            assert_no_key(item, forbidden)
    elif isinstance(value, list):
        for item in value:
            assert_no_key(item, forbidden)


def test_connect_sequence_is_read_only_exact_id_and_diagnostics_is_explicit() -> None:
    async def scenario() -> None:
        context = real_context()
        assert context.device is not None
        bus = fake_bus(context)
        service, _, factory = device_service(context, bus=bus)
        token = await issue_token(service)

        connected = await service.connect(token)
        assert connected.connected is True
        assert all(record.torque_enabled is None for record in connected.records)
        assert [event[0] for event in bus.events] == [
            "open",
            "ping_explicit_ids",
            "read_operating_modes",
            "read_present_positions",
        ]
        assert factory.grants[0].purpose.value == "DIAGNOSTICS"
        coordinated_bus, coordinated_evidence = await service.require_authorized_connected_bus(
            token
        )
        assert coordinated_bus is bus
        assert coordinated_evidence.session_id == factory.grants[0].session.session_id
        selected_ids = (context.device.servo_ids[0],)
        assert set(await bus.ping_explicit_ids(selected_ids)) == set(selected_ids)
        assert set(await bus.read_present_positions(selected_ids)) == set(selected_ids)
        assert set(await bus.read_operating_modes(selected_ids)) == set(selected_ids)
        assert set(await bus.read_torque_states(selected_ids)) == set(selected_ids)
        unallowed_id = next(
            servo_id for servo_id in range(1, 254) if servo_id not in context.device.servo_ids
        )
        with pytest.raises(PermissionError, match="subset"):
            await bus.read_present_positions((unallowed_id,))
        with pytest.raises(PermissionError, match="exactly match"):
            await bus.stop_or_hold(selected_ids)
        with pytest.raises(PermissionError, match="read-only diagnostics"):
            await bus.write_goal_positions({servo_id: 0 for servo_id in context.device.servo_ids})

        snapshot = await service.diagnostics(token)
        assert all(record.torque_enabled is False for record in snapshot.records)
        assert [event[0] for event in bus.events[-4:]] == [
            "ping_explicit_ids",
            "read_operating_modes",
            "read_present_positions",
            "read_torque_states",
        ]
        assert all(
            event[0] not in {"scan", "home", "enable_torque", "write_goal_positions"}
            for event in bus.events
        )

        stopped = await service.stop()
        assert stopped.result is RealStopResult.STOPPED_AND_VERIFIED
        assert stopped.safety_state_known is True
        disconnected = await service.disconnect(token)
        assert disconnected.connected is False
        assert bus.connected is False
        assert (await service.sessions.status()).active is False

    asyncio.run(scenario())


def test_connected_bus_coordination_rejects_replaced_session_without_reopening() -> None:
    async def scenario() -> None:
        context = real_context()
        bus = fake_bus(context)
        service, _, _ = device_service(context, bus=bus)
        first_token = await issue_token(service)
        await service.connect(first_token)
        open_count = [event[0] for event in bus.events].count("open")

        with pytest.raises(DeviceAlreadyConnectedError, match="Close"):
            await issue_token(service)
        replacement = await service.sessions.issue(
            context,
            confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        second_token = replacement.session_token.get_secret_value()
        with pytest.raises(OperatorSessionTokenError):
            await service.require_authorized_connected_bus(first_token)
        with pytest.raises(DeviceNotConnectedError, match="different operator session"):
            await service.require_authorized_connected_bus(second_token)
        assert [event[0] for event in bus.events].count("open") == open_count

        await service.disconnect(second_token)
        assert bus.connected is False

    asyncio.run(scenario())


def test_calibration_change_invalidation_closes_bus_and_blocks_stale_fingerprint() -> None:
    async def scenario() -> None:
        context = real_context()
        bus = fake_bus(context)
        service, _, _ = device_service(context, bus=bus)
        token = await issue_token(service)
        await service.connect(token)

        await service.invalidate_calibration_authorization()

        assert service.connected is False
        assert bus.connected is False
        assert service.context.calibration is None
        assert (await service.sessions.status()).active is False
        report = await service.readiness()
        assert RealHardwareBlocker.CALIBRATION_MISSING in report.blocking_reasons
        assert report.session_authorizable is False
        with pytest.raises(OperatorSessionTokenError):
            await service.require_authorized_connected_bus(token)
        with pytest.raises(OperatorSessionPrerequisiteError):
            await issue_token(service)

    asyncio.run(scenario())


def test_partial_connection_failure_closes_bus_and_invalidates_session() -> None:
    async def scenario() -> None:
        context = real_context()
        assert context.device is not None
        bus = fake_bus(context, missing_ping_ids=(context.device.servo_ids[-1],))
        service, _, _ = device_service(context, bus=bus)
        token = await issue_token(service)

        with pytest.raises(DeviceConnectionError):
            await service.connect(token)
        assert service.connected is False
        assert bus.connected is False
        assert [event[0] for event in bus.events] == [
            "open",
            "ping_explicit_ids",
            "close",
        ]
        assert (await service.sessions.status()).active is False
        with pytest.raises(OperatorSessionTokenError):
            await service.connect(token)

    asyncio.run(scenario())


class BlockingPingBus(FakeServoBus):
    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
        self.ping_started = asyncio.Event()
        self.release_ping = asyncio.Event()

    async def ping_explicit_ids(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, ServoPingResult]:
        self.ping_started.set()
        await self.release_ping.wait()
        return await super().ping_explicit_ids(servo_ids)


class ExpiringPositionBus(FakeServoBus):
    def __init__(self, clock: FakeClock, **values: Any) -> None:
        super().__init__(**values)
        self.clock = clock

    async def read_present_positions(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, int]:
        result = await super().read_present_positions(servo_ids)
        self.clock.elapse(61.0)
        return result


class BlockingDiagnosticsPositionBus(FakeServoBus):
    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
        self.block_reads = False
        self.read_started = asyncio.Event()
        self.release_read = asyncio.Event()

    async def read_present_positions(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, int]:
        if self.block_reads:
            self.read_started.set()
            await self.release_read.wait()
        return await super().read_present_positions(servo_ids)


class BlockingCloseBus(FakeServoBus):
    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
        self.close_started = asyncio.Event()
        self.release_close = asyncio.Event()

    async def close(self) -> None:
        self.close_started.set()
        await self.release_close.wait()
        await super().close()


class BlockingCreateFactory(FakeServoBusFactory):
    def __init__(self, bus: FakeServoBus) -> None:
        super().__init__(bus)
        self.create_started = threading.Event()
        self.release_create = threading.Event()

    def create(self, authorization: RealHardwareAccessGrant) -> FakeServoBus:
        self.create_started.set()
        if not self.release_create.wait(timeout=2.0):
            raise TimeoutError("synthetic factory create was not released")
        return super().create(authorization)


class FailingCloseOnceBus(FakeServoBus):
    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1
        await super().close()
        if self.close_calls == 1:
            raise RuntimeError("synthetic first close failure")


class BlockingSnapshotDeviceService(DeviceDiagnosticsService):
    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
        self.snapshot_started = asyncio.Event()
        self.release_snapshot = asyncio.Event()

    async def _snapshot(
        self,
        records: tuple[ServoDiagnosticRecord, ...],
        *,
        connected: bool | None = None,
        include_transitional_blocker: bool = True,
    ) -> DeviceDiagnosticsSnapshot:
        if connected is True:
            self.snapshot_started.set()
            await self.release_snapshot.wait()
        return await super()._snapshot(
            records,
            connected=connected,
            include_transitional_blocker=include_transitional_blocker,
        )


def test_cancelled_connection_closes_partial_bus_and_revokes_token() -> None:
    async def scenario() -> None:
        context = real_context()
        template = fake_bus(context)
        bus = BlockingPingBus(
            present_positions=template.positions,
            operating_modes={servo_id: "MULTI_TURN" for servo_id in template.positions},
            torque_states={servo_id: False for servo_id in template.positions},
        )
        service, _, _ = device_service(context, bus=bus)
        token = await issue_token(service)

        task = asyncio.create_task(service.connect(token))
        await bus.ping_started.wait()
        stopped = await service.stop()
        assert stopped.result is RealStopResult.STOPPED_AND_VERIFIED
        assert (
            RealHardwareBlocker.DEVICE_SAFETY_STATE_UNCERTAIN
            in (await service.readiness()).blocking_reasons
        )
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert service.connected is False
        assert bus.connected is False
        assert bus.events[-1][0] == "close"
        assert (await service.sessions.status()).active is False

    asyncio.run(scenario())


def test_session_expiry_during_connection_closes_partial_bus() -> None:
    async def scenario() -> None:
        context = real_context()
        clock = FakeClock()
        template = fake_bus(context)
        bus = ExpiringPositionBus(
            clock,
            present_positions=template.positions,
            operating_modes={servo_id: "MULTI_TURN" for servo_id in template.positions},
            torque_states={servo_id: False for servo_id in template.positions},
        )
        service, _, _ = device_service(context, bus=bus, clock=clock)
        token = await issue_token(service)

        with pytest.raises(OperatorSessionTokenError, match="expired"):
            await service.connect(token)
        assert service.connected is False
        assert bus.connected is False
        assert bus.events[-1][0] == "close"
        assert (await service.sessions.status()).active is False

    asyncio.run(scenario())


def test_cancelled_response_snapshot_closes_unpublished_candidate() -> None:
    async def scenario() -> None:
        context = real_context()
        clock = FakeClock()
        authorization = RealHardwareAuthorization()
        sessions = OperatorSessionService(clock, authorization, ttl_s=60.0)
        bus = fake_bus(context)
        service = BlockingSnapshotDeviceService(
            context=context,
            authorization=authorization,
            sessions=sessions,
            bus_factory=FakeServoBusFactory(bus),
            clock=clock,
        )
        token = await issue_token(service)

        task = asyncio.create_task(service.connect(token))
        await service.snapshot_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert service.connected is False
        assert bus.connected is False
        assert bus.events[-1][0] == "close"
        assert (await service.sessions.status()).active is False

    asyncio.run(scenario())


def test_priority_stop_reaches_bus_during_slow_close() -> None:
    async def scenario() -> None:
        context = real_context()
        template = fake_bus(context)
        bus = BlockingCloseBus(
            present_positions=template.positions,
            operating_modes={servo_id: "MULTI_TURN" for servo_id in template.positions},
            torque_states={servo_id: False for servo_id in template.positions},
        )
        service, _, _ = device_service(context, bus=bus)
        token = await issue_token(service)
        await service.connect(token)

        disconnect_task = asyncio.create_task(service.disconnect(token))
        await bus.close_started.wait()
        assert service.connected is False
        assert (
            RealHardwareBlocker.DEVICE_SAFETY_STATE_UNCERTAIN
            in (await service.readiness()).blocking_reasons
        )
        stopped = await asyncio.wait_for(service.stop(), timeout=0.5)
        assert stopped.result is RealStopResult.STOPPED_AND_VERIFIED

        bus.release_close.set()
        disconnected = await disconnect_task
        assert disconnected.connected is False
        assert bus.connected is False

    asyncio.run(scenario())


def test_repeated_cancellation_waits_for_device_close_terminal_state() -> None:
    async def scenario() -> None:
        context = real_context()
        template = fake_bus(context)
        bus = BlockingCloseBus(
            present_positions=template.positions,
            operating_modes={servo_id: "MULTI_TURN" for servo_id in template.positions},
            torque_states={servo_id: False for servo_id in template.positions},
        )
        service, _, _ = device_service(context, bus=bus)
        token = await issue_token(service)
        await service.connect(token)

        disconnect_task = asyncio.create_task(service.disconnect(token))
        await bus.close_started.wait()
        disconnect_task.cancel()
        await asyncio.sleep(0)
        assert disconnect_task.done() is False
        disconnect_task.cancel()
        await asyncio.sleep(0)
        assert disconnect_task.done() is False
        bus.release_close.set()
        with pytest.raises(asyncio.CancelledError):
            await disconnect_task

        assert service.connected is False
        assert bus.connected is False
        assert (await service.sessions.status()).active is False

    asyncio.run(scenario())


def test_repeated_cancellation_observes_inert_factory_before_cleanup() -> None:
    async def scenario() -> None:
        context = real_context()
        clock = FakeClock()
        authorization = RealHardwareAuthorization()
        sessions = OperatorSessionService(clock, authorization, ttl_s=60.0)
        bus = fake_bus(context)
        factory = BlockingCreateFactory(bus)
        service = DeviceDiagnosticsService(
            context=context,
            authorization=authorization,
            sessions=sessions,
            bus_factory=factory,
            clock=clock,
        )
        token = await issue_token(service)

        connect_task = asyncio.create_task(service.connect(token))
        while not factory.create_started.is_set():
            await asyncio.sleep(0)
        connect_task.cancel()
        await asyncio.sleep(0)
        assert connect_task.done() is False
        connect_task.cancel()
        await asyncio.sleep(0)
        assert connect_task.done() is False
        factory.release_create.set()
        with pytest.raises(asyncio.CancelledError):
            await connect_task

        assert service.connected is False
        assert bus.connected is False
        assert [event[0] for event in bus.events] == ["close"]
        assert (await service.sessions.status()).active is False

    asyncio.run(scenario())


def test_failed_partial_close_remains_stoppable_and_blocks_reauthorization() -> None:
    async def scenario() -> None:
        context = real_context()
        assert context.device is not None
        template = fake_bus(context)
        bus = FailingCloseOnceBus(
            present_positions=template.positions,
            operating_modes={servo_id: "MULTI_TURN" for servo_id in template.positions},
            torque_states={servo_id: False for servo_id in template.positions},
            missing_ping_ids=(context.device.servo_ids[-1],),
        )
        service, _, _ = device_service(context, bus=bus)
        token = await issue_token(service)

        with pytest.raises(DeviceConnectionError):
            await service.connect(token)
        report = await service.readiness()
        assert report.ready is False
        assert report.session_authorizable is False
        assert RealHardwareBlocker.DEVICE_SAFETY_STATE_UNCERTAIN in report.blocking_reasons
        with pytest.raises(DeviceAlreadyConnectedError, match="uncertain"):
            await issue_token(service)
        stopped = await service.stop()
        assert stopped.result is RealStopResult.SAFETY_STATE_UNCERTAIN

        await service.shutdown()
        assert bus.close_calls == 2
        assert (await service.readiness()).session_authorizable is True

    asyncio.run(scenario())


def test_connect_rejects_raw_position_outside_profile_logical_limits() -> None:
    async def scenario() -> None:
        context = real_context()
        assert context.device is not None
        template = fake_bus(context)
        positions = template.positions
        positions[context.device.servo_ids[1]] = 30_719
        bus = fake_bus(context, present_positions=positions)
        service, _, _ = device_service(context, bus=bus)
        token = await issue_token(service)

        with pytest.raises(DeviceConnectionError, match="connection failed"):
            await service.connect(token)
        assert service.connected is False
        assert bus.connected is False

    asyncio.run(scenario())


def test_priority_stop_does_not_queue_behind_slow_diagnostics() -> None:
    async def scenario() -> None:
        context = real_context()
        template = fake_bus(context)
        bus = BlockingDiagnosticsPositionBus(
            present_positions=template.positions,
            operating_modes={servo_id: "MULTI_TURN" for servo_id in template.positions},
            torque_states={servo_id: False for servo_id in template.positions},
        )
        service, _, _ = device_service(context, bus=bus)
        token = await issue_token(service)
        await service.connect(token)

        bus.block_reads = True
        diagnostics_task = asyncio.create_task(service.diagnostics(token))
        await bus.read_started.wait()
        stopped = await asyncio.wait_for(service.stop(), timeout=0.5)
        assert stopped.result is RealStopResult.STOPPED_AND_VERIFIED
        assert diagnostics_task.done() is False

        bus.release_read.set()
        await diagnostics_task
        await service.disconnect(token)

    asyncio.run(scenario())


def test_connected_session_expiry_closes_bus_and_allows_fresh_confirmation() -> None:
    async def scenario() -> None:
        context = real_context()
        service, clock, factory = device_service(context)
        token = await issue_token(service)
        await service.connect(token)
        clock.elapse(61.0)
        await clock.settle()

        assert (await service.sessions.status()).active is False
        assert service.connected is False
        assert factory.bus.connected is False
        replacement = await issue_token(service)
        assert replacement != token
        await service.shutdown()

    asyncio.run(scenario())


def test_concurrent_connect_has_exactly_one_owner() -> None:
    async def scenario() -> None:
        context = real_context()
        bus = fake_bus(context)
        service, _, factory = device_service(context, bus=bus)
        token = await issue_token(service)

        outcomes = await asyncio.gather(
            service.connect(token),
            service.connect(token),
            return_exceptions=True,
        )
        assert sum(not isinstance(item, BaseException) for item in outcomes) == 1
        assert sum(isinstance(item, DeviceAlreadyConnectedError) for item in outcomes) == 1
        assert len(factory.grants) == 1
        assert [event[0] for event in bus.events].count("open") == 1
        await service.shutdown()

    asyncio.run(scenario())


def test_default_device_api_is_blocked_and_never_touches_a_bus() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        authorization = RealHardwareAuthorization()
        sessions = OperatorSessionService(clock, authorization, ttl_s=60.0)
        service = DeviceDiagnosticsService(
            context=RealHardwareContext(),
            authorization=authorization,
            sessions=sessions,
            bus_factory=None,
            clock=clock,
        )
        app = isolated_app(service)

        readiness = await request(app, "GET", "/api/v1/device/readiness")
        assert readiness.status_code == 200
        body = readiness.json()
        assert body["ready"] is False
        assert body["session_authorizable"] is False
        assert body["connected"] is False
        assert body["capabilities"] == {
            "real_joint_motion_ready": False,
            "real_cartesian_motion_ready": False,
            "real_playback_ready": False,
            "real_vision_follow_ready": False,
        }
        assert body["confirmation"]["masked_serial_port"] is None

        connect = await request(app, "POST", "/api/v1/device/connect")
        assert connect.status_code == 422
        stopped = await request(app, "POST", "/api/v1/device/stop")
        assert stopped.status_code == 200
        assert stopped.json()["result"] == "NOT_CONNECTED"
        assert stopped.json()["physical_estop_required"] is True

    asyncio.run(scenario())


def test_pending_feetech_dependency_cannot_claim_readiness_or_issue_session() -> None:
    async def scenario() -> None:
        context = real_context()
        clock = FakeClock()
        authorization = RealHardwareAuthorization()
        sessions = OperatorSessionService(clock, authorization, ttl_s=60.0)
        service = DeviceDiagnosticsService(
            context=context,
            authorization=authorization,
            sessions=sessions,
            bus_factory=FeetechServoBusFactory(),
            clock=clock,
        )

        report = await service.readiness()
        assert report.ready is False
        assert report.session_authorizable is False
        assert RealHardwareBlocker.SERVO_BUS_DEPENDENCY_UNAVAILABLE in (report.blocking_reasons)
        with pytest.raises(OperatorSessionPrerequisiteError):
            await service.issue_operator_session(
                confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
                physical_estop_confirmed=True,
            )

    asyncio.run(scenario())


def test_device_api_returns_one_time_token_full_confirmation_and_redacted_diagnostics() -> None:
    async def scenario() -> None:
        context = real_context()
        assert context.device is not None
        service, _, _ = device_service(context)
        app = isolated_app(service)

        before = await request(app, "GET", "/api/v1/device/readiness")
        assert before.status_code == 200
        before_body = before.json()
        assert before_body["state"] == "AWAITING_OPERATOR_SESSION"
        assert before_body["session_authorizable"] is True
        required_text = before_body["confirmation"]["required_confirmation_text"]

        wrong = await request(
            app,
            "POST",
            "/api/v1/device/operator-session",
            json_data={
                "confirmation_text": required_text.lower(),
                "physical_estop_confirmed": True,
            },
        )
        assert wrong.status_code == 422
        issued = await request(
            app,
            "POST",
            "/api/v1/device/operator-session",
            json_data={
                "confirmation_text": required_text,
                "physical_estop_confirmed": True,
            },
        )
        assert issued.status_code == 200
        assert issued.headers["cache-control"] == "no-store"
        issued_body = issued.json()
        assert set(issued_body) == {
            "session_token",
            "session_id",
            "issued_at",
            "expires_at",
            "evidence",
        }
        token = issued_body["session_token"]
        evidence = issued_body["evidence"]
        assert evidence["variant"] == "V2"
        assert evidence["profile_fingerprint"]
        assert evidence["calibration_fingerprint"]
        assert evidence["kinematics_fingerprint"]
        assert evidence["masked_serial_port"] != context.device.serial_port
        assert evidence["masked_servo_ids"] == list(context.device.masked_servo_ids)
        assert evidence["protocol"] == context.device.protocol
        assert evidence["required_confirmation_text"] == required_text

        connected = await request(
            app,
            "POST",
            "/api/v1/device/connect",
            token=token,
        )
        assert connected.status_code == 200
        connected_body = connected.json()
        assert connected_body["connected"] is True
        assert context.device.serial_port not in connected.text
        assert token not in connected.text
        assert_no_key(connected_body, "servo_id")
        assert all(record["torque_enabled"] is None for record in connected_body["records"])

        diagnostics = await request(
            app,
            "POST",
            "/api/v1/device/diagnostics",
            token=token,
        )
        assert diagnostics.status_code == 200
        assert token not in diagnostics.text
        assert all(record["torque_enabled"] is False for record in diagnostics.json()["records"])

        readiness = await request(app, "GET", "/api/v1/device/readiness")
        assert readiness.status_code == 200
        assert token not in readiness.text
        assert readiness.json()["session"]["active"] is True
        assert readiness.json()["capabilities"] == {
            "real_joint_motion_ready": True,
            "real_cartesian_motion_ready": True,
            "real_playback_ready": True,
            "real_vision_follow_ready": True,
        }

        stopped = await request(app, "POST", "/api/v1/device/stop")
        assert stopped.status_code == 200
        assert stopped.json()["result"] == "STOPPED_AND_VERIFIED"
        disconnected = await request(
            app,
            "POST",
            "/api/v1/device/disconnect",
            token=token,
        )
        assert disconnected.status_code == 200
        assert disconnected.json()["connected"] is False

    asyncio.run(scenario())


def test_api_exposes_joint_only_capability_for_provisional_kinematics() -> None:
    async def scenario() -> None:
        context = real_context()
        assert context.kinematics is not None
        provisional = context.kinematics.model_copy(
            update={"verification_status": KinematicsVerificationStatus.PROVISIONAL_DRY_RUN}
        )
        service, _, _ = device_service(context.model_copy(update={"kinematics": provisional}))
        app = isolated_app(service)

        before = (await request(app, "GET", "/api/v1/device/readiness")).json()
        assert before["state"] == "AWAITING_OPERATOR_SESSION"
        assert before["session_authorizable"] is True
        issued = await request(
            app,
            "POST",
            "/api/v1/device/operator-session",
            json_data={
                "confirmation_text": before["confirmation"]["required_confirmation_text"],
                "physical_estop_confirmed": True,
            },
        )
        assert issued.status_code == 200
        token = issued.json()["session_token"]

        after = (await request(app, "GET", "/api/v1/device/readiness")).json()
        assert after["ready"] is False
        assert after["state"] == "BLOCKED_BY_KINEMATICS"
        assert after["capabilities"] == {
            "real_joint_motion_ready": True,
            "real_cartesian_motion_ready": False,
            "real_playback_ready": False,
            "real_vision_follow_ready": False,
        }

        connected = await request(
            app,
            "POST",
            "/api/v1/device/connect",
            token=token,
        )
        assert connected.status_code == 200
        assert connected.json()["kinematics"]["ready_for_real"] is False
        await service.shutdown()

    asyncio.run(scenario())
