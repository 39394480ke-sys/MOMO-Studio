"""Deterministic manual-ROI tracker for the synthetic fixture."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from momo.adapters.vision.synthetic_scene import SyntheticVisionScenario
from momo.domain.vision import (
    FrameMetadata,
    NormalizedBoundingBox,
    TargetKind,
    TargetSelection,
    TrackingResult,
    TrackingStatus,
    VisionFrame,
    VisionProviderCapability,
    VisionProviderKind,
    VisionProviderStatus,
    box_matches_metadata,
)


@dataclass(frozen=True, slots=True)
class _TrackerAnchor:
    selection: NormalizedBoundingBox
    initial_anchor: NormalizedBoundingBox
    target_kind: TargetKind


class SyntheticTargetTracker:
    """Moves a selected ROI with the fixture target and fails closed on bad frames."""

    def __init__(
        self,
        *,
        scenario: SyntheticVisionScenario | None = None,
        source_id: str = "synthetic",
    ) -> None:
        self._scenario = scenario or SyntheticVisionScenario()
        self._source_id = source_id
        self._anchor: _TrackerAnchor | None = None
        self._last_metadata: FrameMetadata | None = None

    @property
    def capability(self) -> VisionProviderCapability:
        return VisionProviderCapability(
            provider_id="synthetic-target-tracker",
            kind=VisionProviderKind.TARGET_TRACKER,
            status=VisionProviderStatus.AVAILABLE,
            display_name="Synthetic target tracker",
            model_source="MOMO deterministic synthetic fixture",
            notice="Deterministic synthetic-scene tracker; not a live-camera tracker.",
        )

    async def initialize(
        self,
        frame: VisionFrame,
        selection: TargetSelection,
    ) -> TrackingResult:
        if frame.source_id != self._source_id:
            return self._failure(frame.metadata, TrackingStatus.FAULTED, "source mismatch")
        if not box_matches_metadata(selection.bounding_box, frame.metadata):
            return self._failure(
                frame.metadata,
                TrackingStatus.STALE,
                "selection does not match the initialization frame",
            )
        target_kind = (
            selection.target_kind
            if selection.target_kind is not TargetKind.MANUAL
            else TargetKind.PERSON
        )
        initial_anchor = self._scenario.bounding_box(frame.metadata, target_kind)
        if initial_anchor is None:
            self._anchor = None
            self._last_metadata = frame.metadata
            return self._failure(frame.metadata, TrackingStatus.LOST, "synthetic target is lost")
        self._anchor = _TrackerAnchor(
            selection=selection.bounding_box,
            initial_anchor=initial_anchor,
            target_kind=target_kind,
        )
        self._last_metadata = frame.metadata
        return TrackingResult(
            metadata=frame.metadata,
            status=TrackingStatus.LOCKED,
            bounding_box=selection.bounding_box,
            confidence=1.0,
            detail="synthetic target initialized",
        )

    async def update(self, frame: VisionFrame) -> TrackingResult:
        anchor = self._anchor
        if anchor is None:
            return self._failure(
                frame.metadata,
                TrackingStatus.UNINITIALIZED,
                "tracker has not been initialized",
            )
        previous = self._last_metadata
        if frame.source_id != self._source_id:
            return self._failure(frame.metadata, TrackingStatus.FAULTED, "source mismatch")
        if frame.width_px != anchor.selection.frame_width_px or (
            frame.height_px != anchor.selection.frame_height_px
        ):
            return self._failure(frame.metadata, TrackingStatus.FAULTED, "frame dimensions changed")
        if previous is not None and (
            frame.frame_id == previous.frame_id or frame.captured_at <= previous.captured_at
        ):
            return self._failure(frame.metadata, TrackingStatus.STALE, "frame did not advance")
        self._last_metadata = frame.metadata

        current_anchor = self._scenario.bounding_box(frame.metadata, anchor.target_kind)
        if current_anchor is None:
            return self._failure(frame.metadata, TrackingStatus.LOST, "synthetic target is lost")
        x = anchor.selection.x + current_anchor.x - anchor.initial_anchor.x
        y = anchor.selection.y + current_anchor.y - anchor.initial_anchor.y
        try:
            tracked_box = NormalizedBoundingBox.from_metadata(
                x=x,
                y=y,
                width=anchor.selection.width,
                height=anchor.selection.height,
                metadata=frame.metadata,
            )
        except ValidationError:
            return self._failure(
                frame.metadata,
                TrackingStatus.LOST,
                "tracked target moved outside the frame",
            )
        return TrackingResult(
            metadata=frame.metadata,
            status=TrackingStatus.LOCKED,
            bounding_box=tracked_box,
            confidence=0.98,
            detail="synthetic target locked",
        )

    async def reset(self) -> None:
        self._anchor = None
        self._last_metadata = None

    @staticmethod
    def _failure(
        metadata: FrameMetadata,
        status: TrackingStatus,
        detail: str,
    ) -> TrackingResult:
        return TrackingResult(metadata=metadata, status=status, confidence=0.0, detail=detail)
