"""Isolated commissioning executor tests; all hardware state is in-memory fake data."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from momo.adapters.hardware.fake_commissioning_motion_bus import (
    FakeCommissioningMotionBus,
)
from momo.application.services.commissioning_motion_test_service import (
    CommissioningEnvelopeExceededError,
    CommissioningMotionConflictError,
    CommissioningMotionTestService,
    MultiJointTestForbiddenError,
)
from momo.application.services.operator_session_service import OperatorSessionTokenError
from momo.domain.commissioning import (
    COMMISSIONING_MOTION_HARD_CAPS,
    CommissioningMotionTestState,
    CommissioningSafetyEnvelope,
    CommissioningTestEvidence,
    CommissioningTestResult,
    PreparedCommissioningTestCommand,
    StopBehavior,
)
from momo.domain.enums import ControlMode, DomainUnit, HardwareAccessPolicy
from momo.domain.real_hardware import (
    COMMISSIONING_MOTION_SCOPES,
    OperatorSessionEvidence,
    OperatorSessionPurpose,
    RealHardwareAuthorizationPurpose,
    RealHardwareContext,
    RealStopResult,
    ServoWriteResult,
    calibration_fingerprint,
    explicit_device_fingerprint,
)
from momo.ports.commissioning_evidence_repository import (
    CommissioningTestEvidenceRepository,
)
from momo.ports.servo_bus import CommissioningPositionReadback
from tests.stage3_helpers import FakeClock
from tests.stage8_hardware_helpers import real_context

_TOKEN = "synthetic-commissioning-token"


class _FakeSessionAuthorizer:
    def __init__(
        self,
        evidence: OperatorSessionEvidence,
        clock: FakeClock,
    ) -> None:
        self.evidence = evidence
        self.clock = clock
        self.calls: list[RealHardwareAuthorizationPurpose] = []

    async def authorize(
        self,
        token: str,
        context: RealHardwareContext,
        *,
        purpose: RealHardwareAuthorizationPurpose,
    ) -> OperatorSessionEvidence:
        del context
        self.calls.append(purpose)
        if token != _TOKEN or self.clock.now() >= self.evidence.expires_at:
            raise OperatorSessionTokenError("Synthetic commissioning session is not active")
        if purpose is not RealHardwareAuthorizationPurpose.COMMISSIONING_SINGLE_JOINT_TEST:
            raise AssertionError("commissioning service requested a production authorization")
        return self.evidence


class _MemoryEvidenceRepository:
    def __init__(self) -> None:
        self.values: dict[UUID, CommissioningTestEvidence] = {}

    async def get(self, evidence_id: UUID) -> CommissioningTestEvidence | None:
        return self.values.get(evidence_id)

    async def list_evidence(self) -> tuple[CommissioningTestEvidence, ...]:
        return tuple(self.values.values())

    async def save(self, evidence: CommissioningTestEvidence) -> None:
        if evidence.id in self.values:
            raise RuntimeError("duplicate synthetic evidence UUID")
        self.values[evidence.id] = evidence


class ProductionMotionBomb(FakeCommissioningMotionBus):
    """Explode if the commissioning executor reaches any production primitive."""

    @staticmethod
    def _forbidden(name: str) -> None:
        raise AssertionError(f"commissioning reached forbidden production primitive: {name}")

    async def write_goal_positions(self, *_args: object, **_kwargs: object) -> None:
        self._forbidden("multi-joint motion")

    async def home(self, *_args: object, **_kwargs: object) -> None:
        self._forbidden("Home")

    async def cartesian(self, *_args: object, **_kwargs: object) -> None:
        self._forbidden("Cartesian")

    async def playback(self, *_args: object, **_kwargs: object) -> None:
        self._forbidden("Playback")

    async def vision_follow(self, *_args: object, **_kwargs: object) -> None:
        self._forbidden("Vision Follow")


class CommissioningEnvelopeBomb(ProductionMotionBomb):
    """Explode if a supposedly prepared command escapes any effective hard cap."""

    async def write_prepared_command(
        self,
        command: PreparedCommissioningTestCommand,
    ) -> ServoWriteResult:
        envelope = command.envelope
        hard = COMMISSIONING_MOTION_HARD_CAPS
        if command.unit is DomainUnit.MM:
            delta_cap = min(envelope.max_prismatic_delta_mm, hard.max_prismatic_delta_mm)
            speed_cap = min(envelope.max_prismatic_speed_mm_s, hard.max_prismatic_speed_mm_s)
            acceleration_cap = min(
                envelope.max_prismatic_acceleration_mm_s2,
                hard.max_prismatic_acceleration_mm_s2,
            )
        else:
            delta_cap = min(envelope.max_revolute_delta_deg, hard.max_revolute_delta_deg)
            speed_cap = min(envelope.max_revolute_speed_deg_s, hard.max_revolute_speed_deg_s)
            acceleration_cap = min(
                envelope.max_revolute_acceleration_deg_s2,
                hard.max_revolute_acceleration_deg_s2,
            )
        assert abs(command.requested_delta) <= delta_cap
        assert command.requested_speed <= speed_cap
        assert command.requested_acceleration <= acceleration_cap
        assert command.command_duration_s <= min(
            envelope.max_command_duration_s,
            hard.max_command_duration_s,
        )
        return await super().write_prepared_command(command)


class FirstReadBarrierBus(FakeCommissioningMotionBus):
    """Hold the first read so a concurrent start can challenge single-flight."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.first_read_started = asyncio.Event()
        self.release_first_read = asyncio.Event()
        self._read_count = 0

    async def read_present_position(self, servo_id: int) -> CommissioningPositionReadback:
        self._read_count += 1
        if self._read_count == 1:
            self.first_read_started.set()
            await self.release_first_read.wait()
        return await super().read_present_position(servo_id)


