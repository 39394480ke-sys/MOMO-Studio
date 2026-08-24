"""Bounded pass-through encoding for already encoded local vision frames."""

from momo.domain.vision import (
    MAX_ENCODED_FRAME_BYTES,
    VisionFrame,
    VisionProviderCapability,
    VisionProviderKind,
    VisionProviderStatus,
)


class PassthroughVisionStreamEncoder:
    """Return PNG/JPEG bytes without retaining, transforming, or recording them."""

    def __init__(self, *, media_type: str = "image/png") -> None:
        if media_type not in {"image/png", "image/jpeg"}:
            raise ValueError("pass-through stream media_type must be image/png or image/jpeg")
        self._media_type = media_type

    @property
    def media_type(self) -> str:
        return self._media_type

    @property
    def capability(self) -> VisionProviderCapability:
        return VisionProviderCapability(
            provider_id="bounded-passthrough-stream-encoder",
            kind=VisionProviderKind.STREAM_ENCODER,
            status=VisionProviderStatus.AVAILABLE,
            display_name="Bounded image stream encoder",
            model_source=None,
            notice="Pass-through encoding only; frames are not stored or recorded.",
        )

    def encode(self, frame: VisionFrame) -> bytes:
        if frame.media_type != self._media_type:
            raise ValueError(
                f"frame media_type {frame.media_type!r} does not match {self._media_type!r}"
            )
        if len(frame.content) > MAX_ENCODED_FRAME_BYTES:  # domain validation also enforces this
            raise ValueError("encoded frame exceeds the stream size limit")
        return frame.content
