"""Focused tests for the narrow commissioning bus and evidence persistence."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from starlette.requests import Request

from momo.adapters.hardware.fake_commissioning_motion_bus import (
    FakeCommissioningMotionBus,
)
from momo.adapters.storage.file_commissioning_evidence_repository import (
    FileCommissioningTestEvidenceRepository,
)
from momo.api.commissioning_schemas import CommissioningRelativeTestRequest
from momo.api.routes.commissioning import run_test
from momo.application.services.commissioning_motion_test_service import (
    CommissioningMotionTestService,
)
from momo.domain.commissioning import (
    CommissioningDirection,
    CommissioningSafetyEnvelope,
    CommissioningTestEvidence,
    CommissioningTestResult,
    PreparedCommissioningTestCommand,
    StopBehavior,
)
from momo.domain.enums import DomainUnit, RobotVariant
from momo.domain.real_hardware import RealStopResult
from momo.ports.commissioning_evidence_repository import (
    CommissioningTestEvidenceRepository,
)
from momo.ports.servo_bus import (
    CommissioningMotionServoBus,
    CommissioningMotionServoBusFacade,
)
from tests.stage3_helpers import FakeClock


def _prepared_command(
    clock: FakeClock,
    session_id: UUID,
    *,
    servo_id: int = 1,
    start_raw: int = 100,
    target_raw: int = 110,
) -> PreparedCommissioningTestCommand:
    return PreparedCommissioningTestCommand(
        session_id=session_id,
        robot_unit_id="unit-v1-001",
        joint_id="j11",
        servo_id=servo_id,
        unit=DomainUnit.DEG,
        start_value=0.0,
        requested_delta=1.0,
        target_value=1.0,
        start_raw=start_raw,
        target_raw=target_raw,
        requested_speed=1.0,
        requested_acceleration=2.0,
        command_duration_s=1.0,
        prepared_at=clock.now(),
        readback_fresh_until=clock.now() + timedelta(seconds=5),
        envelope=CommissioningSafetyEnvelope(),
    )


def _evidence(clock: FakeClock, session_id: UUID) -> CommissioningTestEvidence:
    return CommissioningTestEvidence(
        robot_unit_id="unit-v1-001",
        robot_variant=RobotVariant.V1,
        profile_fingerprint="a" * 64,
        calibration_fingerprint="b" * 64,
        device_fingerprint="c" * 64,
        joint_id="j11",
        unit=DomainUnit.DEG,
        start_value=0.0,
        requested_delta=1.0,
        target_value=1.0,
        final_value=1.0,
        start_raw=100,
        final_raw=110,
        requested_speed=1.0,
        measured_or_observed_result="synthetic readback reached the prepared target",
        direction_expected=CommissioningDirection.POSITIVE,
        direction_observed=CommissioningDirection.POSITIVE,
        divergence=0.0,
        stop_behavior=StopBehavior.PHYSICAL_BEHAVIOR_PENDING,
        started_at=clock.now(),
        completed_at=clock.now() + timedelta(seconds=1),
        software_commit="abcdef1234567",
        operator_id="test-operator",
        request_id="request-001",
        session_id=session_id,
        prepared_target_raw=110,
        prepared_command=_prepared_command(clock, session_id),
        result=CommissioningTestResult.PASSED,
    )


def test_commissioning_bus_surface_is_structurally_narrow() -> None:
    clock = FakeClock()
    session_id = uuid4()
    bus = FakeCommissioningMotionBus(
        allowed_servo_ids=(1,),
        session_id=session_id,
        present_positions={1: 100},
        clock=clock,
    )
    facade = CommissioningMotionServoBusFacade(bus, allowed_servo_ids=(1,))

    assert isinstance(bus, CommissioningMotionServoBus)
    assert isinstance(facade, CommissioningMotionServoBus)
    for forbidden in (
        "open",
        "scan",
        "ping_explicit_ids",
        "read_present_positions",
        "read_register",
        "write_register",
        "write_goal_positions",
        "enable_torque",
        "home",
        "playback",
    ):
        assert not hasattr(facade, forbidden)

    async def scenario() -> None:
        with pytest.raises(PermissionError, match="outside the commissioning allowlist"):
            await facade.read_present_position(2)

    asyncio.run(scenario())


def test_fake_defaults_fail_closed_and_injects_stale_direction_and_divergence() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        session_id = uuid4()
        disabled = FakeCommissioningMotionBus(
            allowed_servo_ids=(1,),
            session_id=session_id,
            present_positions={1: 100},
            clock=clock,
        )
        with pytest.raises(PermissionError, match="writes are disabled"):
            await disabled.write_prepared_command(_prepared_command(clock, session_id))
        assert disabled.positions == {1: 100}

        bus = FakeCommissioningMotionBus(
            allowed_servo_ids=(1,),
            session_id=session_id,
            present_positions={1: 100},
            clock=clock,
            write_enabled=True,
            stale_read_indexes=(1,),
            stale_read_age_s=30.0,
            direction_inverted_ids=(1,),
            divergence_raw_by_servo_id={1: 3},
        )
        stale = await bus.read_present_position(1)
        fresh = await bus.read_present_position(1)
        assert stale.captured_at == clock.now() - timedelta(seconds=30)
        assert fresh.captured_at == clock.now()

        wrong_session = _prepared_command(clock, uuid4())
        with pytest.raises(PermissionError, match="different session"):
            await bus.write_prepared_command(wrong_session)
        assert bus.positions == {1: 100}

        result = await bus.write_prepared_command(_prepared_command(clock, session_id))
        assert result.complete is True
        # Expected +10 raw is inverted to -10, then the configured +3 divergence applies.
        assert bus.positions == {1: 93}

        expired_bus = FakeCommissioningMotionBus(
            allowed_servo_ids=(1,),
            session_id=session_id,
            present_positions={1: 100},
            clock=clock,
            write_enabled=True,
        )
        expired = _prepared_command(clock, session_id)
        await clock.advance(5.0)
        with pytest.raises(PermissionError, match="no longer fresh"):
            await expired_bus.write_prepared_command(expired)
        assert expired_bus.positions == {1: 100}

    asyncio.run(scenario())


def test_stop_fences_delayed_write_and_never_claims_physical_verification() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        session_id = uuid4()
        bus = FakeCommissioningMotionBus(
            allowed_servo_ids=(1,),
            session_id=session_id,
            present_positions={1: 100},
            clock=clock,
            write_enabled=True,
            write_delay_s=1.0,
            stop_result=RealStopResult.HOLD_REQUESTED,
        )
        write_task = asyncio.create_task(
            bus.write_prepared_command(_prepared_command(clock, session_id))
        )
        await FakeClock.settle()
        assert bus.write_in_flight is True

        stopped = await bus.stop_or_hold(1)
        assert stopped.result is RealStopResult.HOLD_REQUESTED
        assert stopped.safety_state_known is False
        assert bus.is_physical_adapter is False
        assert bus.physical_stop_verified is False

        await clock.advance(1.0)
        write_result = await write_task
        assert write_result.complete is False
        assert write_result.safety_state_known is False
        assert bus.positions == {1: 100}
        assert any(event[0] == "write_fenced_by_stop" for event in bus.events)

        await bus.close()
        with pytest.raises(RuntimeError, match="closed"):
            await bus.read_present_position(1)
        after_close = await bus.stop_or_hold(1)
        assert after_close.result is RealStopResult.NOT_CONNECTED

    asyncio.run(scenario())


def test_delayed_write_is_cancellable_without_late_mutation() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        session_id = uuid4()
        bus = FakeCommissioningMotionBus(
            allowed_servo_ids=(1,),
            session_id=session_id,
            present_positions={1: 100},
            clock=clock,
            write_enabled=True,
            write_delay_s=1.0,
        )
        write_task = asyncio.create_task(
            bus.write_prepared_command(_prepared_command(clock, session_id))
        )
        await FakeClock.settle()
        write_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await write_task
        await clock.advance(2.0)
        assert bus.positions == {1: 100}
        assert bus.write_in_flight is False

    asyncio.run(scenario())


def test_fake_rejects_physically_verified_stop_configuration() -> None:
    with pytest.raises(ValueError, match="cannot claim physically verified"):
        FakeCommissioningMotionBus(
            allowed_servo_ids=(1,),
            session_id=uuid4(),
            present_positions={1: 100},
            clock=FakeClock(),
            stop_result=RealStopResult.STOPPED_AND_VERIFIED,
        )


def test_commissioning_evidence_repository_atomic_uuid_roundtrip(tmp_path: Path) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        evidence = _evidence(clock, uuid4())
        directory = tmp_path / "commissioning-evidence"
        repository = FileCommissioningTestEvidenceRepository(directory, clock)
        assert isinstance(repository, CommissioningTestEvidenceRepository)

        await repository.save(evidence)
        expected_path = directory / f"{evidence.id}.json"
        assert expected_path.is_file()
        assert {path.name for path in directory.glob("*.json")} == {expected_path.name}
        assert json.loads(expected_path.read_text(encoding="utf-8"))["id"] == str(evidence.id)

        reloaded = FileCommissioningTestEvidenceRepository(directory, clock)
        assert await reloaded.get(evidence.id) == evidence
        assert await reloaded.get(uuid4()) is None
        assert await reloaded.list_evidence() == (evidence,)

    asyncio.run(scenario())


@pytest.mark.parametrize("command_limit", [24, 120])
def test_commissioning_evidence_accepts_legacy_and_expanded_command_budgets(
    command_limit: int,
) -> None:
    clock = FakeClock()
    evidence = _evidence(clock, uuid4())
    payload = evidence.model_dump(mode="python", round_trip=True)
    payload["prepared_command"]["envelope"]["max_commands_per_session"] = command_limit

    restored = CommissioningTestEvidence.model_validate(payload)

    assert restored.prepared_command is not None
    assert restored.prepared_command.envelope.max_commands_per_session == command_limit
    assert restored.model_dump(mode="python", round_trip=True) == payload


def test_commissioning_route_audit_keeps_evidence_request_id_and_excludes_token() -> None:
    class StubService:
        async def run_relative_test(self, *_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
            return evidence

    async def scenario() -> None:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/device/commissioning/joints/j11/tests/start",
                "headers": [],
            }
        )
        result = await run_test(
            "j11",
            CommissioningRelativeTestRequest(
                signed_delta=1.0,
                requested_speed=1.0,
                requested_acceleration=2.0,
                command_duration_s=1.0,
                request_id="operator-request-001",
            ),
            request,
            cast(CommissioningMotionTestService, StubService()),
            "secret-session-token",
        )

        assert result is evidence
        assert request.state.audit_details["request_id"] == "request-001"
        assert "secret-session-token" not in repr(request.state.audit_details)

    evidence = _evidence(FakeClock(), uuid4())
    asyncio.run(scenario())