def _commissioning_context() -> RealHardwareContext:
    base = real_context()
    assert base.calibration is not None
    calibration = base.calibration.model_copy(update={"robot_unit_id": base.robot_unit_id})
    return base.model_copy(
        update={
            "real_motion_enabled": False,
            "commissioning_motion_test_enabled": True,
            "calibration": calibration,
            "field_acceptance_evidence": None,
        }
    )


def _session(
    context: RealHardwareContext,
    clock: FakeClock,
    *,
    envelope: CommissioningSafetyEnvelope | None = None,
    expires_in_s: float = 60.0,
) -> OperatorSessionEvidence:
    assert context.profile is not None
    assert context.calibration is not None
    assert context.device is not None
    return OperatorSessionEvidence(
        session_id=uuid4(),
        purpose=OperatorSessionPurpose.COMMISSIONING_MOTION_TEST,
        scopes=COMMISSIONING_MOTION_SCOPES,
        robot_id="primary",
        robot_unit_id=context.robot_unit_id,
        operator_id="synthetic-commissioning-operator",
        variant=context.profile.variant,
        profile_fingerprint=context.profile.fingerprint,
        calibration_fingerprint=calibration_fingerprint(context.calibration),
        kinematics_fingerprint=None,
        field_acceptance_evidence_id=None,
        pre_motion_evidence_id=uuid4(),
        commissioning_envelope=envelope or CommissioningSafetyEnvelope(),
        device_fingerprint=explicit_device_fingerprint(context.device),
        allowed_servo_ids=context.device.servo_ids,
        issued_at=clock.now(),
        expires_at=clock.now() + timedelta(seconds=expires_in_s),
        confirmed=True,
        physical_estop_confirmed=True,
        workspace_clear_confirmed=True,
        control_mode=ControlMode.REAL,
        hardware_access_policy=HardwareAccessPolicy.FULL,
    )


