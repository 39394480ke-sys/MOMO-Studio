"""Honest detectors for the known deterministic synthetic fixture only."""

from __future__ import annotations

from momo.adapters.vision.synthetic_scene import SyntheticVisionScenario
from momo.domain.vision import (
    Detection,
    TargetKind,
    VisionFrame,
    VisionProviderCapability,
    VisionProviderKind,
    VisionProviderStatus,
)

SYNTHETIC_MODEL_SOURCE = "MOMO deterministic synthetic fixture"
SYNTHETIC_DETECTOR_NOTICE = (
    "Synthetic-scene annotations only; this is not a general-purpose learned detector."
)


class SyntheticTargetDetector:
    """Detect PERSON or FACE only in frames from its configured synthetic source."""

    def __init__(
        self,
        target_kind: TargetKind,
        *,
        scenario: SyntheticVisionScenario | None = None,
        source_id: str = "synthetic",
    ) -> None:
        if target_kind not in (TargetKind.PERSON, TargetKind.FACE):
            raise ValueError("synthetic detector target_kind must be PERSON or FACE")
        self._target_kind = target_kind
        self._scenario = scenario or SyntheticVisionScenario()
        self._source_id = source_id

    @property
    def target_kind(self) -> TargetKind:
        return self._target_kind

    @property
    def capability(self) -> VisionProviderCapability:
        provider_kind = (
            VisionProviderKind.FACE_DETECTOR
            if self._target_kind is TargetKind.FACE
            else VisionProviderKind.TARGET_DETECTOR
        )
        return VisionProviderCapability(
            provider_id=f"synthetic-{self._target_kind.value.lower()}-detector",
            kind=provider_kind,
            status=VisionProviderStatus.AVAILABLE,
            display_name=f"Synthetic {self._target_kind.value.lower()} detector",
            model_source=SYNTHETIC_MODEL_SOURCE,
            notice=SYNTHETIC_DETECTOR_NOTICE,
        )

    async def detect(self, frame: VisionFrame) -> tuple[Detection, ...]:
        if not frame.content or frame.source_id != self._source_id:
            return ()
        box = self._scenario.bounding_box(frame.metadata, self._target_kind)
        if box is None:
            return ()
        confidence = 0.99 if self._target_kind is TargetKind.PERSON else 0.97
        return (
            Detection(
                target_kind=self._target_kind,
                bounding_box=box,
                confidence=confidence,
                provider_id=self.capability.provider_id,
            ),
        )


class SyntheticPersonDetector(SyntheticTargetDetector):
    def __init__(
        self,
        *,
        scenario: SyntheticVisionScenario | None = None,
        source_id: str = "synthetic",
    ) -> None:
        super().__init__(TargetKind.PERSON, scenario=scenario, source_id=source_id)


class SyntheticFaceDetector(SyntheticTargetDetector):
    def __init__(
        self,
        *,
        scenario: SyntheticVisionScenario | None = None,
        source_id: str = "synthetic",
    ) -> None:
        super().__init__(TargetKind.FACE, scenario=scenario, source_id=source_id)
