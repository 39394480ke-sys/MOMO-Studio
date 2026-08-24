"""Frame-bound target tracker boundary."""

from typing import Protocol, runtime_checkable

from momo.domain.vision import (
    TargetSelection,
    TrackingResult,
    VisionFrame,
    VisionProviderCapability,
)


@runtime_checkable
class TargetTracker(Protocol):
    @property
    def capability(self) -> VisionProviderCapability: ...

    async def initialize(
        self,
        frame: VisionFrame,
        selection: TargetSelection,
    ) -> TrackingResult: ...

    async def update(self, frame: VisionFrame) -> TrackingResult: ...

    async def reset(self) -> None: ...
