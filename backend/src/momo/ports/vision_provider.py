"""Backward-compatible names for the Stage 7 pull-based frame-source port."""

from momo.domain.vision import VisionFrame
from momo.ports.frame_source import FrameSource

VisionProvider = FrameSource

__all__ = ["VisionFrame", "VisionProvider"]
