"""Bounded frame-to-local-stream encoding boundary."""

from typing import Protocol, runtime_checkable

from momo.domain.vision import VisionFrame, VisionProviderCapability


@runtime_checkable
class VisionStreamEncoder(Protocol):
    @property
    def media_type(self) -> str: ...

    @property
    def capability(self) -> VisionProviderCapability: ...

    def encode(self, frame: VisionFrame) -> bytes: ...
