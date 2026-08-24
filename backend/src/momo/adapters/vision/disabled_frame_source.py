"""Fail-closed source used when camera access is completely disabled."""

from momo.domain.vision import (
    VisionFrame,
    VisionProviderCapability,
    VisionProviderKind,
    VisionProviderStatus,
    VisionStatus,
)


class DisabledFrameSource:
    def __init__(self, *, source_id: str = "disabled") -> None:
        self._source_id = source_id
        self._status = VisionStatus.DISABLED

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def status(self) -> VisionStatus:
        return self._status

    @property
    def capability(self) -> VisionProviderCapability:
        return VisionProviderCapability(
            provider_id="disabled-frame-source",
            kind=VisionProviderKind.FRAME_SOURCE,
            status=VisionProviderStatus.UNAVAILABLE,
            display_name="Vision disabled",
            model_source=None,
            notice="Camera access is disabled; no source is imported, opened, or enumerated.",
            detail="CameraAccessPolicy is DISABLED",
        )

    async def latest_frame(self) -> VisionFrame | None:
        return None

    async def aclose(self) -> None:
        self._status = VisionStatus.CLOSED
