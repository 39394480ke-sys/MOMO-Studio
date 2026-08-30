"""Compile the exact command samples before the final safety gateway returns."""

from __future__ import annotations

from datetime import datetime
from math import ceil
from uuid import uuid4

from momo.domain.enums import Easing
from momo.domain.motion_preflight import PreparedContinuousJog, PreparedMotion
from momo.domain.robot import RobotProfile
from momo.domain.trajectory import (
    PreparedTrajectory,
    TrajectoryDigest,
    TrajectoryPlan,
    TrajectoryPreflightCheck,
    TrajectoryPreflightReport,
    TrajectorySample,
    TrajectorySegment,
    TrajectorySegmentKind,
)


def compile_gateway_command_trajectory(
    prepared: PreparedMotion | PreparedContinuousJog,
    profile: RobotProfile,
    state_sequence: int,
    segment_kind: TrajectorySegmentKind,
    *,
    compiled_at: datetime,
    update_hz: float,
    real_motion_ready: bool = False,
    field_acceptance_ready: bool = False,
) -> PreparedTrajectory:
    """Bind gateway-reviewed samples, report, and digest into one immutable value."""

    if not prepared.preflight.accepted:
        raise ValueError("a rejected command preflight cannot become executable")
    if segment_kind not in {
        TrajectorySegmentKind.JOINT,
        TrajectorySegmentKind.CARTESIAN_LINEAR,
    }:
        raise ValueError("command trajectories require a motion segment kind")
    start_id = uuid4()
    end_id = uuid4()
    samples, duration_s, easing = _exact_samples(
        prepared,
        profile,
        start_id=start_id,
        end_id=end_id,
        update_hz=update_hz,
    )
    segment = TrajectorySegment(
        segment_index=0,
        kind=segment_kind,
        from_keyframe_id=start_id,
        to_keyframe_id=end_id,
        easing=easing,
        start_time_s=0.0,
        end_time_s=duration_s,
        duration_s=duration_s,
        start_sample_index=0,
        end_sample_index=len(samples) - 1,
        generated_sample_count=len(samples) - 1,
    )
    provisional = TrajectoryPlan.model_construct(
        motion_id=prepared.command_id,
        motion_revision=1,
        robot_variant=profile.variant,
        profile_fingerprint=profile.fingerprint,
        kinematics_fingerprint=prepared.preflight.kinematics_fingerprint,
        start_state_sequence=state_sequence,
        sample_rate_hz=float(update_hz),
        duration_s=duration_s,
        segments=[segment],
        samples=samples,
        digest=TrajectoryDigest(sha256="0" * 64),
        compiled_at=compiled_at,
    )
    digest = TrajectoryDigest(sha256=provisional.computed_sha256)
    plan = TrajectoryPlan(
        motion_id=prepared.command_id,
        motion_revision=1,
        robot_variant=profile.variant,
        profile_fingerprint=profile.fingerprint,
        kinematics_fingerprint=prepared.preflight.kinematics_fingerprint,
        start_state_sequence=state_sequence,
        sample_rate_hz=float(update_hz),
        duration_s=duration_s,
        segments=[segment],
        samples=samples,
        digest=digest,
        compiled_at=compiled_at,
    )
    checks = [
        TrajectoryPreflightCheck(
            name=check.name,
            passed=check.passed,
            detail=check.detail,
        )
        for check in prepared.preflight.checks
    ]
    checks.append(
        TrajectoryPreflightCheck(
            name="exact_sample_digest",
            passed=True,
            detail=(
                f"Final gateway bound {len(plan.samples)} exact immutable samples "
                "to the executable SHA-256 digest"
            ),
        )
    )
    report = TrajectoryPreflightReport(
        accepted=True,
        motion_id=plan.motion_id,
        motion_revision=plan.motion_revision,
        digest=digest,
        duration_s=plan.duration_s,
        sample_count=len(plan.samples),
        segment_count=len(plan.segments),
        sample_rate_hz=plan.sample_rate_hz,
        checks=checks,
        violations=[],
        real_motion_ready=real_motion_ready,
        field_acceptance_ready=field_acceptance_ready,
    )
    return PreparedTrajectory(plan=plan, preflight=report)


