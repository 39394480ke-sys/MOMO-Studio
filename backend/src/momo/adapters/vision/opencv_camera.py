"""Optional OpenCV camera source with deny-before-import/open policy ordering.

This module deliberately has no ``cv2`` import.  The optional package is loaded only
by an explicit factory call, and ``VideoCapture`` is created only by an explicit
``await source.open()`` after the camera grant has already been validated.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from math import isfinite
from types import ModuleType
from typing import Protocol, cast

from momo.adapters.time.system_clock import SystemClock
from momo.domain.errors import VisionProviderUnavailableError
from momo.domain.vision import (
    CameraAccessPolicy,
    FrameMetadata,
    VisionFrame,
    VisionProviderCapability,
    VisionProviderKind,
    VisionProviderStatus,
    VisionStatus,
)
from momo.ports.clock import Clock

MAX_LIVE_CAMERA_FPS = 30.0
DeviceIdentifier = str | int


class CameraAccessDeniedError(PermissionError):
    """The complete live-camera grant was absent before device access."""


class _EncodedBuffer(Protocol):
    def tobytes(self) -> bytes: ...


class _CapturedImage(Protocol):
    @property
    def shape(self) -> tuple[int, ...]: ...


class _VideoCapture(Protocol):
    def isOpened(self) -> bool: ...

    def read(self) -> tuple[bool, _CapturedImage | None]: ...

    def release(self) -> None: ...


class _OpenCvModule(Protocol):
    def VideoCapture(self, device_identifier: DeviceIdentifier) -> _VideoCapture: ...

    def imencode(
        self,
        extension: str,
        image: _CapturedImage,
    ) -> tuple[bool, _EncodedBuffer]: ...


@dataclass(frozen=True, slots=True)
class _CameraGrant:
    policy: CameraAccessPolicy
    local_config_enabled: bool
    operator_action: bool

    def require_allowed(self) -> None:
        if self.policy is not CameraAccessPolicy.LIVE_CAMERA_ALLOWED:
            raise CameraAccessDeniedError("camera policy does not allow live camera access")
        if self.local_config_enabled is not True:
            raise CameraAccessDeniedError("live camera requires explicit local configuration")
        if self.operator_action is not True:
            raise CameraAccessDeniedError("live camera requires an explicit operator action")


def _validate_device_identifier(device_identifier: DeviceIdentifier) -> None:
    if isinstance(device_identifier, bool):
        raise ValueError("camera device identifier must be an explicit string or integer")
    if isinstance(device_identifier, int):
        if device_identifier < 0 or device_identifier > 64:
            raise ValueError("integer camera device identifier must be between 0 and 64")
        return
    if not isinstance(device_identifier, str):
        raise TypeError("camera device identifier must be an explicit string or integer")
    if not device_identifier.strip() or len(device_identifier) > 256:
        raise ValueError("string camera device identifier must be non-empty and bounded")


class OpenCvCameraSourceFactory:
    """The sole lazy-import construction path for the optional camera adapter."""

    def __init__(self, *, importer: Callable[[str], ModuleType] = import_module) -> None:
        self._importer = importer
        self._capability = VisionProviderCapability(
            provider_id="opencv-camera-source",
            kind=VisionProviderKind.FRAME_SOURCE,
            status=VisionProviderStatus.UNAVAILABLE,
            display_name="OpenCV live camera",
            model_source="Locally installed OpenCV package",
            notice="Optional local provider; it never enumerates devices or records frames.",
            detail="Not loaded; explicit live-camera construction is required",
        )

    @property
    def capability(self) -> VisionProviderCapability:
        return self._capability

    def create(
        self,
        *,
        camera_access_policy: CameraAccessPolicy,
        local_config_enabled: bool,
        device_identifier: DeviceIdentifier,
        operator_action: bool,
        source_id: str = "live-camera",
        clock: Clock | None = None,
        max_fps: float = 15.0,
    ) -> OpenCvCameraSource:
        grant = _CameraGrant(
            policy=camera_access_policy,
            local_config_enabled=local_config_enabled,
            operator_action=operator_action,
        )
        # Ordering is intentional: a denied request cannot even import the optional
        # dependency, much less call VideoCapture.
        grant.require_allowed()
        _validate_device_identifier(device_identifier)
        try:
            cv2_module = cast(_OpenCvModule, self._importer("cv2"))
        except (ImportError, ModuleNotFoundError) as error:
            self._capability = self._capability.model_copy(
                update={"detail": "OpenCV is not installed"}
            )
            raise VisionProviderUnavailableError(
                "OpenCV camera provider is unavailable",
                details={"provider_id": self._capability.provider_id},
            ) from error

        self._capability = self._capability.model_copy(
            update={"status": VisionProviderStatus.AVAILABLE, "detail": ""}
        )
        return OpenCvCameraSource(
            cv2_module=cv2_module,
            grant=grant,
            device_identifier=device_identifier,
            source_id=source_id,
            clock=clock,
            max_fps=max_fps,
        )


class OpenCvCameraSource:
    """One explicitly identified camera; construction performs no device access."""

    def __init__(
        self,
        *,
        cv2_module: _OpenCvModule,
        grant: _CameraGrant,
        device_identifier: DeviceIdentifier,
        source_id: str,
        clock: Clock | None,
        max_fps: float,
    ) -> None:
        _validate_device_identifier(device_identifier)
        if (
            isinstance(max_fps, bool)
            or not isinstance(max_fps, (int, float))
            or not isfinite(max_fps)
            or max_fps <= 0.0
            or max_fps > MAX_LIVE_CAMERA_FPS
        ):
            raise ValueError(f"max_fps must be finite, positive, and at most {MAX_LIVE_CAMERA_FPS}")
        # Source-ID validation occurs without exposing the device identifier.
        FrameMetadata(
            frame_id="validation-00000001",
            source_id=source_id,
            captured_at=SystemClock().now(),
            width_px=1,
            height_px=1,
        )
        self._cv2 = cv2_module
        self._grant = grant
        self._device_identifier = device_identifier
        self._source_id = source_id
        self._clock = clock or SystemClock()
        self._max_fps = float(max_fps)
        self._capture: _VideoCapture | None = None
        self._sequence = 0
        self._last_capture_monotonic: float | None = None
        self._status = VisionStatus.READY
        self._lock = asyncio.Lock()

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def status(self) -> VisionStatus:
        return self._status

    @property
    def capability(self) -> VisionProviderCapability:
        return VisionProviderCapability(
            provider_id="opencv-camera-source",
            kind=VisionProviderKind.FRAME_SOURCE,
            status=VisionProviderStatus.AVAILABLE,
            display_name="OpenCV live camera",
            model_source="Locally installed OpenCV package",
            notice="Explicit-ID local camera; no enumeration, persistence, or recording.",
        )

    async def open(self) -> None:
        async with self._lock:
            if self._capture is not None:
                return
            # Re-check immediately before the only VideoCapture call.  No constructor
            # and no status/capability query can reach this line.
            self._grant.require_allowed()
            capture = await asyncio.to_thread(self._cv2.VideoCapture, self._device_identifier)
            if not await asyncio.to_thread(capture.isOpened):
                await asyncio.to_thread(capture.release)
                self._status = VisionStatus.FAULTED
                raise RuntimeError("explicit camera device could not be opened")
            self._capture = capture
            self._status = VisionStatus.READY

    async def latest_frame(self) -> VisionFrame | None:
        async with self._lock:
            capture = self._capture
            if capture is None or self._status in {
                VisionStatus.DISCONNECTED,
                VisionStatus.CLOSED,
                VisionStatus.FAULTED,
            }:
                return None
            if self._last_capture_monotonic is not None:
                due_at = self._last_capture_monotonic + 1.0 / self._max_fps
                await self._clock.sleep(max(0.0, due_at - self._clock.monotonic()))
            self._last_capture_monotonic = self._clock.monotonic()
            ok, image = await asyncio.to_thread(capture.read)
            if not ok or image is None:
                await self._release_capture_unlocked(VisionStatus.DISCONNECTED)
                return None
            shape = image.shape
            if len(shape) < 2:
                await self._release_capture_unlocked(VisionStatus.FAULTED)
                raise ValueError("OpenCV camera returned an invalid frame shape")
            height_px, width_px = shape[0], shape[1]
            self._sequence += 1
            try:
                metadata = FrameMetadata(
                    frame_id=f"{self._source_id}-{self._sequence:08d}",
                    source_id=self._source_id,
                    captured_at=self._clock.now(),
                    width_px=width_px,
                    height_px=height_px,
                )
            except ValueError:
                await self._release_capture_unlocked(VisionStatus.FAULTED)
                raise
            encoded_ok, encoded = await asyncio.to_thread(self._cv2.imencode, ".jpg", image)
            if not encoded_ok:
                await self._release_capture_unlocked(VisionStatus.FAULTED)
                raise RuntimeError("OpenCV could not encode the captured frame")
            try:
                frame = VisionFrame(
                    metadata=metadata,
                    content=encoded.tobytes(),
                    media_type="image/jpeg",
                )
            except ValueError:
                await self._release_capture_unlocked(VisionStatus.FAULTED)
                raise
            self._status = VisionStatus.STREAMING
            return frame

    async def aclose(self) -> None:
        async with self._lock:
            await self._release_capture_unlocked(VisionStatus.CLOSED)

    async def _release_capture_unlocked(self, status: VisionStatus) -> None:
        capture = self._capture
        self._capture = None
        if capture is not None:
            await asyncio.to_thread(capture.release)
        self._status = status
