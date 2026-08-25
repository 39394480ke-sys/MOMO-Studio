"""Immutable contracts for staged real-hardware commissioning.

The models in this module are inert data.  Constructing them cannot open a port,
create a hardware adapter, issue a goal, or upgrade an operator session.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from momo.domain.enums import DomainUnit, RobotVariant
from momo.domain.pose import TcpPose
from momo.domain.robot import JointId, JointState

RobotUnitId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
OperatorId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
SoftwareCommit = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=7, max_length=64),
]

HARD_MAX_COMMAND_DURATION_S = 2.0
HARD_MAX_SESSION_DURATION_S = 300.0
HARD_MAX_REVOLUTE_DELTA_DEG = 2.0
HARD_MAX_PRISMATIC_DELTA_MM = 1.0
HARD_MAX_REVOLUTE_SPEED_DEG_S = 2.0
HARD_MAX_PRISMATIC_SPEED_MM_S = 1.0
HARD_MAX_REVOLUTE_ACCELERATION_DEG_S2 = 4.0
HARD_MAX_PRISMATIC_ACCELERATION_MM_S2 = 2.0
HARD_DEADMAN_LEASE_MS = 400
HARD_MAX_COMMANDS_PER_SESSION = 24


class CommissioningSafetyEnvelope(BaseModel):
    """Backend-owned caps snapshotted into a motion-test session.

    Every field has a compile-time upper bound.  Runtime/local configuration can
    instantiate a smaller envelope, but Pydantic rejects any attempted expansion.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    max_active_joints: Literal[1] = 1
    max_command_duration_s: float = Field(
        default=HARD_MAX_COMMAND_DURATION_S,
        gt=0.0,
        le=HARD_MAX_COMMAND_DURATION_S,
    )
    max_session_duration_s: float = Field(
        default=HARD_MAX_SESSION_DURATION_S,
        ge=30.0,
        le=HARD_MAX_SESSION_DURATION_S,
    )
    max_revolute_delta_deg: float = Field(
        default=HARD_MAX_REVOLUTE_DELTA_DEG,
        gt=0.0,
        le=HARD_MAX_REVOLUTE_DELTA_DEG,
    )
    max_prismatic_delta_mm: float = Field(
        default=HARD_MAX_PRISMATIC_DELTA_MM,
        gt=0.0,
        le=HARD_MAX_PRISMATIC_DELTA_MM,
    )
    max_revolute_speed_deg_s: float = Field(
        default=HARD_MAX_REVOLUTE_SPEED_DEG_S,
        gt=0.0,
        le=HARD_MAX_REVOLUTE_SPEED_DEG_S,
    )
    max_prismatic_speed_mm_s: float = Field(
        default=HARD_MAX_PRISMATIC_SPEED_MM_S,
        gt=0.0,
        le=HARD_MAX_PRISMATIC_SPEED_MM_S,
    )
    max_revolute_acceleration_deg_s2: float = Field(
        default=HARD_MAX_REVOLUTE_ACCELERATION_DEG_S2,
        gt=0.0,
        le=HARD_MAX_REVOLUTE_ACCELERATION_DEG_S2,
    )
    max_prismatic_acceleration_mm_s2: float = Field(
        default=HARD_MAX_PRISMATIC_ACCELERATION_MM_S2,
        gt=0.0,
        le=HARD_MAX_PRISMATIC_ACCELERATION_MM_S2,
    )
    deadman_lease_ms: int = Field(
        default=HARD_DEADMAN_LEASE_MS,
        strict=True,
        ge=100,
        le=HARD_DEADMAN_LEASE_MS,
    )
    max_commands_per_session: int = Field(
        default=HARD_MAX_COMMANDS_PER_SESSION,
        strict=True,
        ge=2,
        le=HARD_MAX_COMMANDS_PER_SESSION,
    )


COMMISSIONING_MOTION_HARD_CAPS = CommissioningSafetyEnvelope()


class CommissioningMotionTestState(StrEnum):
    IDLE = "IDLE"
    AUTHORIZED = "AUTHORIZED"
    ARMED = "ARMED"
    MOVING = "MOVING"
    VERIFYING = "VERIFYING"
    STOPPING = "STOPPING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class CommissioningTestResult(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class CommissioningDirection(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"


