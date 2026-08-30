"""Latest-value Synthetic vision orchestration with bounded Follow ownership."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncGenerator, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from momo.application.services.robot_service import RobotApplicationService
from momo.application.services.vision_follow import VisionFollowService
from momo.domain.errors import (
    VisionFollowConflictError,
    VisionFrameConflictError,
    VisionProviderUnavailableError,
    VisionSelectionRequiredError,
)
from momo.domain.real_hardware import RealHardwareAuthorizationPurpose
from momo.domain.real_motion import RealExecutionAuthorization
from momo.domain.vision import (
    CameraAccessPolicy,
    Detection,
    FrameMetadata,
    NormalizedBoundingBox,
    TargetKind,
    TargetSelection,
    TrackingResult,
    TrackingStatus,
    VisionFrame,
    VisionProviderCapability,
    VisionProviderStatus,
    VisionStatus,
    box_matches_metadata,
)
from momo.domain.vision_follow import (
    FollowConfiguration,
    FollowOperatorIntent,
    FollowState,
    FollowStatus,
    FollowStopReason,
)
from momo.ports.clock import Clock
from momo.ports.vision import (
    FaceDetector,
    FrameSource,
    OperatorControlledFrameSource,
    TargetDetector,
    TargetTracker,
    VisionStreamEncoder,
)

REAL_FOLLOW_BLOCKED_REASON = (
    "Real Follow is blocked until camera, mapping, and motion are field verified."
)
MAX_FRAME_HISTORY = 64
MAX_FRAME_HISTORY_BYTES = 32 * 1024 * 1024
MAX_DETECTIONS_PER_REQUEST = 100


@dataclass(frozen=True, slots=True)
class VisionCapabilitiesSnapshot:
    camera_access_policy: CameraAccessPolicy
    source: VisionProviderCapability
    trackers: tuple[VisionProviderCapability, ...]
    detectors: tuple[VisionProviderCapability, ...]
    stream: VisionProviderCapability
    real_follow_blocked_reason: str = REAL_FOLLOW_BLOCKED_REASON


@dataclass(frozen=True, slots=True)
class VisionRuntimeSnapshot:
    camera_access_policy: CameraAccessPolicy
    source_state: VisionStatus
    latest_frame: FrameMetadata | None
    selection: TargetSelection | None
    tracking: TrackingResult | None
    follow: FollowStatus
    robot_state: str
    real_follow_blocked_reason: str = REAL_FOLLOW_BLOCKED_REASON


class VisionApplicationService:
    """Coordinate explicit frame pulls, frame-bound observations, and Follow.

    The service stores at most a small metadata/frame history for frame identity
    checks.  Stream consumers pull directly from the source; there is no event or
    image queue that can grow behind a slow client.
    """

    def __init__(
        self,
        *,
        camera_access_policy: CameraAccessPolicy,
        source: FrameSource,
        tracker: TargetTracker,
        person_detector: TargetDetector,
        face_detector: FaceDetector,
        stream_encoder: VisionStreamEncoder,
        follow: VisionFollowService,
        robot: RobotApplicationService,
        clock: Clock,
        max_stream_clients: int = 4,
        frame_request_freshness_s: float = 1.0,
        additional_tracker_capabilities: tuple[VisionProviderCapability, ...] = (),
        additional_detector_capabilities: tuple[VisionProviderCapability, ...] = (),
    ) -> None:
        if max_stream_clients < 1 or max_stream_clients > 16:
            raise ValueError("max_stream_clients must be between 1 and 16")
        if frame_request_freshness_s <= 0.0 or frame_request_freshness_s > 5.0:
            raise ValueError("frame_request_freshness_s must be in (0, 5]")
        self.camera_access_policy = camera_access_policy
        self.source = source
        self.tracker = tracker
        self.person_detector = person_detector
        self.face_detector = face_detector
        self.stream_encoder = stream_encoder
        self.follow = follow
        self.robot = robot
        self.clock = clock
        self.max_stream_clients = max_stream_clients
        self.frame_request_freshness_s = frame_request_freshness_s
        self.additional_tracker_capabilities = additional_tracker_capabilities
        self.additional_detector_capabilities = additional_detector_capabilities
        self._frames: deque[VisionFrame] = deque()
        self._frame_history_bytes = 0
        self._latest_frame: VisionFrame | None = None
        self._selection: TargetSelection | None = None
        self._tracking: TrackingResult | None = None
        self._frame_lock = asyncio.Lock()
        self._stream_lock = asyncio.Lock()
        self._active_streams = 0
        self._follow_pump: asyncio.Task[None] | None = None
        self._closed = False
        self._source_faulted = False

    @property
    def active_streams(self) -> int:
        return self._active_streams

    def capabilities(self) -> VisionCapabilitiesSnapshot:
        return VisionCapabilitiesSnapshot(
            camera_access_policy=self.camera_access_policy,
            source=self.source.capability,
            trackers=(self.tracker.capability, *self.additional_tracker_capabilities),
            detectors=(
                self.person_detector.capability,
                self.face_detector.capability,
                *self.additional_detector_capabilities,
            ),
            stream=self.stream_encoder.capability,
        )

    async def open_live_camera(self) -> VisionRuntimeSnapshot:
        """Open one configured camera only after the explicit HTTP operator action."""

        opening = asyncio.create_task(
            self._complete_open_live_camera(),
            name="vision-live-camera-explicit-open",
        )
        try:
            return await asyncio.shield(opening)
        except asyncio.CancelledError:
            with suppress(Exception):
                await asyncio.shield(opening)
            await asyncio.shield(self._close_live_camera_source())
            raise

    async def _complete_open_live_camera(self) -> VisionRuntimeSnapshot:
        if (
            self.camera_access_policy is not CameraAccessPolicy.LIVE_CAMERA_ALLOWED
            or not isinstance(self.source, OperatorControlledFrameSource)
        ):
            raise VisionProviderUnavailableError(
                "This runtime is not configured for an operator-controlled live camera"
            )
        if self._closed:
            raise VisionProviderUnavailableError("Vision service is closed")
        await self._stop_active_follow(FollowStopReason.OPERATOR_STOP)
        try:
            async with self._frame_lock:
                await self.source.open()
                self._source_faulted = False
                self._clear_frame_state_unlocked()
            frame = await self.capture_frame()
            if frame is None:
                raise VisionProviderUnavailableError(
                    "The configured live camera opened but returned no frame",
                    details={"provider_id": self.source.capability.provider_id},
                )
        except VisionProviderUnavailableError:
            await self._close_live_camera_source()
            raise
        except Exception as error:
            await self._close_live_camera_source()
            raise VisionProviderUnavailableError(
                "The configured live camera could not be opened",
                details={"provider_id": self.source.capability.provider_id},
            ) from error
        return await self.status()

    async def close_live_camera(self) -> VisionRuntimeSnapshot:
        """Release the configured live camera and discard all transient frame state."""

        closing = asyncio.create_task(
            self._complete_close_live_camera(),
            name="vision-live-camera-explicit-close",
        )
        try:
            return await asyncio.shield(closing)
        except asyncio.CancelledError:
            await asyncio.shield(closing)
            raise

    async def _complete_close_live_camera(self) -> VisionRuntimeSnapshot:
        if (
            self.camera_access_policy is not CameraAccessPolicy.LIVE_CAMERA_ALLOWED
            or not isinstance(self.source, OperatorControlledFrameSource)
        ):
            raise VisionProviderUnavailableError(
                "This runtime is not configured for an operator-controlled live camera"
            )
        await self._stop_active_follow(FollowStopReason.OPERATOR_STOP)
        await self._close_live_camera_source()
        return await self.status()

    async def status(self) -> VisionRuntimeSnapshot:
        robot_status = await self.robot.get_status()
        async with self._frame_lock:
            return VisionRuntimeSnapshot(
                camera_access_policy=self.camera_access_policy,
                source_state=(VisionStatus.FAULTED if self._source_faulted else self.source.status),
                latest_frame=(
                    self._latest_frame.metadata if self._latest_frame is not None else None
                ),
                selection=self._selection,
                tracking=self._tracking,
                follow=self.follow.get_status(),
                robot_state=robot_status.connection_state.value,
            )

    async def capture_frame(self) -> VisionFrame | None:
        """Pull one rate-limited frame and publish only its latest observation."""

        if self._closed:
            return None
        if self._source_faulted:
            if self.follow.follow_active:
                await self.follow.stop_for_event(FollowStopReason.CAMERA_DISCONNECTED)
            raise VisionProviderUnavailableError(
                "The configured frame source is faulted and requires restart"
            )
        stop_reason: FollowStopReason | None = None
        captured: VisionFrame | None = None
        source_error: Exception | None = None
        async with self._frame_lock:
            try:
                frame = await self.source.latest_frame()
            except Exception as error:
                self._source_faulted = True
                source_error = error
                frame = None
                stop_reason = FollowStopReason.CAMERA_DISCONNECTED
            if frame is None:
                if self.source.status in {
                    VisionStatus.DISCONNECTED,
                    VisionStatus.FAULTED,
                    VisionStatus.CLOSED,
                }:
                    stop_reason = FollowStopReason.CAMERA_DISCONNECTED
            else:
                captured = frame
                self._latest_frame = frame
                self._append_frame_unlocked(frame)
                if self._selection is not None:
                    try:
                        result = await self.tracker.update(frame)
                    except Exception as error:
                        result = TrackingResult(
                            metadata=frame.metadata,
                            status=TrackingStatus.FAULTED,
                            detail=f"{type(error).__name__}: tracker update failed",
                        )
                    if result.metadata != frame.metadata:
                        result = TrackingResult(
                            metadata=frame.metadata,
                            status=TrackingStatus.FAULTED,
                            detail="tracker update returned a different frame",
                        )
                    self._tracking = result
                    if result.status is TrackingStatus.FAULTED:
                        stop_reason = FollowStopReason.TRACKER_FAULT
                    elif self.follow.follow_active:
                        lease = self.follow.get_status().lease
                        if lease is not None:
                            await self.follow.process_tracking(lease.lease_id, result)

            if (
                stop_reason is FollowStopReason.CAMERA_DISCONNECTED
                and self._tracking is not None
                and self._latest_frame is not None
            ):
                # Source loss invalidates the last directional observation even
                # when no new frame exists on which a tracker could report LOST.
                # Keep the operator's selection separately, but never expose its
                # former LOCKED box as current tracking evidence.
                self._tracking = TrackingResult(
                    metadata=self._latest_frame.metadata,
                    status=TrackingStatus.FAULTED,
                    detail="frame source disconnected",
                )

        if stop_reason is not None and self.follow.follow_active:
            await self.follow.stop_for_event(stop_reason)
        if source_error is not None:
            raise VisionProviderUnavailableError(
                "The configured frame source failed",
                details={"provider_id": self.source.capability.provider_id},
            ) from source_error
        return captured

    async def stream_frames(self) -> AsyncGenerator[VisionFrame, None]:
        """Reserve one bounded pull subscriber and release it on disconnect."""

        async with self._stream_lock:
            if self._active_streams >= self.max_stream_clients:
                raise VisionProviderUnavailableError(
                    "The bounded Vision stream client limit was reached",
                    details={"maximum_clients": self.max_stream_clients},
                )
            self._active_streams += 1
        try:
            while not self._closed:
                frame = await self.capture_frame()
                if frame is None:
                    return
                yield frame
        finally:
            cleanup = asyncio.create_task(
                self._release_stream(),
                name="vision-stream-disconnect-cleanup",
            )
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                # Client cancellation cannot interrupt the safety cleanup owner.
                await asyncio.shield(cleanup)
                raise

    async def select(
        self,
        *,
        frame_id: str,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> VisionRuntimeSnapshot:
        self._require_analysis_allowed()
        await self._stop_active_follow(FollowStopReason.OPERATOR_STOP)
        async with self._frame_lock:
            frame = self._fresh_frame_unlocked(frame_id)
            box = NormalizedBoundingBox.from_metadata(
                x=x,
                y=y,
                width=width,
                height=height,
                metadata=frame.metadata,
            )
            selection = TargetSelection(bounding_box=box, target_kind=TargetKind.MANUAL)
            # Every valid reselection attempt first invalidates the prior target.
            # Provider absence/failure must not preserve an old LOCKED direction.
            self._selection = None
            self._tracking = None
            if self.tracker.capability.status is not VisionProviderStatus.AVAILABLE:
                self._tracking = TrackingResult(
                    metadata=frame.metadata,
                    status=TrackingStatus.FAULTED,
                    detail="selected target tracker is unavailable",
                )
                raise VisionProviderUnavailableError(
                    "The selected target tracker is unavailable",
                    details={"provider_id": self.tracker.capability.provider_id},
                )
            try:
                await self.tracker.reset()
                result = await self.tracker.initialize(frame, selection)
            except Exception as error:
                with suppress(Exception):
                    await self.tracker.reset()
                self._tracking = TrackingResult(
                    metadata=frame.metadata,
                    status=TrackingStatus.FAULTED,
                    detail=f"{type(error).__name__}: tracker initialization failed",
                )
                raise VisionProviderUnavailableError(
                    "The selected target tracker failed to initialize",
                    details={"provider_id": self.tracker.capability.provider_id},
                ) from error
            try:
                self._fresh_frame_unlocked(frame_id)
            except VisionFrameConflictError:
                with suppress(Exception):
                    await self.tracker.reset()
                self._tracking = TrackingResult(
                    metadata=frame.metadata,
                    status=TrackingStatus.STALE,
                    detail="tracker initialization completed after the frame expired",
                )
                raise
            if result.metadata != frame.metadata:
                with suppress(Exception):
                    await self.tracker.reset()
                self._tracking = TrackingResult(
                    metadata=frame.metadata,
                    status=TrackingStatus.FAULTED,
                    detail="tracker initialization returned a different frame",
                )
                raise VisionProviderUnavailableError(
                    "The selected target tracker returned a result for a different frame",
                    details={"provider_id": self.tracker.capability.provider_id},
                )
            if result.status is TrackingStatus.FAULTED:
                self._tracking = result
                raise VisionProviderUnavailableError(
                    "The selected target tracker failed to initialize",
                    details={"provider_id": self.tracker.capability.provider_id},
                )
            if result.status is TrackingStatus.STALE:
                self._tracking = result
                raise VisionFrameConflictError(
                    "The selected target frame became stale during tracker initialization",
                    details={"frame_id": frame.frame_id},
                )
            self._selection = selection
            self._tracking = result
        return await self.status()

    async def clear_selection(self) -> VisionRuntimeSnapshot:
        await self._stop_active_follow(FollowStopReason.OPERATOR_STOP)
        async with self._frame_lock:
            self._selection = None
            self._tracking = None
            try:
                await self.tracker.reset()
            except Exception as error:
                raise VisionProviderUnavailableError(
                    "The selected target tracker failed to reset",
                    details={"provider_id": self.tracker.capability.provider_id},
                ) from error
        return await self.status()

    async def reset_tracking(self) -> VisionRuntimeSnapshot:
        await self._stop_active_follow(FollowStopReason.OPERATOR_STOP)
        async with self._frame_lock:
            self._tracking = None
            try:
                await self.tracker.reset()
            except Exception as error:
                if self._latest_frame is not None:
                    self._tracking = TrackingResult(
                        metadata=self._latest_frame.metadata,
                        status=TrackingStatus.FAULTED,
                        detail=f"{type(error).__name__}: tracker reset failed",
                    )
                raise VisionProviderUnavailableError(
                    "The selected target tracker failed to reset",
                    details={"provider_id": self.tracker.capability.provider_id},
                ) from error
        return await self.status()

    async def detect(
        self,
        detector: Literal["person", "face"],
        frame_id: str,
    ) -> tuple[VisionProviderCapability, tuple[Detection, ...]]:
        self._require_analysis_allowed()
        provider: TargetDetector | FaceDetector = (
            self.person_detector if detector == "person" else self.face_detector
        )
        capability = provider.capability
        if capability.status is not VisionProviderStatus.AVAILABLE:
            return capability, ()
        async with self._frame_lock:
            frame = self._fresh_frame_unlocked(frame_id)
            try:
                detections: Sequence[Detection] = await provider.detect(frame)
            except VisionProviderUnavailableError:
                raise
            except Exception as error:
                raise VisionProviderUnavailableError(
                    "The selected detector failed",
                    details={"provider_id": capability.provider_id},
                ) from error
            self._fresh_frame_unlocked(frame_id)
        if len(detections) > MAX_DETECTIONS_PER_REQUEST:
            raise VisionProviderUnavailableError(
                "Vision detector exceeded the bounded result capacity",
                details={"maximum_detections": MAX_DETECTIONS_PER_REQUEST},
            )
        if any(not box_matches_metadata(item.bounding_box, frame.metadata) for item in detections):
            raise VisionProviderUnavailableError(
                "The selected detector returned observations for a different frame",
                details={"provider_id": capability.provider_id},
            )
        return capability, tuple(detections)

    async def start_follow(
        self,
        configuration: FollowConfiguration,
        *,
        authorization: RealExecutionAuthorization | None = None,
        execution_purpose: RealHardwareAuthorizationPurpose | None = None,
    ) -> FollowStatus:
        if self.camera_access_policy is CameraAccessPolicy.LIVE_CAMERA_ALLOWED:
            raise VisionFollowConflictError(
                "The live camera session is read-only; tracking and Follow are disabled"
            )
        async with self._frame_lock:
            if self._source_faulted or self.source.status in {
                VisionStatus.DISCONNECTED,
                VisionStatus.FAULTED,
                VisionStatus.CLOSED,
            }:
                raise VisionFollowConflictError("The Synthetic frame source is unavailable")
            if self._selection is None or self._tracking is None:
                raise VisionSelectionRequiredError(
                    "Select and lock a current target before starting Follow"
                )
            if self._tracking.status is not TrackingStatus.LOCKED:
                raise VisionSelectionRequiredError(
                    "The current target must be LOCKED before starting Follow"
                )
            try:
                status = await self.follow.start(
                    FollowOperatorIntent(
                        confirmed=True,
                        configuration=configuration,
                    ),
                    authorization=authorization,
                    execution_purpose=execution_purpose,
                )
                lease = status.lease
                if lease is None:  # pragma: no cover - domain state invariant
                    raise AssertionError("ACTIVE Follow omitted its lease")
                processed = await self.follow.process_tracking(lease.lease_id, self._tracking)
                if processed.state is not FollowState.ACTIVE:
                    reason = (
                        processed.stop_reason.value if processed.stop_reason is not None else None
                    )
                    raise VisionFollowConflictError(
                        "Vision Follow stopped during initial target preflight",
                        details={"reason": reason},
                    )
            except asyncio.CancelledError:
                # Losing the request that owns the explicit start intent must not
                # leave an ACTIVE lease before its frame pump has been installed.
                active = self.follow.get_status()
                if active.state is FollowState.ACTIVE and active.lease is not None:
                    cleanup = asyncio.create_task(
                        self.follow.browser_disconnected(active.lease.lease_id),
                        name="vision-follow-cancelled-start-cleanup",
                    )
                    await asyncio.shield(cleanup)
                raise
        self._start_follow_pump()
        return self.follow.get_status()

    async def heartbeat_follow(
        self,
        lease_id: UUID,
        *,
        authorization: RealExecutionAuthorization | None = None,
        execution_purpose: RealHardwareAuthorizationPurpose | None = None,
    ) -> FollowStatus:
        return await self.follow.heartbeat(
            lease_id,
            authorization=authorization,
            execution_purpose=execution_purpose,
        )

    async def stop_follow(self, lease_id: UUID) -> VisionRuntimeSnapshot:
        cleanup = asyncio.create_task(
            self._complete_stop_follow(lease_id),
            name=f"vision-follow-explicit-stop-{lease_id}",
        )
        try:
            return await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            # The first HTTP caller does not own the safety consequence. Finish
            # cancelling the pump/command even if that caller disconnects.
            await asyncio.shield(cleanup)
            raise

    def encode_stream_frame(self, frame: VisionFrame) -> bytes:
        return self.stream_encoder.encode(frame)

    async def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._cancel_follow_pump()
            await self.follow.shutdown()
        finally:
            with suppress(Exception):
                await self.tracker.reset()
            await self.source.aclose()

    def _append_frame_unlocked(self, frame: VisionFrame) -> None:
        self._frames.append(frame)
        self._frame_history_bytes += len(frame.content)
        while len(self._frames) > 1 and (
            len(self._frames) > MAX_FRAME_HISTORY
            or self._frame_history_bytes > MAX_FRAME_HISTORY_BYTES
        ):
            removed = self._frames.popleft()
            self._frame_history_bytes -= len(removed.content)

    def _clear_frame_state_unlocked(self) -> None:
        self._frames.clear()
        self._frame_history_bytes = 0
        self._latest_frame = None
        self._selection = None
        self._tracking = None

    async def _close_live_camera_source(self) -> None:
        async with self._frame_lock:
            await self.source.aclose()
            self._source_faulted = False
            self._clear_frame_state_unlocked()

    def _require_analysis_allowed(self) -> None:
        if self.camera_access_policy is CameraAccessPolicy.LIVE_CAMERA_ALLOWED:
            raise VisionProviderUnavailableError(
                "The live camera session is read-only; selection, detection, and tracking "
                "are disabled"
            )

    async def _release_stream(self) -> None:
        async with self._stream_lock:
            self._active_streams = max(0, self._active_streams - 1)
        follow_status = self.follow.get_status()
        if follow_status.state is FollowState.ACTIVE and follow_status.lease is not None:
            await self._cancel_follow_pump()
            await self.follow.browser_disconnected(follow_status.lease.lease_id)

    def _fresh_frame_unlocked(self, frame_id: str) -> VisionFrame:
        frame = next((item for item in reversed(self._frames) if item.frame_id == frame_id), None)
        if frame is None:
            raise VisionFrameConflictError(
                "The requested frame is no longer in the bounded frame history",
                details={"frame_id": frame_id},
            )
        age_s = (self.clock.now() - frame.captured_at).total_seconds()
        if age_s < -self.frame_request_freshness_s or age_s > self.frame_request_freshness_s:
            raise VisionFrameConflictError(
                "The requested frame is stale",
                details={"frame_id": frame_id, "age_s": age_s},
            )
        return frame

    def _start_follow_pump(self) -> None:
        task = self._follow_pump
        if task is not None and not task.done():
            return
        self._follow_pump = asyncio.create_task(
            self._run_follow_pump(),
            name="synthetic-vision-follow-pump",
        )

    async def _run_follow_pump(self) -> None:
        try:
            while not self._closed and self.follow.follow_active:
                frame = await self.capture_frame()
                if frame is None:
                    return
        except asyncio.CancelledError:
            return
        except Exception:
            if self.follow.follow_active:
                await self.follow.stop_for_event(FollowStopReason.TRACKER_FAULT)

    async def _cancel_follow_pump(self) -> None:
        task = self._follow_pump
        self._follow_pump = None
        if task is None or task.done() or task is asyncio.current_task():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _complete_stop_follow(self, lease_id: UUID) -> VisionRuntimeSnapshot:
        await self._cancel_follow_pump()
        await self.follow.stop(lease_id)
        return await self.status()

    async def _stop_active_follow(self, reason: FollowStopReason) -> None:
        status = self.follow.get_status()
        if status.state is not FollowState.ACTIVE or status.lease is None:
            return
        await self._cancel_follow_pump()
        await self.follow.stop(status.lease.lease_id, reason)