def _service(
    *,
    context: RealHardwareContext,
    clock: FakeClock,
    session: OperatorSessionEvidence,
    bus_updates: dict[str, object] | None = None,
    bus: FakeCommissioningMotionBus | None = None,
) -> tuple[
    CommissioningMotionTestService,
    FakeCommissioningMotionBus,
    _MemoryEvidenceRepository,
    _FakeSessionAuthorizer,
]:
    assert context.device is not None
    values: dict[str, object] = {
        "allowed_servo_ids": context.device.servo_ids,
        "session_id": session.session_id,
        "present_positions": {servo_id: 0 for servo_id in context.device.servo_ids},
        "clock": clock,
        "write_enabled": True,
        "stop_result": RealStopResult.HOLD_REQUESTED,
    }
    values.update(bus_updates or {})
    if bus is None:
        bus = FakeCommissioningMotionBus(**values)  # type: ignore[arg-type]
    repository = _MemoryEvidenceRepository()
    assert isinstance(repository, CommissioningTestEvidenceRepository)
    authorizer = _FakeSessionAuthorizer(session, clock)
    service = CommissioningMotionTestService(
        context=context,
        sessions=authorizer,
        bus=bus,
        allowed_servo_ids=context.device.servo_ids,
        repository=repository,
        clock=clock,
        software_commit=context.software_commit,
    )
    return service, bus, repository, authorizer


async def _start_and_arm(
    service: CommissioningMotionTestService,
    *,
    joint_id: str = "j11",
) -> None:
    started = await service.start_session(_TOKEN)
    assert started.state is CommissioningMotionTestState.AUTHORIZED
    armed = await service.arm(_TOKEN, joint_id=joint_id)
    assert armed.state is CommissioningMotionTestState.ARMED
    assert armed.active_joint_id == joint_id


async def _run_positive(
    service: CommissioningMotionTestService,
    *,
    joint_id: str = "j11",
    request_id: str = "request-positive",
) -> CommissioningTestEvidence:
    return await service.run_relative_test(
        _TOKEN,
        joint_id=joint_id,
        signed_delta=0.5,
        requested_speed=1.0,
        requested_acceleration=2.0,
        command_duration_s=2.0,
        request_id=request_id,
    )


def test_relative_single_joint_success_is_mapped_verified_and_persisted() -> None:
    async def scenario() -> None:
        context = _commissioning_context()
        clock = FakeClock()
        session = _session(context, clock)
        service, bus, repository, authorizer = _service(
            context=context,
            clock=clock,
            session=session,
        )
        await _start_and_arm(service)

        evidence = await _run_positive(service)

        assert evidence.result is CommissioningTestResult.PASSED
        assert evidence.robot_unit_id == context.robot_unit_id
        assert evidence.session_id == session.session_id
        assert evidence.start_raw == 0
        assert evidence.final_raw == evidence.prepared_target_raw
        assert evidence.final_raw != evidence.start_raw
        assert evidence.stop_behavior is StopBehavior.PHYSICAL_BEHAVIOR_PENDING
        assert evidence.failure_reason_optional is None
        assert repository.values == {evidence.id: evidence}
        assert {event[0] for event in bus.events} == {
            "read_present_position",
            "write_started",
            "write_applied",
            "stop_or_hold",
        }
        assert authorizer.calls and set(authorizer.calls) == {
            RealHardwareAuthorizationPurpose.COMMISSIONING_SINGLE_JOINT_TEST
        }
        status = await service.status()
        assert status.state is CommissioningMotionTestState.COMPLETED
        assert status.active_joint_id is None
        assert status.last_evidence_id == evidence.id
        assert status.physical_stop_verification.value == "PENDING"

        # The service intentionally has no production-motion entry point.
        for forbidden in ("home", "cartesian", "playback", "vision_follow", "move_joints"):
            assert not hasattr(service, forbidden)
        await service.shutdown()

    asyncio.run(scenario())


