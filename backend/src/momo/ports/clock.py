"""Injectable wall/monotonic clock boundary for deterministic scheduling."""

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def monotonic(self) -> float: ...

    def now(self) -> datetime: ...

    async def sleep(self, delay_s: float) -> None: ...
