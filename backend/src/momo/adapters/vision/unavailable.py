"""Honest unavailable adapters for optional detector/tracker capabilities."""

from __future__ import annotations

from momo.domain.errors import VisionProviderUnavailableError
from momo.domain.vision import (
    FrameMetadata,
    TargetSelection,
    TrackingResult,
    TrackingStatus,
    VisionFrame,
    VisionProviderCapability,
    VisionProviderKind,
    VisionProviderStatus,
)


class UnavailableTargetDetector:
    def __init__(
        self,
        *,
        provider_id: str = "optional-target-detector",
        display_name: str = "Optional target detector",
        model_source: str | None = None,
        notice: str = "No detector model was downloaded or installed.",
        detail: str = "Optional detector provider is unavailable",
    ) -> None:
        self._capability = VisionProviderCapability(
            provider_id=provider_id,
            kind=VisionProviderKind.TARGET_DETECTOR,
            status=VisionProviderStatus.UNAVAILABLE,
            display_name=display_name,
            model_source=model_source,
            notice=notice,
            detail=detail,
        )

    @property
    def capability(self) -> VisionProviderCapability:
        return self._capability

    async def detect(self, frame: VisionFrame) -> tuple[()]:
        del frame
        raise VisionProviderUnavailableError(
            self._capability.detail,
            details={"provider_id": self._capability.provider_id},
        )


class UnavailableFaceDetector(UnavailableTargetDetector):
    def __init__(self, *, detail: str = "Optional face detector provider is unavailable") -> None:
        super().__init__(
            provider_id="optional-face-detector",
            display_name="Optional face detector",
            model_source=None,
            notice="No face model was downloaded or installed.",
            detail=detail,
        )
        capability_data = self._capability.model_dump(mode="python")
        capability_data["kind"] = VisionProviderKind.FACE_DETECTOR
        self._capability = VisionProviderCapability.model_validate(capability_data)


class UnavailableTargetTracker:
    def __init__(
        self,
        *,
        provider_id: str = "optional-live-target-tracker",
        display_name: str = "Optional live target tracker",
        detail: str = "Optional live tracker provider is unavailable",
    ) -> None:
        self._capability = VisionProviderCapability(
            provider_id=provider_id,
            kind=VisionProviderKind.TARGET_TRACKER,
            status=VisionProviderStatus.UNAVAILABLE,
            display_name=display_name,
            model_source=None,
            notice="No tracker package or model was downloaded or installed.",
            detail=detail,
        )

    @property
    def capability(self) -> VisionProviderCapability:
        return self._capability

    async def initialize(
        self,
        frame: VisionFrame,
        selection: TargetSelection,
    ) -> TrackingResult:
        del selection
        return self._faulted(frame.metadata)

    async def update(self, frame: VisionFrame) -> TrackingResult:
        return self._faulted(frame.metadata)

    async def reset(self) -> None:
        return None

    def _faulted(self, metadata: FrameMetadata) -> TrackingResult:
        return TrackingResult(
            metadata=metadata,
            status=TrackingStatus.FAULTED,
            confidence=0.0,
            detail=self._capability.detail,
        )
