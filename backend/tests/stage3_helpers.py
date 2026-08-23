"""Synthetic Stage 3 timing and motion fixtures; no real sleeps or devices."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from momo.domain.enums import DomainUnit
from momo.domain.motion_preflight import MotionPreflight, PreflightCheck, PreparedMotion
from momo.domain.robot import JointState


class FakeClock:
    """Manually advanced monotonic/wall clock with cancellable sleepers."""

    def __init__(self) -> None:
        self.value = 0.0
        self.sleep_calls: list[float] = []
        self._waiters: list[tuple[float, asyncio.Future[None]]] = []

    def monotonic(self) -> float:
        return self.value

    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=self.value)

    async def sleep(self, delay_s: float) -> None:
        delay = max(0.0, float(delay_s))
        self.sleep_calls.append(delay)
        deadline = self.value + delay
        if deadline <= self.value:
            await asyncio.sleep(0)
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        waiter = (deadline, future)
        self._waiters.append(waiter)
        try:
            await future
        finally:
            if waiter in self._waiters:
                self._waiters.remove(waiter)

    def elapse(self, delta_s: float) -> None:
        self.value += float(delta_s)
        self._wake_due()

    async def advance(self, delta_s: float) -> None:
        self.elapse(delta_s)
        await self.settle()

    @staticmethod
    async def settle(*, turns: int = 20) -> None:
        """Drain cascaded task wakeups without relying on a real-time sleep.

        One clock wake-up resumes the executor's sleep task, which in turn must
        cancel and gather its cancellation waiter before applying a state and
        scheduling the next deadline.  A fixed number of event-loop turns keeps
        this synthetic clock deterministic while allowing that whole chain to
        settle.
        """

        for _ in range(turns):
            await asyncio.sleep(0)

    async def advance_to_next(self) -> None:
        for _ in range(20):
            if self._waiters:
                break
            await asyncio.sleep(0)
        if not self._waiters:
            # Terminal cleanup may still be propagating even though no next
            # sleep is expected.  Let the caller observe executor idleness.
            await self.settle()
            return
        deadline = min(item[0] for item in self._waiters)
        await self.advance(max(0.0, deadline - self.value))

    @property
    def waiter_count(self) -> int:
        return len(self._waiters)

    def _wake_due(self) -> None:
        for deadline, future in tuple(self._waiters):
            if deadline <= self.value and not future.done():
                future.set_result(None)


class RecordingMotionSink:
    def __init__(self, clock: FakeClock, *, work_s: float = 0.0, fail: bool = False) -> None:
        self.clock = clock
        self.work_s = work_s
        self.fail = fail
        self.states: list[JointState] = []
        self.application_times: list[float] = []
        self.faults: list[tuple[UUID, str]] = []
        self.flushes: list[UUID] = []
        self.sequence = 0

    async def apply_motion_state(self, command_id: UUID, state: JointState) -> int:
        del command_id
        if self.fail:
            raise RuntimeError("synthetic sink failure")
        self.application_times.append(self.clock.monotonic())
        self.states.append(state)
        self.sequence += 1
        self.clock.elapse(self.work_s)
        return self.sequence

    async def flush_motion_state(self, command_id: UUID) -> None:
        self.flushes.append(command_id)

    async def mark_motion_fault(self, command_id: UUID, error: str) -> None:
        self.faults.append((command_id, error))


def make_preflight(command_id: UUID) -> MotionPreflight:
    return MotionPreflight(
        accepted=True,
        command_id=command_id,
        checks=[PreflightCheck(name="synthetic", passed=True, detail="test")],
        warnings=["synthetic"],
        profile_fingerprint="a" * 64,
        kinematics_fingerprint="b" * 64,
    )


def make_prepared_motion(
    *,
    duration_s: float = 1.0,
    start: float = 0.0,
    target: float = 10.0,
    command_id: UUID | None = None,
) -> PreparedMotion:
    resolved_id = command_id or uuid4()
    units = {"j11": DomainUnit.DEG}
    return PreparedMotion(
        command_id=resolved_id,
        start_state=JointState(positions={"j11": start}, units=units),
        target_state=JointState(positions={"j11": target}, units=units),
        duration_s=duration_s,
        preflight=make_preflight(resolved_id),
    )
