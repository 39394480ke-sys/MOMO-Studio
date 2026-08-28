"""Single latest-deadline watchdog for a Vision Follow lease."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID

from momo.ports.clock import Clock


class VisionFollowWatchdog:
    def __init__(
        self,
        clock: Clock,
        expired: Callable[[UUID, int], Awaitable[None]],
    ) -> None:
        self.clock = clock
        self.expired = expired
        self._task: asyncio.Task[None] | None = None

    def restart(self, lease_id: UUID, generation: int, deadline: float) -> None:
        self.cancel()
        self._task = asyncio.create_task(
            self._run(lease_id, generation, deadline),
            name=f"vision-follow-lease-{lease_id}",
        )

    def cancel(self) -> None:
        task = self._task
        self._task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _run(self, lease_id: UUID, generation: int, deadline: float) -> None:
        try:
            await self.clock.sleep(max(0.0, deadline - self.clock.monotonic()))
            await self.expired(lease_id, generation)
        except asyncio.CancelledError:
            return