class StopBehavior(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    SOFTWARE_PATH_VERIFIED = "SOFTWARE_PATH_VERIFIED"
    SOFTWARE_PATH_FAILED = "SOFTWARE_PATH_FAILED"
    PHYSICAL_BEHAVIOR_PENDING = "PHYSICAL_BEHAVIOR_PENDING"


class PhysicalStopVerification(StrEnum):
    PENDING = "PENDING"
    VERIFIED_FOR_UNIT = "VERIFIED_FOR_UNIT"


class PreparedCommissioningTestCommand(BaseModel):
    """One immutable, service-prepared relative test command.

    No API request can provide a raw Servo target or construct this model on the
    adapter side.  The application service computes it from a fresh readback.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    command_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    robot_unit_id: RobotUnitId
    joint_id: str
    servo_id: int = Field(strict=True, ge=1, le=253)
    unit: DomainUnit
    start_value: float
    requested_delta: float
    target_value: float
    start_raw: int = Field(strict=True)
    target_raw: int = Field(strict=True)
    requested_speed: float = Field(gt=0.0)
    requested_acceleration: float = Field(gt=0.0)
    command_duration_s: float = Field(gt=0.0)
    prepared_at: datetime
    readback_fresh_until: datetime
    envelope: CommissioningSafetyEnvelope

    @field_validator("prepared_at", "readback_fresh_until")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        return _aware(value, "command timestamp")

    @model_validator(mode="after")
    def validate_prepared_command(self) -> Self:
        if self.readback_fresh_until <= self.prepared_at:
            raise ValueError("prepared readback freshness must extend beyond preparation")
        if self.target_value != _stable_add(self.start_value, self.requested_delta):
            raise ValueError("target_value must equal start_value plus requested_delta")
        if self.target_raw == self.start_raw:
            raise ValueError("a commissioning test must request a non-zero raw change")
        delta_cap = (
            self.envelope.max_prismatic_delta_mm
            if self.unit is DomainUnit.MM
            else self.envelope.max_revolute_delta_deg
        )
        speed_cap = (
            self.envelope.max_prismatic_speed_mm_s
            if self.unit is DomainUnit.MM
            else self.envelope.max_revolute_speed_deg_s
        )
        acceleration_cap = (
            self.envelope.max_prismatic_acceleration_mm_s2
            if self.unit is DomainUnit.MM
            else self.envelope.max_revolute_acceleration_deg_s2
        )
        if abs(self.requested_delta) > delta_cap:
            raise ValueError("requested delta exceeds the commissioning envelope")
        if self.requested_speed > speed_cap:
            raise ValueError("requested speed exceeds the commissioning envelope")
        if self.requested_acceleration > acceleration_cap:
            raise ValueError("requested acceleration exceeds the commissioning envelope")
        if self.command_duration_s > self.envelope.max_command_duration_s:
            raise ValueError("command duration exceeds the commissioning envelope")
        return self


def _stable_add(left: float, right: float) -> float:
    """Canonical float addition shared by command producers and validation."""

    return float(left) + float(right)


class CommissioningTestEvidence(BaseModel):
    """Immutable local result for one positive or negative joint test."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    revision: Literal[1] = 1
    id: UUID = Field(default_factory=uuid4)
    robot_unit_id: RobotUnitId
    robot_variant: RobotVariant
    profile_fingerprint: Fingerprint
    calibration_fingerprint: Fingerprint
    device_fingerprint: Fingerprint
    joint_id: str
    unit: DomainUnit
    start_value: float
    requested_delta: float
    target_value: float
    final_value: float
    start_raw: int = Field(strict=True)
    final_raw: int = Field(strict=True)
    requested_speed: float = Field(gt=0.0)
    measured_or_observed_result: str
    direction_expected: CommissioningDirection
    direction_observed: CommissioningDirection | None = None
    divergence: float = Field(ge=0.0)
    stop_behavior: StopBehavior
    started_at: datetime
    completed_at: datetime
    software_commit: SoftwareCommit
    operator_id: OperatorId
    request_id: str
    session_id: UUID
    prepared_target_raw: int = Field(strict=True)
    prepared_command: PreparedCommissioningTestCommand | None = None
    result: CommissioningTestResult
    failure_reason_optional: str | None = None

    @property
    def created_at(self) -> datetime:
        return self.completed_at

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        return _aware(value, "commissioning evidence timestamp")

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("commissioning evidence completion precedes start")
        if self.result is CommissioningTestResult.PASSED:
            if self.failure_reason_optional is not None:
                raise ValueError("passed commissioning evidence cannot contain a failure")
            if self.direction_observed is not self.direction_expected:
                raise ValueError("passed evidence must observe the commanded direction")
            if self.prepared_command is None:
                raise ValueError("passed commissioning evidence requires its prepared command")
        elif not self.failure_reason_optional:
            raise ValueError("failed commissioning evidence requires a failure reason")
        prepared = self.prepared_command
        if prepared is not None and (
            prepared.session_id != self.session_id
            or prepared.robot_unit_id != self.robot_unit_id
            or prepared.joint_id != self.joint_id
            or prepared.unit is not self.unit
            or prepared.start_value != self.start_value
            or prepared.requested_delta != self.requested_delta
            or prepared.target_value != self.target_value
            or prepared.start_raw != self.start_raw
            or prepared.target_raw != self.prepared_target_raw
            or prepared.requested_speed != self.requested_speed
            or prepared.prepared_at < self.started_at
            or prepared.prepared_at > self.completed_at
        ):
            raise ValueError("prepared command does not match commissioning evidence")
        return self


class FieldAcceptanceCapability(StrEnum):
    PRE_MOTION_CHECKS = "PRE_MOTION_CHECKS"
    JOINT_MOTION = "JOINT_MOTION"
    CARTESIAN = "CARTESIAN"
    PLAYBACK = "PLAYBACK"
    VISION_FOLLOW = "VISION_FOLLOW"


class FieldAcceptanceEvidenceState(StrEnum):
    MISSING = "MISSING"
    STALE = "STALE"
    STALE_LEGACY_EVIDENCE = "STALE_LEGACY_EVIDENCE"
    VALID = "VALID"


class PreMotionDiagnosticRecord(BaseModel):
    """Persisted read-only proof for one explicitly configured joint/servo."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    joint_id: JointId
    servo_id: int = Field(strict=True, ge=1, le=253)
    ping_responded: Literal[True]
    operating_mode: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ]
    present_raw: int = Field(strict=True)
    logical_value: float
    raw_bounds: tuple[int, int]
    torque_enabled: Literal[False]

    @model_validator(mode="after")
    def validate_raw_bounds(self) -> Self:
        if self.raw_bounds[0] >= self.raw_bounds[1]:
            raise ValueError("pre-motion raw bounds must be ordered")
        if not self.raw_bounds[0] <= self.present_raw <= self.raw_bounds[1]:
            raise ValueError("pre-motion position must be inside raw bounds")
        return self


class PreMotionChecksSnapshot(BaseModel):
    """Typed diagnostic snapshot that can survive READ_ONLY to FULL restart."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operator_session_id: UUID
    captured_at: datetime
    records: tuple[PreMotionDiagnosticRecord, ...]

    @field_validator("captured_at")
    @classmethod
    def require_aware_capture_time(cls, value: datetime) -> datetime:
        return _aware(value, "pre-motion captured_at")

    @field_validator("records")
    @classmethod
    def require_unique_nonempty_records(
        cls,
        value: tuple[PreMotionDiagnosticRecord, ...],
    ) -> tuple[PreMotionDiagnosticRecord, ...]:
        if not value:
            raise ValueError("pre-motion snapshot requires diagnostic records")
        joint_ids = tuple(item.joint_id for item in value)
        servo_ids = tuple(item.servo_id for item in value)
        if len(joint_ids) != len(set(joint_ids)):
            raise ValueError("pre-motion snapshot joint IDs must be unique")
        if len(servo_ids) != len(set(servo_ids)):
            raise ValueError("pre-motion snapshot servo IDs must be unique")
        return value


class FieldAcceptanceEvidence(BaseModel):
    """Backward-readable v1 record or capability-scoped v2 evidence.

    Schema v1 represented the removed global ``PASSED`` assertion.  It remains
    readable for audit but can never appear in ``valid_capabilities``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1, 2] = 2
    revision: Literal[1] = 1
    evidence_id: UUID = Field(default_factory=uuid4)
    status: Literal["PASSED"] = "PASSED"
    robot_unit_id: RobotUnitId | None = None
    robot_variant: RobotVariant
    profile_fingerprint: Fingerprint
    calibration_fingerprint: Fingerprint
    device_fingerprint: Fingerprint
    kinematics_fingerprint: Fingerprint | None = None
    capability: FieldAcceptanceCapability | None = None
    checklist_version: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ]
    test_evidence_ids: tuple[UUID, ...] = ()
    pre_motion_snapshot: PreMotionChecksSnapshot | None = None
    accepted_at: datetime
    accepted_by: OperatorId | None = None
    reviewed_by_optional: OperatorId | None = None
    software_commit: SoftwareCommit | None = None

    @property
    def id(self) -> UUID:
        return self.evidence_id

    @property
    def created_at(self) -> datetime:
        return self.accepted_at

    @field_validator("accepted_at")
    @classmethod
    def require_aware_acceptance_time(cls, value: datetime) -> datetime:
        return _aware(value, "accepted_at")

    @model_validator(mode="after")
    def validate_schema_generation(self) -> Self:
        if self.schema_version == 1:
            if (
                self.capability is not None
                or self.robot_unit_id is not None
                or self.pre_motion_snapshot is not None
            ):
                raise ValueError("legacy global evidence cannot contain v2 capability identity")
            return self
        if self.robot_unit_id is None or self.capability is None:
            raise ValueError("capability evidence requires robot_unit_id and capability")
        if self.accepted_by is None or self.software_commit is None:
            raise ValueError("capability evidence requires accepted_by and software_commit")
        if self.capability is FieldAcceptanceCapability.PRE_MOTION_CHECKS:
            if self.pre_motion_snapshot is None or self.test_evidence_ids:
                raise ValueError("pre-motion capability requires a typed snapshot and no test IDs")
        elif self.pre_motion_snapshot is not None or not self.test_evidence_ids:
            raise ValueError("capability evidence requires completed test evidence")
        if len(self.test_evidence_ids) != len(set(self.test_evidence_ids)):
            raise ValueError("test evidence IDs must be unique")
        return self

    @classmethod
    def for_capability(
        cls,
        *,
        context: Any,
        capability: FieldAcceptanceCapability,
        checklist_version: str,
        test_evidence_ids: tuple[UUID | str, ...],
        accepted_at: datetime,
        accepted_by: str,
        software_commit: str,
        reviewed_by_optional: str | None = None,
        pre_motion_snapshot: PreMotionChecksSnapshot | None = None,
    ) -> FieldAcceptanceEvidence:
        from momo.domain.real_hardware import calibration_fingerprint, explicit_device_fingerprint

        profile = context.profile
        calibration = context.calibration
        device = context.device
        robot_unit_id = context.robot_unit_id
        if profile is None or calibration is None or device is None or not robot_unit_id:
            raise ValueError("current unit, Profile, Calibration, and Device are required")
        return cls(
            robot_unit_id=robot_unit_id,
            robot_variant=profile.variant,
            profile_fingerprint=profile.fingerprint,
            calibration_fingerprint=calibration_fingerprint(calibration),
            device_fingerprint=explicit_device_fingerprint(device),
            kinematics_fingerprint=(
                context.kinematics.fingerprint
                if capability
                in {
                    FieldAcceptanceCapability.CARTESIAN,
                    FieldAcceptanceCapability.PLAYBACK,
                    FieldAcceptanceCapability.VISION_FOLLOW,
                }
                and context.kinematics is not None
                else None
            ),
            capability=capability,
            checklist_version=checklist_version,
            test_evidence_ids=tuple(UUID(str(value)) for value in test_evidence_ids),
            pre_motion_snapshot=pre_motion_snapshot,
            accepted_at=accepted_at,
            accepted_by=accepted_by,
            reviewed_by_optional=reviewed_by_optional,
            software_commit=software_commit,
        )


class FieldAcceptanceBundle(BaseModel):
    """Immutable audit history; unresolved records never grant authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    records: tuple[FieldAcceptanceEvidence, ...] = ()

    @field_validator("records")
    @classmethod
    def require_unique_evidence_ids(
        cls,
        value: tuple[FieldAcceptanceEvidence, ...],
    ) -> tuple[FieldAcceptanceEvidence, ...]:
        ids = tuple(item.evidence_id for item in value)
        if len(ids) != len(set(ids)):
            raise ValueError("field acceptance evidence IDs must be unique")
        return value

    def valid_capabilities(self, context: Any) -> frozenset[FieldAcceptanceCapability]:
        del context
        return frozenset()

    def newest_for(
        self,
        capability: FieldAcceptanceCapability,
    ) -> FieldAcceptanceEvidence | None:
        matching = [item for item in self.records if item.capability is capability]
        return max(matching, key=lambda item: item.accepted_at, default=None)


class ValidatedFieldAcceptanceBundle(FieldAcceptanceBundle):
    """Application-resolved evidence chains that may participate in authorization.

    Persisted FieldAcceptance records always deserialize as the audit-only base
    class.  A service must resolve their linked evidence repositories and create
    this transient projection before any capability becomes authoritative.
    """

    def valid_capabilities(self, context: Any) -> frozenset[FieldAcceptanceCapability]:
        from momo.domain.real_hardware import field_acceptance_evidence_state

        capabilities: set[FieldAcceptanceCapability] = set()
        for evidence in self.records:
            state, _ = field_acceptance_evidence_state(context, evidence)
            if state is FieldAcceptanceEvidenceState.VALID and evidence.capability is not None:
                capabilities.add(evidence.capability)
        return frozenset(capabilities)


class KinematicsVerificationThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    max_position_error_mm: float = Field(default=5.0, gt=0.0, le=25.0)
    max_orientation_error_deg: float = Field(default=5.0, gt=0.0, le=15.0)


class KinematicsVerificationPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    point_id: UUID = Field(default_factory=uuid4)
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    joint_state: JointState
    joint_state_sequence: int = Field(ge=0)
    joint_state_captured_at: datetime
    snapshot_session_id: UUID
    predicted_tcp: TcpPose
    measured_tcp: TcpPose
    position_error_mm: float = Field(ge=0.0)
    orientation_error_deg: float = Field(ge=0.0)
    measured_at: datetime

    @field_validator("joint_state_captured_at", "measured_at")
    @classmethod
    def require_aware_measurement_time(cls, value: datetime) -> datetime:
        return _aware(value, "kinematics verification timestamp")


class KinematicsVerificationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    revision: Literal[1] = 1
    id: UUID = Field(default_factory=uuid4)
    robot_unit_id: RobotUnitId
    variant: RobotVariant
    profile_fingerprint: Fingerprint
    calibration_fingerprint: Fingerprint
    device_fingerprint: Fingerprint
    kinematics_fingerprint: Fingerprint
    kinematics_model_schema_version: str
    verification_checklist_version: str
    test_points: tuple[KinematicsVerificationPoint, ...]
    thresholds: KinematicsVerificationThresholds
    accepted_at: datetime
    accepted_by: OperatorId
    software_commit: SoftwareCommit

    @property
    def created_at(self) -> datetime:
        return self.accepted_at

    @field_validator("accepted_at")
    @classmethod
    def require_aware_acceptance_time(cls, value: datetime) -> datetime:
        return _aware(value, "accepted_at")

    @model_validator(mode="after")
    def require_multiple_passing_points(self) -> Self:
        if len(self.test_points) < 3:
            raise ValueError("kinematics verification requires at least three test points")
        point_ids = tuple(point.point_id for point in self.test_points)
        if len(point_ids) != len(set(point_ids)):
            raise ValueError("kinematics verification point IDs must be unique")
        joint_positions = {
            tuple(sorted(point.joint_state.positions.items())) for point in self.test_points
        }
        if len(joint_positions) < 3:
            raise ValueError("kinematics verification requires three distinct joint states")
        state_sequences = tuple(point.joint_state_sequence for point in self.test_points)
        if len(state_sequences) != len(set(state_sequences)):
            raise ValueError("kinematics verification state sequences must be unique")
        if any(
            point.position_error_mm > self.thresholds.max_position_error_mm
            or point.orientation_error_deg > self.thresholds.max_orientation_error_deg
            for point in self.test_points
        ):
            raise ValueError("every kinematics test point must pass both residual thresholds")
        return self


class KinematicsEvidenceState(StrEnum):
    MISSING = "MISSING"
    STALE = "STALE"
    VALID = "VALID"


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone offset")
    return value


__all__ = [
    "COMMISSIONING_MOTION_HARD_CAPS",
    "CommissioningDirection",
    "CommissioningMotionTestState",
    "CommissioningSafetyEnvelope",
    "CommissioningTestEvidence",
    "CommissioningTestResult",
    "FieldAcceptanceBundle",
    "FieldAcceptanceCapability",
    "FieldAcceptanceEvidence",
    "FieldAcceptanceEvidenceState",
    "KinematicsEvidenceState",
    "KinematicsVerificationEvidence",
    "KinematicsVerificationPoint",
    "KinematicsVerificationThresholds",
    "PhysicalStopVerification",
    "PreMotionChecksSnapshot",
    "PreMotionDiagnosticRecord",
    "PreparedCommissioningTestCommand",
    "RobotUnitId",
    "StopBehavior",
    "ValidatedFieldAcceptanceBundle",
]
