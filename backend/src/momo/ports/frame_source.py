"""Pull-based, latest-only frame acquisition boundary."""

from typing import Protocol, runtime_checkable

from momo.domain.vision import VisionFrame, VisionProviderCapability, VisionStatus


@runtime_checkable
class FrameSource(Protocol):
    """A source that captures only when pulled and owns no unbounded frame queue."""

    @property
    def source_id(self) -> str: ...

    @property
    def status(self) -> VisionStatus: ...

    @property
    def capability(self) -> VisionProviderCapability: ...

    async def latest_frame(self) -> VisionFrame | None: ...

    async def aclose(self) -> None: ...


@runtime_checkable
class OperatorControlledFrameSource(FrameSource, Protocol):
    """A configured source that can only be opened by an explicit operator action."""

    async def open(self) -> None: ...
