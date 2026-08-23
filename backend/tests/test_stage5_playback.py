"""Deterministic Stage 5 playback scheduling, safety, and state-machine tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

import pytest

from momo.application.services.playback_service import PlaybackService
from momo.domain.enums import (
    ControlMode,
    DomainUnit,
    HardwareAccessPolicy,
    RobotVariant,
)
from momo.domain.errors import MotionConflictError, MotionPreflightError
from momo.domain.playback import (
    PlaybackEvent,
    PlaybackExecutionSnapshot,
    PlaybackOperatorIntent,
    PlaybackState,
)
from momo.domain.robot import JointState
from momo.ports.playback import PreparedTrajectoryView
from tests.stage3_helpers import FakeClock


@dataclass(frozen=True, slots=True)
class FakeDigest:
    sha256: str = "d" * 64


@dataclass(frozen=True, slots=True)
class FakeSample:
    time_s: float
    positions: dict[str, float]
    units: dict[str, DomainUnit]
    keyframe_id: UUID
    segment_index: int
    sample_index: int


@dataclass(frozen=True, slots=True)
class FakePlan:
    motion_id: UUID
    motion_revision: int
    robot_variant: RobotVariant
    profile_fingerprint: str
    kinematics_fingerprint: str
    start_state_sequence: int
    sample_rate_hz: float
    duration_s: float
    samples: tuple[FakeSample, ...]
    digest: FakeDigest


@dataclass(frozen=True, slots=True)
class FakePreflight:
    accepted: bool = True


@dataclass(frozen=True, slots=True)
class FakePrepared:
    plan: FakePlan
    preflight: FakePreflight = FakePreflight()


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list[PlaybackEvent] = []

    def publish_playback_event(self, event: PlaybackEvent) -> None:
        self.events.append(event)


class RecordingSink:
    def __init__(
        self,
        clock: FakeClock,
        *,
        work_s: float = 0.0,
        fail_at: int | None = None,
        block_at: int | None = None,
        failure_message: str = "synthetic playback sink failure",
    ) -> None:
        self.clock = clock
        self.work_s = work_s
        self.fail_at = fail_at
        self.block_at = block_at
        self.failure_message = failure_message
        self.blocker = asyncio.Event()
        self.entered_block = asyncio.Event()
        self.states: list[JointState] = []
        self.application_times: list[float] = []
        self.flushes: list[UUID] = []
        self.faults: list[tuple[UUID, str]] = []

    async def apply_motion_state(self, command_id: UUID, state: JointState) -> int:
        del command_id
        next_count = len(self.states) + 1
        if self.block_at == next_count:
            self.entered_block.set()
            await self.blocker.wait()
        if self.fail_at == next_count:
            raise RuntimeError(self.failure_message)
        self.application_times.append(self.clock.monotonic())
        self.states.append(state)
        self.clock.elapse(self.work_s)
        return len(self.states)

    async def flush_motion_state(self, command_id: UUID) -> None:
        self.flushes.append(command_id)

    async def mark_motion_fault(self, command_id: UUID, error: str) -> None:
        self.faults.append((command_id, error))


class FakeValidator:
    def __init__(self) -> None:
        self.overrides: dict[str, object] = {}
        self.block = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    @asynccontextmanager
    async def validate_playback_execution(
        self,
        prepared: PreparedTrajectoryView,
        intent: PlaybackOperatorIntent,
    ) -> AsyncIterator[PlaybackExecutionSnapshot]:
        self.calls += 1
        self.entered.set()
        if self.block:
            await self.release.wait()
        plan = prepared.plan
        values: dict[str, object] = {
            "operator_intent_id": intent.intent_id,
            "motion_id": plan.motion_id,
            "motion_revision": plan.motion_revision,
            "robot_variant": plan.robot_variant,
            "state_sequence": plan.start_state_sequence,
            "profile_fingerprint": plan.profile_fingerprint,
            "kinematics_fingerprint": plan.kinematics_fingerprint,
            "connected": True,
            "stale": False,
            "stop_capable": True,
            "control_mode": ControlMode.DRY_RUN,
            "hardware_access_policy": HardwareAccessPolicy.DISABLED,
            "safety_gateway_validated": True,
            "hardware_accessed": False,
        }
        values.update(self.overrides)
        yield PlaybackExecutionSnapshot.model_validate(values)


def make_prepared(
    *,
    values: tuple[float, ...] = (0.0, 2.5, 5.0, 7.5, 10.0),
    duration_s: float = 1.0,
) -> FakePrepared:
    motion_id = uuid4()
    times = tuple(index * duration_s / (len(values) - 1) for index in range(len(values)))
    samples = tuple(
        FakeSample(
            time_s=time_s,
            positions={"j11": value},
            units={"j11": DomainUnit.DEG},
            keyframe_id=UUID(int=min(index + 1, 2)),
            segment_index=0 if index == 0 else 1,
            sample_index=index,
        )
        for index, (time_s, value) in enumerate(zip(times, values, strict=True))
    )
    return FakePrepared(
        plan=FakePlan(
            motion_id=motion_id,
            motion_revision=3,
            robot_variant=RobotVariant.V2,
            profile_fingerprint="a" * 64,
            kinematics_fingerprint="b" * 64,
            start_state_sequence=17,
            sample_rate_hz=4.0,
            duration_s=duration_s,
            samples=samples,
            digest=FakeDigest(),
        )
    )


def make_intent(prepared: FakePrepared) -> PlaybackOperatorIntent:
    return PlaybackOperatorIntent(
        motion_id=prepared.plan.motion_id,
        motion_revision=prepared.plan.motion_revision,
        trajectory_digest=prepared.plan.digest.sha256,
        confirmed=True,
    )


def make_service(
    *,
    clock: FakeClock | None = None,
    sink: RecordingSink | None = None,
    validator: FakeValidator | None = None,
    observer: RecordingObserver | None = None,
) -> tuple[PlaybackService, FakeClock, RecordingSink, FakeValidator, RecordingObserver]:
    resolved_clock = clock or FakeClock()
    resolved_sink = sink or RecordingSink(resolved_clock)
    resolved_validator = validator or FakeValidator()
    resolved_observer = observer or RecordingObserver()
    return (
        PlaybackService(
            resolved_clock,
            resolved_sink,
            resolved_validator,
            resolved_observer,
        ),
        resolved_clock,
        resolved_sink,
        resolved_validator,
        resolved_observer,
    )


async def settle_until(
    predicate: Callable[[], bool],
    *,
    turns: int = 100,
) -> None:
    for _ in range(turns):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition did not settle")


async def finish_playback(service: PlaybackService, clock: FakeClock) -> None:
    for _ in range(400):
        if service.get_status().state in {
            PlaybackState.COMPLETED,
            PlaybackState.FAULTED,
            PlaybackState.STOPPED,
        }:
            await FakeClock.settle()
            return
        await clock.advance_to_next()
    raise AssertionError("playback did not reach a terminal state")


def test_play_uses_absolute_deadlines_without_drift_and_publishes_states() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        sink = RecordingSink(clock, work_s=0.03)
        service, _, _, _, observer = make_service(clock=clock, sink=sink)
        prepared = make_prepared()

        initial = await service.play(prepared, make_intent(prepared))
        assert initial.state is PlaybackState.PREFLIGHTING
        await finish_playback(service, clock)

        assert sink.application_times == pytest.approx([0.0, 0.25, 0.5, 0.75, 1.0])
        assert clock.sleep_calls == pytest.approx([0.22, 0.22, 0.22, 0.22])
        assert [state.positions["j11"] for state in sink.states] == pytest.approx(
            [0.0, 2.5, 5.0, 7.5, 10.0]
        )
        status = service.get_status()
        assert status.state is PlaybackState.COMPLETED
        assert status.progress == 1.0
        assert status.elapsed_s == 1.0
        assert status.hardware_accessed is False
        published_states = [
            event.status.state for event in observer.events if event.kind.value == "STATE"
        ]
        assert published_states == [
            PlaybackState.PREFLIGHTING,
            PlaybackState.READY,
            PlaybackState.PLAYING,
            PlaybackState.COMPLETED,
        ]
        assert [event.sequence for event in observer.events] == list(
            range(1, len(observer.events) + 1)
        )

    asyncio.run(scenario())


def test_pause_freezes_position_and_resume_has_no_backlog_burst() -> None:
    async def scenario() -> None:
        service, clock, sink, _, _ = make_service()
        prepared = make_prepared()
        await service.play(prepared, make_intent(prepared))
        await settle_until(lambda: len(sink.states) == 1)
        await clock.advance_to_next()
        assert len(sink.states) == 2

        pause_task = asyncio.create_task(service.pause())
        await settle_until(lambda: service.get_status().state is PlaybackState.PAUSED)
        await pause_task
        paused = service.get_status()
        paused_count = len(sink.states)
        paused_value = sink.states[-1].positions["j11"]
        await clock.advance(5.0)
        assert service.get_status().elapsed_s == paused.elapsed_s
        assert len(sink.states) == paused_count
        assert sink.states[-1].positions["j11"] == paused_value

        await service.resume()
        assert service.get_status().state is PlaybackState.PLAYING
        await clock.advance(0.249)
        assert len(sink.states) == paused_count
        await clock.advance(0.001)
        assert len(sink.states) == paused_count + 1
        assert sink.states[-1].positions["j11"] == pytest.approx(5.0)
        await finish_playback(service, clock)

    asyncio.run(scenario())


def test_late_scheduler_skips_overdue_samples_instead_of_bursting() -> None:
    async def scenario() -> None:
        service, clock, sink, _, _ = make_service()
        prepared = make_prepared()
        await service.play(prepared, make_intent(prepared))
        await settle_until(lambda: len(sink.states) == 1)

        await clock.advance(10.0)
        await finish_playback(service, clock)
        assert len(sink.states) == 2
        assert [state.positions["j11"] for state in sink.states] == pytest.approx([0.0, 10.0])
        assert sink.application_times == pytest.approx([0.0, 10.0])
        assert service.get_status().state is PlaybackState.COMPLETED

    asyncio.run(scenario())


def test_rate_change_rebases_time_without_jump_and_rate_is_bounded() -> None:
    async def scenario() -> None:
        service, clock, sink, _, _ = make_service()
        prepared = make_prepared()
        await service.play(prepared, make_intent(prepared))
        await settle_until(lambda: len(sink.states) == 1)
        await clock.advance_to_next()
        assert service.get_status().elapsed_s == pytest.approx(0.25)

        changed = await service.set_rate(2.0)
        assert changed.elapsed_s == pytest.approx(0.25)
        await clock.advance(0.124)
        assert len(sink.states) == 2
        await clock.advance(0.001)
        assert len(sink.states) == 3
        assert sink.application_times[-1] == pytest.approx(0.375)
        await finish_playback(service, clock)

        with pytest.raises(ValueError, match=r"between 0\.25 and 2\.0"):
            await service.set_rate(2.01)

    asyncio.run(scenario())


def test_rate_change_at_an_old_deadline_preserves_current_virtual_time() -> None:
    async def scenario() -> None:
        service, clock, sink, _, _ = make_service()
        prepared = make_prepared()
        await service.play(prepared, make_intent(prepared))
        await settle_until(lambda: len(sink.states) == 1 and clock.waiter_count == 1)

        clock.elapse(0.25)
        await service.set_rate(0.25)
        await FakeClock.settle()
        assert len(sink.states) == 2
        assert service.get_status().elapsed_s == pytest.approx(0.25)
        assert sink.application_times[-1] == pytest.approx(0.25)
        await service.stop()

    asyncio.run(scenario())


def test_repeated_rate_changes_preserve_integrated_time_without_drift() -> None:
    async def scenario() -> None:
        service, clock, sink, _, _ = make_service()
        prepared = make_prepared()
        await service.play(prepared, make_intent(prepared))
        await settle_until(lambda: len(sink.states) == 1 and clock.waiter_count == 1)

        await clock.advance(0.10)
        await service.set_rate(2.0)
        await FakeClock.settle()
        await clock.advance(0.04)
        assert len(sink.states) == 1

        await service.set_rate(0.5)
        await FakeClock.settle()
        await clock.advance(0.13)
        assert len(sink.states) == 1

        await service.set_rate(2.0)
        await FakeClock.settle()
        await clock.advance(0.0024)
        assert len(sink.states) == 1
        await clock.advance(0.0001)
        assert len(sink.states) == 2
        assert sink.application_times[-1] == pytest.approx(0.2725)
        assert service.get_status().elapsed_s == pytest.approx(0.25)
        await service.stop()

    asyncio.run(scenario())


def test_closed_loop_is_bounded_and_discontinuous_loop_is_rejected() -> None:
    async def scenario() -> None:
        service, clock, sink, _, _ = make_service()
        closed = make_prepared(values=(0.0, 5.0, 0.0))
        await service.play(closed, make_intent(closed), loop=True, loop_count=3)
        await finish_playback(service, clock)
        status = service.get_status()
        assert status.state is PlaybackState.COMPLETED
        assert status.completed_loops == 3
        assert len(sink.states) == 7
        assert [state.positions["j11"] for state in sink.states] == pytest.approx(
            [0.0, 5.0, 0.0, 5.0, 0.0, 5.0, 0.0]
        )

        other, _, _, _, _ = make_service()
        discontinuous = make_prepared()
        with pytest.raises(MotionPreflightError) as captured:
            await other.play(
                discontinuous,
                make_intent(discontinuous),
                loop=True,
                loop_count=2,
            )
        assert captured.value.details == {"reason": "DISCONTINUOUS_LOOP"}

    asyncio.run(scenario())


def test_loop_can_be_disabled_and_active_loop_can_be_stopped() -> None:
    async def scenario() -> None:
        service, clock, sink, _, _ = make_service()
        prepared = make_prepared(values=(0.0, 5.0, 0.0))
        await service.play(prepared, make_intent(prepared), loop=True, loop_count=100)
        await settle_until(lambda: len(sink.states) == 1)
        await clock.advance_to_next()
        await service.set_loop(False)
        await finish_playback(service, clock)
        assert service.get_status().completed_loops == 1

        service2, _, sink2, _, _ = make_service()
        await service2.play(prepared, make_intent(prepared), loop=True, loop_count=100)
        await settle_until(lambda: len(sink2.states) == 1)
        stopped = await service2.stop()
        assert stopped.state is PlaybackState.STOPPED
        assert len(sink2.states) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("field", "replacement", "reason"),
    [
        ("state_sequence", 18, "STATE_SEQUENCE_CHANGED"),
        ("profile_fingerprint", "c" * 64, "PROFILE_FINGERPRINT_CHANGED"),
        ("kinematics_fingerprint", "c" * 64, "KINEMATICS_FINGERPRINT_CHANGED"),
        ("robot_variant", RobotVariant.V1, "ROBOT_VARIANT_CHANGED"),
        ("motion_revision", 4, "MOTION_REVISION_CHANGED"),
    ],
)
def test_fresh_execution_validation_rejects_changed_preflight_inputs(
    field: str,
    replacement: object,
    reason: str,
) -> None:
    async def scenario() -> None:
        validator = FakeValidator()
        validator.overrides[field] = replacement
        service, clock, sink, _, _ = make_service(validator=validator)
        prepared = make_prepared()
        await service.play(prepared, make_intent(prepared))
        await finish_playback(service, clock)

        assert service.get_status().state is PlaybackState.FAULTED
        assert service.get_status().error == f"Playback safety validation failed ({reason})"
        assert sink.states == []
        assert sink.faults == []

    asyncio.run(scenario())


def test_sink_fault_is_terminal_and_reports_bounded_reason() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        sink = RecordingSink(clock, fail_at=2)
        service, _, _, _, _ = make_service(clock=clock, sink=sink)
        prepared = make_prepared()
        await service.play(prepared, make_intent(prepared))
        await finish_playback(service, clock)

        status = service.get_status()
        assert status.state is PlaybackState.FAULTED
        assert status.error == "Playback execution failed (PLAYBACK_RUNTIME_FAULT)"
        assert len(sink.states) == 1
        assert sink.faults == [(status.session_id, status.error)]

    asyncio.run(scenario())


def test_runtime_fault_does_not_publish_exception_text_paths_or_secrets() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        sensitive = (
            "Traceback (most recent call last): /Users/operator/private.py api_key=sk-stage5-secret"
        )
        sink = RecordingSink(clock, fail_at=1, failure_message=sensitive)
        observer = RecordingObserver()
        service, _, _, _, _ = make_service(clock=clock, sink=sink, observer=observer)
        prepared = make_prepared()
        await service.play(prepared, make_intent(prepared))
        await finish_playback(service, clock)

        public_reason = "Playback execution failed (PLAYBACK_RUNTIME_FAULT)"
        status = service.get_status()
        assert status.state is PlaybackState.FAULTED
        assert status.error == public_reason
        assert sink.faults == [(status.session_id, public_reason)]
        assert observer.events[-1].status.error == public_reason
        serialized = " ".join(event.model_dump_json() for event in observer.events)
        assert "Traceback" not in serialized
        assert "/Users/operator" not in serialized
        assert "sk-stage5-secret" not in serialized

    asyncio.run(scenario())


def test_validation_fault_only_publishes_allowlisted_codes() -> None:
    async def scenario() -> None:
        sensitive = "Traceback /private/validator.py token=STAGE5_SUPER_SECRET"

        class SensitiveValidator(FakeValidator):
            @asynccontextmanager
            async def validate_playback_execution(
                self,
                prepared: PreparedTrajectoryView,
                intent: PlaybackOperatorIntent,
            ) -> AsyncIterator[PlaybackExecutionSnapshot]:
                del prepared, intent
                raise MotionPreflightError(
                    sensitive,
                    details={"reason": "STAGE5_SUPER_SECRET"},
                )
                yield PlaybackExecutionSnapshot.model_construct()  # pragma: no cover

        validator = SensitiveValidator()
        service, clock, _, _, observer = make_service(validator=validator)
        prepared = make_prepared()
        await service.play(prepared, make_intent(prepared))
        await finish_playback(service, clock)

        public_reason = "Playback safety validation failed (PLAYBACK_VALIDATION_FAILED)"
        assert service.get_status().error == public_reason
        assert observer.events[-1].status.error == public_reason
        serialized = " ".join(event.model_dump_json() for event in observer.events)
        assert "Traceback" not in serialized
        assert "/private/validator.py" not in serialized
        assert "STAGE5_SUPER_SECRET" not in serialized

    asyncio.run(scenario())


def test_stop_cancels_blocked_validation_and_concurrent_play_is_rejected() -> None:
    async def scenario() -> None:
        validator = FakeValidator()
        validator.block = True
        service, _, sink, _, observer = make_service(validator=validator)
        first = make_prepared()
        await service.play(first, make_intent(first))
        await validator.entered.wait()

        second = make_prepared()
        with pytest.raises(MotionConflictError, match="active"):
            await service.play(second, make_intent(second))
        stopped = await service.stop()
        assert stopped.state is PlaybackState.STOPPED
        assert sink.states == []
        assert observer.events[-2].status.state is PlaybackState.STOPPING
        assert observer.events[-1].status.state is PlaybackState.STOPPED

    asyncio.run(scenario())


def test_stop_cancels_in_flight_state_application_with_highest_priority() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        sink = RecordingSink(clock, block_at=1)
        service, _, _, _, _ = make_service(clock=clock, sink=sink)
        prepared = make_prepared()
        await service.play(prepared, make_intent(prepared))
        await sink.entered_block.wait()

        stopped = await service.stop()
        assert stopped.state is PlaybackState.STOPPED
        assert sink.states == []
        assert clock.value == 0.0

    asyncio.run(scenario())


def test_cancelled_stop_caller_cannot_strand_stopping_or_motion_ownership() -> None:
    async def scenario() -> None:
        class BlockingFlushSink(RecordingSink):
            def __init__(self, clock: FakeClock) -> None:
                super().__init__(clock)
                self.flush_entered = asyncio.Event()
                self.release_flush = asyncio.Event()

            async def flush_motion_state(self, command_id: UUID) -> None:
                self.flushes.append(command_id)
                self.flush_entered.set()
                await self.release_flush.wait()

        clock = FakeClock()
        sink = BlockingFlushSink(clock)
        validator = FakeValidator()
        validator.block = True
        service, _, _, _, _ = make_service(
            clock=clock,
            sink=sink,
            validator=validator,
        )
        prepared = make_prepared()
        await service.play(prepared, make_intent(prepared))
        await validator.entered.wait()

        first_stop = asyncio.create_task(service.stop())
        await sink.flush_entered.wait()
        first_stop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first_stop

        assert service.get_status().state is PlaybackState.STOPPING
        assert service.motion_active is True
        second_stop = asyncio.create_task(service.stop())
        await asyncio.sleep(0)
        assert second_stop.done() is False

        sink.release_flush.set()
        stopped = await second_stop
        assert stopped.state is PlaybackState.STOPPED
        assert service.motion_active is False
        assert service._stop_completion_task is None

    asyncio.run(scenario())


def test_ready_hook_requires_exact_prepared_object_at_play_time() -> None:
    async def scenario() -> None:
        service, _, _, _, observer = make_service()
        prepared = make_prepared()
        ready = await service.set_ready(prepared)
        assert ready.state is PlaybackState.READY
        assert ready.session_id is None
        assert observer.events[-1].status.state is PlaybackState.READY

        structurally_equal = replace(prepared)
        with pytest.raises(MotionConflictError) as captured:
            await service.play(structurally_equal, make_intent(structurally_equal))
        assert captured.value.details == {"reason": "PREPARED_TRAJECTORY_IDENTITY_CHANGED"}

        started = await service.play(prepared, make_intent(prepared))
        assert started.state is PlaybackState.PREFLIGHTING
        await service.stop()

    asyncio.run(scenario())


def test_stop_from_ready_invalidates_that_preflight_binding() -> None:
    async def scenario() -> None:
        service, _, _, _, _ = make_service()
        prepared = make_prepared()
        await service.set_ready(prepared)
        stopped = await service.stop()
        assert stopped.state is PlaybackState.STOPPED
        assert stopped.error == "Prepared trajectory cancelled by Stop"
        with pytest.raises(MotionConflictError) as captured:
            await service.play(prepared, make_intent(prepared))
        assert captured.value.details == {"reason": "PREFLIGHT_CANCELLED"}
        assert (await service.clear_ready()).state is PlaybackState.IDLE

    asyncio.run(scenario())


def test_preflight_orchestration_clears_old_ready_and_is_observable() -> None:
    async def scenario() -> None:
        service, _, _, _, observer = make_service()
        prepared = make_prepared()
        await service.set_ready(prepared)
        assert service.motion_active is False

        cleared = await service.clear_ready()
        assert cleared.state is PlaybackState.IDLE
        assert service.motion_active is False
        pending = await service.begin_preflight(
            prepared.plan.motion_id,
            prepared.plan.motion_revision,
        )
        assert pending.state is PlaybackState.PREFLIGHTING
        assert service.motion_active is True
        failed = await service.preflight_failed("synthetic rejected\nunsafe detail")
        assert failed.state is PlaybackState.FAULTED
        assert failed.error == "synthetic rejected unsafe detail"
        assert service.motion_active is False
        assert [event.status.state for event in observer.events[-3:]] == [
            PlaybackState.IDLE,
            PlaybackState.PREFLIGHTING,
            PlaybackState.FAULTED,
        ]

        await service.begin_preflight(prepared.plan.motion_id, prepared.plan.motion_revision)
        ready = await service.set_ready(prepared)
        assert ready.state is PlaybackState.READY
        assert service.motion_active is False

        await service.clear_ready()
        await service.begin_preflight(prepared.plan.motion_id, prepared.plan.motion_revision)
        different = make_prepared()
        with pytest.raises(MotionConflictError) as captured:
            await service.set_ready(different)
        assert captured.value.details == {"reason": "PREFLIGHT_RESULT_MISMATCH"}
        await service.clear_ready()

        await service.begin_preflight(prepared.plan.motion_id, prepared.plan.motion_revision)
        stopped = await service.cancel_preflight("operator Stop")
        assert stopped.state is PlaybackState.STOPPED
        assert stopped.error == "operator Stop"
        assert service.motion_active is False
        assert await service.preflight_failed() == stopped
        with pytest.raises(MotionConflictError) as cancelled:
            await service.set_ready(prepared)
        assert cancelled.value.details == {"reason": "PREFLIGHT_CANCELLED"}
        await service.clear_ready()

        await service.begin_preflight(prepared.plan.motion_id, prepared.plan.motion_revision)
        stopped_by_general_stop = await service.stop()
        assert stopped_by_general_stop.state is PlaybackState.STOPPED
        assert service.motion_active is False

    asyncio.run(scenario())


def test_operator_intent_must_match_digest_revision_and_motion() -> None:
    async def scenario() -> None:
        service, _, _, _, _ = make_service()
        prepared = make_prepared()
        wrong = make_intent(prepared).model_copy(update={"trajectory_digest": "e" * 64})
        with pytest.raises(MotionPreflightError) as captured:
            await service.play(prepared, wrong)
        assert captured.value.details == {"reason": "OPERATOR_INTENT_MISMATCH"}

    asyncio.run(scenario())
