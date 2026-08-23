"""Production process clock; it has no device side effects."""

import asyncio
import time
from datetime import UTC, datetime


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, delay_s: float) -> None:
        await asyncio.sleep(max(0.0, delay_s))
