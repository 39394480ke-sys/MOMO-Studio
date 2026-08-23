"""Prepared trajectory and playback API; no route accepts executable samples."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, status

from momo.api.dependencies import get_trajectory_service
from momo.api.trajectory_schemas import (
    PlaybackLoopRequest,
    PlaybackRateRequest,
    PlaybackStartRequest,
    TrajectoryKeyframeMarker,
    TrajectoryPreflightRequest,
    TrajectoryPreflightResponse,
    TrajectoryPreviewPoint,
    TrajectoryPreviewResponse,
    TrajectorySegmentPreview,
    TrajectoryTcpPreviewPoint,
)
from momo.application.services.trajectory_service import TrajectoryApplicationService
from momo.domain.enums import MotionMode
from momo.domain.playback import PlaybackStatus
from momo.domain.trajectory import TrajectoryCompileOutcome, TrajectorySegmentKind

router = APIRouter(tags=["trajectory-playback"])
TrajectoryService = Annotated[TrajectoryApplicationService, Depends(get_trajectory_service)]
TrajectoryDigestPath = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]


def _preflight_response(outcome: TrajectoryCompileOutcome) -> TrajectoryPreflightResponse:
    report = outcome.report
    return TrajectoryPreflightResponse(
        passed=report.accepted,
        digest=report.digest.sha256 if report.digest is not None else None,
        motion_id=report.motion_id,
        motion_revision=report.motion_revision,
        duration_s=report.duration_s,
        sample_count=report.sample_count,
        segment_count=report.segment_count,
        sample_rate_hz=report.sample_rate_hz,
        violations=list(report.violations),
        checks=list(report.checks),
        prepared_at=(outcome.prepared.plan.compiled_at if outcome.prepared is not None else None),
        real_motion_ready=False,
        field_acceptance_ready=False,
        hardware_accessed=False,
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
    return _preflight_response(outcome)


@router.post(
    "/motions/{motion_id}/play",
    response_model=PlaybackStatus,
    status_code=status.HTTP_202_ACCEPTED,
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


@router.post("/playback/pause", response_model=PlaybackStatus)
async def pause_playback(service: TrajectoryService) -> PlaybackStatus:
    return await service.pause()


@router.post("/playback/resume", response_model=PlaybackStatus)
async def resume_playback(service: TrajectoryService) -> PlaybackStatus:
    return await service.resume()


@router.post("/playback/stop", response_model=PlaybackStatus)
async def stop_playback(service: TrajectoryService) -> PlaybackStatus:
    return await service.stop()


@router.put("/playback/rate", response_model=PlaybackStatus)
async def set_playback_rate(
    request: PlaybackRateRequest,
    service: TrajectoryService,
) -> PlaybackStatus:
    return await service.set_rate(request.rate)


@router.put("/playback/loop", response_model=PlaybackStatus)
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
    plan = source.prepared.plan
    joint_series = {
        joint_id: [
            TrajectoryPreviewPoint(
                time_s=plan.samples[index].time_s,
                value=plan.samples[index].positions[joint_id],
                unit=plan.samples[index].units[joint_id],
            )
            for index in source.sample_indices
        ]
        for joint_id in plan.samples[0].positions
    }
    tcp_path = []
    for index in source.sample_indices:
        sample = plan.samples[index]
        if sample.tcp_pose is None:
            continue
        position = sample.tcp_pose.position_mm
        tcp_path.append(
            TrajectoryTcpPreviewPoint(
                time_s=sample.time_s,
                x_mm=position.x,
                y_mm=position.y,
                z_mm=position.z,
            )
        )
    segments = [
        TrajectorySegmentPreview(
            segment_index=segment.segment_index,
            motion_mode=(
                MotionMode.JOINT
                if segment.kind is TrajectorySegmentKind.JOINT
                else (
                    MotionMode.CARTESIAN_LINEAR
                    if segment.kind is TrajectorySegmentKind.CARTESIAN_LINEAR
                    else "HOLD"
                )
            ),
            start_time_s=segment.start_time_s,
            end_time_s=segment.end_time_s,
            sample_count=segment.end_sample_index - segment.start_sample_index + 1,
            start_keyframe_id=segment.from_keyframe_id,
            end_keyframe_id=segment.to_keyframe_id,
        )
        for segment in plan.segments
    ]
    labels = {keyframe.id: keyframe.label for keyframe in source.motion.keyframes}
    marker_data: dict[UUID, tuple[float, int]] = {source.motion.keyframes[0].id: (0.0, 0)}
    for segment in plan.segments:
        if segment.kind is not TrajectorySegmentKind.HOLD:
            marker_data[segment.to_keyframe_id] = (
                segment.end_time_s,
                segment.end_sample_index,
            )
    markers = [
        TrajectoryKeyframeMarker(
            keyframe_id=keyframe.id,
            label=labels[keyframe.id],
            time_s=marker_data[keyframe.id][0],
            sample_index=marker_data[keyframe.id][1],
        )
        for keyframe in source.motion.keyframes
        if keyframe.id in marker_data
    ]
    return TrajectoryPreviewResponse(
        digest=plan.digest.sha256,
        motion_id=plan.motion_id,
        duration_s=plan.duration_s,
        sample_rate_hz=plan.sample_rate_hz,
        sample_count=len(plan.samples),
        segments=segments,
        joint_series=joint_series,
        tcp_path=tcp_path,
        keyframe_markers=markers,
    )
