"""Continuous jog lease/deadman behavior with a manually advanced clock."""

from __future__ import annotations

import asyncio
from typing import cast
from uuid import UUID

import pytest

from momo.application.services.jog_service import JogLeaseService
from momo.application.services.motion_service import MotionApplicationService
from momo.domain.enums import (
    DomainUnit,
    MotionCommandSource,
    MotionCommandState,
    MotionCommandType,
)
from momo.domain.errors import (
    JogLeaseExpiredError,
    MotionCommandNotFoundError,
    MotionConflictError,
)
from momo.domain.motion_command import ContinuousJogPayload, MotionCommand
from momo.domain.motion_preflight import MotionAccepted, MotionCommandStatus
from tests.stage3_helpers import FakeClock, make_preflight


def command(key: str) -> MotionCommand:
    return MotionCommand(
        robot_id="primary",
        source=MotionCommandSource.CONTROL,
        expected_state_sequence=1,
        expected_profile_fingerprint="a" * 64,
        expected_kinematics_fingerprint="b" * 64,
        command_type=MotionCommandType.CONTINUOUS_JOG,
        payload=ContinuousJogPayload(
            joint_id="j11",
            direction=1,
            speed_units_s=10.0,
            unit=DomainUnit.DEG,
        ),
        idempotency_key=key,
    )


class FakeMotionService:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.statuses: dict[UUID, MotionCommandStatus] = {}
        self.by_key: dict[str, UUID] = {}
        self.cancel_calls: list[UUID] = []

    async def submit(self, intent: MotionCommand) -> MotionAccepted:
        command_id = self.by_key.setdefault(intent.idempotency_key, intent.command_id)
        status = self.statuses.get(command_id)
        if status is None:
            preflight = make_preflight(command_id)
            status = MotionCommandStatus(
                command_id=command_id,
                state=MotionCommandState.RUNNING,
                progress=0.0,
                preflight=preflight,
                updated_at=self.clock.now(),
            )
            self.statuses[command_id] = status
        return MotionAccepted(
            command_id=command_id,
            status=status.state,
            preflight=status.preflight,
        )

    def get_status(self, command_id: UUID) -> MotionCommandStatus:
        status = self.statuses.get(command_id)
        if status is None:
            raise MotionCommandNotFoundError(f"expired: {command_id}")
        return status

    async def cancel_command(self, command_id: UUID) -> MotionCommandStatus | None:
        self.cancel_calls.append(command_id)
        status = self.statuses.get(command_id)
        if status is None:
            return None
        if status.state in {
            MotionCommandState.CANCELLED,
            MotionCommandState.COMPLETED,
            MotionCommandState.FAULTED,
        }:
            return status
        cancelled = status.model_copy(
            update={
                "state": MotionCommandState.CANCELLED,
                "updated_at": self.clock.now(),
                "finished_at": self.clock.now(),
            }
        )
        self.statuses[command_id] = cancelled
        return cancelled


def service(
    clock: FakeClock,
    motion: FakeMotionService,
    *,
    limit: int = 256,
) -> JogLeaseService:
    return JogLeaseService(
        cast(MotionApplicationService, motion),
        clock,
        lease_ttl_ms=400,
        session_limit=limit,
    )


def test_start_is_idempotent_for_one_command_and_duplicate_stop_is_safe() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        motion = FakeMotionService(clock)
        jog = service(clock, motion)
        intent = command("same-jog")

        first = await jog.start(intent)
        repeated = await jog.start(intent)
        assert repeated.jog_session_id == first.jog_session_id
        assert repeated.command_id == first.command_id
        assert first.lease_expires_in_ms == 400

        stopped = await jog.stop(first.jog_session_id)
        duplicate = await jog.stop(first.jog_session_id)
        assert stopped.stopped is True
        assert duplicate.stopped is True
        assert duplicate.status is MotionCommandState.CANCELLED

    asyncio.run(scenario())


def test_cancelling_start_after_submit_cancels_unleased_command_and_releases_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        motion = FakeMotionService(clock)
        jog = service(clock, motion, limit=8)
        intent = command("cancel-between-submit-and-register")
        entered_registration = asyncio.Event()
        release_registration = asyncio.Event()
        original_register = jog._register

        async def blocked_register(
            pending_command: MotionCommand,
            command_id: UUID,
        ) -> object:
            entered_registration.set()
            await release_registration.wait()
            return await original_register(pending_command, command_id)

        monkeypatch.setattr(jog, "_register", blocked_register)
        start_task = asyncio.create_task(jog.start(intent))
        await entered_registration.wait()
        start_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start_task

        assert jog._pending_reservations == 0
        assert jog._sessions == {}
        assert jog._by_command == {}
        assert motion.get_status(intent.command_id).state is MotionCommandState.CANCELLED
        assert motion.cancel_calls == [intent.command_id]

    asyncio.run(scenario())


