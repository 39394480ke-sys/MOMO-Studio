"""Person/general-target and face detection boundaries."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from momo.domain.vision import Detection, VisionFrame, VisionProviderCapability


@runtime_checkable
class TargetDetector(Protocol):
    @property
    def capability(self) -> VisionProviderCapability: ...

    async def detect(self, frame: VisionFrame) -> Sequence[Detection]: ...


@runtime_checkable
class FaceDetector(Protocol):
    @property
    def capability(self) -> VisionProviderCapability: ...

    async def detect(self, frame: VisionFrame) -> Sequence[Detection]: ...
