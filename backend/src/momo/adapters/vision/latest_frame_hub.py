"""Bounded latest-frame fan-out with one shared slot and no per-client queues."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import TracebackType

from momo.domain.vision import VisionFrame

MAX_LATEST_FRAME_SUBSCRIBERS = 32


class LatestFrameSubscription(AsyncIterator[VisionFrame]):
    def __init__(self, hub: LatestFrameHub, subscription_id: int, seen_version: int) -> None:
        self._hub = hub
        self._subscription_id = subscription_id
        self._seen_version = seen_version
        self._closed = False

    def __aiter__(self) -> LatestFrameSubscription:
        return self

    async def __anext__(self) -> VisionFrame:
        if self._closed:
            raise StopAsyncIteration
        item = await self._hub._next_after(self._seen_version)
        if item is None:
            await self.aclose()
            raise StopAsyncIteration
        version, frame = item
        self._seen_version = version
        return frame

    async def __aenter__(self) -> LatestFrameSubscription:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        await self.aclose()

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            await self._hub._unsubscribe(self._subscription_id)


class LatestFrameHub:
    """A slow subscriber observes the newest frame and skips every older frame."""

    def __init__(self, *, max_subscribers: int = 8) -> None:
        if (
            isinstance(max_subscribers, bool)
            or not isinstance(max_subscribers, int)
            or max_subscribers < 1
            or max_subscribers > MAX_LATEST_FRAME_SUBSCRIBERS
        ):
            raise ValueError(
                f"max_subscribers must be between 1 and {MAX_LATEST_FRAME_SUBSCRIBERS}"
            )
        self._max_subscribers = max_subscribers
        self._condition = asyncio.Condition()
        self._latest: VisionFrame | None = None
        self._version = 0
        self._next_subscription_id = 1
        self._subscriptions: set[int] = set()
        self._closed = False

    @property
    def subscriber_count(self) -> int:
        return len(self._subscriptions)

    @property
    def latest(self) -> VisionFrame | None:
        return self._latest

    async def publish(self, frame: VisionFrame) -> None:
        async with self._condition:
            if self._closed:
                raise RuntimeError("latest-frame hub is closed")
            self._latest = frame
            self._version += 1
            self._condition.notify_all()

    async def subscribe(self, *, replay_latest: bool = True) -> LatestFrameSubscription:
        async with self._condition:
            if self._closed:
                raise RuntimeError("latest-frame hub is closed")
            if len(self._subscriptions) >= self._max_subscribers:
                raise RuntimeError("latest-frame subscriber limit reached")
            subscription_id = self._next_subscription_id
            self._next_subscription_id += 1
            self._subscriptions.add(subscription_id)
            seen_version = self._version - 1 if replay_latest and self._latest else self._version
            return LatestFrameSubscription(self, subscription_id, seen_version)

    async def stream(self, *, replay_latest: bool = True) -> AsyncIterator[VisionFrame]:
        subscription = await self.subscribe(replay_latest=replay_latest)
        try:
            async for frame in subscription:
                yield frame
        finally:
            await subscription.aclose()

    async def aclose(self) -> None:
        async with self._condition:
            self._closed = True
            self._latest = None
            self._condition.notify_all()

    async def _next_after(self, seen_version: int) -> tuple[int, VisionFrame] | None:
        async with self._condition:
            await self._condition.wait_for(
                lambda: self._closed or (self._version > seen_version and self._latest is not None)
            )
            if self._closed:
                return None
            latest = self._latest
            if latest is None:  # pragma: no cover - condition predicate excludes this
                return None
            return self._version, latest

    async def _unsubscribe(self, subscription_id: int) -> None:
        async with self._condition:
            self._subscriptions.discard(subscription_id)
