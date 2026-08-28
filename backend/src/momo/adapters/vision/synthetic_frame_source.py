"""Pull-paced deterministic synthetic video with no camera or storage access."""

from __future__ import annotations

import asyncio
import struct
import zlib
from collections.abc import Collection
from math import isfinite

from momo.adapters.time.system_clock import SystemClock
from momo.adapters.vision.synthetic_scene import SyntheticVisionScenario
from momo.domain.vision import (
    MAX_ENCODED_FRAME_BYTES,
    CameraAccessPolicy,
    FrameMetadata,
    TargetKind,
    VisionFrame,
    VisionProviderCapability,
    VisionProviderKind,
    VisionProviderStatus,
    VisionStatus,
)
from momo.ports.clock import Clock

MAX_SYNTHETIC_FPS = 30.0
MAX_SYNTHETIC_DELAY_S = 10.0


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


def _render_png(metadata: FrameMetadata, scenario: SyntheticVisionScenario) -> bytes:
    width = metadata.width_px
    height = metadata.height_px
    # Fixed dark background with sparse guide lines makes output deterministic while
    # keeping the compressed fixture small.
    row = bytearray((24, 31, 42) * width)
    pixels = bytearray()
    for y in range(height):
        current = bytearray(row)
        if y % 40 == 0:
            for x in range(width):
                offset = x * 3
                current[offset : offset + 3] = b"\x26\x30\x42"
        pixels.append(0)  # PNG filter type: None
        pixels.extend(current)

    def fill_box(box: tuple[int, int, int, int], colour: bytes) -> None:
        left, top, box_width, box_height = box
        right = min(width, left + box_width)
        bottom = min(height, top + box_height)
        for y in range(max(0, top), bottom):
            row_offset = y * (width * 3 + 1) + 1
            for x in range(max(0, left), right):
                offset = row_offset + x * 3
                pixels[offset : offset + 3] = colour

    person = scenario.bounding_box(metadata, TargetKind.PERSON)
    face = scenario.bounding_box(metadata, TargetKind.FACE)
    if person is not None:
        fill_box(person.to_pixels(), b"\x3b\x82\xf6")
    if face is not None:
        fill_box(face.to_pixels(), b"\xfd\xba\x74")

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    encoded = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(bytes(pixels), level=6))
        + _png_chunk(b"IEND", b"")
    )
    if len(encoded) > MAX_ENCODED_FRAME_BYTES:  # pragma: no cover - resolution cap proves this
        raise ValueError("synthetic encoded frame exceeds the domain frame-size limit")
    return encoded


class SyntheticFrameSource:
    """A deterministic, latest-only source whose rate is bounded at construction."""

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        source_id: str = "synthetic",
        width_px: int = 640,
        height_px: int = 360,
        fps: float = 10.0,
        delay_s: float = 0.0,
        disconnect_after_frames: int | None = None,
        lost_frame_numbers: Collection[int] = (),
        target_lost_after_frame: int | None = None,
        scenario: SyntheticVisionScenario | None = None,
        camera_access_policy: CameraAccessPolicy = CameraAccessPolicy.SYNTHETIC_ONLY,
    ) -> None:
        # Constructing even this synthetic adapter under DISABLED is an explicit
        # configuration error; LIVE_CAMERA_ALLOWED does not disable synthetic use.
        if camera_access_policy is CameraAccessPolicy.DISABLED:
            raise ValueError("camera access policy DISABLED forbids all frame sources")
        if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not isfinite(fps):
            raise ValueError("fps must be a finite number")
        if fps <= 0.0 or fps > MAX_SYNTHETIC_FPS:
            raise ValueError(f"fps must be greater than zero and at most {MAX_SYNTHETIC_FPS}")
        if (
            isinstance(delay_s, bool)
            or not isinstance(delay_s, (int, float))
            or not isfinite(delay_s)
            or delay_s < 0.0
            or delay_s > MAX_SYNTHETIC_DELAY_S
        ):
            raise ValueError(f"delay_s must be finite and between zero and {MAX_SYNTHETIC_DELAY_S}")
        if disconnect_after_frames is not None and (
            isinstance(disconnect_after_frames, bool)
            or not isinstance(disconnect_after_frames, int)
            or disconnect_after_frames < 0
        ):
            raise ValueError("disconnect_after_frames must be a non-negative integer")
        # Reuse domain validation for source identity and the resolution budget.
        FrameMetadata(
            frame_id="validation-00000001",
            source_id=source_id,
            captured_at=SystemClock().now(),
            width_px=width_px,
            height_px=height_px,
        )
        if scenario is not None and (lost_frame_numbers or target_lost_after_frame is not None):
            raise ValueError("configure target loss either through scenario or source arguments")

        self._clock = clock or SystemClock()
        self._source_id = source_id
        self._width_px = width_px
        self._height_px = height_px
        self._fps = float(fps)
        self._delay_s = float(delay_s)
        self._disconnect_after_frames = disconnect_after_frames
        self._scenario = scenario or SyntheticVisionScenario.with_lost_frames(
            lost_frame_numbers,
            target_lost_after_frame=target_lost_after_frame,
        )
        self._sequence = 0
        self._last_capture_monotonic: float | None = None
        self._status = VisionStatus.READY
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def status(self) -> VisionStatus:
        return self._status

    @property
    def scenario(self) -> SyntheticVisionScenario:
        return self._scenario

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def capability(self) -> VisionProviderCapability:
        return VisionProviderCapability(
            provider_id="synthetic-frame-source",
            kind=VisionProviderKind.FRAME_SOURCE,
            status=VisionProviderStatus.AVAILABLE,
            display_name="Synthetic video",
            model_source=None,
            notice="Generated in memory; frames are not stored or recorded.",
        )

    async def latest_frame(self) -> VisionFrame | None:
        async with self._lock:
            if self._closed or self._status is VisionStatus.DISCONNECTED:
                return None
            if (
                self._disconnect_after_frames is not None
                and self._sequence >= self._disconnect_after_frames
            ):
                self._status = VisionStatus.DISCONNECTED
                return None

            if self._last_capture_monotonic is not None:
                due_at = self._last_capture_monotonic + 1.0 / self._fps
                await self._clock.sleep(max(0.0, due_at - self._clock.monotonic()))
            self._last_capture_monotonic = self._clock.monotonic()
            self._sequence += 1
            metadata = FrameMetadata(
                frame_id=f"{self._source_id}-{self._sequence:08d}",
                source_id=self._source_id,
                captured_at=self._clock.now(),
                width_px=self._width_px,
                height_px=self._height_px,
            )
            frame = VisionFrame(
                metadata=metadata,
                content=_render_png(metadata, self._scenario),
                media_type="image/png",
            )
            if self._delay_s:
                await self._clock.sleep(self._delay_s)
            self._status = VisionStatus.STREAMING
            return frame

    async def disconnect(self) -> None:
        async with self._lock:
            if not self._closed:
                self._status = VisionStatus.DISCONNECTED

    async def aclose(self) -> None:
        async with self._lock:
            self._closed = True
            self._status = VisionStatus.CLOSED
