"""Synthetic-only Stage 7 Vision and lease-bound Dry Run Follow routes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse

from momo.api.dependencies import authorize_real_vision_follow_request, get_vision_service
from momo.api.security import (
    authorize_control_keepalive_request,
    authorize_control_request,
    authorize_priority_stop_request,
    reauthorize_http_stream,
)
from momo.api.vision_schemas import (
    NormalizedBoundingBoxDto,
    VisionCameraOpenRequest,
    VisionCapabilitiesResponse,
    VisionDetectionRequest,
    VisionDetectionResponse,
    VisionDetectionResponseItem,
    VisionFollowLeaseResponse,
    VisionFollowStartRequest,
    VisionFollowStatusResponse,
    VisionFrameMetadataResponse,
    VisionProviderCapabilityResponse,
    VisionSelectionRequest,
    VisionStatusResponse,
    VisionTargetSelectionResponse,
    VisionTrackingResponse,
)
from momo.application.services.vision_service import (
    VisionApplicationService,
    VisionCapabilitiesSnapshot,
    VisionRuntimeSnapshot,
)
from momo.domain.errors import VisionProviderUnavailableError
from momo.domain.security import SecuritySurface
from momo.domain.vision import (
    NormalizedBoundingBox,
    TrackingStatus,
    VisionProviderCapability,
    VisionProviderStatus,
    VisionStatus,
)
from momo.domain.vision_follow import (
    FollowActuatorMapping,
    FollowConfiguration,
    FollowState,
    FollowStatus,
)

router = APIRouter(prefix="/vision", tags=["vision"])
VisionServiceDependency = Annotated[VisionApplicationService, Depends(get_vision_service)]
STREAM_BOUNDARY = "momo-vision-frame"
PublicTrackingStatus = Literal["LOCKED", "LOST", "STALE", "FAULTED"]


def _capability(
    value: VisionProviderCapability,
    *,
    active: bool,
) -> VisionProviderCapabilityResponse:
    available = value.status is VisionProviderStatus.AVAILABLE
    return VisionProviderCapabilityResponse(
        provider_id=value.provider_id,
        kind=value.kind.value,
        available=available,
        active=active and available,
        model_source=value.model_source or "No external model",
        notice=value.notice,
        reason=value.detail or (None if available else "Provider is unavailable"),
    )


def _box(value: NormalizedBoundingBox) -> NormalizedBoundingBoxDto:
    return NormalizedBoundingBoxDto(
        x=value.x,
        y=value.y,
        width=value.width,
        height=value.height,
    )


def _follow(value: FollowStatus) -> VisionFollowStatusResponse:
    metrics = value.metrics
    lease = value.lease
    return VisionFollowStatusResponse(
        active=value.state is FollowState.ACTIVE,
        lease_id=lease.lease_id if lease is not None else None,
        expires_at=lease.expires_at if lease is not None else None,
        stop_reason=value.stop_reason.value if value.stop_reason is not None else None,
        error_x=metrics.error_x if metrics is not None else None,
        error_y=metrics.error_y if metrics is not None else None,
        ema_error_x=metrics.ema_error_x if metrics is not None else None,
        ema_error_y=metrics.ema_error_y if metrics is not None else None,
        last_command_id=value.active_command_id,
    )


def _status(
    snapshot: VisionRuntimeSnapshot,
    *,
    now: datetime,
) -> VisionStatusResponse:
    metadata = snapshot.latest_frame
    latest = None
    if metadata is not None:
        age_ms = max(0.0, (now - metadata.captured_at).total_seconds() * 1000.0)
        latest = VisionFrameMetadataResponse(
            frame_id=metadata.frame_id,
            width_px=metadata.width_px,
            height_px=metadata.height_px,
            captured_at=metadata.captured_at,
            source_id=metadata.source_id,
            age_ms=age_ms,
        )
    selection = None
    if snapshot.selection is not None:
        selection_box = snapshot.selection.bounding_box
        selection = VisionTargetSelectionResponse(
            frame_id=selection_box.frame_id,
            bounding_box=_box(selection_box),
        )
    tracking = None
    if snapshot.tracking is not None:
        result = snapshot.tracking
        tracking_box = result.bounding_box
        public_status = cast(
            PublicTrackingStatus,
            result.status.value
            if result.status
            in {
                TrackingStatus.LOCKED,
                TrackingStatus.LOST,
                TrackingStatus.STALE,
                TrackingStatus.FAULTED,
            }
            else TrackingStatus.LOST.value,
        )
        tracking = VisionTrackingResponse(
            frame_id=result.metadata.frame_id,
            source_id=result.metadata.source_id,
            captured_at=result.metadata.captured_at,
            bounding_box=_box(tracking_box) if tracking_box is not None else None,
            confidence=result.confidence,
            status=public_status,
            error=result.detail or None,
        )
    return VisionStatusResponse(
        camera_access_policy=snapshot.camera_access_policy.value,
        source_state=snapshot.source_state.value,
        latest_frame=latest,
        selection=selection,
        tracking=tracking,
        follow=_follow(snapshot.follow),
        robot_state=snapshot.robot_state,
        real_follow_blocked_reason=snapshot.real_follow_blocked_reason,
    )


def _capabilities(
    snapshot: VisionCapabilitiesSnapshot,
    runtime: VisionRuntimeSnapshot,
    service: VisionApplicationService,
) -> VisionCapabilitiesResponse:
    return VisionCapabilitiesResponse(
        camera_access_policy=snapshot.camera_access_policy.value,
        source=_capability(
            snapshot.source,
            active=runtime.source_state.value in {"READY", "STREAMING"},
        ),
        trackers=[
            _capability(item, active=runtime.tracking is not None) for item in snapshot.trackers
        ],
        detectors=[_capability(item, active=False) for item in snapshot.detectors],
        stream=_capability(snapshot.stream, active=service.active_streams > 0),
        real_follow_blocked_reason=snapshot.real_follow_blocked_reason,
    )


@router.get("/capabilities", response_model=VisionCapabilitiesResponse)
async def capabilities(service: VisionServiceDependency) -> VisionCapabilitiesResponse:
    runtime = await service.status()
    return _capabilities(service.capabilities(), runtime, service)


@router.get("/status", response_model=VisionStatusResponse)
async def vision_status(service: VisionServiceDependency) -> VisionStatusResponse:
    return _status(await service.status(), now=service.clock.now())


@router.post(
    "/camera/open",
    response_model=VisionStatusResponse,
    dependencies=[Depends(authorize_control_request)],
)
async def open_live_camera(
    request: VisionCameraOpenRequest,
    service: VisionServiceDependency,
) -> VisionStatusResponse:
    del request
    return _status(await service.open_live_camera(), now=service.clock.now())


@router.post(
    "/camera/close",
    response_model=VisionStatusResponse,
    dependencies=[Depends(authorize_priority_stop_request)],
)
async def close_live_camera(service: VisionServiceDependency) -> VisionStatusResponse:
    return _status(await service.close_live_camera(), now=service.clock.now())


@router.get("/frame")
async def latest_frame(service: VisionServiceDependency) -> Response:
    frame = await service.capture_frame()
    if frame is None:
        raise VisionProviderUnavailableError("The configured frame source has no current frame")
    return Response(
        content=frame.content,
        media_type=frame.media_type,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "X-Frame-Id": frame.frame_id,
            "X-Source-Id": frame.source_id,
            "X-Captured-At": frame.captured_at.isoformat(),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/stream")
async def stream(request: Request, service: VisionServiceDependency) -> StreamingResponse:
    if service.source.capability.status is not VisionProviderStatus.AVAILABLE:
        raise VisionProviderUnavailableError(
            service.source.capability.detail or "The configured frame source is unavailable"
        )
    if service.source.status not in {VisionStatus.READY, VisionStatus.STREAMING}:
        raise VisionProviderUnavailableError(
            "The configured frame source is not open",
            details={"source_state": service.source.status.value},
        )

    async def parts() -> AsyncIterator[bytes]:
        async for frame in service.stream_frames():
            if not reauthorize_http_stream(request, SecuritySurface.VISION):
                return
            payload = service.encode_stream_frame(frame)
            headers = (
                f"--{STREAM_BOUNDARY}\r\n"
                f"Content-Type: {frame.media_type}\r\n"
                f"Content-Length: {len(payload)}\r\n"
                f"X-Frame-Id: {frame.frame_id}\r\n"
                "Cache-Control: no-store\r\n\r\n"
            ).encode("ascii")
            yield headers + payload + b"\r\n"

    return StreamingResponse(
        parts(),
        media_type=f"multipart/x-mixed-replace; boundary={STREAM_BOUNDARY}",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/selection", response_model=VisionStatusResponse)
async def select_target(
    request: VisionSelectionRequest,
    service: VisionServiceDependency,
) -> VisionStatusResponse:
    box = request.bounding_box
    snapshot = await service.select(
        frame_id=request.frame_id,
        x=box.x,
        y=box.y,
        width=box.width,
        height=box.height,
    )
    return _status(snapshot, now=service.clock.now())


@router.delete("/selection", response_model=VisionStatusResponse)
async def clear_target(service: VisionServiceDependency) -> VisionStatusResponse:
    return _status(await service.clear_selection(), now=service.clock.now())


@router.post("/detect/{detector}", response_model=VisionDetectionResponse)
async def detect_target(
    detector: Literal["person", "face"],
    request: VisionDetectionRequest,
    service: VisionServiceDependency,
) -> VisionDetectionResponse:
    capability, detections = await service.detect(detector, request.frame_id)
    return VisionDetectionResponse(
        capability=_capability(capability, active=False),
        detections=[
            VisionDetectionResponseItem(
                detection_id=(f"{item.provider_id}:{item.metadata.frame_id}:{index}"),
                frame_id=item.metadata.frame_id,
                source_id=item.metadata.source_id,
                captured_at=item.metadata.captured_at,
                bounding_box=_box(item.bounding_box),
                confidence=item.confidence,
                label=item.target_kind.value.lower(),
            )
            for index, item in enumerate(detections, start=1)
        ],
    )


@router.post("/tracking/reset", response_model=VisionStatusResponse)
async def reset_tracking(service: VisionServiceDependency) -> VisionStatusResponse:
    return _status(await service.reset_tracking(), now=service.clock.now())


@router.post(
    "/follow/start",
    response_model=VisionFollowLeaseResponse,
    dependencies=[
        Depends(authorize_control_keepalive_request),
        Depends(authorize_real_vision_follow_request),
    ],
)
async def start_follow(
    request: VisionFollowStartRequest,
    service: VisionServiceDependency,
) -> VisionFollowLeaseResponse:
    mapping = FollowActuatorMapping.model_validate(request.mapping.model_dump(mode="python"))
    configuration = FollowConfiguration.model_validate(
        {
            **request.configuration.model_dump(mode="python"),
            "mapping": mapping,
        }
    )
    follow = await service.start_follow(configuration)
    lease = follow.lease
    if lease is None:  # pragma: no cover - Follow domain invariant
        raise AssertionError("Follow start omitted its lease")
    runtime = await service.status()
    return VisionFollowLeaseResponse(
        lease_id=lease.lease_id,
        expires_at=lease.expires_at,
        status=_status(runtime, now=service.clock.now()),
    )


@router.post(
    "/follow/{lease_id}/heartbeat",
    response_model=VisionFollowLeaseResponse,
    dependencies=[
        Depends(authorize_control_request),
        Depends(authorize_real_vision_follow_request),
    ],
)
async def heartbeat_follow(
    lease_id: UUID,
    service: VisionServiceDependency,
) -> VisionFollowLeaseResponse:
    follow = await service.heartbeat_follow(lease_id)
    lease = follow.lease
    if lease is None:  # pragma: no cover - Follow domain invariant
        raise AssertionError("Follow heartbeat omitted its lease")
    return VisionFollowLeaseResponse(
        lease_id=lease.lease_id,
        expires_at=lease.expires_at,
        status=_status(await service.status(), now=service.clock.now()),
    )


@router.post(
    "/follow/{lease_id}/stop",
    response_model=VisionStatusResponse,
    dependencies=[Depends(authorize_priority_stop_request)],
)
async def stop_follow(
    lease_id: UUID,
    service: VisionServiceDependency,
) -> VisionStatusResponse:
    return _status(await service.stop_follow(lease_id), now=service.clock.now())
