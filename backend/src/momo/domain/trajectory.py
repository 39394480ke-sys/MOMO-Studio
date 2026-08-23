"""Immutable compiled trajectories and whole-plan preflight evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from math import isfinite
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from momo.domain.enums import DomainUnit, Easing, RobotVariant
from momo.domain.immutable import freeze_mapping, freeze_sequence
from momo.domain.pose import Fingerprint, TcpPose, _require_aware
from momo.domain.robot import JointId

TRAJECTORY_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"

FiniteTime = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
PositiveFinite = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
ViolationCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80, pattern=r"^[A-Z0-9_]+$"),
]


class TrajectorySegmentKind(StrEnum):
    JOINT = "JOINT"
    CARTESIAN_LINEAR = "CARTESIAN_LINEAR"
    HOLD = "HOLD"


class TrajectoryDigest(BaseModel):
    """Content identity of a trajectory's semantic, execution-relevant values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    algorithm: Literal["SHA-256"] = "SHA-256"
    sha256: Fingerprint


class TrajectorySample(BaseModel):
    """One canonical domain-unit sample; no raw or adapter-unit values are exposed."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    time_s: FiniteTime
    positions: dict[JointId, float]
    units: dict[JointId, DomainUnit]
    tcp_pose: TcpPose | None = None
    keyframe_id: UUID
    segment_index: Annotated[int, Field(strict=True, ge=0)]
    sample_index: Annotated[int, Field(strict=True, ge=0)]
    is_hold: bool = False

    @field_validator("positions")
    @classmethod
    def freeze_positions(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not isfinite(position) for position in value.values()):
            raise ValueError("trajectory positions must be finite")
        return freeze_mapping(value)

    @field_validator("units")
    @classmethod
    def freeze_units(cls, value: dict[str, DomainUnit]) -> dict[str, DomainUnit]:
        return freeze_mapping(value)

    @model_validator(mode="after")
    def require_explicit_units(self) -> Self:
        if set(self.positions) != set(self.units):
            raise ValueError("trajectory sample units must exactly match positions")
        return self


class TrajectorySegment(BaseModel):
    """A transition or hold and its shared-boundary sample range."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    segment_index: Annotated[int, Field(strict=True, ge=0)]
    kind: TrajectorySegmentKind
    from_keyframe_id: UUID
    to_keyframe_id: UUID
    easing: Easing | None
    start_time_s: FiniteTime
    end_time_s: FiniteTime
    duration_s: PositiveFinite
    start_sample_index: Annotated[int, Field(strict=True, ge=0)]
    end_sample_index: Annotated[int, Field(strict=True, ge=0)]
    generated_sample_count: Annotated[int, Field(strict=True, ge=1)]

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end_time_s <= self.start_time_s:
            raise ValueError("trajectory segment end time must follow its start")
        if abs((self.end_time_s - self.start_time_s) - self.duration_s) > 1e-9:
            raise ValueError("trajectory segment duration does not match its time range")
        if self.end_sample_index <= self.start_sample_index:
            raise ValueError("trajectory segment must introduce at least one sample")
        if self.end_sample_index - self.start_sample_index != self.generated_sample_count:
            raise ValueError("trajectory segment sample range is inconsistent")
        if self.kind is TrajectorySegmentKind.HOLD:
            if self.easing is not None or self.from_keyframe_id != self.to_keyframe_id:
                raise ValueError("hold segments cannot have easing or different keyframes")
        elif self.easing is None:
            raise ValueError("motion segments require easing")
        return self


class TrajectoryPreflightCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    passed: bool
    detail: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class TrajectoryViolation(BaseModel):
    """A bounded, UI-safe reason that a whole trajectory was rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    code: ViolationCode
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    check: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    segment_index: Annotated[int, Field(strict=True, ge=0)] | None = None
    sample_index: Annotated[int, Field(strict=True, ge=0)] | None = None
    joint_id: JointId | None = None
    actual: Annotated[float, Field(strict=True, allow_inf_nan=False)] | None = None
    limit: Annotated[float, Field(strict=True, allow_inf_nan=False)] | None = None
    unit: DomainUnit | None = None
    blocking: Literal[True] = True


class TrajectoryPlan(BaseModel):
    """Complete deterministic sample plan bound to one observed robot state."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        revalidate_instances="always",
    )

    schema_version: Literal["1.0.0"] = TRAJECTORY_SCHEMA_VERSION
    motion_id: UUID
    motion_revision: Annotated[int, Field(strict=True, ge=1)]
    robot_variant: RobotVariant
    profile_fingerprint: Fingerprint
    kinematics_fingerprint: Fingerprint
    start_state_sequence: Annotated[int, Field(strict=True, ge=0)]
    sample_rate_hz: Annotated[float, Field(strict=True, gt=0, le=100, allow_inf_nan=False)]
    duration_s: PositiveFinite
    segments: Annotated[list[TrajectorySegment], Field(min_length=1, max_length=2000)]
    samples: Annotated[list[TrajectorySample], Field(min_length=2, max_length=20000)]
    digest: TrajectoryDigest
    compiled_at: datetime

    @field_validator("segments")
    @classmethod
    def freeze_segments(cls, value: list[TrajectorySegment]) -> list[TrajectorySegment]:
        return freeze_sequence(value)

    @field_validator("samples")
    @classmethod
    def freeze_samples(cls, value: list[TrajectorySample]) -> list[TrajectorySample]:
        return freeze_sequence(value)

    @field_validator("compiled_at")
    @classmethod
    def compiled_at_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "compiled_at")

    @model_validator(mode="after")
    def validate_plan_shape(self) -> Self:
        if [segment.segment_index for segment in self.segments] != list(range(len(self.segments))):
            raise ValueError("trajectory segment indices must be contiguous")
        if [sample.sample_index for sample in self.samples] != list(range(len(self.samples))):
            raise ValueError("trajectory sample indices must be contiguous")
        times = [sample.time_s for sample in self.samples]
        if times[0] != 0.0:
            raise ValueError("trajectory must begin at time zero")
        if any(current <= previous for previous, current in pairwise(times)):
            raise ValueError("trajectory sample times must be strictly increasing")
        if abs(times[-1] - self.duration_s) > 1e-9:
            raise ValueError("trajectory final sample must equal the exact duration")
        if self.segments[-1].end_sample_index != len(self.samples) - 1:
            raise ValueError("trajectory final segment must end on the final sample")
        if abs(self.segments[-1].end_time_s - self.duration_s) > 1e-9:
            raise ValueError("trajectory final segment must end at the exact duration")
        if self.digest.sha256 != self.computed_sha256:
            raise ValueError("trajectory digest does not match execution-relevant plan values")
        return self

    @property
    def computed_sha256(self) -> str:
        """Recompute content identity without the intentionally variable timestamp."""

        semantic_payload = {
            "schema_version": self.schema_version,
            "motion_id": str(self.motion_id),
            "motion_revision": self.motion_revision,
            "robot_variant": self.robot_variant.value,
            "profile_fingerprint": self.profile_fingerprint,
            "kinematics_fingerprint": self.kinematics_fingerprint,
            "start_state_sequence": self.start_state_sequence,
            "sample_rate_hz": self.sample_rate_hz,
            "duration_s": self.duration_s,
            "segments": [segment.model_dump(mode="json") for segment in self.segments],
            "samples": [sample.model_dump(mode="json") for sample in self.samples],
        }
        encoded = json.dumps(
            semantic_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class TrajectoryPreflightReport(BaseModel):
    """Whole-plan evidence suitable for API and UI presentation."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    accepted: bool
    motion_id: UUID
    motion_revision: Annotated[int, Field(strict=True, ge=1)]
    digest: TrajectoryDigest | None
    duration_s: FiniteTime
    sample_count: Annotated[int, Field(strict=True, ge=0, le=20000)]
    segment_count: Annotated[int, Field(strict=True, ge=0, le=2000)]
    sample_rate_hz: Annotated[float, Field(strict=True, gt=0, le=100, allow_inf_nan=False)]
    checks: list[TrajectoryPreflightCheck]
    violations: list[TrajectoryViolation]
    real_motion_ready: Literal[False] = False
    field_acceptance_ready: Literal[False] = False
    hardware_accessed: Literal[False] = False

    @field_validator("checks")
    @classmethod
    def freeze_checks(cls, value: list[TrajectoryPreflightCheck]) -> list[TrajectoryPreflightCheck]:
        return freeze_sequence(value)

    @field_validator("violations")
    @classmethod
    def freeze_violations(cls, value: list[TrajectoryViolation]) -> list[TrajectoryViolation]:
        return freeze_sequence(value)

    @model_validator(mode="after")
    def validate_acceptance(self) -> Self:
        if self.accepted != (not self.violations and self.digest is not None):
            raise ValueError("preflight acceptance must match violations and digest")
        if not self.accepted and self.digest is not None:
            raise ValueError("rejected preflight cannot expose an executable digest")
        return self


class PreparedTrajectory(BaseModel):
    """The exact accepted plan; execution must not compile a replacement."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    plan: TrajectoryPlan
    preflight: TrajectoryPreflightReport

    @model_validator(mode="after")
    def report_must_bind_exact_plan(self) -> Self:
        if not self.preflight.accepted:
            raise ValueError("prepared trajectory requires an accepted preflight")
        if self.preflight.motion_id != self.plan.motion_id:
            raise ValueError("prepared trajectory motion ID mismatch")
        if self.preflight.motion_revision != self.plan.motion_revision:
            raise ValueError("prepared trajectory motion revision mismatch")
        if self.preflight.digest != self.plan.digest:
            raise ValueError("prepared trajectory digest mismatch")
        if self.preflight.duration_s != self.plan.duration_s:
            raise ValueError("prepared trajectory duration mismatch")
        if self.preflight.sample_count != len(self.plan.samples):
            raise ValueError("prepared trajectory sample count mismatch")
        if self.preflight.segment_count != len(self.plan.segments):
            raise ValueError("prepared trajectory segment count mismatch")
        return self

    @property
    def trajectory_id(self) -> str:
        return self.plan.digest.sha256

    @property
    def initial_state_sequence(self) -> int:
        return self.plan.start_state_sequence

    @property
    def sampling_interval_s(self) -> float:
        return 1.0 / self.plan.sample_rate_hz

    def binding_violations(
        self,
        *,
        motion_revision: int,
        robot_variant: RobotVariant,
        profile_fingerprint: str,
        kinematics_fingerprint: str,
        state_sequence: int,
    ) -> tuple[TrajectoryViolation, ...]:
        """Recheck all mutable execution bindings without recompiling the plan."""

        checks = (
            (
                motion_revision == self.plan.motion_revision,
                "MOTION_REVISION_CHANGED",
                "motion_revision",
                "Motion revision changed after preflight",
            ),
            (
                robot_variant is self.plan.robot_variant,
                "VARIANT_CHANGED",
                "variant",
                "Robot variant changed after preflight",
            ),
            (
                profile_fingerprint == self.plan.profile_fingerprint,
                "PROFILE_CHANGED",
                "profile",
                "Profile changed after preflight",
            ),
            (
                kinematics_fingerprint == self.plan.kinematics_fingerprint,
                "KINEMATICS_CHANGED",
                "kinematics",
                "Kinematics changed after preflight",
            ),
            (
                state_sequence == self.plan.start_state_sequence,
                "STATE_SEQUENCE_CHANGED",
                "state_sequence",
                "Robot state sequence changed after preflight",
            ),
        )
        return tuple(
            TrajectoryViolation(code=code, check=check, message=message)
            for condition, code, check, message in checks
            if not condition
        )


class TrajectoryCompileOutcome(BaseModel):
    """Non-throwing compiler result with an optional executable prepared value."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    report: TrajectoryPreflightReport
    prepared: PreparedTrajectory | None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.report.accepted != (self.prepared is not None):
            raise ValueError("accepted compile outcome must contain exactly one prepared plan")
        if self.prepared is not None and self.prepared.preflight != self.report:
            raise ValueError("compile outcome report must be the prepared plan report")
        return self


__all__ = [
    "PreparedTrajectory",
    "TrajectoryCompileOutcome",
    "TrajectoryDigest",
    "TrajectoryPlan",
    "TrajectoryPreflightCheck",
    "TrajectoryPreflightReport",
    "TrajectorySample",
    "TrajectorySegment",
    "TrajectorySegmentKind",
    "TrajectoryViolation",
]
