"""Deterministic in-memory scene shared by Stage 7 synthetic adapters."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field

from momo.domain.vision import FrameMetadata, NormalizedBoundingBox, TargetKind

MAX_CONFIGURED_LOST_FRAMES = 10_000


def synthetic_frame_number(frame_id: str, source_id: str) -> int | None:
    prefix = f"{source_id}-"
    if not frame_id.startswith(prefix):
        return None
    suffix = frame_id.removeprefix(prefix)
    if len(suffix) != 8 or not suffix.isascii() or not suffix.isdigit():
        return None
    number = int(suffix)
    return number if number >= 1 else None


@dataclass(frozen=True, slots=True)
class SyntheticVisionScenario:
    """Small bounded fixture configuration, never a learned detection model."""

    lost_frame_numbers: frozenset[int] = field(default_factory=frozenset)
    target_lost_after_frame: int | None = None

    def __post_init__(self) -> None:
        if len(self.lost_frame_numbers) > MAX_CONFIGURED_LOST_FRAMES:
            raise ValueError(
                f"lost_frame_numbers cannot exceed {MAX_CONFIGURED_LOST_FRAMES} entries"
            )
        for number in self.lost_frame_numbers:
            if isinstance(number, bool) or not isinstance(number, int) or number < 1:
                raise ValueError("lost frame numbers must be positive integers")
        if self.target_lost_after_frame is not None and (
            isinstance(self.target_lost_after_frame, bool)
            or not isinstance(self.target_lost_after_frame, int)
            or self.target_lost_after_frame < 0
        ):
            raise ValueError("target_lost_after_frame must be a non-negative integer")

    @classmethod
    def with_lost_frames(
        cls,
        frame_numbers: Collection[int],
        *,
        target_lost_after_frame: int | None = None,
    ) -> SyntheticVisionScenario:
        return cls(
            lost_frame_numbers=frozenset(frame_numbers),
            target_lost_after_frame=target_lost_after_frame,
        )

    def target_is_visible(self, frame_number: int) -> bool:
        if frame_number in self.lost_frame_numbers:
            return False
        return self.target_lost_after_frame is None or frame_number <= self.target_lost_after_frame

    def bounding_box(
        self,
        metadata: FrameMetadata,
        target_kind: TargetKind,
    ) -> NormalizedBoundingBox | None:
        frame_number = synthetic_frame_number(metadata.frame_id, metadata.source_id)
        if frame_number is None or not self.target_is_visible(frame_number):
            return None

        # A horizontal triangle wave stays comfortably inside the normalized frame.
        phase = (frame_number - 1) % 80
        triangle = phase if phase <= 40 else 80 - phase
        person_x = 0.10 + triangle * 0.01
        person_y = 0.28
        if target_kind is TargetKind.FACE:
            return NormalizedBoundingBox.from_metadata(
                x=person_x + 0.05,
                y=person_y + 0.04,
                width=0.08,
                height=0.12,
                metadata=metadata,
            )
        return NormalizedBoundingBox.from_metadata(
            x=person_x,
            y=person_y,
            width=0.18,
            height=0.52,
            metadata=metadata,
        )