def test_production_motion_and_envelope_bombs_remain_silent_for_bounded_flow() -> None:
    async def scenario() -> None:
        context = _commissioning_context()
        assert context.device is not None
        clock = FakeClock()
        envelope = CommissioningSafetyEnvelope(
            max_revolute_delta_deg=1.0,
            max_revolute_speed_deg_s=1.0,
            max_revolute_acceleration_deg_s2=2.0,
            max_command_duration_s=1.0,
        )
        session = _session(context, clock, envelope=envelope)
        bus = CommissioningEnvelopeBomb(
            allowed_servo_ids=context.device.servo_ids,
            session_id=session.session_id,
            present_positions={servo_id: 0 for servo_id in context.device.servo_ids},
            clock=clock,
            write_enabled=True,
            stop_result=RealStopResult.HOLD_REQUESTED,
        )
        service, _, repository, _ = _service(
            context=context,
            clock=clock,
            session=session,
            bus=bus,
        )
        await _start_and_arm(service)
        evidence = await service.run_relative_test(
            _TOKEN,
            joint_id="j11",
            signed_delta=0.25,
            requested_speed=1.0,
            requested_acceleration=2.0,
            command_duration_s=1.0,
            request_id="safety-bombs-bounded",
        )
        assert evidence.result is CommissioningTestResult.PASSED
        assert repository.values == {evidence.id: evidence}
        await service.shutdown()

    asyncio.run(scenario())


def test_concurrent_test_start_cannot_replace_the_reserved_attempt() -> None:
    async def scenario() -> None:
        context = _commissioning_context()
        assert context.device is not None
        clock = FakeClock()
        session = _session(context, clock)
        bus = FirstReadBarrierBus(
            allowed_servo_ids=context.device.servo_ids,
            session_id=session.session_id,
            present_positions={servo_id: 0 for servo_id in context.device.servo_ids},
            clock=clock,
            write_enabled=True,
            stop_result=RealStopResult.HOLD_REQUESTED,
        )
        service, _, repository, _ = _service(
            context=context,
            clock=clock,
            session=session,
            bus=bus,
        )
        await _start_and_arm(service)
        first = asyncio.create_task(_run_positive(service, request_id="single-flight-first"))
        await bus.first_read_started.wait()

        with pytest.raises(CommissioningMotionConflictError):
            await _run_positive(service, request_id="single-flight-second")

        bus.release_first_read.set()
        evidence = await first
        assert evidence.result is CommissioningTestResult.PASSED
        assert evidence.request_id == "single-flight-first"
        assert tuple(repository.values.values()) == (evidence,)
        assert len([event for event in bus.events if event[0] == "write_started"]) == 1
        await service.shutdown()

    asyncio.run(scenario())


def test_completed_stop_is_idempotent_and_safe_terminal_session_can_rebind() -> None:
    async def scenario() -> None:
        context = _commissioning_context()
        clock = FakeClock()
        first_session = _session(context, clock)
        service, bus, _, authorizer = _service(
            context=context,
            clock=clock,
            session=first_session,
        )
        await _start_and_arm(service)
        completed = await _run_positive(service)
        assert completed.result is CommissioningTestResult.PASSED

        released = await service.priority_stop()
        assert released.state is CommissioningMotionTestState.COMPLETED
        rearmed = await service.arm(_TOKEN, joint_id="j11")
        assert rearmed.state is CommissioningMotionTestState.ARMED
        stopped = await service.stop(_TOKEN)
        assert stopped.state is CommissioningMotionTestState.AUTHORIZED

        replacement = _session(context, clock)
        authorizer.evidence = replacement
        rebound = await service.start_session(_TOKEN)
        assert rebound.state is CommissioningMotionTestState.AUTHORIZED
        assert rebound.session_id == replacement.session_id
        assert ("reset_for_session", replacement.session_id) in bus.events
        await service.shutdown()

    asyncio.run(scenario())


