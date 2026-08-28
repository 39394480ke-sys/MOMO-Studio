"""Shared bounded HTTP presentation for compiler evidence and trajectory previews."""

from uuid import UUID

from momo.api.trajectory_schemas import (
    TrajectoryKeyframeMarker,
    TrajectoryPreflightResponse,
    TrajectoryPreviewPoint,
    TrajectoryPreviewResponse,
    TrajectorySegmentPreview,
    TrajectoryTcpPreviewPoint,
)
from momo.domain.enums import MotionMode
from momo.domain.motion import Motion
from momo.domain.trajectory import (
    PreparedTrajectory,
    TrajectoryCompileOutcome,
    TrajectorySegmentKind,
)

PREVIEW_POINT_LIMIT = 1000


def preflight_response(outcome: TrajectoryCompileOutcome) -> TrajectoryPreflightResponse:
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


def preview_indices(sample_count: int) -> tuple[int, ...]:
    if sample_count <= PREVIEW_POINT_LIMIT:
        return tuple(range(sample_count))
    last = sample_count - 1
    return tuple(
        sorted(
            {
                round(index * last / (PREVIEW_POINT_LIMIT - 1))
                for index in range(PREVIEW_POINT_LIMIT)
            }
        )
    )


def preview_response(
    prepared: PreparedTrajectory,
    motion: Motion,
    *,
    sample_indices: tuple[int, ...] | None = None,
) -> TrajectoryPreviewResponse:
    plan = prepared.plan
    indices = sample_indices if sample_indices is not None else preview_indices(len(plan.samples))
    joint_series = {
        joint_id: [
            TrajectoryPreviewPoint(
                time_s=plan.samples[index].time_s,
                value=plan.samples[index].positions[joint_id],
                unit=plan.samples[index].units[joint_id],
            )
            for index in indices
        ]
        for joint_id in plan.samples[0].positions
    }
    tcp_path = []
    for index in indices:
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
    labels = {keyframe.id: keyframe.label for keyframe in motion.keyframes}
    marker_data: dict[UUID, tuple[float, int]] = {motion.keyframes[0].id: (0.0, 0)}
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
        for keyframe in motion.keyframes
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
