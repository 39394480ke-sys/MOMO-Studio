"""Concurrency-safe ownership of motion commands emitted by Vision Follow."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from momo.domain.enums import MotionCommandState
from momo.domain.errors import MotionCommandNotFoundError, MotionConflictError
from momo.domain.motion_command import MotionCommand
from momo.domain.motion_preflight import MotionAccepted, MotionCommandStatus


class VisionMotionGateway(Protocol):
    """Only the reviewed motion application surface Follow may call."""

    async def submit(self, command: MotionCommand) -> MotionAccepted: ...

    def get_status(self, command_id: UUID) -> MotionCommandStatus: ...

    async def cancel_command(self, command_id: UUID) -> MotionCommandStatus | None: ...


@dataclass(frozen=True, slots=True)
class VisionCommandSnapshot:
    active_command_id: UUID | None
    dispatch_busy: bool
    status: MotionCommandStatus | None


class VisionCommandCoordinator:
    """Fence Follow command races without exposing an executor or raw adapter."""

    def __init__(self, motion: VisionMotionGateway) -> None:
        self.motion = motion
        self._guard = asyncio.Lock()
        self._epoch = 0
        self._active_command_id: UUID | None = None
        self._pending_command_id: UUID | None = None
        self._dispatch_task: asyncio.Task[MotionAccepted] | None = None
        self._global_stop_epochs: set[int] = set()

    async def begin_owner(self) -> int:
        async with self._guard:
            if self._active_command_id is not None or (self._dispatch_task is not None):
                raise MotionConflictError("A prior Vision command still owns motion")
            self._epoch += 1
            return self._epoch

    async def inspect(self, epoch: int) -> VisionCommandSnapshot:
        async with self._guard:
            if epoch != self._epoch:
                return VisionCommandSnapshot(None, False, None)
            task = self._dispatch_task
            active_command_id = self._active_command_id
            dispatch_busy = task is not None
        if dispatch_busy or active_command_id is None:
            return VisionCommandSnapshot(active_command_id, dispatch_busy, None)
        try:
            status = self.motion.get_status(active_command_id)
        except MotionCommandNotFoundError:
            status = None
        if status is None or status.state in {
            MotionCommandState.CANCELLED,
            MotionCommandState.COMPLETED,
            MotionCommandState.FAULTED,
        }:
            async with self._guard:
                if epoch == self._epoch and self._active_command_id == active_command_id:
                    self._active_command_id = None
            return VisionCommandSnapshot(None, False, status)
        return VisionCommandSnapshot(active_command_id, False, status)

    async def dispatch(self, epoch: int, command: MotionCommand) -> UUID | None:
        async with self._guard:
            if epoch != self._epoch:
                return None
            if self._active_command_id is not None or (self._dispatch_task is not None):
                raise MotionConflictError("Vision command ownership is busy")
            task = asyncio.create_task(
                self.motion.submit(command),
                name=f"vision-follow-command-{command.command_id}",
            )
            self._pending_command_id = command.command_id
            self._dispatch_task = task

        try:
            accepted = await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            caller_cancelled = bool(current is not None and current.cancelling())
            cleanup = asyncio.create_task(self._finish_interrupted(epoch, command.command_id))
            await asyncio.shield(cleanup)
            if caller_cancelled:
                raise
            return None
        except Exception:
            await self._clear_pending(epoch, command.command_id)
            raise

        cancel_late_acceptance = False
        async with self._guard:
            if epoch != self._epoch or self._pending_command_id != command.command_id:
                cancel_late_acceptance = epoch not in self._global_stop_epochs
                self._global_stop_epochs.discard(epoch)
            else:
                self._pending_command_id = None
                self._dispatch_task = None
                self._active_command_id = accepted.command_id
                return accepted.command_id
        if cancel_late_acceptance:
            await self.motion.cancel_command(accepted.command_id)
        return None

    async def suspend(self, epoch: int) -> None:
        """Cancel the current direction while retaining the Follow lease."""

        async with self._guard:
            if epoch != self._epoch:
                return
            active, pending, task = self._clear_ownership_unlocked()
        await self._cancel_task_and_commands(task, active, pending)

    async def stop(self, epoch: int, *, global_stop: bool) -> None:
        """Invalidate one owner; Global Stop already cancelled the executor first."""

        async with self._guard:
            if epoch != self._epoch:
                return
            active, pending, task = self._clear_ownership_unlocked()
            self._epoch += 1
            if global_stop:
                if pending is not None or task is not None:
                    self._global_stop_epochs.add(epoch)
                return
        await self._cancel_task_and_commands(task, active, pending)

    async def _finish_interrupted(self, epoch: int, command_id: UUID) -> None:
        async with self._guard:
            globally_stopped = epoch in self._global_stop_epochs
            self._global_stop_epochs.discard(epoch)
            if epoch == self._epoch:
                if self._pending_command_id == command_id:
                    self._pending_command_id = None
                if self._dispatch_task is not None and self._dispatch_task.done():
                    self._dispatch_task = None
        if not globally_stopped:
            await self.motion.cancel_command(command_id)

    async def _clear_pending(self, epoch: int, command_id: UUID) -> None:
        async with self._guard:
            self._global_stop_epochs.discard(epoch)
            if epoch != self._epoch:
                return
            if self._pending_command_id == command_id:
                self._pending_command_id = None
                self._dispatch_task = None

    def _clear_ownership_unlocked(
        self,
    ) -> tuple[UUID | None, UUID | None, asyncio.Task[MotionAccepted] | None]:
        active = self._active_command_id
        pending = self._pending_command_id
        task = self._dispatch_task
        self._active_command_id = None
        self._pending_command_id = None
        self._dispatch_task = None
        return active, pending, task

    async def _cancel_task_and_commands(
        self,
        task: asyncio.Task[MotionAccepted] | None,
        *command_ids: UUID | None,
    ) -> None:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        seen: set[UUID] = set()
        for command_id in command_ids:
            if command_id is None or command_id in seen:
                continue
            seen.add(command_id)
            await self.motion.cancel_command(command_id)