def test_one_armed_joint_and_every_dynamic_envelope_cap_are_backend_enforced() -> None:
    async def scenario() -> None:
        context = _commissioning_context()
        clock = FakeClock()
        envelope = CommissioningSafetyEnvelope(max_commands_per_session=2)
        session = _session(context, clock, envelope=envelope)
        service, bus, _, _ = _service(context=context, clock=clock, session=session)
        await _start_and_arm(service, joint_id="j11")

        with pytest.raises(MultiJointTestForbiddenError):
            await service.run_relative_test(
                _TOKEN,
                joint_id="j12",
                signed_delta=0.5,
                requested_speed=1.0,
                requested_acceleration=2.0,
                command_duration_s=2.0,
                request_id="wrong-joint",
            )
        for changes in (
            {"signed_delta": envelope.max_revolute_delta_deg + 0.01},
            {"requested_speed": envelope.max_revolute_speed_deg_s + 0.01},
            {"requested_acceleration": (envelope.max_revolute_acceleration_deg_s2 + 0.01)},
            {"command_duration_s": envelope.max_command_duration_s + 0.01},
        ):
            request: dict[str, object] = {
                "joint_id": "j11",
                "signed_delta": 0.5,
                "requested_speed": 1.0,
                "requested_acceleration": 2.0,
                "command_duration_s": 2.0,
                "request_id": f"over-cap-{len(bus.events)}",
            }
            request.update(changes)
            with pytest.raises(CommissioningEnvelopeExceededError):
                await service.run_relative_test(_TOKEN, **request)  # type: ignore[arg-type]
        assert not any(event[0] == "write_started" for event in bus.events)

        first = await _run_positive(service, request_id="first")
        assert first.result is CommissioningTestResult.PASSED
        await service.arm(_TOKEN, joint_id="j11")
        second = await service.run_relative_test(
            _TOKEN,
            joint_id="j11",
            signed_delta=-0.5,
            requested_speed=1.0,
            requested_acceleration=2.0,
            command_duration_s=2.0,
            request_id="second",
        )
        assert second.result is CommissioningTestResult.PASSED
        with pytest.raises(CommissioningEnvelopeExceededError):
            await service.arm(_TOKEN, joint_id="j11")
        await service.shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("bus_updates", "failure_reason", "stop_behavior"),
    (
        ({"stale_read_indexes": (1,)}, "READBACK_STALE", StopBehavior.PHYSICAL_BEHAVIOR_PENDING),
        (
            {"direction_inverted_ids": (2,)},
            "DIRECTION_MISMATCH",
            StopBehavior.PHYSICAL_BEHAVIOR_PENDING,
        ),
        (
            {"divergence_raw_by_servo_id": {2: 20}},
            "DIVERGENCE_EXCEEDED",
            StopBehavior.PHYSICAL_BEHAVIOR_PENDING,
        ),
        (
            {"stop_result": RealStopResult.FAILED},
            "PHYSICAL_STOP_NOT_VERIFIED",
            StopBehavior.SOFTWARE_PATH_FAILED,
        ),
    ),
)
def test_stale_direction_divergence_and_stop_faults_persist_failed_evidence(
    bus_updates: dict[str, object],
    failure_reason: str,
    stop_behavior: StopBehavior,
) -> None:
    async def scenario() -> None:
        context = _commissioning_context()
        clock = FakeClock()
        session = _session(context, clock)
        service, bus, repository, _ = _service(
            context=context,
            clock=clock,
            session=session,
            bus_updates=bus_updates,
        )
        await _start_and_arm(service)

        evidence = await _run_positive(service)

        assert evidence.result is CommissioningTestResult.FAILED
        assert evidence.failure_reason_optional == failure_reason
        assert evidence.stop_behavior is stop_behavior
        assert repository.values == {evidence.id: evidence}
        if failure_reason == "READBACK_STALE":
            assert not any(event[0] == "write_started" for event in bus.events)
        status = await service.status()
        assert status.state is CommissioningMotionTestState.FAILED
        await service.shutdown()

    asyncio.run(scenario())