def test_network_loss_expires_lease_and_cancels_motion_without_real_sleep() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        motion = FakeMotionService(clock)
        jog = service(clock, motion)
        lease = await jog.start(command("network-loss"))
        await asyncio.sleep(0)

        await clock.advance(0.4)
        await asyncio.sleep(0)
        assert motion.get_status(lease.command_id).state is MotionCommandState.CANCELLED
        assert motion.cancel_calls == [lease.command_id]
        with pytest.raises(JogLeaseExpiredError):
            await jog.heartbeat(lease.jog_session_id)

    asyncio.run(scenario())


def test_heartbeat_extends_backend_owned_deadman_deadline() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        motion = FakeMotionService(clock)
        jog = service(clock, motion)
        lease = await jog.start(command("heartbeat"))
        await asyncio.sleep(0)

        await clock.advance(0.2)
        renewed = await jog.heartbeat(lease.jog_session_id)
        assert renewed.lease_expires_in_ms == 400
        await clock.advance(0.39)
        assert motion.get_status(lease.command_id).state is MotionCommandState.RUNNING
        await clock.advance(0.01)
        await asyncio.sleep(0)
        assert motion.get_status(lease.command_id).state is MotionCommandState.CANCELLED

    asyncio.run(scenario())


def test_stopped_terminal_session_history_and_command_index_are_bounded() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        motion = FakeMotionService(clock)
        jog = service(clock, motion, limit=8)
        for index in range(20):
            lease = await jog.start(command(f"bounded-{index}"))
            await jog.stop(lease.jog_session_id)

        assert len(jog._sessions) == 8
        assert len(jog._by_command) == 8
        assert len(jog._by_idempotency_key) == 8
        await jog.shutdown()

    asyncio.run(scenario())


def test_active_sessions_and_pending_watchdogs_cannot_exceed_hard_limit() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        motion = FakeMotionService(clock)
        jog = service(clock, motion, limit=8)
        for index in range(8):
            await jog.start(command(f"active-{index}"))

        rejected = command("capacity-rejected")
        with pytest.raises(MotionConflictError, match="capacity"):
            await jog.start(rejected)
        assert rejected.command_id not in motion.statuses
        assert len(jog._sessions) == len(jog._by_command) == 8
        assert sum(session.watchdog is not None for session in jog._sessions.values()) == 8
        await jog.shutdown()

    asyncio.run(scenario())


def test_completed_sessions_are_not_renewed_and_are_pruned_at_capacity() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        motion = FakeMotionService(clock)
        jog = service(clock, motion, limit=8)
        leases = [await jog.start(command(f"terminal-{index}")) for index in range(8)]
        for lease in leases:
            running = motion.statuses[lease.command_id]
            motion.statuses[lease.command_id] = running.model_copy(
                update={"state": MotionCommandState.COMPLETED}
            )

        with pytest.raises(JogLeaseExpiredError):
            await jog.heartbeat(leases[0].jog_session_id)
        replacement = await jog.start(command("terminal-replacement"))
        assert replacement.status is MotionCommandState.RUNNING
        assert len(jog._sessions) <= 8
        assert len(jog._by_command) == len(jog._by_idempotency_key) == len(jog._sessions)
        await jog.shutdown()

    asyncio.run(scenario())


def test_evicted_executor_history_uses_retained_terminal_state_without_fabrication() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        motion = FakeMotionService(clock)
        jog = service(clock, motion, limit=8)
        lease = await jog.start(command("evicted-terminal"))
        first_stop = await jog.stop(lease.jog_session_id)
        assert first_stop.status is MotionCommandState.CANCELLED

        del motion.statuses[lease.command_id]
        duplicate = await jog.stop(lease.jog_session_id)
        assert duplicate.status is MotionCommandState.CANCELLED
        jog._prune_terminal_sessions()
        assert jog._sessions[lease.jog_session_id].last_state is MotionCommandState.CANCELLED
        await jog.shutdown()

    asyncio.run(scenario())
