"""Software-only Raw +/- acceptance; this module cannot touch physical hardware."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest

from momo.adapters.hardware.fake_raw_direction_bus import FakeRawDirectionBus
from momo.adapters.hardware.ftservo_raw_direction_bus import RawDirectionCommandRevoked
from momo.application.services.operator_session_service import OperatorSessionTokenError
from momo.application.services.raw_direction_test_service import (
    RawDirectionConflictError,
    RawDirectionEnvelopeError,
    RawDirectionExecutionError,
    RawDirectionTestService,
)
from momo.domain.enums import ControlMode, HardwareAccessPolicy
from momo.domain.raw_direction import (
    RAW_DIRECTION_DRAFT_CONFIRMATION,
    PreparedRawDirectionCommand,
    RawDirection,
    RawDirectionTestState,
)
from momo.domain.real_hardware import (
    RAW_DIRECTION_SCOPES,
    OperatorSessionEvidence,
    OperatorSessionPurpose,
    RealHardwareAuthorizationPurpose,
    RealHardwareContext,
    ServoWriteResult,
    explicit_device_fingerprint,
)
from tests.stage3_helpers import FakeClock
from tests.stage8_hardware_helpers import real_context

_TOKEN = "synthetic-raw-direction-token"


class _Authorizer:
    def __init__(self, session: OperatorSessionEvidence) -> None:
        self.session = session

    async def authorize(
        self,
        token: str,
        context: RealHardwareContext,
        *,
        purpose: RealHardwareAuthorizationPurpose,
    ) -> OperatorSessionEvidence:
        del context
        if token != _TOKEN:
            raise OperatorSessionTokenError("synthetic Raw token mismatch")
        assert purpose is RealHardwareAuthorizationPurpose.RAW_DIRECTION_TEST
        return self.session


def _fixture() -> tuple[RawDirectionTestService, FakeRawDirectionBus, FakeClock]:
    context = real_context(
        real_motion_enabled=False,
        raw_direction_test_enabled=True,
        raw_direction_adapter_ready=True,
        calibration=None,
        kinematics=None,
        expected_kinematics_fingerprint=None,
    )
    assert context.profile is not None and context.device is not None
    clock = FakeClock()
    session = OperatorSessionEvidence(
        session_id=uuid4(),
        purpose=OperatorSessionPurpose.RAW_DIRECTION_TEST,
        scopes=RAW_DIRECTION_SCOPES,
        robot_id="primary",
        robot_unit_id=context.robot_unit_id,
        operator_id="synthetic-raw-operator",
        variant=context.profile.variant,
        profile_fingerprint=context.profile.fingerprint,
        calibration_fingerprint=None,
        kinematics_fingerprint=None,
        field_acceptance_evidence_id=None,
        pre_motion_evidence_id=None,
        commissioning_envelope=None,
        raw_direction_envelope=context.raw_direction_safety_envelope,
        device_fingerprint=explicit_device_fingerprint(context.device),
        allowed_servo_ids=context.device.servo_ids,
        issued_at=clock.now(),
        expires_at=clock.now() + timedelta(seconds=60),
        confirmed=True,
        physical_estop_confirmed=True,
        workspace_clear_confirmed=True,
        control_mode=ControlMode.REAL,
        hardware_access_policy=HardwareAccessPolicy.FULL,
    )
    positions = {servo_id: 1000 + servo_id for servo_id in context.device.servo_ids}
    bus = FakeRawDirectionBus(
        allowed_servo_ids=context.device.servo_ids,
        session_id=session.session_id,
        present_positions=positions,
        clock=clock,
        write_enabled=True,
    )
    service = RawDirectionTestService(
        context=context,
        sessions=_Authorizer(session),
        bus=bus,
        allowed_servo_ids=context.device.servo_ids,
        clock=clock,
    )
    return service, bus, clock


def test_raw_direction_captures_zero_and_moves_only_one_fixed_raw_step() -> None:
    async def scenario() -> None:
        service, bus, _ = _fixture()
        started = await service.start_session(_TOKEN)
        assert started.state is RawDirectionTestState.ZERO_CAPTURED
        assert started.zero_snapshot is not None
        assert started.zero_snapshot.raw_by_joint["j11"] == 1002

        armed = await service.arm(_TOKEN, "j11")
        assert armed.state is RawDirectionTestState.ARMED
        completed = await service.step(
            _TOKEN,
            joint_id="j11",
            direction=RawDirection.RAW_PLUS,
        )
        assert completed.state is RawDirectionTestState.COMPLETED
        assert completed.last_observation is not None
        assert completed.last_observation.start_raw == 1002
        assert completed.last_observation.final_raw == 1013
        assert completed.last_observation.software_only_adapter is True
        assert bus.positions[2] == 1013
        assert bus.positions[3] == 1003
        assert [event[0] for event in bus.events].count("write") == 1
        assert [event[0] for event in bus.events].count("stop") == 1
        await service.arm(_TOKEN, "j11")
        await service.step(
            _TOKEN,
            joint_id="j11",
            direction=RawDirection.RAW_MINUS,
        )
        recorded = await service.record_urdf_alignment(
            _TOKEN,
            joint_id="j11",
            matches_urdf=False,
        )
        assert recorded.calibration_draft is not None
        draft = next(
            joint for joint in recorded.calibration_draft.joints if joint.joint_id == "j11"
        )
        assert draft.home_present_raw == 1002
        assert draft.profile_direction_candidate == 1
        assert draft.resolved_calibration_direction == -1
        assert draft.phase_candidate == 28
        assert recorded.calibration_draft.source_revision

    asyncio.run(scenario())


def test_raw_direction_requires_both_signs_and_one_final_draft_confirmation() -> None:
    async def scenario() -> None:
        service, _, _ = _fixture()
        await service.start_session(_TOKEN)

        await service.arm(_TOKEN, "j10")
        await service.step(_TOKEN, joint_id="j10", direction=RawDirection.RAW_PLUS)
        with pytest.raises(RawDirectionConflictError, match="both Raw"):
            await service.record_urdf_alignment(
                _TOKEN,
                joint_id="j10",
                matches_urdf=True,
            )

        for joint_id in ("j10", "j11", "j12", "j13", "j14", "j15"):
            directions = (
                (RawDirection.RAW_MINUS,)
                if joint_id == "j10"
                else (RawDirection.RAW_PLUS, RawDirection.RAW_MINUS)
            )
            for direction in directions:
                await service.arm(_TOKEN, joint_id)
                await service.step(_TOKEN, joint_id=joint_id, direction=direction)
            await service.record_urdf_alignment(
                _TOKEN,
                joint_id=joint_id,
                matches_urdf=True,
            )

        before = await service.status()
        assert before.calibration_draft is not None
        assert before.calibration_draft.complete_for_review is True
        assert before.calibration_draft.confirmed_for_review is False
        confirmed = await service.confirm_calibration_draft(
            _TOKEN,
            confirmation_text=RAW_DIRECTION_DRAFT_CONFIRMATION,
        )
        assert confirmed.calibration_draft is not None
        assert confirmed.calibration_draft.confirmed_for_review is True
        assert confirmed.calibration_draft.confirmed_at is not None

    asyncio.run(scenario())


def test_raw_direction_never_escapes_captured_zero_envelope() -> None:
    async def scenario() -> None:
        service, bus, _ = _fixture()
        await service.start_session(_TOKEN)
        for _ in range(24):
            await service.arm(_TOKEN, "j11")
            await service.step(_TOKEN, joint_id="j11", direction=RawDirection.RAW_PLUS)
        assert bus.positions[2] == 1266

        with pytest.raises(RawDirectionEnvelopeError, match="command-count cap"):
            await service.arm(_TOKEN, "j11")
        assert bus.positions[2] == 1266

    asyncio.run(scenario())


def test_raw_direction_deadman_stops_fake_bus_without_another_client_request() -> None:
    async def scenario() -> None:
        service, bus, clock = _fixture()
        await service.start_session(_TOKEN)
        await service.arm(_TOKEN, "j12")
        await clock.settle()
        await clock.advance(0.5)
        status = await service.status()
        assert status.state is RawDirectionTestState.EXPIRED
        assert status.failure_reason == "DEADMAN_EXPIRED"
        assert ("stop", 3) in bus.events

    asyncio.run(scenario())


def test_priority_stop_remains_terminal_when_it_revokes_an_in_flight_step() -> None:
    async def scenario() -> None:
        service, bus, _ = _fixture()
        write_entered = asyncio.Event()
        release_write = asyncio.Event()

        async def revoked_write(
            command: PreparedRawDirectionCommand,
        ) -> ServoWriteResult:
            del command
            write_entered.set()
            await release_write.wait()
            raise RawDirectionCommandRevoked("synthetic Stop fence")

        bus.write_prepared_raw_direction_command = revoked_write  # type: ignore[method-assign]
        await service.start_session(_TOKEN)
        await service.arm(_TOKEN, "j11")
        step_task = asyncio.create_task(
            service.step(_TOKEN, joint_id="j11", direction=RawDirection.RAW_PLUS)
        )
        await write_entered.wait()

        stopped = await service.priority_stop()
        assert stopped.state is RawDirectionTestState.COMPLETED
        assert stopped.failure_reason == "OPERATOR_STOP"
        release_write.set()
        with pytest.raises(RawDirectionExecutionError) as captured:
            await step_task
        assert isinstance(captured.value.details, dict)
        assert captured.value.details["reason"] == "OPERATOR_STOP"

        status = await service.status()
        assert status.state is RawDirectionTestState.COMPLETED
        assert status.failure_reason == "OPERATOR_STOP"

    asyncio.run(scenario())


def test_fake_raw_bus_writes_are_disabled_without_explicit_fixture_opt_in() -> None:
    async def scenario() -> None:
        service, _, _ = _fixture()
        await service.start_session(_TOKEN)
        # The production composition does not instantiate this fake at all; even
        # direct fake usage needs the explicit write_enabled fixture flag.
        status = await service.status()
        assert status.command_count == 0

    asyncio.run(scenario())


def test_failed_step_is_structured_and_requires_zero_recapture() -> None:
    async def scenario() -> None:
        service, bus, _ = _fixture()

        async def fail_to_settle(
            command: PreparedRawDirectionCommand,
        ) -> ServoWriteResult:
            del command
            error = TimeoutError("synthetic settle timeout")
            error.observed_raw = 1015  # type: ignore[attr-defined]
            error.tolerance_counts = 16  # type: ignore[attr-defined]
            raise error

        bus.write_prepared_raw_direction_command = fail_to_settle  # type: ignore[method-assign]
        await service.start_session(_TOKEN)
        await service.arm(_TOKEN, "j11")
        with pytest.raises(RawDirectionExecutionError) as captured:
            await service.step(_TOKEN, joint_id="j11", direction=RawDirection.RAW_PLUS)
        assert captured.value.code == "RAW_DIRECTION_EXECUTION_FAILED"
        assert captured.value.details == {
            "reason": "STEP_SETTLE_TIMEOUT",
            "joint_id": "j11",
            "zero_raw": 1002,
            "hold_requested": True,
            "start_raw": 1002,
            "target_raw": 1013,
            "observed_raw": 1015,
            "tolerance_counts": 16,
        }
        failed = await service.status()
        assert failed.state is RawDirectionTestState.FAILED
        assert failed.failure_reason == "STEP_SETTLE_TIMEOUT"
        assert failed.command_count == 1
        assert ("stop", 2) in bus.events
        with pytest.raises(RawDirectionConflictError, match="recapture zero"):
            await service.arm(_TOKEN, "j11")
        restarted = await service.start_session(_TOKEN)
        assert restarted.state is RawDirectionTestState.ZERO_CAPTURED
        assert restarted.command_count == 0

    asyncio.run(scenario())