def test_backend_deadman_fences_delayed_write_and_session_expiry_stops_arm() -> None:
    async def scenario() -> None:
        context = _commissioning_context()
        clock = FakeClock()
        session = _session(context, clock)
        service, bus, repository, _ = _service(
            context=context,
            clock=clock,
            session=session,
            bus_updates={"write_delay_s": 1.0},
        )
        await _start_and_arm(service)
        run = asyncio.create_task(_run_positive(service))
        await FakeClock.settle()
        assert bus.write_in_flight is True

        await clock.advance(0.4)
        status = await service.status()
        assert status.state is CommissioningMotionTestState.EXPIRED
        assert status.failure_reason == "DEADMAN_EXPIRED"
        assert bus.positions[2] == 0
        await clock.advance(0.6)
        evidence = await run
        assert evidence.result is CommissioningTestResult.FAILED
        assert evidence.failure_reason_optional == "DEADMAN_EXPIRED"
        assert repository.values == {evidence.id: evidence}
        assert bus.positions[2] == 0
        assert any(event[0] == "write_fenced_by_stop" for event in bus.events)
        await service.shutdown()

        expiry_clock = FakeClock()
        expiring_session = _session(context, expiry_clock, expires_in_s=0.5)
        expiry_service, expiry_bus, _, _ = _service(
            context=context,
            clock=expiry_clock,
            session=expiring_session,
        )
        await _start_and_arm(expiry_service)
        await expiry_clock.advance(0.5)
        expiry_status = await expiry_service.status()
        assert expiry_status.state is CommissioningMotionTestState.EXPIRED
        assert expiry_status.failure_reason == "SESSION_EXPIRED"
        assert any(event[0] == "stop_or_hold" for event in expiry_bus.events)
        await expiry_service.shutdown()

    asyncio.run(scenario())


def test_logical_and_raw_derived_limits_reject_before_any_goal_write() -> None:
    async def scenario() -> None:
        context = _commissioning_context()

        logical_clock = FakeClock()
        logical_session = _session(context, logical_clock)
        assert context.device is not None
        logical_positions = {servo_id: 0 for servo_id in context.device.servo_ids}
        logical_positions[2] = 2048  # j11 is exactly +180 degrees at this synthetic mapping.
        logical_service, logical_bus, logical_repository, _ = _service(
            context=context,
            clock=logical_clock,
            session=logical_session,
            bus_updates={"present_positions": logical_positions},
        )
        await _start_and_arm(logical_service, joint_id="j11")
        logical_evidence = await _run_positive(logical_service, joint_id="j11")
        assert logical_evidence.result is CommissioningTestResult.FAILED
        assert logical_evidence.failure_reason_optional == "COMMISSIONING_ENVELOPE_EXCEEDED"
        assert logical_repository.values == {logical_evidence.id: logical_evidence}
        assert not any(event[0] == "write_started" for event in logical_bus.events)
        await logical_service.shutdown()

        raw_clock = FakeClock()
        raw_session = _session(context, raw_clock)
        raw_positions = {servo_id: 0 for servo_id in context.device.servo_ids}
        raw_positions[1] = 30_700  # j10 remains in bounds, but +0.25 mm does not.
        raw_service, raw_bus, raw_repository, _ = _service(
            context=context,
            clock=raw_clock,
            session=raw_session,
            bus_updates={"present_positions": raw_positions},
        )
        await _start_and_arm(raw_service, joint_id="j10")
        raw_evidence = await raw_service.run_relative_test(
            _TOKEN,
            joint_id="j10",
            signed_delta=0.25,
            requested_speed=0.5,
            requested_acceleration=1.0,
            command_duration_s=2.0,
            request_id="raw-derived-bound",
        )
        assert raw_evidence.result is CommissioningTestResult.FAILED
        assert raw_evidence.failure_reason_optional == "COMMISSIONING_PREFLIGHT_OR_READBACK_FAILED"
        assert raw_repository.values == {raw_evidence.id: raw_evidence}
        assert not any(event[0] == "write_started" for event in raw_bus.events)
        await raw_service.shutdown()

    asyncio.run(scenario())