def _exact_samples(
    prepared: PreparedMotion | PreparedContinuousJog,
    profile: RobotProfile,
    *,
    start_id: object,
    end_id: object,
    update_hz: float,
) -> tuple[list[TrajectorySample], float, Easing]:
    # UUID is intentionally kept local to the public compiler; accepting object
    # here avoids exporting a second public helper merely for type plumbing.
    from uuid import UUID

    if not isinstance(start_id, UUID) or not isinstance(end_id, UUID):
        raise TypeError("trajectory keyframe IDs must be UUIDs")
    if isinstance(prepared, PreparedMotion):
        duration_s = prepared.duration_s
        if prepared.trajectory_samples is not None:
            provided_samples = [
                TrajectorySample(
                    time_s=float(item.time_s),
                    positions=dict(item.joint_state.positions),
                    units=dict(item.joint_state.units or {}),
                    tcp_pose=item.tcp_pose,
                    keyframe_id=start_id if index == 0 else end_id,
                    segment_index=0,
                    sample_index=index,
                )
                for index, item in enumerate(prepared.trajectory_samples)
            ]
            return provided_samples, duration_s, Easing.LINEAR
        count = max(2, ceil(duration_s * update_hz) + 1)
        samples: list[TrajectorySample] = []
        for index in range(count):
            time_s = duration_s if index == count - 1 else index / update_hz
            progress = min(1.0, time_s / duration_s)
            interpolation = progress * progress * (3.0 - 2.0 * progress)
            samples.append(
                TrajectorySample(
                    time_s=float(time_s),
                    positions={
                        joint_id: prepared.start_state.positions[joint_id]
                        + (
                            prepared.target_state.positions[joint_id]
                            - prepared.start_state.positions[joint_id]
                        )
                        * interpolation
                        for joint_id in profile.enabled_joints
                    },
                    units=dict(prepared.target_state.units or {}),
                    keyframe_id=start_id if index == 0 else end_id,
                    segment_index=0,
                    sample_index=index,
                )
            )
        return samples, duration_s, Easing.SMOOTHSTEP

    start_value = prepared.start_state.positions[prepared.joint_id]
    travel = (
        prepared.maximum - start_value if prepared.direction > 0 else start_value - prepared.minimum
    )
    ramp_duration = prepared.speed_units_s / prepared.acceleration_units_s2
    ramp_distance = 0.5 * prepared.acceleration_units_s2 * ramp_duration * ramp_duration
    duration_s = (
        (2.0 * travel / prepared.acceleration_units_s2) ** 0.5
        if travel <= ramp_distance
        else ramp_duration + (travel - ramp_distance) / prepared.speed_units_s
    )
    duration_s = max(0.05, min(30.0, duration_s))
    count = max(2, ceil(duration_s * update_hz) + 1)
    samples = []
    for index in range(count):
        time_s = duration_s if index == count - 1 else index / update_hz
        if time_s < ramp_duration:
            distance = 0.5 * prepared.acceleration_units_s2 * time_s * time_s
        else:
            distance = ramp_distance + prepared.speed_units_s * (time_s - ramp_duration)
        value = start_value + prepared.direction * min(travel, distance)
        positions = dict(prepared.start_state.positions)
        positions[prepared.joint_id] = value
        samples.append(
            TrajectorySample(
                time_s=float(time_s),
                positions=positions,
                units=dict(prepared.start_state.units or {}),
                keyframe_id=start_id if index == 0 else end_id,
                segment_index=0,
                sample_index=index,
            )
        )
    return samples, duration_s, Easing.SMOOTHSTEP


__all__ = ["compile_gateway_command_trajectory"]
