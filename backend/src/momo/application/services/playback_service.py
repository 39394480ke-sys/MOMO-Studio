"""Bounded, drift-resistant execution of one immutable prepared trajectory."""

from __future__ import annotations

import asyncio
from bisect import bisect_right
from contextlib import suppress
from math import isclose, isfinite
from uuid import UUID, uuid4

from momo.domain.enums import ControlMode, HardwareAccessPolicy
from momo.domain.errors import MotionConflictError, MotionPreflightError
from momo.domain.playback import (
    MAX_PLAYBACK_LOOPS,
    MAX_PLAYBACK_RATE,
    MIN_PLAYBACK_RATE,
    PlaybackEvent,
    PlaybackEventKind,
    PlaybackExecutionSnapshot,
    PlaybackOperatorIntent,
    PlaybackState,
    PlaybackStatus,
)
from momo.domain.real_motion import RealExecutionAuthorization
from momo.domain.robot import JointState
from momo.ports.clock import Clock
from momo.ports.playback import (
    PlaybackExecutionValidator,
    PlaybackObserver,
    PlaybackStateSink,
    PreparedTrajectoryView,
    TrajectoryPlanView,
    TrajectorySampleView,
)

_ACTIVE_STATES = frozenset(
    {
        PlaybackState.PREFLIGHTING,
        PlaybackState.PLAYING,
        PlaybackState.PAUSED,
        PlaybackState.STOPPING,
    }
)
_TERMINAL_STATES = frozenset(
    {PlaybackState.STOPPED, PlaybackState.COMPLETED, PlaybackState.FAULTED}
)
_TIME_TOLERANCE_S = 1e-9
_POSITION_TOLERANCE = 1e-9
_MAX_TRAJECTORY_DURATION_S = 600.0
_MAX_TRAJECTORY_SAMPLES = 20_000
_PUBLIC_VALIDATION_FAULT_CODES = frozenset(
    {
        "CONTROL_MODE_CHANGED",
        "HARDWARE_POLICY_CHANGED",
        "KINEMATICS_CHANGED",
        "KINEMATICS_FINGERPRINT_CHANGED",
        "MOTION_COMMAND_ACTIVE",
        "MOTION_ID_CHANGED",
        "MOTION_REVISION_CHANGED",
        "OPERATOR_INTENT_CHANGED",
        "OPERATOR_INTENT_MISMATCH",
        "PREFLIGHT_NOT_ACCEPTED",
        "PROFILE_CHANGED",
        "PROFILE_FINGERPRINT_CHANGED",
        "REAL_ARTIFACTS_CHANGED",
        "ROBOT_NOT_CONNECTED",
        "ROBOT_STATE_STALE",
        "ROBOT_VARIANT_CHANGED",
        "START_STATE_CHANGED",
        "STATE_SEQUENCE_CHANGED",
        "STOP_CAPABILITY_UNAVAILABLE",
        "UNSAFE_EXECUTION_CONTEXT",
        "VARIANT_CHANGED",
    }
)