def test_operator_stop_network_loss_and_envelope_session_duration_all_stop() -> None:
    async def scenario() -> None:
        context = _commissioning_context()

        stop_clock = FakeClock()
        stop_session = _session(context, stop_clock)
        stop_service, stop_bus, _, _ = _service(
            context=context,
            clock=stop_clock,
            session=stop_session,
            bus_updates={"write_delay_s": 1.0},
        )
        await _start_and_arm(stop_service)
        stopped_run = asyncio.create_task(_run_positive(stop_service))
        await FakeClock.settle()
        stopped = await stop_service.stop(_TOKEN)
        assert stopped.state is CommissioningMotionTestState.STOPPING
        await stop_clock.advance(1.0)
        stopped_evidence = await stopped_run
        assert stopped_evidence.failure_reason_optional == "OPERATOR_STOP"
        assert stop_bus.positions[2] == 0
        await stop_service.shutdown()

        priority_clock = FakeClock()
        priority_session = _session(context, priority_clock)
        priority_service, priority_bus, _, _ = _service(
            context=context,
            clock=priority_clock,
            session=priority_session,
            bus_updates={"write_delay_s": 1.0},
        )
        await _start_and_arm(priority_service)
        priority_run = asyncio.create_task(_run_positive(priority_service))
        await FakeClock.settle()
        priority_stopped = await priority_service.priority_stop()
        assert priority_stopped.state is CommissioningMotionTestState.STOPPING
        await priority_clock.advance(1.0)
        priority_evidence = await priority_run
        assert priority_evidence.failure_reason_optional == "OPERATOR_PRIORITY_STOP"
        assert priority_bus.positions[2] == 0
        await priority_service.shutdown()

        network_clock = FakeClock()
        network_session = _session(context, network_clock)
        network_service, network_bus, _, _ = _service(
            context=context,
            clock=network_clock,
            session=network_session,
            bus_updates={"write_delay_s": 1.0},
        )
        await _start_and_arm(network_service)
        network_run = asyncio.create_task(_run_positive(network_service))
        await FakeClock.settle()
        disconnected = await network_service.network_disconnected()
        assert disconnected.state is CommissioningMotionTestState.EXPIRED
        assert disconnected.failure_reason == "NETWORK_DISCONNECTED"
        await network_clock.advance(1.0)
        network_evidence = await network_run
        assert network_evidence.failure_reason_optional == "NETWORK_DISCONNECTED"
        assert network_bus.positions[2] == 0
        await network_service.shutdown()

        duration_clock = FakeClock()
        duration_envelope = CommissioningSafetyEnvelope(max_session_duration_s=30.0)
        duration_session = _session(
            context,
            duration_clock,
            envelope=duration_envelope,
            expires_in_s=60.0,
        )
        duration_service, duration_bus, _, _ = _service(
            context=context,
            clock=duration_clock,
            session=duration_session,
        )
        await _start_and_arm(duration_service)
        await duration_clock.advance(30.0)
        duration_status = await duration_service.status()
        assert duration_status.state is CommissioningMotionTestState.EXPIRED
        assert duration_status.failure_reason == "SESSION_EXPIRED"
        assert any(event[0] == "stop_or_hold" for event in duration_bus.events)
        await duration_service.shutdown()

    asyncio.run(scenario())


def test_heartbeat_extends_only_deadman_and_shutdown_closes_without_late_mutation() -> None:
    async def scenario() -> None:
        context = _commissioning_context()
        clock = FakeClock()
        session = _session(context, clock)
        service, _, _, _ = _service(context=context, clock=clock, session=session)
        await _start_and_arm(service)
        await clock.advance(0.2)
        extended = await service.heartbeat(_TOKEN)
        assert extended.state is CommissioningMotionTestState.ARMED
        await clock.advance(0.3)
        assert (await service.status()).state is CommissioningMotionTestState.ARMED
        await clock.advance(0.101)
        assert (await service.status()).state is CommissioningMotionTestState.EXPIRED
        await service.shutdown()

        shutdown_clock = FakeClock()
        shutdown_session = _session(context, shutdown_clock)
        shutdown_service, shutdown_bus, _, _ = _service(
            context=context,
            clock=shutdown_clock,
            session=shutdown_session,
            bus_updates={"write_delay_s": 1.0},
        )
        await _start_and_arm(shutdown_service)
        run = asyncio.create_task(_run_positive(shutdown_service))
        await FakeClock.settle()
        await shutdown_service.shutdown()
        assert shutdown_bus.connected is False
        await shutdown_clock.advance(1.0)
        evidence = await run
        assert evidence.result is CommissioningTestResult.FAILED
        assert evidence.failure_reason_optional == "BACKEND_SHUTDOWN"
        assert shutdown_bus.positions[2] == 0
        with pytest.raises(CommissioningMotionConflictError):
            await shutdown_service.start_session(_TOKEN)

    asyncio.run(scenario())
