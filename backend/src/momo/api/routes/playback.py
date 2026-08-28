"""Prepared trajectory and playback API; no route accepts executable samples."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status

from momo.api.dependencies import (
    OptionalOperatorToken,
    authorize_real_playback_request,
    get_trajectory_service,
)
from momo.api.security import authorize_control_request, authorize_priority_stop_request
from momo.api.trajectory_presenters import preflight_response, preview_response
from momo.api.trajectory_schemas import (
    PlaybackLoopRequest,
    PlaybackRateRequest,
    PlaybackStartRequest,
    TrajectoryPreflightRequest,
    TrajectoryPreflightResponse,
    TrajectoryPreviewResponse,
)
from momo.application.services.device_diagnostics_service import DeviceDiagnosticsService
from momo.application.services.operator_session_service import OperatorSessionTokenError
from momo.application.services.trajectory_service import TrajectoryApplicationService
from momo.domain.enums import ControlMode, MotionMode
from momo.domain.playback import PlaybackStatus
from momo.domain.real_hardware import RealHardwareAuthorizationPurpose

router = APIRouter(tags=["trajectory-playback"])
TrajectoryService = Annotated[TrajectoryApplicationService, Depends(get_trajectory_service)]
TrajectoryDigestPath = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]


async def authorize_motion_playback_kind(
    motion_id: UUID,
    request: Request,
    service: TrajectoryService,
    token: OptionalOperatorToken = None,
) -> None:
    """Require Cartesian scope only when the stored Motion contains Cartesian legs."""

    device = request.app.state.device_diagnostics_service
    if not isinstance(device, DeviceDiagnosticsService):
        raise TypeError("device diagnostics service is not configured")
    if device.context.control_mode is not ControlMode.REAL:
        return
    if token is None:
        raise OperatorSessionTokenError("A valid operator session token is required")
    await device.authorize_operator_purpose(
        token,
        purpose=RealHardwareAuthorizationPurpose.REAL_PLAYBACK,
    )
    motion = await service.library.get_motion(motion_id)
    if any(
        keyframe.incoming_transition is not None
        and keyframe.incoming_transition.motion_mode is MotionMode.CARTESIAN_LINEAR
        for keyframe in motion.keyframes
    ):
        await device.authorize_operator_purpose(
            token,
            purpose=RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION,
        )


@router.post("/motions/{motion_id}/preflight", response_model=TrajectoryPreflightResponse)
async def preflight_motion(
    motion_id: UUID,
    request: TrajectoryPreflightRequest,
    service: TrajectoryService,
) -> TrajectoryPreflightResponse:
    outcome = await service.preflight(
        motion_id,
        expected_revision=request.expected_revision,
        sample_rate_hz=request.sample_rate_hz,
    )
    return preflight_response(outcome)


@router.post(
    "/motions/{motion_id}/play",
    response_model=PlaybackStatus,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(authorize_control_request),
        Depends(authorize_motion_playback_kind),
    ],
)
async def play_motion(
    motion_id: UUID,
    request: PlaybackStartRequest,
    service: TrajectoryService,
) -> PlaybackStatus:
    return await service.play(
        motion_id,
        expected_revision=request.expected_revision,
        trajectory_digest=request.trajectory_digest,
        loop=request.loop,
        rate=request.rate,
    )


@router.post(
    "/playback/pause",
    response_model=PlaybackStatus,
    dependencies=[
        Depends(authorize_control_request),
        Depends(authorize_real_playback_request),
    ],
)
async def pause_playback(service: TrajectoryService) -> PlaybackStatus:
    return await service.pause()


@router.post(
    "/playback/resume",
    response_model=PlaybackStatus,
    dependencies=[
        Depends(authorize_control_request),
        Depends(authorize_real_playback_request),
    ],
)
async def resume_playback(service: TrajectoryService) -> PlaybackStatus:
    return await service.resume()


@router.post(
    "/playback/stop",
    response_model=PlaybackStatus,
    dependencies=[Depends(authorize_priority_stop_request)],
)
async def stop_playback(service: TrajectoryService) -> PlaybackStatus:
    return await service.stop()


@router.put(
    "/playback/rate",
    response_model=PlaybackStatus,
    dependencies=[
        Depends(authorize_control_request),
        Depends(authorize_real_playback_request),
    ],
)
async def set_playback_rate(
    request: PlaybackRateRequest,
    service: TrajectoryService,
) -> PlaybackStatus:
    return await service.set_rate(request.rate)


@router.put(
    "/playback/loop",
    response_model=PlaybackStatus,
    dependencies=[
        Depends(authorize_control_request),
        Depends(authorize_real_playback_request),
    ],
)
async def set_playback_loop(
    request: PlaybackLoopRequest,
    service: TrajectoryService,
) -> PlaybackStatus:
    return await service.set_loop(request.loop)


@router.get("/playback", response_model=PlaybackStatus)
def get_playback(service: TrajectoryService) -> PlaybackStatus:
    return service.get_status()


@router.get("/trajectory/{digest}/preview", response_model=TrajectoryPreviewResponse)
async def preview_trajectory(
    digest: TrajectoryDigestPath,
    service: TrajectoryService,
) -> TrajectoryPreviewResponse:
    source = service.preview(digest)
    return preview_response(
        source.prepared,
        source.motion,
        sample_indices=source.sample_indices,
    )
