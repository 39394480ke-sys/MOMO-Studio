"""Deterministic Stage 3 Dry Run executor scheduling and cancellation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from momo.adapters.motion.dry_run_motion_executor import DryRunMotionExecutor
from momo.api.app import create_app
from momo.domain.enums import DomainUnit, MotionCommandState
from momo.domain.motion_preflight import PreparedContinuousJog, PreparedMotion
from momo.domain.robot import JointState
from momo.domain.runtime import RuntimeState
from momo.settings import Settings
from tests.stage3_helpers import (
    FakeClock,
    RecordingMotionSink,
    make_preflight,
    make_prepared_motion,
)


async def finish_active(executor: DryRunMotionExecutor, clock: FakeClock) -> None:
    for _ in range(100):
        if executor.active_command_id is None:
            return
        await clock.advance_to_next()
    raise AssertionError("executor did not become idle")


def test_executor_uses_absolute_monotonic_deadlines_without_drift_or_real_sleep() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        sink = RecordingMotionSink(clock, work_s=0.03)
        executor = DryRunMotionExecutor(clock, sink, update_hz=20.0)
        prepared = make_prepared_motion(duration_s=1.0)

        accepted = await executor.submit(prepared)
        assert accepted.state is MotionCommandState.ACCEPTED
        await finish_active(executor, clock)

        status = executor.get_status(prepared.command_id)
        assert status is not None
        assert status.state is MotionCommandState.COMPLETED
        assert status.progress == 1.0
        assert sink.application_times == pytest.approx(
            [index / 20.0 for index in range(1, 21)], abs=1e-9
        )
        assert clock.sleep_calls[0] == pytest.approx(0.05)
        assert clock.sleep_calls[1:] == pytest.approx([0.02] * 19, abs=1e-9)
        assert sink.sequence == 20
        assert sink.states[-1].positions["j11"] == pytest.approx(10.0)
        assert sink.flushes == [prepared.command_id]

    asyncio.run(scenario())


def test_large_fake_clock_jump_never_overshoots_target_or_progress() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        sink = RecordingMotionSink(clock)
        executor = DryRunMotionExecutor(clock, sink, update_hz=20.0)
        prepared = make_prepared_motion(duration_s=1.0, target=5.0)
        await executor.submit(prepared)
        await asyncio.sleep(0)
        await clock.advance(5.0)
        await finish_active(executor, clock)

        assert sink.states
        assert len(sink.states) == 1
        assert all(0.0 <= state.positions["j11"] <= 5.0 for state in sink.states)
        assert sink.states[-1].positions["j11"] == pytest.approx(5.0)
        status = executor.get_status(prepared.command_id)
        assert status is not None
        assert status.progress == 1.0
        assert status.state is MotionCommandState.COMPLETED

    asyncio.run(scenario())


def test_minimum_duration_at_minimum_rate_has_two_distinct_interpolated_updates() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        sink = RecordingMotionSink(clock)
        executor = DryRunMotionExecutor(clock, sink, update_hz=20.0)
        prepared = make_prepared_motion(duration_s=0.1, target=10.0)
        await executor.submit(prepared)
        await finish_active(executor, clock)

        assert [state.positions["j11"] for state in sink.states] == pytest.approx([5.0, 10.0])
        assert sink.application_times == pytest.approx([0.05, 0.1])

    asyncio.run(scenario())


def test_continuous_jog_uses_acceleration_bounded_ramp_and_stops_at_envelope() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        sink = RecordingMotionSink(clock)
        executor = DryRunMotionExecutor(clock, sink, update_hz=20.0)
        base = make_prepared_motion().command_id
        prepared = PreparedContinuousJog(
            command_id=base,
            start_state=JointState(
                positions={"j11": 0.0},
                units={"j11": DomainUnit.DEG},
            ),
            joint_id="j11",
            direction=1,
            speed_units_s=10.0,
            acceleration_units_s2=20.0,
            unit=DomainUnit.DEG,
            minimum=0.0,
            maximum=2.0,
            preflight=make_preflight(base),
        )
        await executor.submit_continuous_jog(prepared)
        await clock.advance_to_next()
        assert sink.states[0].positions["j11"] == pytest.approx(0.025)
        assert sink.states[0].positions["j11"] < 1.0
        await finish_active(executor, clock)

        status = executor.get_status(base)
        assert status is not None
        assert status.state is MotionCommandState.COMPLETED
        assert sink.states[-1].positions["j11"] == pytest.approx(2.0)
        assert all(state.positions["j11"] <= 2.0 for state in sink.states)
        assert sink.application_times == pytest.approx([index / 20.0 for index in range(1, 10)])
        assert sink.flushes == [base]

    asyncio.run(scenario())


def test_cancel_event_wakes_fake_clock_sleep_without_advancing_time() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        sink = RecordingMotionSink(clock)
        executor = DryRunMotionExecutor(clock, sink, update_hz=25.0)
        prepared = make_prepared_motion(duration_s=10.0)
        await executor.submit(prepared)
        await asyncio.sleep(0)

        cancelled = await asyncio.wait_for(executor.cancel_active(), timeout=0.2)
        assert cancelled is not None
        assert cancelled.state is MotionCommandState.CANCELLED
        assert executor.active_command_id is None
        assert sink.states == []
        assert sink.flushes == [prepared.command_id]
        assert clock.monotonic() == 0.0

    asyncio.run(scenario())


def test_sink_exception_faults_command_and_records_only_safe_error_type() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        sink = RecordingMotionSink(clock, fail=True)
        executor = DryRunMotionExecutor(clock, sink, update_hz=20.0)
        prepared = make_prepared_motion(duration_s=0.1)
        await executor.submit(prepared)
        await clock.advance_to_next()
        await finish_active(executor, clock)

        status = executor.get_status(prepared.command_id)
        assert status is not None
        assert status.state is MotionCommandState.FAULTED
        assert status.error == "RuntimeError"
        assert sink.faults == [(prepared.command_id, "RuntimeError")]
        assert executor.active_command_id is None

    asyncio.run(scenario())


def test_injected_clock_exception_faults_command_without_unretrieved_task() -> None:
    class FaultClock(FakeClock):
        async def sleep(self, delay_s: float) -> None:
            del delay_s
            raise RuntimeError("synthetic clock failure")

    async def scenario() -> None:
        clock = FaultClock()
        sink = RecordingMotionSink(clock)
        executor = DryRunMotionExecutor(clock, sink, update_hz=20.0)
        prepared = make_prepared_motion(duration_s=1.0)
        await executor.submit(prepared)
        for _ in range(10):
            if executor.active_command_id is None:
                break
            await asyncio.sleep(0)

        status = executor.get_status(prepared.command_id)
        assert status is not None
        assert status.state is MotionCommandState.FAULTED
        assert status.error == "RuntimeError"
        assert sink.faults == [(prepared.command_id, "RuntimeError")]

    asyncio.run(scenario())


def test_injected_clock_exception_at_executor_start_faults_and_clears_active() -> None:
    class StartFaultClock(FakeClock):
        def monotonic(self) -> float:
            raise RuntimeError("synthetic start failure")

    async def scenario() -> None:
        clock = StartFaultClock()
        sink = RecordingMotionSink(clock)
        executor = DryRunMotionExecutor(clock, sink, update_hz=20.0)
        prepared = make_prepared_motion(duration_s=1.0)
        await executor.submit(prepared)
        await FakeClock.settle()

        status = executor.get_status(prepared.command_id)
        assert status is not None
        assert status.state is MotionCommandState.FAULTED
        assert status.error == "RuntimeError"
        assert sink.faults == [(prepared.command_id, "RuntimeError")]
        assert executor.active_command_id is None

    asyncio.run(scenario())


@pytest.mark.parametrize("update_hz", [0.1, 19.999, 100.001])
def test_executor_rejects_update_rates_that_cannot_guarantee_interpolation(
    update_hz: float,
) -> None:
    clock = FakeClock()
    with pytest.raises(ValueError, match="between 20 and 100"):
        DryRunMotionExecutor(clock, RecordingMotionSink(clock), update_hz=update_hz)


def test_executor_history_is_bounded_and_keeps_latest_terminal_commands() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        sink = RecordingMotionSink(clock)
        executor = DryRunMotionExecutor(clock, sink, update_hz=20.0, history_limit=8)
        command_ids = []
        for _ in range(12):
            prepared = make_prepared_motion(duration_s=0.1)
            command_ids.append(prepared.command_id)
            await executor.submit(prepared)
            await finish_active(executor, clock)

        assert executor.get_status(command_ids[0]) is None
        assert executor.get_status(command_ids[-1]) is not None
        assert len(executor._statuses) == 8

    asyncio.run(scenario())


def test_executor_robot_service_and_runtime_persistence_apply_interpolated_dry_run_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = create_app(
            Settings(
                runtime_state_directory=str(tmp_path / "runtime"),
                calibration_directory=str(tmp_path / "no-calibration"),
            )
        )
        robot = app.state.robot_service
        await robot.connect()
        await robot.drain_runtime_persistence()
        persisted_snapshots: list[RuntimeState] = []
        original_save = robot.runtime_repository.save

        def record_save(snapshot: RuntimeState) -> None:
            persisted_snapshots.append(snapshot)
            original_save(snapshot)

        monkeypatch.setattr(robot.runtime_repository, "save", record_save)
        initial_status, _profile, current = await robot.get_motion_snapshot()
        target_positions = dict(current.positions)
        target_positions["j11"] += 4.0
        target = JointState(positions=target_positions, units=current.units)
        command_id = uuid4()
        prepared = PreparedMotion(
            command_id=command_id,
            start_state=current,
            target_state=target,
            duration_s=0.2,
            preflight=make_preflight(command_id),
        )
        clock = FakeClock()
        executor = DryRunMotionExecutor(clock, robot, update_hz=20.0)
        sequences: list[int] = []
        observed_positions: list[float] = []

        await executor.submit(prepared)
        while executor.active_command_id is not None:
            await clock.advance_to_next()
            status = await robot.get_status()
            if not sequences or status.state_sequence != sequences[-1]:
                sequences.append(status.state_sequence)
                observed_positions.append(status.positions["j11"])

        final_status = await robot.get_status()
        await robot.drain_runtime_persistence()
        persisted = robot.runtime_repository.load(final_status.robot_id)
        command_status = executor.get_status(command_id)

        assert command_status is not None
        assert command_status.state is MotionCommandState.COMPLETED
        assert len(observed_positions) == 4
        assert observed_positions == sorted(observed_positions)
        assert current.positions["j11"] < observed_positions[0] < target_positions["j11"]
        assert observed_positions[-1] == pytest.approx(target_positions["j11"])
        assert sequences == list(
            range(initial_status.state_sequence + 1, initial_status.state_sequence + 5)
        )
        assert final_status.hardware_accessed is False
        assert persisted is not None
        assert persisted.state_sequence == final_status.state_sequence
        assert persisted.positions["j11"] == pytest.approx(target_positions["j11"])
        assert len(persisted_snapshots) == 1

    asyncio.run(scenario())