class PlaybackService:
    """Execute canonical samples only after explicit, fresh gateway validation.

    The service has no hardware port and cannot compile or alter trajectories. The
    injected state sink accepts canonical domain-unit joint states, while the
    validator is responsible for invoking the reviewed motion safety entry point.
    """

    def __init__(
        self,
        clock: Clock,
        state_sink: PlaybackStateSink,
        validator: PlaybackExecutionValidator,
        observer: PlaybackObserver,
    ) -> None:
        self.clock = clock
        self.state_sink = state_sink
        self.validator = validator
        self.observer = observer
        self._guard = asyncio.Lock()
        self._status = PlaybackStatus(updated_at=self.clock.now())
        self._event_sequence = 0
        self._active_task: asyncio.Task[None] | None = None
        self._stop_completion_task: asyncio.Task[PlaybackStatus] | None = None
        self._control_event: asyncio.Event | None = None
        self._stop_requested = False
        self._pause_requested = False
        self._pause_ack: asyncio.Event | None = None
        self._anchor_monotonic = 0.0
        self._anchor_elapsed_s = 0.0
        self._ready_prepared: PreparedTrajectoryView | None = None
        self._preflight_only = False
        self._cancelled_preflight: tuple[UUID, int] | None = None

    def get_status(self) -> PlaybackStatus:
        return self._status

    @property
    def motion_active(self) -> bool:
        """Whether playback currently owns the process-wide motion slot."""

        return self._status.state in _ACTIVE_STATES

    async def begin_preflight(self, motion_id: UUID, motion_revision: int) -> PlaybackStatus:
        """Publish orchestration-owned compilation/preflight work without a runner."""

        if (
            isinstance(motion_revision, bool)
            or not isinstance(motion_revision, int)
            or motion_revision < 1
        ):
            raise ValueError("motion_revision must be a positive integer")
        async with self._guard:
            self._reject_if_active()
            self._ready_prepared = None
            self._preflight_only = True
            self._cancelled_preflight = None
            self._status = PlaybackStatus(
                state=PlaybackState.PREFLIGHTING,
                motion_id=motion_id,
                motion_revision=motion_revision,
                updated_at=self.clock.now(),
            )
            self._emit_locked(PlaybackEventKind.STATE)
            return self._status

    async def preflight_failed(
        self, reason: str = "Trajectory preflight rejected"
    ) -> PlaybackStatus:
        """Close an orchestration preflight without retaining an older READY plan."""

        safe_reason = reason.strip().replace("\n", " ")[:240] or "Trajectory preflight rejected"
        async with self._guard:
            if (
                self._status.state is PlaybackState.STOPPED
                and self._cancelled_preflight is not None
            ):
                return self._status
            if not self._preflight_only or self._active_task is not None:
                raise self._transition_error("fail preflight")
            now = self.clock.now()
            self._ready_prepared = None
            self._preflight_only = False
            self._cancelled_preflight = None
            self._status = self._status.model_copy(
                update={
                    "state": PlaybackState.FAULTED,
                    "error": safe_reason,
                    "updated_at": now,
                    "finished_at": now,
                }
            )
            self._emit_locked(PlaybackEventKind.STATE)
            return self._status

    async def clear_ready(self) -> PlaybackStatus:
        """Drop cached preflight state before compiling a replacement plan."""

        async with self._guard:
            task = self._active_task
            if task is not None and not task.done():
                raise MotionConflictError("Cannot clear READY while playback is active")
            self._ready_prepared = None
            self._preflight_only = False
            self._cancelled_preflight = None
            self._status = PlaybackStatus(updated_at=self.clock.now())
            self._emit_locked(PlaybackEventKind.STATE)
            return self._status

    async def set_ready(self, prepared: PreparedTrajectoryView) -> PlaybackStatus:
        """Publish a completed preflight without starting a playback task.

        Orchestration may call this after ``POST /motions/{id}/preflight``. A
        later ``play`` call still performs fresh execution-time validation and
        consumes this exact prepared object rather than compiling again.
        """

        self._validate_prepared_shape(prepared)
        async with self._guard:
            if not self._preflight_only:
                self._reject_if_active()
            elif self._active_task is not None:
                raise MotionConflictError("Playback execution became active during preflight")
            plan = prepared.plan
            if self._cancelled_preflight == (plan.motion_id, plan.motion_revision):
                raise MotionConflictError(
                    "Trajectory preflight was cancelled by Stop",
                    details={"reason": "PREFLIGHT_CANCELLED"},
                )
            if self._preflight_only and (
                self._status.motion_id != plan.motion_id
                or self._status.motion_revision != plan.motion_revision
            ):
                raise MotionConflictError(
                    "Completed preflight does not match the pending Motion revision",
                    details={"reason": "PREFLIGHT_RESULT_MISMATCH"},
                )
            self._ready_prepared = prepared
            self._preflight_only = False
            self._cancelled_preflight = None
            self._status = PlaybackStatus(
                state=PlaybackState.READY,
                motion_id=plan.motion_id,
                motion_revision=plan.motion_revision,
                trajectory_digest=plan.digest.sha256,
                duration_s=plan.duration_s,
                updated_at=self.clock.now(),
            )
            self._emit_locked(PlaybackEventKind.STATE)
            return self._status

    async def play(
        self,
        prepared: PreparedTrajectoryView,
        intent: PlaybackOperatorIntent,
        *,
        rate: float = 1.0,
        loop: bool = False,
        loop_count: int = 2,
        authorization: RealExecutionAuthorization | None = None,
    ) -> PlaybackStatus:
        """Start one task for an already-preflighted immutable trajectory."""

        if authorization is not None:
            raise ValueError("DRY_RUN playback cannot accept a REAL authorization")

        resolved_rate = self._validate_rate(rate)
        resolved_loop_count = self._validate_loop(loop, loop_count)
        self._validate_prepared_shape(prepared)
        self._validate_intent(prepared, intent)
        if loop:
            self._require_closed_loop(prepared.plan)

        async with self._guard:
            self._reject_if_active()
            if self._cancelled_preflight == (
                prepared.plan.motion_id,
                prepared.plan.motion_revision,
            ):
                raise MotionConflictError(
                    "Trajectory preflight was cancelled by Stop",
                    details={"reason": "PREFLIGHT_CANCELLED"},
                )
            if self._ready_prepared is not None and self._ready_prepared is not prepared:
                raise MotionConflictError(
                    "Playback must use the exact PreparedTrajectory stored by preflight",
                    details={"reason": "PREPARED_TRAJECTORY_IDENTITY_CHANGED"},
                )
            self._ready_prepared = prepared
            self._preflight_only = False
            session_id = uuid4()
            self._control_event = asyncio.Event()
            self._stop_requested = False
            self._pause_requested = False
            self._pause_ack = None
            self._anchor_elapsed_s = 0.0
            self._anchor_monotonic = self.clock.monotonic()
            self._status = PlaybackStatus(
                session_id=session_id,
                state=PlaybackState.PREFLIGHTING,
                motion_id=prepared.plan.motion_id,
                motion_revision=prepared.plan.motion_revision,
                trajectory_digest=prepared.plan.digest.sha256,
                duration_s=prepared.plan.duration_s,
                loop=loop,
                loop_count=resolved_loop_count,
                rate=resolved_rate,
                operator_intent_id=intent.intent_id,
                updated_at=self.clock.now(),
            )
            self._emit_locked(PlaybackEventKind.STATE)
            task = asyncio.create_task(
                self._run_session(session_id, prepared, intent),
                name=f"dry-run-playback-{session_id}",
            )
            self._active_task = task
            return self._status

    async def pause(self) -> PlaybackStatus:
        """Pause at a sample boundary and return only after the position is frozen."""

        async with self._guard:
            if self._status.state is not PlaybackState.PLAYING:
                raise self._transition_error("pause")
            if self._pause_requested:
                raise MotionConflictError("Playback pause is already pending")
            self._pause_requested = True
            ack = asyncio.Event()
            self._pause_ack = ack
            self._wake_runner_locked()
        await ack.wait()
        return self._status

    async def resume(self) -> PlaybackStatus:
        async with self._guard:
            if self._status.state is not PlaybackState.PAUSED:
                raise self._transition_error("resume")
            self._pause_requested = False
            self._anchor_elapsed_s = self._status.elapsed_s
            self._anchor_monotonic = self.clock.monotonic()
            self._status = self._status.model_copy(
                update={
                    "state": PlaybackState.PLAYING,
                    "updated_at": self.clock.now(),
                }
            )
            self._emit_locked(PlaybackEventKind.STATE)
            self._wake_runner_locked()
            return self._status

    async def stop(self) -> PlaybackStatus:
        """Highest-priority task cancellation, including preflight and paused waits."""

        async with self._guard:
            completion = self._stop_completion_task
            if completion is not None and not completion.done():
                pass
            else:
                completion = None
            task = self._active_task
            session_id = self._status.session_id
            if completion is None:
                if task is None and self._preflight_only and session_id is None:
                    return self._cancel_preflight_locked("Trajectory preflight cancelled by Stop")
                if task is None and self._status.state is PlaybackState.READY:
                    return self._cancel_ready_locked("Prepared trajectory cancelled by Stop")
                if task is None or session_id is None or self._status.state in _TERMINAL_STATES:
                    return self._status
                self._stop_requested = True
                self._status = self._status.model_copy(
                    update={
                        "state": PlaybackState.STOPPING,
                        "updated_at": self.clock.now(),
                    }
                )
                self._emit_locked(PlaybackEventKind.STATE)
                self._wake_runner_locked()
                self._release_pause_waiter_locked()
                task.cancel()
                completion = asyncio.create_task(
                    self._complete_stop(task, session_id),
                    name=f"dry-run-playback-stop-{session_id}",
                )
                self._stop_completion_task = completion

        # Caller cancellation must not cancel the one cleanup owner. A later Stop
        # joins the same task instead of returning a permanently stranded STOPPING.
        return await asyncio.shield(completion)

    async def _complete_stop(
        self,
        task: asyncio.Task[None],
        session_id: UUID,
    ) -> PlaybackStatus:
        """Finish one Stop exactly once, independently of the initiating caller."""

        await asyncio.gather(task, return_exceptions=True)
        with suppress(Exception, asyncio.CancelledError):
            await self.state_sink.flush_motion_state(session_id)
        async with self._guard:
            if (
                self._status.session_id == session_id
                and self._status.state is PlaybackState.STOPPING
            ):
                now = self.clock.now()
                self._status = self._status.model_copy(
                    update={
                        "state": PlaybackState.STOPPED,
                        "updated_at": now,
                        "finished_at": now,
                    }
                )
                self._emit_locked(PlaybackEventKind.STATE)
            if self._active_task is task:
                self._active_task = None
            self._ready_prepared = None
            if self._stop_completion_task is asyncio.current_task():
                self._stop_completion_task = None
            return self._status

    async def cancel_preflight(
        self,
        reason: str = "Trajectory preflight cancelled",
    ) -> PlaybackStatus:
        """Cancel orchestration-owned PREFLIGHTING and release motion ownership."""

        async with self._guard:
            if (
                self._status.state is PlaybackState.STOPPED
                and self._cancelled_preflight is not None
            ):
                return self._status
            if not self._preflight_only or self._active_task is not None:
                raise self._transition_error("cancel preflight")
            return self._cancel_preflight_locked(reason)

    async def set_rate(self, rate: float) -> PlaybackStatus:
        """Rebase the virtual timeline so rate changes are time-continuous."""

        resolved = self._validate_rate(rate)
        async with self._guard:
            if self._status.state not in {
                PlaybackState.READY,
                PlaybackState.PLAYING,
                PlaybackState.PAUSED,
            }:
                raise self._transition_error("change rate")
            if self._status.state is PlaybackState.PLAYING:
                now_monotonic = self.clock.monotonic()
                self._anchor_elapsed_s = min(
                    self._status.duration_s,
                    self._anchor_elapsed_s
                    + max(0.0, now_monotonic - self._anchor_monotonic) * self._status.rate,
                )
                self._anchor_monotonic = now_monotonic
            self._status = self._status.model_copy(
                update={"rate": resolved, "updated_at": self.clock.now()}
            )
            self._emit_locked(PlaybackEventKind.STATE)
            self._wake_runner_locked()
            return self._status

    async def set_loop(
        self,
        enabled: bool,
        *,
        loop_count: int = 2,
    ) -> PlaybackStatus:
        resolved_loop_count = self._validate_loop(enabled, loop_count)
        async with self._guard:
            if self._status.state not in {
                PlaybackState.READY,
                PlaybackState.PLAYING,
                PlaybackState.PAUSED,
            }:
                raise self._transition_error("change loop")
            prepared = self._ready_prepared
            if enabled and prepared is not None:
                self._require_closed_loop(prepared.plan)
            self._status = self._status.model_copy(
                update={
                    "loop": enabled,
                    "loop_count": resolved_loop_count,
                    "updated_at": self.clock.now(),
                }
            )
            self._emit_locked(PlaybackEventKind.STATE)
            self._wake_runner_locked()
            return self._status

    async def shutdown(self) -> None:
        await self.stop()

    async def _run_session(
        self,
        session_id: UUID,
        prepared: PreparedTrajectoryView,
        intent: PlaybackOperatorIntent,
    ) -> None:
        execution_started = False
        try:
            async with self.validator.validate_playback_execution(prepared, intent) as evidence:
                self._validate_execution_snapshot(prepared, intent, evidence)
                async with self._guard:
                    if self._session_stopping_locked(session_id):
                        return
                    self._status = self._status.model_copy(
                        update={"state": PlaybackState.READY, "updated_at": self.clock.now()}
                    )
                    self._emit_locked(PlaybackEventKind.STATE)
                    now = self.clock.now()
                    self._anchor_elapsed_s = 0.0
                    self._anchor_monotonic = self.clock.monotonic()
                    self._status = self._status.model_copy(
                        update={
                            "state": PlaybackState.PLAYING,
                            "started_at": now,
                            "updated_at": now,
                        }
                    )
                    self._emit_locked(PlaybackEventKind.STATE)
                execution_started = True
            await self._execute_plan(session_id, prepared.plan)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._fault_session(session_id, error, report_to_sink=execution_started)
        finally:
            async with self._guard:
                if self._active_task is asyncio.current_task():
                    self._active_task = None
                self._release_pause_waiter_locked()

    async def _execute_plan(self, session_id: UUID, plan: TrajectoryPlanView) -> None:
        times = tuple(sample.time_s for sample in plan.samples)
        index = -1
        while True:
            if not await self._wait_until_playing(session_id):
                return

            async with self._guard:
                if self._session_stopping_locked(session_id):
                    return
                now_elapsed = min(
                    plan.duration_s,
                    self._anchor_elapsed_s
                    + max(0.0, self.clock.monotonic() - self._anchor_monotonic) * self._status.rate,
                )
                due_index = bisect_right(times, now_elapsed + _TIME_TOLERANCE_S) - 1
                target_index = max(index + 1, due_index)
                target_index = min(target_index, len(plan.samples) - 1)
                target = plan.samples[target_index]
                deadline = self._anchor_monotonic + (
                    max(0.0, target.time_s - self._anchor_elapsed_s) / self._status.rate
                )

            if deadline > self.clock.monotonic() + _TIME_TOLERANCE_S:
                controlled = await self._sleep_until_control(deadline)
                if controlled:
                    continue

            if not await self._wait_until_playing(session_id):
                return
            async with self._guard:
                latest_elapsed = min(
                    plan.duration_s,
                    self._anchor_elapsed_s
                    + max(0.0, self.clock.monotonic() - self._anchor_monotonic) * self._status.rate,
                )
                latest_due = bisect_right(times, latest_elapsed + _TIME_TOLERANCE_S) - 1
            if latest_due > target_index or target.time_s > latest_elapsed + _TIME_TOLERANCE_S:
                # Time can jump after target selection but before the sleep task
                # is installed. Re-select once instead of emitting that stale
                # sample followed by a backlog burst.
                continue
            await self._apply_sample(session_id, plan, target)
            index = target_index
            await self._acknowledge_pause_if_requested(session_id)
            if not await self._wait_until_playing(session_id):
                return
            if index < len(plan.samples) - 1:
                continue

            async with self._guard:
                if self._session_stopping_locked(session_id):
                    return
                completed = self._status.completed_loops + 1
                should_repeat = self._status.loop and completed < self._status.loop_count
                if should_repeat:
                    self._status = self._status.model_copy(
                        update={
                            "progress": 0.0,
                            "elapsed_s": 0.0,
                            "current_keyframe_id": plan.samples[0].keyframe_id,
                            "current_segment_index": plan.samples[0].segment_index,
                            "current_sample_index": plan.samples[0].sample_index,
                            "completed_loops": completed,
                            "updated_at": self.clock.now(),
                        }
                    )
                    self._anchor_elapsed_s = 0.0
                    self._anchor_monotonic = self.clock.monotonic()
                    self._emit_locked(PlaybackEventKind.PROGRESS)
                    # A safe loop is closed, so the endpoint already is sample
                    # zero's state. Skip re-applying that duplicate boundary.
                    index = 0
                    continue
                now = self.clock.now()
                self._status = self._status.model_copy(
                    update={
                        "state": PlaybackState.COMPLETED,
                        "progress": 1.0,
                        "elapsed_s": plan.duration_s,
                        "completed_loops": completed,
                        "updated_at": now,
                        "finished_at": now,
                    }
                )
                self._emit_locked(PlaybackEventKind.STATE)
                self._ready_prepared = None
            await self.state_sink.flush_motion_state(session_id)
            return

    async def _apply_sample(
        self,
        session_id: UUID,
        plan: TrajectoryPlanView,
        sample: TrajectorySampleView,
    ) -> None:
        state = JointState(
            positions=dict(sample.positions),
            units=dict(sample.units),
        )
        await self.state_sink.apply_motion_state(session_id, state)
        async with self._guard:
            if self._session_stopping_locked(session_id):
                return
            progress = min(1.0, sample.time_s / plan.duration_s)
            self._status = self._status.model_copy(
                update={
                    "progress": progress,
                    "elapsed_s": sample.time_s,
                    "current_keyframe_id": sample.keyframe_id,
                    "current_segment_index": sample.segment_index,
                    "current_sample_index": sample.sample_index,
                    "updated_at": self.clock.now(),
                }
            )
            self._emit_locked(PlaybackEventKind.PROGRESS)

    async def _wait_until_playing(self, session_id: UUID) -> bool:
        while True:
            async with self._guard:
                if self._session_stopping_locked(session_id):
                    return False
                if self._pause_requested and self._status.state is PlaybackState.PLAYING:
                    self._status = self._status.model_copy(
                        update={
                            "state": PlaybackState.PAUSED,
                            "updated_at": self.clock.now(),
                        }
                    )
                    self._emit_locked(PlaybackEventKind.STATE)
                    self._release_pause_waiter_locked()
                if self._status.state is PlaybackState.PLAYING:
                    return True
                event = self._control_event
                if event is None:
                    return False
                event.clear()
            await event.wait()

    async def _acknowledge_pause_if_requested(self, session_id: UUID) -> None:
        async with self._guard:
            if (
                not self._session_stopping_locked(session_id)
                and self._pause_requested
                and self._status.state is PlaybackState.PLAYING
            ):
                self._status = self._status.model_copy(
                    update={"state": PlaybackState.PAUSED, "updated_at": self.clock.now()}
                )
                self._emit_locked(PlaybackEventKind.STATE)
                self._release_pause_waiter_locked()

    async def _sleep_until_control(self, deadline: float) -> bool:
        event = self._control_event
        if event is None:
            return True
        if event.is_set():
            event.clear()
            return True

        async def sleep_to_absolute_deadline() -> None:
            # Compute inside the scheduled task. A synthetic or overloaded
            # event loop can advance between task creation and its first turn;
            # capturing a relative delay earlier would add that lag as drift.
            await self.clock.sleep(max(0.0, deadline - self.clock.monotonic()))

        sleep_task = asyncio.create_task(sleep_to_absolute_deadline())
        control_task = asyncio.create_task(event.wait())
        done, pending = await asyncio.wait(
            {sleep_task, control_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if sleep_task in done:
            await sleep_task
        controlled = control_task in done and event.is_set()
        if controlled:
            event.clear()
        return controlled

    async def _fault_session(
        self,
        session_id: UUID,
        error: Exception,
        *,
        report_to_sink: bool,
    ) -> None:
        reason = self._public_fault_reason(error, validation_failed=not report_to_sink)
        if report_to_sink:
            with suppress(Exception):
                await self.state_sink.mark_motion_fault(session_id, reason)
        async with self._guard:
            if (
                self._status.session_id != session_id
                or self._status.state is PlaybackState.STOPPING
            ):
                return
            now = self.clock.now()
            self._status = self._status.model_copy(
                update={
                    "state": PlaybackState.FAULTED,
                    "error": reason,
                    "updated_at": now,
                    "finished_at": now,
                }
            )
            self._emit_locked(PlaybackEventKind.STATE)
            self._ready_prepared = None

    @staticmethod
    def _public_fault_reason(error: Exception, *, validation_failed: bool) -> str:
        """Return a stable public fault without reflecting exception text.

        Playback status is transported over HTTP and WebSocket and may also be
        persisted by the state sink.  Runtime exceptions can contain paths,
        credentials, or tracebacks, so only a bounded structured preflight code
        is retained; all other failures use a fixed public code.
        """

        if validation_failed and isinstance(error, MotionPreflightError):
            details = error.details
            reason = details.get("reason") if isinstance(details, dict) else None
            reasons = details.get("reasons") if isinstance(details, dict) else None
            candidates: tuple[object, ...] = (
                reason,
                *(reasons if isinstance(reasons, list) else []),
            )
            for candidate in candidates:
                if isinstance(candidate, str) and candidate in _PUBLIC_VALIDATION_FAULT_CODES:
                    return f"Playback safety validation failed ({candidate})"
            return "Playback safety validation failed (PLAYBACK_VALIDATION_FAILED)"
        return "Playback execution failed (PLAYBACK_RUNTIME_FAULT)"

    def _validate_execution_snapshot(
        self,
        prepared: PreparedTrajectoryView,
        intent: PlaybackOperatorIntent,
        actual: PlaybackExecutionSnapshot,
    ) -> None:
        plan = prepared.plan
        expected: tuple[tuple[str, object, object], ...] = (
            ("operator_intent", intent.intent_id, actual.operator_intent_id),
            ("motion_id", plan.motion_id, actual.motion_id),
            ("motion_revision", plan.motion_revision, actual.motion_revision),
            ("robot_variant", plan.robot_variant, actual.robot_variant),
            ("state_sequence", plan.start_state_sequence, actual.state_sequence),
            ("profile_fingerprint", plan.profile_fingerprint, actual.profile_fingerprint),
            (
                "kinematics_fingerprint",
                plan.kinematics_fingerprint,
                actual.kinematics_fingerprint,
            ),
        )
        for name, wanted, observed in expected:
            if wanted != observed:
                raise MotionPreflightError(
                    f"Prepared trajectory {name} changed before execution",
                    details={"reason": f"{name.upper()}_CHANGED"},
                )
        if (
            not actual.connected
            or actual.stale
            or not actual.stop_capable
            or actual.control_mode is not ControlMode.DRY_RUN
            or actual.hardware_access_policy is not HardwareAccessPolicy.DISABLED
            or actual.hardware_accessed
        ):
            raise MotionPreflightError(
                "Playback execution context is not safe for Stage 5 Dry Run",
                details={"reason": "UNSAFE_EXECUTION_CONTEXT"},
            )

    @staticmethod
    def _validate_prepared_shape(prepared: PreparedTrajectoryView) -> None:
        if not prepared.preflight.accepted:
            raise MotionPreflightError("Trajectory preflight did not pass")
        plan = prepared.plan
        if not isfinite(plan.duration_s) or not 0.0 < plan.duration_s <= _MAX_TRAJECTORY_DURATION_S:
            raise MotionPreflightError("Prepared trajectory duration is invalid")
        if not isfinite(plan.sample_rate_hz) or not 1.0 <= plan.sample_rate_hz <= 100.0:
            raise MotionPreflightError("Prepared trajectory sample rate is invalid")
        if not 2 <= len(plan.samples) <= _MAX_TRAJECTORY_SAMPLES:
            raise MotionPreflightError("Prepared trajectory sample count is invalid")
        expected_joints = set(plan.samples[0].positions)
        expected_units = dict(plan.samples[0].units)
        prior_time = -1.0
        for expected_index, sample in enumerate(plan.samples):
            if not isfinite(sample.time_s) or sample.time_s <= prior_time:
                raise MotionPreflightError("Prepared trajectory sample times are not monotonic")
            if sample.sample_index != expected_index:
                raise MotionPreflightError("Prepared trajectory sample indices are not canonical")
            if set(sample.positions) != set(sample.units):
                raise MotionPreflightError("Prepared trajectory sample units are incomplete")
            if (
                set(sample.positions) != expected_joints
                or dict(sample.units) != expected_units
                or sample.segment_index < 0
            ):
                raise MotionPreflightError("Prepared trajectory sample joint contract changed")
            if not sample.positions or not all(
                isfinite(value) for value in sample.positions.values()
            ):
                raise MotionPreflightError("Prepared trajectory contains invalid joint values")
            prior_time = sample.time_s
        if not isclose(plan.samples[0].time_s, 0.0, abs_tol=_TIME_TOLERANCE_S):
            raise MotionPreflightError("Prepared trajectory must start at time zero")
        if not isclose(
            plan.samples[-1].time_s,
            plan.duration_s,
            rel_tol=0.0,
            abs_tol=_TIME_TOLERANCE_S,
        ):
            raise MotionPreflightError("Prepared trajectory endpoint must equal its duration")

    @staticmethod
    def _validate_intent(
        prepared: PreparedTrajectoryView,
        intent: PlaybackOperatorIntent,
    ) -> None:
        plan = prepared.plan
        if (
            intent.motion_id != plan.motion_id
            or intent.motion_revision != plan.motion_revision
            or intent.trajectory_digest != plan.digest.sha256
        ):
            raise MotionPreflightError(
                "Operator intent does not match the prepared trajectory",
                details={"reason": "OPERATOR_INTENT_MISMATCH"},
            )

    @staticmethod
    def _require_closed_loop(plan: TrajectoryPlanView) -> None:
        start = plan.samples[0]
        end = plan.samples[-1]
        if set(start.positions) != set(end.positions) or any(
            not isclose(
                start.positions[joint_id],
                end.positions[joint_id],
                rel_tol=0.0,
                abs_tol=_POSITION_TOLERANCE,
            )
            for joint_id in start.positions
        ):
            raise MotionPreflightError(
                "Loop playback requires matching first and final joint positions",
                details={"reason": "DISCONTINUOUS_LOOP"},
            )

    @staticmethod
    def _validate_rate(rate: float) -> float:
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            raise TypeError("playback rate must be numeric")
        resolved = float(rate)
        if not isfinite(resolved) or not MIN_PLAYBACK_RATE <= resolved <= MAX_PLAYBACK_RATE:
            raise ValueError(
                f"playback rate must be between {MIN_PLAYBACK_RATE} and {MAX_PLAYBACK_RATE}"
            )
        return resolved

    @staticmethod
    def _validate_loop(enabled: bool, loop_count: int) -> int:
        if not isinstance(enabled, bool):
            raise TypeError("loop enabled must be a boolean")
        if isinstance(loop_count, bool) or not isinstance(loop_count, int):
            raise TypeError("loop_count must be an integer")
        if enabled and not 2 <= loop_count <= MAX_PLAYBACK_LOOPS:
            raise ValueError(f"enabled loop_count must be between 2 and {MAX_PLAYBACK_LOOPS}")
        return loop_count if enabled else 1

    def _reject_if_active(self) -> None:
        task = self._active_task
        if self._status.state in _ACTIVE_STATES or (task is not None and not task.done()):
            raise MotionConflictError(
                "Another playback session is active",
                details={"active_session_id": str(self._status.session_id)},
            )

    def _session_stopping_locked(self, session_id: UUID) -> bool:
        return (
            self._status.session_id != session_id
            or self._stop_requested
            or self._status.state in {PlaybackState.STOPPING, PlaybackState.STOPPED}
        )

    def _wake_runner_locked(self) -> None:
        if self._control_event is not None:
            self._control_event.set()

    def _release_pause_waiter_locked(self) -> None:
        if self._pause_ack is not None:
            self._pause_ack.set()
            self._pause_ack = None

    def _cancel_preflight_locked(self, reason: str) -> PlaybackStatus:
        safe_reason = reason.strip().replace("\n", " ")[:240] or "Trajectory preflight cancelled"
        binding = (self._status.motion_id, self._status.motion_revision)
        if binding[0] is not None and binding[1] is not None:
            self._cancelled_preflight = (binding[0], binding[1])
        now = self.clock.now()
        self._status = self._status.model_copy(
            update={
                "state": PlaybackState.STOPPING,
                "error": safe_reason,
                "updated_at": now,
            }
        )
        self._emit_locked(PlaybackEventKind.STATE)
        self._preflight_only = False
        self._ready_prepared = None
        self._status = self._status.model_copy(
            update={
                "state": PlaybackState.STOPPED,
                "updated_at": now,
                "finished_at": now,
            }
        )
        self._emit_locked(PlaybackEventKind.STATE)
        return self._status

    def _cancel_ready_locked(self, reason: str) -> PlaybackStatus:
        safe_reason = reason.strip().replace("\n", " ")[:240] or "Prepared trajectory cancelled"
        binding = (self._status.motion_id, self._status.motion_revision)
        if binding[0] is not None and binding[1] is not None:
            self._cancelled_preflight = (binding[0], binding[1])
        self._ready_prepared = None
        now = self.clock.now()
        self._status = self._status.model_copy(
            update={
                "state": PlaybackState.STOPPING,
                "error": safe_reason,
                "updated_at": now,
            }
        )
        self._emit_locked(PlaybackEventKind.STATE)
        self._status = self._status.model_copy(
            update={
                "state": PlaybackState.STOPPED,
                "updated_at": now,
                "finished_at": now,
            }
        )
        self._emit_locked(PlaybackEventKind.STATE)
        return self._status

    def _emit_locked(self, kind: PlaybackEventKind) -> None:
        self._event_sequence += 1
        event = PlaybackEvent(
            sequence=self._event_sequence,
            kind=kind,
            status=self._status,
            emitted_at=self.clock.now(),
        )
        # This boundary is deliberately synchronous and latest-value only. A
        # failing WebSocket observer cannot alter or fault robot execution.
        with suppress(Exception):
            self.observer.publish_playback_event(event)

    def _transition_error(self, action: str) -> MotionConflictError:
        return MotionConflictError(
            f"Cannot {action} playback while {self._status.state.value}",
            details={"state": self._status.state.value},
        )
