"""Bounded latest-value playback event publication."""

from __future__ import annotations

from momo.domain.playback import PlaybackEvent


class LatestValuePlaybackObserver:
    """Retain one immutable event for read-only transports; never queue history."""

    def __init__(self) -> None:
        self._latest: PlaybackEvent | None = None

    def publish_playback_event(self, event: PlaybackEvent) -> None:
        self._latest = event

    @property
    def latest(self) -> PlaybackEvent | None:
        return self._latest
