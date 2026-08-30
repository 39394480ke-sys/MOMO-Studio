"""Cancelable, drift-resistant in-memory motion execution."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from contextlib import suppress
from uuid import UUID

from momo.domain.enums import MotionCommandState
from momo.domain.errors import MotionConflictError
from momo.domain.motion_preflight import (
    MotionCommandStatus,
    PreparedContinuousJog,
    PreparedMotion,
)
from momo.domain.pose import utc_now
from momo.domain.real_hardware import RealHardwareAuthorizationPurpose
from momo.domain.real_motion import RealExecutionAuthorization
from momo.domain.robot import JointState
from momo.ports.clock import Clock
from momo.ports.motion_state_sink import MotionStateSink


class DryRunMotionExecutor:
    """Exactly one active task; every target is already prepared by the gateway."""

    def __init__(
        self,
        clock: Clock,
        state_sink: MotionStateSink,
        *,
        update_hz: float = 25.0,
        history_limit: int = 256,
    ) -> None:
        if not 20.0 <= update_hz <= 100.0:
            raise ValueError("update_hz must be between 20 and 100 Hz")
        self.clock = clock
        self.state_sink = state_sink
        self.update_hz = float(update_hz)
        self.history_limit = max(8, int(history_limit))
        self._guard = asyncio.Lock()
        self._active_command_id: UUID | None = None
        self._active_task: asyncio.Task[None] | None = None
        self._cancel_event: asyncio.Event | None = None
        self._statuses: OrderedDict[UUID, MotionCommandStatus] = OrderedDict()
        self._latest_command_id: UUID | None = None

    @property
    def active_command_id(self) -> UUID | None:
        task = self._active_task
        if self._active_command_id is None or task is None or task.done():
            return None
        return self._active_command_id

    def get_status(self, command_id: UUID) -> MotionCommandStatus | None:
        return self._statuses.get(command_id)

    def active_status(self) -> MotionCommandStatus | None:
        command_id = self.active_command_id
        return self._statuses.get(command_id) if command_id is not None else None

    def latest_status(self) -> MotionCommandStatus | None:
        command_id = self._latest_command_id
        return self._statuses.get(command_id) if command_id is not None else None

    async def submit(
        self,
        prepared: PreparedMotion,
        *,
        authorization: RealExecutionAuthorization | None = None,
        execution_purpose: RealHardwareAuthorizationPurpose | None = None,
        continuous_write_guard: Callable[[], bool] | None = None,
    ) -> MotionCommandStatus:
        del continuous_write_guard
        if authorization is not None or execution_purpose is not None:
            raise ValueError("DRY_RUN execution cannot accept a Real authorization")
        return await self._start(prepared.command_id, prepared, continuous=False)

    async def submit_continuous_jog(
        self,
        prepared: PreparedContinuousJog,
        *,
        authorization: RealExecutionAuthorization | None = None,
        execution_purpose: RealHardwareAuthorizationPurpose | None = None,
        continuous_write_guard: Callable[[], bool] | None = None,
    ) -> MotionCommandStatus:
        del continuous_write_guard
        if authorization is not None or execution_purpose is not None:
            raise ValueError("DRY_RUN execution cannot accept a Real authorization")
        return await self._start(prepared.command_id, prepared, continuous=True)

    async def _start(
        self,
        command_id: UUID,
        prepared: PreparedMotion | PreparedContinuousJog,
        *,
        continuous: bool,
    ) -> MotionCommandStatus:
        async with self._guard:
            if self.active_command_id is not None:
                raise MotionConflictError(
                    "Another motion is active",
                    details={"active_command_id": str(self.active_command_id)},
                )
            cancel_event = asyncio.Event()
            try:
                accepted_at = self.clock.now()
            except Exception as error:
                accepted_at = utc_now()
                status = MotionCommandStatus(
                    command_id=command_id,
                    state=MotionCommandState.FAULTED,
                    progress=0.0,
                    preflight=prepared.preflight,
                    error=type(error).__name__,
                    updated_at=accepted_at,
                    finished_at=accepted_at,
                    hardware_accessed=False,
                )
                self._remember(status)
                # Status/history must remain bounded and terminal even if a
                # secondary fault reporter is itself unavailable.
                with suppress(Exception):
                    await self.state_sink.mark_motion_fault(command_id, type(error).__name__)
                return status
            status = MotionCommandStatus(
                command_id=command_id,
                state=MotionCommandState.ACCEPTED,
                progress=0.0,
                preflight=prepared.preflight,
                updated_at=accepted_at,
                hardware_accessed=False,
            )
            self._remember(status)
            self._active_command_id = command_id
            self._cancel_event = cancel_event
            coroutine = (
                self._run_continuous_jog(prepared, cancel_event)
                if continuous and isinstance(prepared, PreparedContinuousJog)
                else self._run_motion(prepared, cancel_event)
            )
            self._active_task = asyncio.create_task(
                coroutine,
                name=f"dry-run-motion-{command_id}",
            )
            return status

    async def _run_motion(
        self,
        prepared: PreparedMotion | PreparedContinuousJog,
        cancel_event: asyncio.Event,
    ) -> None:
        if not isinstance(prepared, PreparedMotion):
            raise TypeError("expected PreparedMotion")
        command_id = prepared.command_id
        try:
            self._set_running(command_id)
            start = self.clock.monotonic()
            tick = 1
            trajectory_cursor = 1
            while True:
                deadline = start + min(prepared.duration_s, tick / self.update_hz)
                if await self._sleep_until_or_cancel(deadline, cancel_event):
                    await self.state_sink.flush_motion_state(command_id)
                    self._set_cancelled(command_id)
                    return
                elapsed = max(0.0, self.clock.monotonic() - start)
                # Derive scheduled progress from the integral tick rather than
                # subtracting two monotonic floats.  At an exact final deadline,
                # float cancellation could otherwise produce 0.9999999999999998
                # and replay a zero-delay final tick forever.
                scheduled_progress = min(
                    1.0,
                    tick / (prepared.duration_s * self.update_hz),
                )
                progress = min(1.0, max(scheduled_progress, elapsed / prepared.duration_s))
                if prepared.trajectory_samples is not None:
                    while (
                        trajectory_cursor < len(prepared.trajectory_samples) - 1
                        and prepared.trajectory_samples[trajectory_cursor].time_s < elapsed
                    ):
                        trajectory_cursor += 1
                    right = prepared.trajectory_samples[trajectory_cursor]
                    left = prepared.trajectory_samples[trajectory_cursor - 1]
                    sample_span = right.time_s - left.time_s
                    local_fraction = (
                        1.0
                        if sample_span <= 0.0
                        else min(1.0, max(0.0, (elapsed - left.time_s) / sample_span))
                    )
                    positions = {
                        joint_id: left.joint_state.positions[joint_id]
                        + (
                            right.joint_state.positions[joint_id]
                            - left.joint_state.positions[joint_id]
                        )
                        * local_fraction
                        for joint_id in prepared.start_state.positions
                    }
                else:
                    interpolation = progress * progress * (3.0 - 2.0 * progress)
                    positions = {
                        joint_id: (
                            prepared.start_state.positions[joint_id]
                            + (
                                prepared.target_state.positions[joint_id]
                                - prepared.start_state.positions[joint_id]
                            )
                            * interpolation
                        )
                        for joint_id in prepared.start_state.positions
                    }
                await self.state_sink.apply_motion_state(
                    command_id,
                    JointState(positions=positions, units=prepared.target_state.units),
                )
                self._set_progress(command_id, progress)
                if progress >= 1.0:
                    break
                # Skip every missed deadline instead of replaying overdue ticks.
                tick = max(tick + 1, int(elapsed * self.update_hz) + 1)
            await self.state_sink.flush_motion_state(command_id)
            self._set_completed(command_id)
        except Exception as error:
            await self._fault(command_id, error)
        finally:
            await self._clear_active(command_id)

    async def _run_continuous_jog(
        self,
        prepared: PreparedContinuousJog,
        cancel_event: asyncio.Event,
    ) -> None:
        command_id = prepared.command_id
        try:
            self._set_running(command_id)
            start = self.clock.monotonic()
            tick = 1
            while not cancel_event.is_set():
                deadline = start + tick / self.update_hz
                if await self._sleep_until_or_cancel(deadline, cancel_event):
                    break
                elapsed = max(0.0, self.clock.monotonic() - start)
                ramp_duration = prepared.speed_units_s / prepared.acceleration_units_s2
                if elapsed < ramp_duration:
                    distance = 0.5 * prepared.acceleration_units_s2 * elapsed * elapsed
                else:
                    ramp_distance = (
                        0.5 * prepared.acceleration_units_s2 * ramp_duration * ramp_duration
                    )
                    distance = ramp_distance + prepared.speed_units_s * (elapsed - ramp_duration)
                start_value = prepared.start_state.positions[prepared.joint_id]
                value = start_value + prepared.direction * distance
                bounded = max(prepared.minimum, min(prepared.maximum, value))
                positions = dict(prepared.start_state.positions)
                positions[prepared.joint_id] = bounded
                await self.state_sink.apply_motion_state(
                    command_id,
                    JointState(positions=positions, units=prepared.start_state.units),
                )
                envelope = prepared.maximum - prepared.minimum
                progress = abs(bounded - start_value) / envelope if envelope > 0 else 1.0
                self._set_progress(command_id, progress)
                if bounded != value:
                    await self.state_sink.flush_motion_state(command_id)
                    self._set_completed(command_id)
                    return
                tick = max(tick + 1, int(elapsed * self.update_hz) + 1)
            await self.state_sink.flush_motion_state(command_id)
            self._set_cancelled(command_id)
        except Exception as error:
            await self._fault(command_id, error)
        finally:
            await self._clear_active(command_id)

    async def cancel_active(self) -> MotionCommandStatus | None:
        """Highest-priority cancellation; never waits behind a lifecycle command lock."""

        async with self._guard:
            command_id = self.active_command_id
            task = self._active_task
            cancel_event = self._cancel_event
            if command_id is None or task is None or cancel_event is None:
                return None
            cancel_event.set()
        await asyncio.shield(task)
        return self._statuses.get(command_id)

    async def cancel(self, command_id: UUID) -> MotionCommandStatus | None:
        if self.active_command_id != command_id:
            return self._statuses.get(command_id)
        return await self.cancel_active()

    async def shutdown(self) -> None:
        await self.cancel_active()

    async def _sleep_until_or_cancel(
        self,
        deadline: float,
        cancel_event: asyncio.Event,
    ) -> bool:
        if cancel_event.is_set():
            return True
        sleep_task = asyncio.create_task(
            self.clock.sleep(max(0.0, deadline - self.clock.monotonic()))
        )
        cancel_task = asyncio.create_task(cancel_event.wait())
        done, pending = await asyncio.wait(
            {sleep_task, cancel_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if sleep_task in done:
            # Propagate injected Clock faults into the command fault path.
            await sleep_task
        return cancel_task in done and cancel_event.is_set()

    def _set_running(self, command_id: UUID) -> None:
        current = self._statuses[command_id]
        now = self.clock.now()
        self._remember(
            current.model_copy(
                update={
                    "state": MotionCommandState.RUNNING,
                    "started_at": now,
                    "updated_at": now,
                }
            )
        )

    def _set_progress(self, command_id: UUID, progress: float) -> None:
        current = self._statuses[command_id]
        self._remember(
            current.model_copy(
                update={"progress": min(1.0, progress), "updated_at": self.clock.now()}
            )
        )

    def _set_completed(self, command_id: UUID) -> None:
        current = self._statuses[command_id]
        now = self.clock.now()
        self._remember(
            current.model_copy(
                update={
                    "state": MotionCommandState.COMPLETED,
                    "progress": 1.0,
                    "updated_at": now,
                    "finished_at": now,
                }
            )
        )

    def _set_cancelled(self, command_id: UUID) -> None:
        current = self._statuses[command_id]
        now = self.clock.now()
        self._remember(
            current.model_copy(
                update={
                    "state": MotionCommandState.CANCELLED,
                    "updated_at": now,
                    "finished_at": now,
                }
            )
        )

    async def _fault(self, command_id: UUID, error: Exception) -> None:
        safe_error = type(error).__name__
        current = self._statuses[command_id]
        try:
            now = self.clock.now()
        except Exception:
            now = utc_now()
        self._remember(
            current.model_copy(
                update={
                    "state": MotionCommandState.FAULTED,
                    "error": safe_error,
                    "updated_at": now,
                    "finished_at": now,
                }
            )
        )
        # The primary executor status is still deterministically terminal if
        # the secondary fault reporter is unavailable.
        with suppress(Exception):
            await self.state_sink.mark_motion_fault(command_id, safe_error)

    async def _clear_active(self, command_id: UUID) -> None:
        async with self._guard:
            if self._active_command_id == command_id:
                self._active_command_id = None
                self._active_task = None
                self._cancel_event = None

    def _remember(self, status: MotionCommandStatus) -> None:
        self._latest_command_id = status.command_id
        self._statuses[status.command_id] = status
        self._statuses.move_to_end(status.command_id)
        while len(self._statuses) > self.history_limit:
            oldest_id, oldest = next(iter(self._statuses.items()))
            if oldest_id == self.active_command_id:
                break
            if oldest.state in {MotionCommandState.ACCEPTED, MotionCommandState.RUNNING}:
                break
            self._statuses.popitem(last=False)
