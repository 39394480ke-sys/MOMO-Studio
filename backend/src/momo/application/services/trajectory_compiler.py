"""Deterministic whole-motion compiler for immutable Dry Run trajectories."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from math import acos, ceil, degrees, fsum, isfinite, sin, sqrt
from typing import Protocol

from momo.domain.calibration import CalibrationDocument
from momo.domain.enums import (
    ControlMode,
    DomainUnit,
    Easing,
    HardwareAccessPolicy,
    JointType,
    MotionCommandSource,
    MotionMode,
    RealReadiness,
    RobotVariant,
)
from momo.domain.errors import HardwareMappingError
from momo.domain.hardware_mapping import effective_logical_limits_from_raw_bounds
from momo.domain.kinematics.model import KinematicsModel
from momo.domain.kinematics.results import ForwardKinematicsResult, InverseKinematicsResult
from momo.domain.motion import MOTION_SCHEMA_VERSION, Motion
from momo.domain.pose import QuaternionXYZW, TcpPose, Vector3, utc_now
from momo.domain.robot import JointState, RobotProfile
from momo.domain.trajectory import (
    PreparedTrajectory,
    TrajectoryCompileOutcome,
    TrajectoryDigest,
    TrajectoryPlan,
    TrajectoryPreflightCheck,
    TrajectoryPreflightReport,
    TrajectorySample,
    TrajectorySegment,
    TrajectorySegmentKind,
    TrajectoryViolation,
)

DEFAULT_SAMPLE_RATE_HZ = 20.0
MIN_SAMPLE_RATE_HZ = 1.0
MAX_SAMPLE_RATE_HZ = 100.0
MAX_TRAJECTORY_DURATION_S = 600.0
MAX_TRAJECTORY_SAMPLES = 20_000
MAX_TRAJECTORY_SEGMENTS = 2_000
POSITION_RESIDUAL_LIMIT_MM = 1.0
ORIENTATION_RESIDUAL_LIMIT_DEG = degrees(0.02)
START_STATE_TOLERANCE = 1e-6
WORKSPACE_X_MM = (-750.0, 750.0)
WORKSPACE_Y_MM = (-750.0, 750.0)
WORKSPACE_Z_MM = (-500.0, 750.0)

CancelCheck = Callable[[], bool]


class TrajectoryKinematics(Protocol):
    """The pure subset of KinematicsService required by trajectory compilation."""

    def model_for(self, profile: RobotProfile) -> KinematicsModel: ...

    async def forward(
        self,
        profile: RobotProfile,
        state: JointState,
        *,
        state_sequence: int,
        robot_id: str = "primary",
    ) -> ForwardKinematicsResult: ...

    async def inverse(
        self,
        profile: RobotProfile,
        target: TcpPose,
        *,
        seed: JointState | None = None,
        position_only: bool = False,
        maximum_iterations: int = 200,
    ) -> InverseKinematicsResult: ...


@dataclass(frozen=True, slots=True)
class _SegmentSpec:
    kind: TrajectorySegmentKind
    from_index: int
    to_index: int
    duration_s: float
    easing: Easing | None


class _CompilationFailure(RuntimeError):
    def __init__(self, violation: TrajectoryViolation) -> None:
        super().__init__(violation.message)
        self.violation = violation


class TrajectoryCompiler:
    """Compile once, preflight the full plan, and return that same immutable value."""

    def __init__(self, kinematics: TrajectoryKinematics) -> None:
        self.kinematics = kinematics

    async def compile(
        self,
        *,
        motion: Motion,
        profile: RobotProfile,
        start_state: JointState,
        start_state_sequence: int,
        expected_motion_revision: int,
        expected_robot_variant: RobotVariant,
        expected_profile_fingerprint: str,
        expected_kinematics_fingerprint: str,
        expected_state_sequence: int,
        connected: bool,
        state_fresh: bool,
        hardware_access_policy: HardwareAccessPolicy,
        sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ,
        calibration: CalibrationDocument | None = None,
        control_mode: ControlMode = ControlMode.DRY_RUN,
        stop_capable: bool = True,
        source: MotionCommandSource = MotionCommandSource.LIBRARY,
        real_readiness: RealReadiness = RealReadiness.BLOCKED_BY_STAGE_POLICY,
        field_acceptance_complete: bool = False,
        cancellation_requested: CancelCheck | None = None,
    ) -> TrajectoryCompileOutcome:
        """Return structured rejection evidence or the exact prepared trajectory.

        No hardware operation or implicit entry move occurs. ``start_state`` must
        already match the first embedded keyframe, and every mutable binding supplied
        by the caller is incorporated into preflight evidence.
        """

        checks: list[TrajectoryPreflightCheck] = []
        violations: list[TrajectoryViolation] = []
        effective_rate = self._validated_sample_rate(sample_rate_hz, checks, violations)

        self._check(
            motion.schema_version == MOTION_SCHEMA_VERSION,
            checks,
            violations,
            name="motion_schema",
            code="MOTION_SCHEMA_UNSUPPORTED",
            passed_detail=f"Motion schema {MOTION_SCHEMA_VERSION} is supported",
            failed_detail="Motion schema is not supported by this compiler",
        )
        self._check(
            expected_motion_revision == motion.revision,
            checks,
            violations,
            name="motion_revision",
            code="MOTION_REVISION_MISMATCH",
            passed_detail=f"Motion revision {motion.revision} matches",
            failed_detail="Expected Motion revision does not match the stored Motion",
        )
        variant_matches = (
            expected_robot_variant is profile.variant
            and motion.robot_variant is profile.variant
            and all(
                keyframe.pose_snapshot.robot_variant is profile.variant
                for keyframe in motion.keyframes
            )
        )
        self._check(
            variant_matches,
            checks,
            violations,
            name="variant",
            code="VARIANT_MISMATCH",
            passed_detail=f"Motion and profile use {profile.variant.value}",
            failed_detail="Expected variant, Motion, snapshots, and active profile do not match",
        )
        profile_matches = expected_profile_fingerprint == profile.fingerprint and all(
            keyframe.pose_snapshot.profile_fingerprint == profile.fingerprint
            for keyframe in motion.keyframes
        )
        self._check(
            profile_matches,
            checks,
            violations,
            name="profile",
            code="PROFILE_MISMATCH",
            passed_detail="Motion snapshots match the active profile fingerprint",
            failed_detail="Expected, active, and embedded profile fingerprints do not match",
        )
        self._check(
            expected_state_sequence == start_state_sequence,
            checks,
            violations,
            name="state_sequence",
            code="STATE_SEQUENCE_MISMATCH",
            passed_detail=f"Start state sequence {start_state_sequence} matches",
            failed_detail="Expected robot state sequence is stale",
        )
        self._check(
            source in {MotionCommandSource.LIBRARY, MotionCommandSource.STUDIO},
            checks,
            violations,
            name="source",
            code="SOURCE_NOT_ALLOWED",
            passed_detail=f"{source.value} is an accepted trajectory source",
            failed_detail="Trajectory compilation only accepts Library or Studio motion intent",
        )
        self._check(
            connected,
            checks,
            violations,
            name="connected",
            code="ROBOT_NOT_CONNECTED",
            passed_detail="Active Dry Run robot is connected",
            failed_detail="Trajectory preflight requires a connected Dry Run robot",
        )
        self._check(
            state_fresh,
            checks,
            violations,
            name="state_freshness",
            code="ROBOT_STATE_STALE",
            passed_detail="Active robot state is fresh",
            failed_detail="Trajectory preflight rejects stale robot state",
        )
        self._check(
            hardware_access_policy is HardwareAccessPolicy.DISABLED,
            checks,
            violations,
            name="hardware_policy",
            code="HARDWARE_ACCESS_POLICY_INVALID",
            passed_detail="Hardware access policy is DISABLED",
            failed_detail="Current product policy requires hardware access DISABLED",
        )
        self._check(
            control_mode is ControlMode.DRY_RUN,
            checks,
            violations,
            name="control_mode",
            code="REAL_MOTION_DISABLED",
            passed_detail="Control mode is DRY_RUN",
            failed_detail="Trajectory compilation is currently restricted to DRY_RUN",
        )
        self._check(
            stop_capable,
            checks,
            violations,
            name="stop_capability",
            code="STOP_CAPABILITY_UNAVAILABLE",
            passed_detail="Executor stop capability is available",
            failed_detail="Trajectory playback requires a working stop capability",
        )
        self._check(
            real_readiness is RealReadiness.BLOCKED_BY_STAGE_POLICY,
            checks,
            violations,
            name="real_readiness",
            code="REAL_READINESS_INVALID",
            passed_detail="Real motion remains blocked by product stage policy",
            failed_detail="The compiler cannot claim real-hardware readiness",
        )
        self._check(
            not field_acceptance_complete,
            checks,
            violations,
            name="field_acceptance",
            code="FIELD_ACCEPTANCE_INVALID",
            passed_detail="Real-hardware field acceptance remains outstanding",
            failed_detail="The compiler cannot claim real-hardware field acceptance",
        )

        model: KinematicsModel | None = None
        try:
            model = self.kinematics.model_for(profile)
        except (KeyError, TypeError, ValueError) as error:
            self._failed_check(
                checks,
                violations,
                name="kinematics",
                code="KINEMATICS_UNAVAILABLE",
                detail=f"Active kinematics model is unavailable: {error}",
            )
        if model is not None:
            kinematics_matches = (
                model.variant is profile.variant
                and expected_kinematics_fingerprint == model.fingerprint
                and all(
                    keyframe.pose_snapshot.kinematics_fingerprint == model.fingerprint
                    for keyframe in motion.keyframes
                )
            )
            self._check(
                kinematics_matches,
                checks,
                violations,
                name="kinematics",
                code="KINEMATICS_MISMATCH",
                passed_detail="Motion snapshots match the active kinematics fingerprint",
                failed_detail=(
                    "Expected, active, and embedded kinematics fingerprints do not match"
                ),
            )

        self._validate_motion_and_start(
            motion,
            profile,
            start_state,
            checks,
            violations,
        )
        raw_limits = self._raw_limits(calibration, profile, checks, violations)
        specs = self._segment_specs(motion)
        duration_s = fsum(spec.duration_s for spec in specs)
        expected_samples = 1 + sum(
            self._samples_for_duration(spec.duration_s, effective_rate) for spec in specs
        )
        self._check(
            0.0 < duration_s <= MAX_TRAJECTORY_DURATION_S,
            checks,
            violations,
            name="duration",
            code="MOTION_DURATION_LIMIT",
            passed_detail=(
                f"Trajectory duration {duration_s:.6f}s is within the "
                f"{MAX_TRAJECTORY_DURATION_S:.0f}s limit"
            ),
            failed_detail=(
                f"Trajectory duration must be within (0, {MAX_TRAJECTORY_DURATION_S:.0f}] seconds"
            ),
            actual=duration_s if isfinite(duration_s) else None,
            limit=MAX_TRAJECTORY_DURATION_S,
        )
        self._check(
            len(specs) <= MAX_TRAJECTORY_SEGMENTS,
            checks,
            violations,
            name="segment_count",
            code="SEGMENT_COUNT_LIMIT",
            passed_detail=f"Trajectory has {len(specs)} bounded segments",
            failed_detail=f"Trajectory exceeds the {MAX_TRAJECTORY_SEGMENTS} segment limit",
            actual=float(len(specs)),
            limit=float(MAX_TRAJECTORY_SEGMENTS),
        )
        self._check(
            expected_samples <= MAX_TRAJECTORY_SAMPLES,
            checks,
            violations,
            name="sample_count",
            code="SAMPLE_COUNT_LIMIT",
            passed_detail=f"Trajectory has {expected_samples} bounded samples",
            failed_detail=f"Trajectory exceeds the {MAX_TRAJECTORY_SAMPLES} sample limit",
            actual=float(expected_samples),
            limit=float(MAX_TRAJECTORY_SAMPLES),
        )
        self._record_cancellation(cancellation_requested, checks, violations)

        if violations or model is None:
            return self._rejected(
                motion,
                effective_rate,
                duration_s,
                expected_samples,
                len(specs),
                checks,
                violations,
            )

        try:
            samples, segments = await self._compile_samples(
                motion=motion,
                profile=profile,
                start_state=start_state,
                start_state_sequence=start_state_sequence,
                sample_rate_hz=effective_rate,
                specs=specs,
                duration_s=duration_s,
                raw_limits=raw_limits,
                cancellation_requested=cancellation_requested,
            )
            await self._validate_dynamics(
                samples,
                profile,
                cancellation_requested=cancellation_requested,
            )
        except _CompilationFailure as error:
            self._failed_check(
                checks,
                violations,
                name=error.violation.check,
                code=error.violation.code,
                detail=error.violation.message,
                violation=error.violation,
            )
            return self._rejected(
                motion,
                effective_rate,
                duration_s,
                expected_samples,
                len(specs),
                checks,
                violations,
            )

        checks.extend(
            [
                TrajectoryPreflightCheck(
                    name="joint_limits",
                    passed=True,
                    detail="Every compiled sample is within logical joint limits",
                ),
                TrajectoryPreflightCheck(
                    name="raw_derived_limits",
                    passed=True,
                    detail=("Every compiled sample satisfies applicable raw-derived limits"),
                ),
                TrajectoryPreflightCheck(
                    name="velocity",
                    passed=True,
                    detail="Every sample interval is within provisional per-joint velocity limits",
                ),
                TrajectoryPreflightCheck(
                    name="acceleration",
                    passed=True,
                    detail=(
                        "Every sampled velocity transition is within provisional acceleration "
                        "limits"
                    ),
                ),
                TrajectoryPreflightCheck(
                    name="fk",
                    passed=True,
                    detail=(
                        "FK succeeded for every initial, Joint, and Cartesian verification sample"
                    ),
                ),
                TrajectoryPreflightCheck(
                    name="ik",
                    passed=True,
                    detail="IK succeeded at every Cartesian sample with prior-sample seeding",
                ),
                TrajectoryPreflightCheck(
                    name="residual",
                    passed=True,
                    detail="Cartesian FK/IK residuals remained within bounded tolerances",
                ),
                TrajectoryPreflightCheck(
                    name="continuity",
                    passed=True,
                    detail="Cartesian joint steps remained continuous",
                ),
                TrajectoryPreflightCheck(
                    name="workspace",
                    passed=True,
                    detail="Every target and computed TCP remained inside the Dry Run workspace",
                ),
            ]
        )
        digest = TrajectoryDigest(
            sha256=self._digest(
                motion,
                profile,
                model,
                start_state_sequence,
                effective_rate,
                duration_s,
                segments,
                samples,
            )
        )
        checks.append(
            TrajectoryPreflightCheck(
                name="digest",
                passed=True,
                detail="Deterministic SHA-256 digest covers every execution-relevant plan value",
            )
        )
        plan = TrajectoryPlan(
            motion_id=motion.id,
            motion_revision=motion.revision,
            robot_variant=motion.robot_variant,
            profile_fingerprint=profile.fingerprint,
            kinematics_fingerprint=model.fingerprint,
            start_state_sequence=start_state_sequence,
            sample_rate_hz=effective_rate,
            duration_s=duration_s,
            segments=segments,
            samples=samples,
            digest=digest,
            compiled_at=utc_now(),
        )
        report = TrajectoryPreflightReport(
            accepted=True,
            motion_id=motion.id,
            motion_revision=motion.revision,
            digest=digest,
            duration_s=duration_s,
            sample_count=len(samples),
            segment_count=len(segments),
            sample_rate_hz=effective_rate,
            checks=checks,
            violations=[],
        )
        prepared = PreparedTrajectory(plan=plan, preflight=report)
        return TrajectoryCompileOutcome(report=report, prepared=prepared)

    @staticmethod
    def _validated_sample_rate(
        requested: float,
        checks: list[TrajectoryPreflightCheck],
        violations: list[TrajectoryViolation],
    ) -> float:
        valid = (
            not isinstance(requested, bool)
            and isinstance(requested, (int, float))
            and isfinite(float(requested))
            and MIN_SAMPLE_RATE_HZ <= float(requested) <= MAX_SAMPLE_RATE_HZ
        )
        if valid:
            value = float(requested)
            checks.append(
                TrajectoryPreflightCheck(
                    name="sample_rate",
                    passed=True,
                    detail=f"Sample rate {value:g}Hz is within safe bounds",
                )
            )
            return value
        checks.append(
            TrajectoryPreflightCheck(
                name="sample_rate",
                passed=False,
                detail=(
                    f"Sample rate must be finite and within [{MIN_SAMPLE_RATE_HZ:g}, "
                    f"{MAX_SAMPLE_RATE_HZ:g}]Hz"
                ),
            )
        )
        violations.append(
            TrajectoryViolation(
                code="SAMPLE_RATE_INVALID",
                check="sample_rate",
                message=(
                    f"Sample rate must be finite and within [{MIN_SAMPLE_RATE_HZ:g}, "
                    f"{MAX_SAMPLE_RATE_HZ:g}]Hz"
                ),
            )
        )
        # The report itself always remains schema-valid even for a hostile request.
        return DEFAULT_SAMPLE_RATE_HZ

    @staticmethod
    def _check(
        condition: bool,
        checks: list[TrajectoryPreflightCheck],
        violations: list[TrajectoryViolation],
        *,
        name: str,
        code: str,
        passed_detail: str,
        failed_detail: str,
        actual: float | None = None,
        limit: float | None = None,
        unit: DomainUnit | None = None,
    ) -> None:
        checks.append(
            TrajectoryPreflightCheck(
                name=name,
                passed=condition,
                detail=passed_detail if condition else failed_detail,
            )
        )
        if not condition:
            violations.append(
                TrajectoryViolation(
                    code=code,
                    check=name,
                    message=failed_detail,
                    actual=actual,
                    limit=limit,
                    unit=unit,
                )
            )

    @staticmethod
    def _failed_check(
        checks: list[TrajectoryPreflightCheck],
        violations: list[TrajectoryViolation],
        *,
        name: str,
        code: str,
        detail: str,
        violation: TrajectoryViolation | None = None,
    ) -> None:
        checks.append(TrajectoryPreflightCheck(name=name, passed=False, detail=detail))
        violations.append(
            violation
            if violation is not None
            else TrajectoryViolation(code=code, check=name, message=detail)
        )

    def _validate_motion_and_start(
        self,
        motion: Motion,
        profile: RobotProfile,
        start_state: JointState,
        checks: list[TrajectoryPreflightCheck],
        violations: list[TrajectoryViolation],
    ) -> None:
        try:
            motion.validate_against(profile)
        except ValueError as error:
            self._failed_check(
                checks,
                violations,
                name="joint_limits",
                code="JOINT_LIMIT_VIOLATION",
                detail=f"Embedded Motion state is invalid: {error}",
            )
        try:
            start_state.validate_against(profile)
        except ValueError as error:
            self._failed_check(
                checks,
                violations,
                name="start_state",
                code="START_STATE_INVALID",
                detail=f"Active start state is invalid: {error}",
            )
            return
        expected_units = {
            joint_id: profile.definitions_by_id[joint_id].domain_unit
            for joint_id in profile.enabled_joints
        }
        if start_state.units is None or dict(start_state.units) != expected_units:
            self._failed_check(
                checks,
                violations,
                name="start_state",
                code="START_STATE_UNITS_INVALID",
                detail="Active start state must include exact canonical units",
            )
            return
        first = motion.keyframes[0].pose_snapshot.joint_state
        for joint_id in profile.enabled_joints:
            delta = abs(start_state.positions[joint_id] - first.positions[joint_id])
            if delta > START_STATE_TOLERANCE:
                definition = profile.definitions_by_id[joint_id]
                violations.append(
                    TrajectoryViolation(
                        code="START_STATE_MISMATCH",
                        check="start_state",
                        message=(
                            "Active state does not match the Motion first keyframe; "
                            "no implicit entry move is allowed"
                        ),
                        joint_id=joint_id,
                        actual=delta,
                        limit=START_STATE_TOLERANCE,
                        unit=definition.domain_unit,
                    )
                )
                checks.append(
                    TrajectoryPreflightCheck(
                        name="start_state",
                        passed=False,
                        detail="Active state does not match the Motion first keyframe",
                    )
                )
                return
        checks.append(
            TrajectoryPreflightCheck(
                name="start_state",
                passed=True,
                detail="Active state exactly matches the Motion first keyframe",
            )
        )

    def _raw_limits(
        self,
        calibration: CalibrationDocument | None,
        profile: RobotProfile,
        checks: list[TrajectoryPreflightCheck],
        violations: list[TrajectoryViolation],
    ) -> dict[str, tuple[float, float]] | None:
        if calibration is None:
            checks.append(
                TrajectoryPreflightCheck(
                    name="calibration_compatibility",
                    passed=True,
                    detail=(
                        "Not applicable: no calibration is configured; logical Dry Run limits "
                        "remain authoritative"
                    ),
                )
            )
            return None
        compatible = (
            calibration.robot_variant is profile.variant
            and calibration.profile_fingerprint == profile.fingerprint
            and set(calibration.joints_by_id) == set(profile.enabled_joints)
            and all(
                calibration.joints_by_id[joint_id].servo_id
                == profile.definitions_by_id[joint_id].servo_id
                for joint_id in profile.enabled_joints
            )
        )
        if not compatible:
            self._failed_check(
                checks,
                violations,
                name="calibration_compatibility",
                code="CALIBRATION_MISMATCH",
                detail="Configured calibration is incompatible with the active profile",
            )
            return None
        try:
            limits = {
                joint_id: effective_logical_limits_from_raw_bounds(
                    joint_id,
                    profile,
                    calibration.joints_by_id[joint_id],
                )
                for joint_id in profile.enabled_joints
            }
        except HardwareMappingError as error:
            self._failed_check(
                checks,
                violations,
                name="calibration_compatibility",
                code="RAW_DERIVED_LIMITS_INVALID",
                detail=f"Raw-derived limits are invalid: {error}",
            )
            return None
        checks.append(
            TrajectoryPreflightCheck(
                name="calibration_compatibility",
                passed=True,
                detail="Compatible calibration raw-derived limits will be checked for every sample",
            )
        )
        return limits

    @staticmethod
    def _segment_specs(motion: Motion) -> list[_SegmentSpec]:
        specs: list[_SegmentSpec] = []
        if motion.keyframes[0].hold_s > 0.0:
            specs.append(
                _SegmentSpec(
                    kind=TrajectorySegmentKind.HOLD,
                    from_index=0,
                    to_index=0,
                    duration_s=float(motion.keyframes[0].hold_s),
                    easing=None,
                )
            )
        for index in range(1, len(motion.keyframes)):
            keyframe = motion.keyframes[index]
            transition = keyframe.incoming_transition
            if transition is None:  # pragma: no cover - Motion validates this invariant
                raise AssertionError("validated Motion has no incoming transition")
            specs.append(
                _SegmentSpec(
                    kind=(
                        TrajectorySegmentKind.JOINT
                        if transition.motion_mode is MotionMode.JOINT
                        else TrajectorySegmentKind.CARTESIAN_LINEAR
                    ),
                    from_index=index - 1,
                    to_index=index,
                    duration_s=float(transition.duration_s),
                    easing=transition.easing,
                )
            )
            if keyframe.hold_s > 0.0:
                specs.append(
                    _SegmentSpec(
                        kind=TrajectorySegmentKind.HOLD,
                        from_index=index,
                        to_index=index,
                        duration_s=float(keyframe.hold_s),
                        easing=None,
                    )
                )
        return specs

    @staticmethod
    def _samples_for_duration(duration_s: float, sample_rate_hz: float) -> int:
        return max(1, ceil(duration_s * sample_rate_hz - 1e-12))

    def _record_cancellation(
        self,
        cancellation_requested: CancelCheck | None,
        checks: list[TrajectoryPreflightCheck],
        violations: list[TrajectoryViolation],
    ) -> None:
        try:
            cancelled = cancellation_requested is not None and cancellation_requested()
        except Exception as error:  # a broken cancellation source must fail closed
            self._failed_check(
                checks,
                violations,
                name="cancellation",
                code="CANCELLATION_CHECK_FAILED",
                detail=f"Cancellation check failed safely: {type(error).__name__}",
            )
            return
        self._check(
            not cancelled,
            checks,
            violations,
            name="cancellation",
            code="COMPILATION_CANCELLED",
            passed_detail="Cancellation hook is checked at every bounded sample when supplied",
            failed_detail="Trajectory compilation was cancelled",
        )

    async def _compile_samples(
        self,
        *,
        motion: Motion,
        profile: RobotProfile,
        start_state: JointState,
        start_state_sequence: int,
        sample_rate_hz: float,
        specs: list[_SegmentSpec],
        duration_s: float,
        raw_limits: dict[str, tuple[float, float]] | None,
        cancellation_requested: CancelCheck | None,
    ) -> tuple[list[TrajectorySample], list[TrajectorySegment]]:
        units = {
            joint_id: profile.definitions_by_id[joint_id].domain_unit
            for joint_id in profile.enabled_joints
        }
        self._require_state_limits(
            start_state,
            profile,
            raw_limits,
            segment_index=0,
            sample_index=0,
        )
        initial_tcp = await self._forward_checked(
            profile,
            start_state,
            start_state_sequence,
            segment_index=0,
            sample_index=0,
        )
        first_tcp = motion.keyframes[0].pose_snapshot.tcp_pose
        self._require_pose_residual(
            first_tcp,
            initial_tcp,
            segment_index=0,
            sample_index=0,
            code="START_FK_MISMATCH",
        )
        self._require_workspace(first_tcp, segment_index=0, sample_index=0)
        samples = [
            TrajectorySample(
                time_s=0.0,
                positions={
                    joint_id: float(start_state.positions[joint_id])
                    for joint_id in profile.enabled_joints
                },
                units=units,
                tcp_pose=initial_tcp,
                keyframe_id=motion.keyframes[0].id,
                segment_index=0,
                sample_index=0,
                is_hold=specs[0].kind is TrajectorySegmentKind.HOLD,
            )
        ]
        segments: list[TrajectorySegment] = []
        elapsed_parts: list[float] = []
        previous_state = start_state
        previous_tcp = initial_tcp

        for segment_index, spec in enumerate(specs):
            segment_start = fsum(elapsed_parts)
            segment_end = (
                duration_s
                if segment_index == len(specs) - 1
                else fsum((*elapsed_parts, spec.duration_s))
            )
            additions = self._samples_for_duration(spec.duration_s, sample_rate_hz)
            start_sample_index = len(samples) - 1
            from_keyframe = motion.keyframes[spec.from_index]
            to_keyframe = motion.keyframes[spec.to_index]
            segment_start_state = previous_state
            for local_index in range(1, additions + 1):
                # The production kinematics adapter exposes an async contract but
                # performs bounded CPU work without an internal await.  Yield here
                # before every sample so lifecycle Stop and a superseding preflight
                # can run promptly, then observe their cancellation request before
                # doing the next FK/IK operation.
                await asyncio.sleep(0)
                self._require_not_cancelled(cancellation_requested, segment_index, len(samples))
                local_time = (
                    spec.duration_s
                    if local_index == additions
                    else min(local_index / sample_rate_hz, spec.duration_s)
                )
                sample_time = (
                    segment_end if local_index == additions else segment_start + local_time
                )
                fraction = min(1.0, local_time / spec.duration_s)
                sample_index = len(samples)
                if spec.kind is TrajectorySegmentKind.HOLD:
                    state = previous_state
                    tcp_pose = previous_tcp
                elif spec.kind is TrajectorySegmentKind.JOINT:
                    eased = self._eased_fraction(fraction, spec.easing)
                    state = self._joint_interpolation(
                        segment_start_state,
                        to_keyframe.pose_snapshot.joint_state,
                        profile,
                        eased,
                    )
                    self._require_state_limits(
                        state,
                        profile,
                        raw_limits,
                        segment_index,
                        sample_index,
                    )
                    tcp_pose = await self._forward_checked(
                        profile,
                        state,
                        start_state_sequence,
                        segment_index=segment_index,
                        sample_index=sample_index,
                    )
                    self._require_workspace(
                        tcp_pose,
                        segment_index=segment_index,
                        sample_index=sample_index,
                    )
                    if local_index == additions:
                        self._require_pose_residual(
                            to_keyframe.pose_snapshot.tcp_pose,
                            tcp_pose,
                            segment_index=segment_index,
                            sample_index=sample_index,
                            code="KEYFRAME_FK_MISMATCH",
                        )
                else:
                    path_fraction = self._eased_fraction(fraction, spec.easing)
                    target_tcp = self._interpolate_tcp_pose(
                        from_keyframe.pose_snapshot.tcp_pose,
                        to_keyframe.pose_snapshot.tcp_pose,
                        path_fraction,
                    )
                    self._require_workspace(
                        target_tcp,
                        segment_index=segment_index,
                        sample_index=sample_index,
                    )
                    state = await self._inverse_checked(
                        profile,
                        target_tcp,
                        previous_state,
                        segment_index,
                        sample_index,
                    )
                    self._require_state_limits(
                        state,
                        profile,
                        raw_limits,
                        segment_index,
                        sample_index,
                    )
                    self._require_continuity(
                        previous_state,
                        state,
                        profile,
                        segment_index,
                        sample_index,
                    )
                    actual_tcp = await self._forward_checked(
                        profile,
                        state,
                        start_state_sequence,
                        segment_index=segment_index,
                        sample_index=sample_index,
                    )
                    self._require_pose_residual(
                        target_tcp,
                        actual_tcp,
                        segment_index=segment_index,
                        sample_index=sample_index,
                        code="CARTESIAN_RESIDUAL",
                    )
                    self._require_workspace(
                        actual_tcp,
                        segment_index=segment_index,
                        sample_index=sample_index,
                    )
                    tcp_pose = target_tcp
                samples.append(
                    TrajectorySample(
                        time_s=float(sample_time),
                        positions={
                            joint_id: float(state.positions[joint_id])
                            for joint_id in profile.enabled_joints
                        },
                        units=units,
                        tcp_pose=tcp_pose,
                        keyframe_id=to_keyframe.id,
                        segment_index=segment_index,
                        sample_index=sample_index,
                        is_hold=spec.kind is TrajectorySegmentKind.HOLD,
                    )
                )
                previous_state = state
                previous_tcp = tcp_pose
            segments.append(
                TrajectorySegment(
                    segment_index=segment_index,
                    kind=spec.kind,
                    from_keyframe_id=from_keyframe.id,
                    to_keyframe_id=to_keyframe.id,
                    easing=spec.easing,
                    start_time_s=float(segment_start),
                    end_time_s=float(segment_end),
                    duration_s=float(spec.duration_s),
                    start_sample_index=start_sample_index,
                    end_sample_index=len(samples) - 1,
                    generated_sample_count=additions,
                )
            )
            elapsed_parts.append(spec.duration_s)
        return samples, segments

    @staticmethod
    def _eased_fraction(fraction: float, easing: Easing | None) -> float:
        if easing is Easing.LINEAR:
            return fraction
        if easing is Easing.SMOOTHSTEP:
            return fraction * fraction * (3.0 - 2.0 * fraction)
        if easing is Easing.EASE_IN_OUT:
            # Quintic smootherstep: zero velocity and acceleration at both endpoints.
            return fraction**3 * (fraction * (fraction * 6.0 - 15.0) + 10.0)
        raise _CompilationFailure(
            TrajectoryViolation(
                code="EASING_UNSUPPORTED",
                check="easing",
                message="Motion segment has an unsupported easing mode",
            )
        )

    @staticmethod
    def _joint_interpolation(
        start: JointState,
        end: JointState,
        profile: RobotProfile,
        fraction: float,
    ) -> JointState:
        units = {
            joint_id: profile.definitions_by_id[joint_id].domain_unit
            for joint_id in profile.enabled_joints
        }
        return JointState(
            positions={
                joint_id: start.positions[joint_id]
                + (end.positions[joint_id] - start.positions[joint_id]) * fraction
                for joint_id in profile.enabled_joints
            },
            units=units,
        )

    async def _forward_checked(
        self,
        profile: RobotProfile,
        state: JointState,
        state_sequence: int,
        *,
        segment_index: int,
        sample_index: int,
    ) -> TcpPose:
        try:
            result = await self.kinematics.forward(
                profile,
                state,
                state_sequence=state_sequence,
                robot_id="primary",
            )
        except Exception as error:
            raise _CompilationFailure(
                TrajectoryViolation(
                    code="FK_FAILED",
                    check="fk",
                    message=f"FK failed safely at trajectory sample: {type(error).__name__}",
                    segment_index=segment_index,
                    sample_index=sample_index,
                )
            ) from error
        return result.tcp_pose

    async def _inverse_checked(
        self,
        profile: RobotProfile,
        target: TcpPose,
        seed: JointState,
        segment_index: int,
        sample_index: int,
    ) -> JointState:
        try:
            result = await self.kinematics.inverse(
                profile,
                target,
                seed=seed,
                position_only=False,
            )
        except Exception as error:
            raise _CompilationFailure(
                TrajectoryViolation(
                    code="IK_FAILED",
                    check="ik",
                    message=f"Cartesian IK failed safely: {type(error).__name__}",
                    segment_index=segment_index,
                    sample_index=sample_index,
                )
            ) from error
        if not result.success or result.joint_state_optional is None:
            raise _CompilationFailure(
                TrajectoryViolation(
                    code="IK_FAILED",
                    check="ik",
                    message=(
                        "Cartesian IK failed; the segment was rejected without Joint fallback "
                        f"({result.termination_reason})"
                    ),
                    segment_index=segment_index,
                    sample_index=sample_index,
                )
            )
        if result.position_error_mm > POSITION_RESIDUAL_LIMIT_MM:
            raise _CompilationFailure(
                TrajectoryViolation(
                    code="IK_POSITION_RESIDUAL",
                    check="residual",
                    message="Cartesian IK position residual exceeds the Dry Run limit",
                    segment_index=segment_index,
                    sample_index=sample_index,
                    actual=float(result.position_error_mm),
                    limit=POSITION_RESIDUAL_LIMIT_MM,
                    unit=DomainUnit.MM,
                )
            )
        if (
            result.orientation_error_deg is None
            or result.orientation_error_deg > ORIENTATION_RESIDUAL_LIMIT_DEG
        ):
            raise _CompilationFailure(
                TrajectoryViolation(
                    code="IK_ORIENTATION_RESIDUAL",
                    check="residual",
                    message="Cartesian IK orientation residual exceeds the Dry Run limit",
                    segment_index=segment_index,
                    sample_index=sample_index,
                    actual=(
                        float(result.orientation_error_deg)
                        if result.orientation_error_deg is not None
                        else None
                    ),
                    limit=ORIENTATION_RESIDUAL_LIMIT_DEG,
                    unit=DomainUnit.DEG,
                )
            )
        solution = result.joint_state_optional
        expected_units = {
            joint_id: profile.definitions_by_id[joint_id].domain_unit
            for joint_id in profile.enabled_joints
        }
        if solution.units is None or dict(solution.units) != expected_units:
            raise _CompilationFailure(
                TrajectoryViolation(
                    code="IK_UNITS_INVALID",
                    check="ik",
                    message="Cartesian IK solution must include exact canonical joint units",
                    segment_index=segment_index,
                    sample_index=sample_index,
                )
            )
        return solution

    @staticmethod
    def _require_state_limits(
        state: JointState,
        profile: RobotProfile,
        raw_limits: dict[str, tuple[float, float]] | None,
        segment_index: int,
        sample_index: int,
    ) -> None:
        try:
            state.validate_against(profile)
        except ValueError as error:
            raise _CompilationFailure(
                TrajectoryViolation(
                    code="JOINT_LIMIT_VIOLATION",
                    check="joint_limits",
                    message=f"Trajectory sample violates logical joint limits: {error}",
                    segment_index=segment_index,
                    sample_index=sample_index,
                )
            ) from error
        if raw_limits is None:
            return
        for joint_id in profile.enabled_joints:
            lower, upper = raw_limits[joint_id]
            value = state.positions[joint_id]
            if not lower <= value <= upper:
                definition = profile.definitions_by_id[joint_id]
                raise _CompilationFailure(
                    TrajectoryViolation(
                        code="RAW_DERIVED_LIMIT_VIOLATION",
                        check="raw_derived_limits",
                        message=f"{joint_id} sample is outside raw-derived limits",
                        segment_index=segment_index,
                        sample_index=sample_index,
                        joint_id=joint_id,
                        actual=float(value),
                        limit=float(lower if value < lower else upper),
                        unit=definition.domain_unit,
                    )
                )

    @staticmethod
    def _require_continuity(
        previous: JointState,
        current: JointState,
        profile: RobotProfile,
        segment_index: int,
        sample_index: int,
    ) -> None:
        for joint_id in profile.enabled_joints:
            definition = profile.definitions_by_id[joint_id]
            limit = 20.0 if definition.joint_type is JointType.PRISMATIC else 15.0
            jump = abs(current.positions[joint_id] - previous.positions[joint_id])
            if jump > limit + 1e-9:
                raise _CompilationFailure(
                    TrajectoryViolation(
                        code="CARTESIAN_JOINT_JUMP",
                        check="continuity",
                        message=f"Cartesian IK introduced a discontinuous {joint_id} jump",
                        segment_index=segment_index,
                        sample_index=sample_index,
                        joint_id=joint_id,
                        actual=float(jump),
                        limit=limit,
                        unit=definition.domain_unit,
                    )
                )

    @staticmethod
    def _interpolate_tcp_pose(start: TcpPose, end: TcpPose, fraction: float) -> TcpPose:
        if start.frame != end.frame:
            raise _CompilationFailure(
                TrajectoryViolation(
                    code="CARTESIAN_FRAME_MISMATCH",
                    check="cartesian_frame",
                    message="Cartesian keyframes must use the same TCP frame",
                )
            )
        start_position = start.position_mm
        end_position = end.position_mm
        quaternion = TrajectoryCompiler._shortest_slerp(
            start.orientation_quaternion_xyzw,
            end.orientation_quaternion_xyzw,
            fraction,
        )
        return TcpPose(
            frame=start.frame,
            position_mm=Vector3(
                x=start_position.x + (end_position.x - start_position.x) * fraction,
                y=start_position.y + (end_position.y - start_position.y) * fraction,
                z=start_position.z + (end_position.z - start_position.z) * fraction,
            ),
            orientation_quaternion_xyzw=quaternion,
        )

    @staticmethod
    def _shortest_slerp(
        start: QuaternionXYZW,
        end: QuaternionXYZW,
        fraction: float,
    ) -> QuaternionXYZW:
        first = (start.x, start.y, start.z, start.w)
        second = (end.x, end.y, end.z, end.w)
        dot = sum(left * right for left, right in zip(first, second, strict=True))
        if dot < 0.0:
            second = (-second[0], -second[1], -second[2], -second[3])
            dot = -dot
        dot = min(1.0, max(-1.0, dot))
        if dot > 0.9995:
            values = tuple(
                left + fraction * (right - left) for left, right in zip(first, second, strict=True)
            )
        else:
            angle = acos(dot)
            denominator = sin(angle)
            left_weight = sin((1.0 - fraction) * angle) / denominator
            right_weight = sin(fraction * angle) / denominator
            values = tuple(
                left_weight * left + right_weight * right
                for left, right in zip(first, second, strict=True)
            )
        norm = sqrt(sum(value * value for value in values))
        normalized = tuple(value / norm for value in values)
        return QuaternionXYZW(
            x=normalized[0],
            y=normalized[1],
            z=normalized[2],
            w=normalized[3],
        )

    @staticmethod
    def _require_workspace(
        pose: TcpPose,
        *,
        segment_index: int,
        sample_index: int,
    ) -> None:
        position = pose.position_mm
        inside = (
            WORKSPACE_X_MM[0] <= position.x <= WORKSPACE_X_MM[1]
            and WORKSPACE_Y_MM[0] <= position.y <= WORKSPACE_Y_MM[1]
            and WORKSPACE_Z_MM[0] <= position.z <= WORKSPACE_Z_MM[1]
        )
        if not inside:
            raise _CompilationFailure(
                TrajectoryViolation(
                    code="WORKSPACE_VIOLATION",
                    check="workspace",
                    message="Trajectory TCP sample is outside the bounded Dry Run workspace",
                    segment_index=segment_index,
                    sample_index=sample_index,
                )
            )

    @staticmethod
    def _pose_residual(expected: TcpPose, actual: TcpPose) -> tuple[float, float]:
        expected_position = expected.position_mm
        actual_position = actual.position_mm
        position_error = sqrt(
            (expected_position.x - actual_position.x) ** 2
            + (expected_position.y - actual_position.y) ** 2
            + (expected_position.z - actual_position.z) ** 2
        )
        first = expected.orientation_quaternion_xyzw
        second = actual.orientation_quaternion_xyzw
        dot = abs(first.x * second.x + first.y * second.y + first.z * second.z + first.w * second.w)
        orientation_error = degrees(2.0 * acos(min(1.0, max(-1.0, dot))))
        return position_error, orientation_error

    @classmethod
    def _require_pose_residual(
        cls,
        expected: TcpPose,
        actual: TcpPose,
        *,
        segment_index: int,
        sample_index: int,
        code: str,
    ) -> None:
        if expected.frame != actual.frame:
            raise _CompilationFailure(
                TrajectoryViolation(
                    code=code,
                    check="residual",
                    message="Computed TCP frame does not match the embedded frame",
                    segment_index=segment_index,
                    sample_index=sample_index,
                )
            )
        position_error, orientation_error = cls._pose_residual(expected, actual)
        if (
            position_error > POSITION_RESIDUAL_LIMIT_MM
            or orientation_error > ORIENTATION_RESIDUAL_LIMIT_DEG
        ):
            raise _CompilationFailure(
                TrajectoryViolation(
                    code=code,
                    check="residual",
                    message=(
                        "Computed TCP does not match the requested pose within residual limits "
                        f"(position={position_error:.6f}mm, orientation={orientation_error:.6f}deg)"
                    ),
                    segment_index=segment_index,
                    sample_index=sample_index,
                )
            )

    @classmethod
    async def _validate_dynamics(
        cls,
        samples: list[TrajectorySample],
        profile: RobotProfile,
        *,
        cancellation_requested: CancelCheck | None,
    ) -> None:
        previous_velocity = {joint_id: 0.0 for joint_id in profile.enabled_joints}
        last_dt = 1.0 / DEFAULT_SAMPLE_RATE_HZ
        for previous, current in pairwise(samples):
            # Dynamics is another potentially large CPU-only pass.  A bounded
            # checkpoint prevents it from becoming an uncancellable tail after
            # sample generation has yielded cooperatively.
            if current.sample_index % 64 == 0:
                await asyncio.sleep(0)
            cls._require_not_cancelled(
                cancellation_requested,
                current.segment_index,
                current.sample_index,
            )
            dt = current.time_s - previous.time_s
            if not isfinite(dt) or dt <= 0.0:
                raise _CompilationFailure(
                    TrajectoryViolation(
                        code="TIME_NOT_MONOTONIC",
                        check="time",
                        message="Trajectory sample times must be finite and strictly increasing",
                        sample_index=current.sample_index,
                    )
                )
            last_dt = dt
            for joint_id in profile.enabled_joints:
                definition = profile.definitions_by_id[joint_id]
                velocity_limit = 100.0 if definition.joint_type is JointType.PRISMATIC else 90.0
                acceleration_limit = (
                    800.0 if definition.joint_type is JointType.PRISMATIC else 720.0
                )
                velocity = (current.positions[joint_id] - previous.positions[joint_id]) / dt
                if abs(velocity) > velocity_limit + 1e-9:
                    raise _CompilationFailure(
                        TrajectoryViolation(
                            code="JOINT_VELOCITY_LIMIT",
                            check="velocity",
                            message=f"{joint_id} exceeds its provisional velocity limit",
                            segment_index=current.segment_index,
                            sample_index=current.sample_index,
                            joint_id=joint_id,
                            actual=float(abs(velocity)),
                            limit=velocity_limit,
                            unit=definition.domain_unit,
                        )
                    )
                acceleration = (velocity - previous_velocity[joint_id]) / dt
                if abs(acceleration) > acceleration_limit + 1e-9:
                    raise _CompilationFailure(
                        TrajectoryViolation(
                            code="JOINT_ACCELERATION_LIMIT",
                            check="acceleration",
                            message=f"{joint_id} exceeds its provisional acceleration limit",
                            segment_index=current.segment_index,
                            sample_index=current.sample_index,
                            joint_id=joint_id,
                            actual=float(abs(acceleration)),
                            limit=acceleration_limit,
                            unit=definition.domain_unit,
                        )
                    )
                previous_velocity[joint_id] = velocity
        for joint_id in profile.enabled_joints:
            definition = profile.definitions_by_id[joint_id]
            acceleration_limit = 800.0 if definition.joint_type is JointType.PRISMATIC else 720.0
            terminal_acceleration = abs(previous_velocity[joint_id]) / last_dt
            if terminal_acceleration > acceleration_limit + 1e-9:
                raise _CompilationFailure(
                    TrajectoryViolation(
                        code="JOINT_ACCELERATION_LIMIT",
                        check="acceleration",
                        message=f"{joint_id} cannot decelerate within its provisional limit",
                        segment_index=samples[-1].segment_index,
                        sample_index=samples[-1].sample_index,
                        joint_id=joint_id,
                        actual=float(terminal_acceleration),
                        limit=acceleration_limit,
                        unit=definition.domain_unit,
                    )
                )

    @staticmethod
    def _require_not_cancelled(
        cancellation_requested: CancelCheck | None,
        segment_index: int,
        sample_index: int,
    ) -> None:
        if cancellation_requested is None:
            return
        try:
            cancelled = cancellation_requested()
        except Exception as error:
            raise _CompilationFailure(
                TrajectoryViolation(
                    code="CANCELLATION_CHECK_FAILED",
                    check="cancellation",
                    message=f"Cancellation check failed safely: {type(error).__name__}",
                    segment_index=segment_index,
                    sample_index=sample_index,
                )
            ) from error
        if cancelled:
            raise _CompilationFailure(
                TrajectoryViolation(
                    code="COMPILATION_CANCELLED",
                    check="cancellation",
                    message="Trajectory compilation was cancelled",
                    segment_index=segment_index,
                    sample_index=sample_index,
                )
            )

    @staticmethod
    def _digest(
        motion: Motion,
        profile: RobotProfile,
        model: KinematicsModel,
        start_state_sequence: int,
        sample_rate_hz: float,
        duration_s: float,
        segments: list[TrajectorySegment],
        samples: list[TrajectorySample],
    ) -> str:
        semantic_payload = {
            "schema_version": "1.0.0",
            "motion_id": str(motion.id),
            "motion_revision": motion.revision,
            "robot_variant": motion.robot_variant.value,
            "profile_fingerprint": profile.fingerprint,
            "kinematics_fingerprint": model.fingerprint,
            "start_state_sequence": start_state_sequence,
            "sample_rate_hz": sample_rate_hz,
            "duration_s": duration_s,
            "segments": [segment.model_dump(mode="json") for segment in segments],
            "samples": [sample.model_dump(mode="json") for sample in samples],
        }
        encoded = json.dumps(
            semantic_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _rejected(
        motion: Motion,
        sample_rate_hz: float,
        duration_s: float,
        sample_count: int,
        segment_count: int,
        checks: list[TrajectoryPreflightCheck],
        violations: list[TrajectoryViolation],
    ) -> TrajectoryCompileOutcome:
        # Defensive fallback: the rejected report invariant requires at least one reason.
        if not violations:
            violations.append(
                TrajectoryViolation(
                    code="TRAJECTORY_REJECTED",
                    check="compiler",
                    message="Trajectory compilation was rejected safely",
                )
            )
        report = TrajectoryPreflightReport(
            accepted=False,
            motion_id=motion.id,
            motion_revision=motion.revision,
            digest=None,
            duration_s=float(duration_s) if isfinite(duration_s) and duration_s >= 0 else 0.0,
            sample_count=min(max(0, sample_count), MAX_TRAJECTORY_SAMPLES),
            segment_count=min(max(0, segment_count), MAX_TRAJECTORY_SEGMENTS),
            sample_rate_hz=sample_rate_hz,
            checks=checks,
            violations=violations,
        )
        return TrajectoryCompileOutcome(report=report, prepared=None)


__all__ = [
    "DEFAULT_SAMPLE_RATE_HZ",
    "MAX_SAMPLE_RATE_HZ",
    "MAX_TRAJECTORY_DURATION_S",
    "MAX_TRAJECTORY_SAMPLES",
    "MIN_SAMPLE_RATE_HZ",
    "TrajectoryCompiler",
    "TrajectoryKinematics",
]
