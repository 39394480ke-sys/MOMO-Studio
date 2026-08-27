"""Fail-closed Stage 8 contracts for explicit real-hardware authorization.

These values describe authorization evidence and bounded ServoBus outcomes.  They
do not import an SDK, open a device, scan IDs, enable torque, or authorize motion
on their own.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from momo.domain.calibration import CalibrationDocument
from momo.domain.commissioning import (
    CommissioningSafetyEnvelope,
    FieldAcceptanceBundle,
    FieldAcceptanceCapability,
    FieldAcceptanceEvidence,
    FieldAcceptanceEvidenceState,
    KinematicsEvidenceState,
    KinematicsVerificationEvidence,
    PhysicalStopVerification,
    RobotUnitId,
)
from momo.domain.enums import (
    ControlMode,
    HardwareAccessPolicy,
    RobotVariant,
)
from momo.domain.kinematics.model import KinematicsModel
from momo.domain.raw_direction import RawDirectionSafetyEnvelope
from momo.domain.robot import RobotProfile

REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT = "I UNDERSTAND REAL HARDWARE CAN MOVE"
REQUIRED_COMMISSIONING_CONFIRMATION_TEXT = "I UNDERSTAND COMMISSIONING IS READ ONLY"
REQUIRED_COMMISSIONING_MOTION_CONFIRMATION_TEXT = (
    "I UNDERSTAND COMMISSIONING MOTION TEST CAN MOVE ONE JOINT"
)
REQUIRED_RAW_DIRECTION_CONFIRMATION_TEXT = (
    "I CONFIRM CURRENT POSE MATCHES URDF ZERO AND RAW TEST CAN MOVE ONE JOINT"
)
REQUIRED_FIELD_ACCEPTANCE_CONFIRMATION_TEXT: Literal[
    "I CONFIRM THE FIELD ACCEPTANCE CHECKLIST IS COMPLETE"
] = "I CONFIRM THE FIELD ACCEPTANCE CHECKLIST IS COMPLETE"
DEFAULT_FIELD_ACCEPTANCE_CHECKLIST_VERSION = "1"
DEFAULT_KINEMATICS_VERIFICATION_CHECKLIST_VERSION = "1"
MAX_EXPLICIT_SERVO_IDS = 32

ServoId = Annotated[int, Field(strict=True, ge=1, le=253)]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
BoundedDetail = Annotated[str, StringConstraints(max_length=500)]


class FieldAcceptanceStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class RealHardwareReadinessState(StrEnum):
    BLOCKED_BY_STAGE_POLICY = "BLOCKED_BY_STAGE_POLICY"
    BLOCKED_BY_CONTROL_MODE = "BLOCKED_BY_CONTROL_MODE"
    BLOCKED_BY_HARDWARE_POLICY = "BLOCKED_BY_HARDWARE_POLICY"
    BLOCKED_BY_PROFILE = "BLOCKED_BY_PROFILE"
    BLOCKED_BY_CALIBRATION = "BLOCKED_BY_CALIBRATION"
    BLOCKED_BY_KINEMATICS = "BLOCKED_BY_KINEMATICS"
    BLOCKED_BY_DEVICE = "BLOCKED_BY_DEVICE"
    BLOCKED_BY_OPERATOR_AUTHORIZATION = "BLOCKED_BY_OPERATOR_AUTHORIZATION"
    BLOCKED_BY_FIELD_ACCEPTANCE = "BLOCKED_BY_FIELD_ACCEPTANCE"
    AWAITING_OPERATOR_SESSION = "AWAITING_OPERATOR_SESSION"
    COMMISSIONING_READY = "COMMISSIONING_READY"
    READY = "READY"


class RealHardwareBlocker(StrEnum):
    CONTROL_MODE_MUST_BE_REAL = "CONTROL_MODE_MUST_BE_REAL"
    HARDWARE_POLICY_MUST_BE_FULL = "HARDWARE_POLICY_MUST_BE_FULL"
    HARDWARE_POLICY_MUST_BE_READ_ONLY = "HARDWARE_POLICY_MUST_BE_READ_ONLY"
    REAL_MOTION_NOT_ENABLED = "REAL_MOTION_NOT_ENABLED"
    STARTUP_HARDWARE_FLAG_MISSING = "STARTUP_HARDWARE_FLAG_MISSING"
    EXPLICIT_LOCAL_CONFIG_MISSING = "EXPLICIT_LOCAL_CONFIG_MISSING"
    PROFILE_MISSING = "PROFILE_MISSING"
    PROFILE_IS_TEMPLATE = "PROFILE_IS_TEMPLATE"
    PROFILE_NOT_VERIFIED_FOR_REAL = "PROFILE_NOT_VERIFIED_FOR_REAL"
    CALIBRATION_MISSING = "CALIBRATION_MISSING"
    CALIBRATION_IS_TEMPLATE = "CALIBRATION_IS_TEMPLATE"
    CALIBRATION_VARIANT_MISMATCH = "CALIBRATION_VARIANT_MISMATCH"
    CALIBRATION_PROFILE_MISMATCH = "CALIBRATION_PROFILE_MISMATCH"
    CALIBRATION_JOINT_SET_MISMATCH = "CALIBRATION_JOINT_SET_MISMATCH"
    CALIBRATION_MAPPING_MISMATCH = "CALIBRATION_MAPPING_MISMATCH"
    CALIBRATION_INCOMPLETE = "CALIBRATION_INCOMPLETE"
    CALIBRATION_ROBOT_UNIT_MISMATCH = "CALIBRATION_ROBOT_UNIT_MISMATCH"
    KINEMATICS_MISSING = "KINEMATICS_MISSING"
    KINEMATICS_NOT_VERIFIED_FOR_REAL = "KINEMATICS_NOT_VERIFIED_FOR_REAL"
    KINEMATICS_FINGERPRINT_MISSING = "KINEMATICS_FINGERPRINT_MISSING"
    KINEMATICS_FINGERPRINT_MISMATCH = "KINEMATICS_FINGERPRINT_MISMATCH"
    KINEMATICS_PROFILE_MISMATCH = "KINEMATICS_PROFILE_MISMATCH"
    FIELD_ACCEPTANCE_NOT_PASSED = "FIELD_ACCEPTANCE_NOT_PASSED"
    FIELD_ACCEPTANCE_EVIDENCE_MISSING = "FIELD_ACCEPTANCE_EVIDENCE_MISSING"
    FIELD_ACCEPTANCE_EVIDENCE_STALE = "FIELD_ACCEPTANCE_EVIDENCE_STALE"
    ROBOT_UNIT_ID_REQUIRED = "ROBOT_UNIT_ID_REQUIRED"
    ROBOT_UNIT_MISMATCH = "ROBOT_UNIT_MISMATCH"
    COMMISSIONING_MOTION_NOT_ENABLED = "COMMISSIONING_MOTION_NOT_ENABLED"
    RAW_DIRECTION_TEST_NOT_ENABLED = "RAW_DIRECTION_TEST_NOT_ENABLED"
    RAW_DIRECTION_ADAPTER_UNAVAILABLE = "RAW_DIRECTION_ADAPTER_UNAVAILABLE"
    SOFTWARE_COMMIT_REQUIRED = "SOFTWARE_COMMIT_REQUIRED"
    PRE_MOTION_CHECKS_INCOMPLETE = "PRE_MOTION_CHECKS_INCOMPLETE"
    COMMISSIONING_MOTION_SESSION_REQUIRED = "COMMISSIONING_MOTION_SESSION_REQUIRED"
    RAW_DIRECTION_SESSION_REQUIRED = "RAW_DIRECTION_SESSION_REQUIRED"
    JOINT_MOTION_ACCEPTANCE_PENDING = "JOINT_MOTION_ACCEPTANCE_PENDING"
    CARTESIAN_ACCEPTANCE_PENDING = "CARTESIAN_ACCEPTANCE_PENDING"
    PLAYBACK_ACCEPTANCE_PENDING = "PLAYBACK_ACCEPTANCE_PENDING"
    VISION_FOLLOW_ACCEPTANCE_PENDING = "VISION_FOLLOW_ACCEPTANCE_PENDING"
    KINEMATICS_VERIFICATION_PENDING = "KINEMATICS_VERIFICATION_PENDING"
    KINEMATICS_EVIDENCE_STALE = "KINEMATICS_EVIDENCE_STALE"
    PHYSICAL_STOP_NOT_VERIFIED = "PHYSICAL_STOP_NOT_VERIFIED"
    SERVO_BUS_DEPENDENCY_UNAVAILABLE = "SERVO_BUS_DEPENDENCY_UNAVAILABLE"
    SERVO_BUS_DEPENDENCY_IDENTITY_MISSING = "SERVO_BUS_DEPENDENCY_IDENTITY_MISSING"
    EXPLICIT_DEVICE_MISSING = "EXPLICIT_DEVICE_MISSING"
    DEVICE_SERVO_IDS_MISMATCH = "DEVICE_SERVO_IDS_MISMATCH"
    DEVICE_SAFETY_STATE_UNCERTAIN = "DEVICE_SAFETY_STATE_UNCERTAIN"
    OPERATOR_SESSION_MISSING = "OPERATOR_SESSION_MISSING"
    OPERATOR_SESSION_EXPIRED = "OPERATOR_SESSION_EXPIRED"
    OPERATOR_SESSION_MISMATCH = "OPERATOR_SESSION_MISMATCH"


class RealStopResult(StrEnum):
    STOPPED_AND_VERIFIED = "STOPPED_AND_VERIFIED"
    HOLD_REQUESTED = "HOLD_REQUESTED"
    TORQUE_DISABLE_REQUESTED = "TORQUE_DISABLE_REQUESTED"
    NOT_CONNECTED = "NOT_CONNECTED"
    FAILED = "FAILED"
    SAFETY_STATE_UNCERTAIN = "SAFETY_STATE_UNCERTAIN"


class HardwareDependencyState(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    PENDING_ADAPTER_VERIFICATION = "PENDING_ADAPTER_VERIFICATION"


class RealHardwareAuthorizationPurpose(StrEnum):
    """Narrow purpose bound into every access grant; diagnostics is read-only."""

    DIAGNOSTICS = "DIAGNOSTICS"
    CALIBRATION_CAPTURE = "CALIBRATION_CAPTURE"
    COMMISSIONING_SINGLE_JOINT_TEST = "COMMISSIONING_SINGLE_JOINT_TEST"
    RAW_DIRECTION_TEST = "RAW_DIRECTION_TEST"
    REAL_JOINT_MOTION = "REAL_JOINT_MOTION"
    REAL_CARTESIAN_MOTION = "REAL_CARTESIAN_MOTION"
    REAL_PLAYBACK = "REAL_PLAYBACK"
    REAL_VISION_FOLLOW = "REAL_VISION_FOLLOW"


class OperatorSessionPurpose(StrEnum):
    """A session is born with one purpose and can never be upgraded."""

    COMMISSIONING_READ_ONLY = "COMMISSIONING_READ_ONLY"
    COMMISSIONING_MOTION_TEST = "COMMISSIONING_MOTION_TEST"
    RAW_DIRECTION_TEST = "RAW_DIRECTION_TEST"
    REAL_MOTION = "REAL_MOTION"


class OperatorSessionScope(StrEnum):
    DIAGNOSTICS_READ = "DIAGNOSTICS_READ"
    CALIBRATION_CAPTURE = "CALIBRATION_CAPTURE"
    COMMISSIONING_SINGLE_JOINT_TEST = "COMMISSIONING_SINGLE_JOINT_TEST"
    RAW_DIRECTION_TEST = "RAW_DIRECTION_TEST"
    REAL_JOINT_MOTION = "REAL_JOINT_MOTION"
    REAL_CARTESIAN_MOTION = "REAL_CARTESIAN_MOTION"
    REAL_PLAYBACK = "REAL_PLAYBACK"
    REAL_VISION_FOLLOW = "REAL_VISION_FOLLOW"


COMMISSIONING_SCOPES = frozenset(
    {
        OperatorSessionScope.DIAGNOSTICS_READ,
        OperatorSessionScope.CALIBRATION_CAPTURE,
    }
)
COMMISSIONING_MOTION_SCOPES = frozenset({OperatorSessionScope.COMMISSIONING_SINGLE_JOINT_TEST})
RAW_DIRECTION_SCOPES = frozenset({OperatorSessionScope.RAW_DIRECTION_TEST})
MOTION_SCOPES = frozenset(
    {
        OperatorSessionScope.REAL_JOINT_MOTION,
        OperatorSessionScope.REAL_CARTESIAN_MOTION,
        OperatorSessionScope.REAL_PLAYBACK,
        OperatorSessionScope.REAL_VISION_FOLLOW,
    }
)

AUTHORIZATION_PURPOSE_SCOPE = {
    RealHardwareAuthorizationPurpose.DIAGNOSTICS: OperatorSessionScope.DIAGNOSTICS_READ,
    RealHardwareAuthorizationPurpose.CALIBRATION_CAPTURE: (
        OperatorSessionScope.CALIBRATION_CAPTURE
    ),
    RealHardwareAuthorizationPurpose.COMMISSIONING_SINGLE_JOINT_TEST: (
        OperatorSessionScope.COMMISSIONING_SINGLE_JOINT_TEST
    ),
    RealHardwareAuthorizationPurpose.RAW_DIRECTION_TEST: OperatorSessionScope.RAW_DIRECTION_TEST,
    RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION: (OperatorSessionScope.REAL_JOINT_MOTION),
    RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION: (
        OperatorSessionScope.REAL_CARTESIAN_MOTION
    ),
    RealHardwareAuthorizationPurpose.REAL_PLAYBACK: OperatorSessionScope.REAL_PLAYBACK,
    RealHardwareAuthorizationPurpose.REAL_VISION_FOLLOW: (OperatorSessionScope.REAL_VISION_FOLLOW),
}


class ExplicitServoDevice(BaseModel):
    """One explicitly configured device and exact ID allowlist; never a scan range."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Empty is accepted only so safe defaults and legacy local configs remain
    # readable.  Every commissioning/Real authorization gate rejects it.
    robot_unit_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=64),
    ] = ""
    serial_port: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
    ] = Field(repr=False)
    protocol: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=64,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        ),
    ]
    servo_ids: tuple[ServoId, ...]

    @field_validator("servo_ids")
    @classmethod
    def require_explicit_unique_ids(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if not value:
            raise ValueError("at least one explicit servo ID is required")
        if len(value) > MAX_EXPLICIT_SERVO_IDS:
            raise ValueError(f"at most {MAX_EXPLICIT_SERVO_IDS} servo IDs are allowed")
        if len(value) != len(set(value)):
            raise ValueError("explicit servo IDs must be unique")
        return value

    @field_validator("robot_unit_id")
    @classmethod
    def validate_optional_robot_unit_id(cls, value: str) -> str:
        if value:
            # Reuse the strict product identifier contract without requiring it
            # merely to parse a legacy/safe configuration.
            from pydantic import TypeAdapter

            TypeAdapter(RobotUnitId).validate_python(value)
        return value

    @property
    def masked_serial_port(self) -> str:
        # Always hide at least one character, including short names such as COM3.
        visible_count = min(4, max(1, len(self.serial_port) // 4))
        tail = self.serial_port[-visible_count:]
        return f"***{tail}"

    @property
    def masked_servo_ids(self) -> tuple[str, ...]:
        return tuple(f"servo-{index}" for index, _ in enumerate(self.servo_ids, start=1))


class ServoPingResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    servo_id: ServoId
    responded: bool
    detail: BoundedDetail = ""


class ServoWriteResult(BaseModel):
    """Exact write partition; partial success never masquerades as completion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_ids: tuple[ServoId, ...]
    written_ids: tuple[ServoId, ...]
    failed_ids: tuple[ServoId, ...]
    connected: bool
    complete: bool
    safety_state_known: bool
    detail: BoundedDetail = ""

    @model_validator(mode="after")
    def validate_partition(self) -> Self:
        requested = set(self.requested_ids)
        written = set(self.written_ids)
        failed = set(self.failed_ids)
        if any(
            len(values) != len(set(values))
            for values in (self.requested_ids, self.written_ids, self.failed_ids)
        ):
            raise ValueError("write result IDs must be unique")
        if not requested:
            raise ValueError("write result requires at least one requested ID")
        if written & failed:
            raise ValueError("written_ids and failed_ids must be disjoint")
        if written | failed != requested:
            raise ValueError("written_ids and failed_ids must exactly partition requested_ids")
        expected_complete = self.connected and written == requested and not failed
        if self.complete is not expected_complete:
            raise ValueError("complete must exactly describe the write partition")
        if self.complete and not self.safety_state_known:
            raise ValueError("a complete write must have a known safety state")
        if not self.connected and written:
            raise ValueError("a disconnected write cannot report written IDs")
        return self


class RealStopOutcome(BaseModel):
    """Software Stop truth; only STOPPED_AND_VERIFIED claims verified stopping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    result: RealStopResult
    requested_ids: tuple[ServoId, ...]
    affected_ids: tuple[ServoId, ...]
    connected: bool
    safety_state_known: bool
    detail: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]

    @model_validator(mode="after")
    def validate_truthfulness(self) -> Self:
        requested = set(self.requested_ids)
        affected = set(self.affected_ids)
        if len(requested) != len(self.requested_ids) or len(affected) != len(self.affected_ids):
            raise ValueError("Stop outcome IDs must be unique")
        if not affected <= requested:
            raise ValueError("affected_ids must be a subset of requested_ids")
        if not self.connected and affected:
            raise ValueError("a disconnected Stop cannot claim affected IDs")
        if self.result is RealStopResult.STOPPED_AND_VERIFIED:
            if (
                not requested
                or not self.connected
                or not self.safety_state_known
                or affected != requested
            ):
                raise ValueError("STOPPED_AND_VERIFIED requires all IDs verified while connected")
        elif self.result is RealStopResult.NOT_CONNECTED:
            if self.connected or self.safety_state_known or affected:
                raise ValueError("NOT_CONNECTED cannot claim affected IDs or a known safety state")
        elif self.result in {
            RealStopResult.HOLD_REQUESTED,
            RealStopResult.TORQUE_DISABLE_REQUESTED,
        }:
            if not self.connected or affected != requested or self.safety_state_known:
                raise ValueError(f"{self.result.value} requires every connected ID to be requested")
        elif self.safety_state_known:
            raise ValueError(f"{self.result.value} cannot claim a verified physical stop")
        return self


class HardwareConfirmationEvidence(BaseModel):
    """Redacted facts the operator must compare before requesting a session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    robot_id: str | None = None
    robot_unit_id: str | None = None
    variant: RobotVariant | None = None
    profile_fingerprint: Fingerprint | None = None
    calibration_fingerprint: Fingerprint | None = None
    kinematics_fingerprint: Fingerprint | None = None
    field_acceptance_evidence_id: UUID | None = None
    pre_motion_evidence_id: UUID | None = None
    masked_serial_port: str | None = None
    masked_servo_ids: tuple[str, ...] = ()
    protocol: str | None = None
    session_purpose: OperatorSessionPurpose = OperatorSessionPurpose.REAL_MOTION
    physical_estop_required: Literal[True] = True
    workspace_clear_required: bool = False
    required_confirmation_text: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ] = REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT

    @model_validator(mode="after")
    def validate_confirmation_text(self) -> Self:
        expected = confirmation_text_for(self.session_purpose)
        if self.required_confirmation_text != expected:
            raise ValueError("confirmation text must match the operator session purpose")
        if self.workspace_clear_required is not (
            self.session_purpose
            in {
                OperatorSessionPurpose.COMMISSIONING_MOTION_TEST,
                OperatorSessionPurpose.RAW_DIRECTION_TEST,
            }
        ):
            raise ValueError("workspace-clear requirement must match the session purpose")
        return self


class FieldAcceptanceEvidenceStatus(BaseModel):
    """Current-context interpretation; a legacy PASSED string is never authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: FieldAcceptanceEvidenceState
    effective_status: FieldAcceptanceStatus
    checklist_version: str
    stale_fields: tuple[str, ...] = ()
    evidence_id: UUID | None = None
    accepted_at: datetime | None = None
    accepted_by: str | None = None
    required_confirmation_text: Literal["I CONFIRM THE FIELD ACCEPTANCE CHECKLIST IS COMPLETE"] = (
        REQUIRED_FIELD_ACCEPTANCE_CONFIRMATION_TEXT
    )

    @model_validator(mode="after")
    def validate_evidence_summary(self) -> Self:
        has_evidence = self.evidence_id is not None and self.accepted_at is not None
        if self.state is FieldAcceptanceEvidenceState.MISSING and (
            has_evidence or self.stale_fields
        ):
            raise ValueError("missing acceptance evidence cannot retain evidence metadata")
        if self.state is not FieldAcceptanceEvidenceState.MISSING and not has_evidence:
            raise ValueError("stored acceptance evidence requires identity and acceptance time")
        if self.state is FieldAcceptanceEvidenceState.VALID:
            if self.stale_fields:
                raise ValueError("valid capability evidence must be unstale")
        elif self.effective_status is FieldAcceptanceStatus.PASSED:
            raise ValueError("only valid acceptance evidence can report PASSED")
        if self.accepted_at is not None:
            _require_aware(self.accepted_at, "accepted_at")
        return self


class OperatorSessionEvidence(BaseModel):
    """Token-free authorization evidence shared with later real execution paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID
    purpose: OperatorSessionPurpose
    scopes: frozenset[OperatorSessionScope]
    robot_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    robot_unit_id: RobotUnitId
    operator_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
    ]
    variant: RobotVariant
    profile_fingerprint: Fingerprint
    calibration_fingerprint: Fingerprint | None = None
    kinematics_fingerprint: Fingerprint | None = None
    field_acceptance_evidence_id: UUID | None = None
    pre_motion_evidence_id: UUID | None = None
    commissioning_envelope: CommissioningSafetyEnvelope | None = None
    raw_direction_envelope: RawDirectionSafetyEnvelope | None = None
    device_fingerprint: Fingerprint
    allowed_servo_ids: tuple[ServoId, ...]
    issued_at: datetime
    expires_at: datetime
    confirmed: Literal[True] = True
    physical_estop_confirmed: Literal[True] = True
    workspace_clear_confirmed: bool = False
    control_mode: Literal[ControlMode.REAL] = ControlMode.REAL
    hardware_access_policy: HardwareAccessPolicy

    @model_validator(mode="after")
    def validate_session(self) -> Self:
        _require_aware(self.issued_at, "issued_at")
        _require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.issued_at:
            raise ValueError("operator session expiry must follow issuance")
        if not self.allowed_servo_ids or len(self.allowed_servo_ids) != len(
            set(self.allowed_servo_ids)
        ):
            raise ValueError("operator session requires unique allowed servo IDs")
        if not self.scopes:
            raise ValueError("operator session requires at least one scope")
        if self.purpose is OperatorSessionPurpose.COMMISSIONING_READ_ONLY:
            if self.hardware_access_policy is not HardwareAccessPolicy.READ_ONLY:
                raise ValueError("commissioning sessions require READ_ONLY hardware policy")
            if self.scopes != COMMISSIONING_SCOPES:
                raise ValueError("commissioning sessions have an exact read-only scope set")
            if self.calibration_fingerprint is not None or self.kinematics_fingerprint is not None:
                raise ValueError("commissioning sessions cannot bind motion evidence")
            if self.field_acceptance_evidence_id is not None:
                raise ValueError("commissioning sessions cannot bind field acceptance")
            if (
                self.pre_motion_evidence_id is not None
                or self.commissioning_envelope is not None
                or self.raw_direction_envelope is not None
            ):
                raise ValueError("read-only commissioning cannot bind motion-test evidence")
            if self.workspace_clear_confirmed:
                raise ValueError(
                    "read-only commissioning does not carry workspace-clear motion intent"
                )
        elif self.purpose is OperatorSessionPurpose.COMMISSIONING_MOTION_TEST:
            if self.hardware_access_policy is not HardwareAccessPolicy.FULL:
                raise ValueError("commissioning motion-test sessions require FULL hardware policy")
            if self.scopes != COMMISSIONING_MOTION_SCOPES:
                raise ValueError("commissioning motion-test sessions have one exact scope")
            if self.calibration_fingerprint is None:
                raise ValueError("commissioning motion-test sessions require Calibration")
            if self.kinematics_fingerprint is not None:
                raise ValueError("single-joint commissioning does not bind Kinematics authority")
            if self.field_acceptance_evidence_id is not None:
                raise ValueError("commissioning motion tests cannot bind production acceptance")
            if self.commissioning_envelope is None:
                raise ValueError("commissioning motion tests require a fixed safety envelope")
            if not self.workspace_clear_confirmed:
                raise ValueError("commissioning motion tests require workspace-clear confirmation")
            if self.raw_direction_envelope is not None:
                raise ValueError("calibrated commissioning cannot inherit raw-direction authority")
        elif self.purpose is OperatorSessionPurpose.RAW_DIRECTION_TEST:
            if self.hardware_access_policy is not HardwareAccessPolicy.FULL:
                raise ValueError("raw-direction sessions require FULL hardware policy")
            if self.scopes != RAW_DIRECTION_SCOPES:
                raise ValueError("raw-direction sessions have one exact scope")
            if self.calibration_fingerprint is not None or self.kinematics_fingerprint is not None:
                raise ValueError("raw-direction sessions cannot claim calibrated motion evidence")
            if self.field_acceptance_evidence_id is not None:
                raise ValueError("raw-direction sessions cannot bind production acceptance")
            if self.pre_motion_evidence_id is not None:
                raise ValueError(
                    "raw-direction sessions cannot claim calibrated pre-motion evidence"
                )
            if self.raw_direction_envelope is None:
                raise ValueError("raw-direction sessions require a fixed raw-count envelope")
            if self.commissioning_envelope is not None:
                raise ValueError(
                    "raw-direction sessions cannot inherit logical commissioning authority"
                )
            if not self.workspace_clear_confirmed:
                raise ValueError("raw-direction tests require workspace-clear confirmation")
        else:
            if self.hardware_access_policy is not HardwareAccessPolicy.FULL:
                raise ValueError("motion sessions require FULL hardware policy")
            if self.scopes & COMMISSIONING_SCOPES:
                raise ValueError("motion sessions cannot contain commissioning scopes")
            if not self.scopes <= MOTION_SCOPES:
                raise ValueError("motion sessions contain an unknown scope")
            if OperatorSessionScope.REAL_JOINT_MOTION not in self.scopes:
                raise ValueError("motion sessions require the joint-motion scope")
            if self.calibration_fingerprint is None:
                raise ValueError("motion sessions require a calibration fingerprint")
            if self.field_acceptance_evidence_id is None:
                raise ValueError("motion sessions require capability acceptance evidence")
            if (
                self.pre_motion_evidence_id is not None
                or self.commissioning_envelope is not None
                or self.raw_direction_envelope is not None
            ):
                raise ValueError("production motion cannot inherit commissioning-test authority")
            geometry_scopes = {
                OperatorSessionScope.REAL_CARTESIAN_MOTION,
                OperatorSessionScope.REAL_PLAYBACK,
                OperatorSessionScope.REAL_VISION_FOLLOW,
            }
            if self.scopes & geometry_scopes and self.kinematics_fingerprint is None:
                raise ValueError("geometry motion scopes require a kinematics fingerprint")
        return self


class IssuedOperatorSession(BaseModel):
    """Raw token is held as SecretStr and is revealed only by the API presenter once."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_token: SecretStr = Field(repr=False)
    evidence: OperatorSessionEvidence


class OperatorSessionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    active: bool
    session_id: UUID | None = None
    expires_at: datetime | None = None
    purpose: OperatorSessionPurpose | None = None
    scopes: frozenset[OperatorSessionScope] = frozenset()

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        complete_identity = (
            self.session_id is not None
            and self.expires_at is not None
            and self.purpose is not None
            and bool(self.scopes)
        )
        if self.active is not complete_identity:
            raise ValueError("active session status requires identity and expiry")
        if not self.active and (self.purpose is not None or self.scopes):
            raise ValueError("inactive session status cannot retain purpose or scopes")
        if self.expires_at is not None:
            _require_aware(self.expires_at, "expires_at")
        return self


class RealHardwareContext(BaseModel):
    """Pure gate inputs; defaults are deliberately incapable of hardware access."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    control_mode: ControlMode = ControlMode.DRY_RUN
    hardware_access_policy: HardwareAccessPolicy = HardwareAccessPolicy.DISABLED
    real_motion_enabled: bool = False
    commissioning_motion_test_enabled: bool = False
    raw_direction_test_enabled: bool = False
    raw_direction_adapter_ready: bool = False
    startup_hardware_enabled: bool = False
    explicit_local_config: bool = False
    robot_unit_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=64),
    ] = ""
    software_commit: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=64),
    ] = ""
    robot_id: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
        ]
        | None
    ) = None
    profile: RobotProfile | None = Field(default=None, repr=False)
    calibration: CalibrationDocument | None = Field(default=None, repr=False)
    kinematics: KinematicsModel | None = Field(default=None, repr=False)
    expected_kinematics_fingerprint: Fingerprint | None = None
    field_acceptance_evidence: FieldAcceptanceEvidence | None = Field(
        default=None,
        repr=False,
    )
    field_acceptance_bundle: FieldAcceptanceBundle = Field(
        default_factory=FieldAcceptanceBundle,
        repr=False,
    )
    kinematics_verification_evidence: KinematicsVerificationEvidence | None = Field(
        default=None,
        repr=False,
    )
    physical_stop_verification: PhysicalStopVerification = PhysicalStopVerification.PENDING
    commissioning_safety_envelope: CommissioningSafetyEnvelope = Field(
        default_factory=CommissioningSafetyEnvelope,
    )
    raw_direction_safety_envelope: RawDirectionSafetyEnvelope = Field(
        default_factory=RawDirectionSafetyEnvelope,
    )
    field_acceptance_checklist_version: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ] = DEFAULT_FIELD_ACCEPTANCE_CHECKLIST_VERSION
    kinematics_verification_checklist_version: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ] = DEFAULT_KINEMATICS_VERIFICATION_CHECKLIST_VERSION
    # Compatibility/display hint only. A PASSED value never grants motion without
    # matching persisted FieldAcceptanceEvidence.
    field_acceptance_status: FieldAcceptanceStatus = FieldAcceptanceStatus.PENDING
    dependency_state: HardwareDependencyState = HardwareDependencyState.UNAVAILABLE
    dependency_adapter_id: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
        ]
        | None
    ) = None
    device: ExplicitServoDevice | None = Field(default=None, repr=False)

    @field_validator("robot_unit_id")
    @classmethod
    def validate_optional_robot_unit_id(cls, value: str) -> str:
        if value:
            from pydantic import TypeAdapter

            TypeAdapter(RobotUnitId).validate_python(value)
        return value

    @property
    def calibration_fingerprint(self) -> str | None:
        return calibration_fingerprint(self.calibration) if self.calibration is not None else None

    @property
    def device_fingerprint(self) -> str | None:
        return explicit_device_fingerprint(self.device) if self.device is not None else None


class RealHardwareGateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    context: RealHardwareContext = Field(repr=False)
    evaluated_at: datetime
    operator_session: OperatorSessionEvidence | None = Field(default=None, repr=False)

    @field_validator("evaluated_at")
    @classmethod
    def require_aware_evaluation_time(cls, value: datetime) -> datetime:
        return _require_aware(value, "evaluated_at")


class CapabilityReadinessDetail(BaseModel):
    """Explain one backend-derived capability without frontend inference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ready: bool = False
    authorized: bool = False
    blocked_reasons: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_detail(self) -> Self:
        if self.authorized and not self.ready:
            raise ValueError("an authorized capability must be ready")
        if self.ready and self.blocked_reasons:
            raise ValueError("a ready capability cannot retain blockers")
        return self


class RealHardwareCapabilityDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    commissioning_read_only: CapabilityReadinessDetail = Field(
        default_factory=CapabilityReadinessDetail
    )
    commissioning_motion_test: CapabilityReadinessDetail = Field(
        default_factory=CapabilityReadinessDetail
    )
    raw_direction_test: CapabilityReadinessDetail = Field(default_factory=CapabilityReadinessDetail)
    real_joint_motion: CapabilityReadinessDetail = Field(default_factory=CapabilityReadinessDetail)
    real_cartesian_motion: CapabilityReadinessDetail = Field(
        default_factory=CapabilityReadinessDetail
    )
    real_playback: CapabilityReadinessDetail = Field(default_factory=CapabilityReadinessDetail)
    real_vision_follow: CapabilityReadinessDetail = Field(default_factory=CapabilityReadinessDetail)


class RealHardwareCapabilityReadiness(BaseModel):
    """Independent capabilities; joint-only readiness never implies geometry safety."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    commissioning_read_only_ready: bool = False
    commissioning_diagnostics_ready: bool = False
    calibration_capture_ready: bool = False
    commissioning_motion_test_ready: bool = False
    raw_direction_test_ready: bool = False
    real_joint_motion_ready: bool = False
    real_cartesian_motion_ready: bool = False
    real_playback_ready: bool = False
    real_vision_follow_ready: bool = False

    @model_validator(mode="after")
    def validate_dependency_direction(self) -> Self:
        if self.calibration_capture_ready and not self.commissioning_diagnostics_ready:
            raise ValueError("calibration capture requires commissioning diagnostics readiness")
        geometry_capability_ready = (
            self.real_cartesian_motion_ready
            or self.real_playback_ready
            or self.real_vision_follow_ready
        )
        if geometry_capability_ready and not self.real_joint_motion_ready:
            raise ValueError("geometry-dependent capabilities require joint readiness")
        return self

    @property
    def all_ready(self) -> bool:
        return (
            self.real_joint_motion_ready
            and self.real_cartesian_motion_ready
            and self.real_playback_ready
            and self.real_vision_follow_ready
        )


class RealHardwareReadinessReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: RealHardwareReadinessState
    ready: bool
    session_authorizable: bool
    commissioning_session_authorizable: bool = False
    commissioning_motion_session_authorizable: bool = False
    raw_direction_session_authorizable: bool = False
    motion_session_authorizable: bool = False
    blocking_reasons: tuple[RealHardwareBlocker, ...]
    capabilities: RealHardwareCapabilityReadiness
    capability_details: RealHardwareCapabilityDetails = Field(
        default_factory=RealHardwareCapabilityDetails
    )
    confirmation: HardwareConfirmationEvidence
    session: OperatorSessionStatus | None = None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.ready is not (
            self.state is RealHardwareReadinessState.READY
            and not self.blocking_reasons
            and self.capabilities.all_ready
        ):
            raise ValueError("ready must mean READY with every capability ready")
        if self.session_authorizable is not (
            self.commissioning_session_authorizable
            or self.commissioning_motion_session_authorizable
            or self.raw_direction_session_authorizable
            or self.motion_session_authorizable
        ):
            raise ValueError("session_authorizable must summarize purpose-specific readiness")
        if self.commissioning_session_authorizable and not (
            self.capabilities.commissioning_diagnostics_ready
            and self.capabilities.calibration_capture_ready
        ):
            raise ValueError("commissioning authorization requires both read-only capabilities")
        if (
            self.commissioning_motion_session_authorizable
            and self.capabilities.commissioning_motion_test_ready
        ):
            raise ValueError("motion-test authorization ends once its session is active")
        if self.raw_direction_session_authorizable and self.capabilities.raw_direction_test_ready:
            raise ValueError("raw-direction authorization ends once its session is active")
        if self.motion_session_authorizable and self.capabilities.real_joint_motion_ready:
            raise ValueError("motion session authorization ends once joint motion is ready")
        any_capability_ready = (
            self.capabilities.raw_direction_test_ready
            or self.capabilities.real_joint_motion_ready
            or self.capabilities.real_cartesian_motion_ready
            or self.capabilities.real_playback_ready
            or self.capabilities.real_vision_follow_ready
        )
        if any_capability_ready and (self.session is None or not self.session.active):
            raise ValueError("a ready capability requires an active operator session")
        if (
            self.commissioning_session_authorizable
            or self.commissioning_motion_session_authorizable
            or self.raw_direction_session_authorizable
            or self.motion_session_authorizable
        ) and self.session is not None:
            raise ValueError("an authorizable report cannot already contain a session")
        return self


class RealHardwareAccessGrant(BaseModel):
    """Token-free, short-lived result emitted only for its matching ready purpose."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session: OperatorSessionEvidence = Field(repr=False)
    confirmation: HardwareConfirmationEvidence
    adapter_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
    ]
    device_fingerprint: Fingerprint = Field(repr=False)
    purpose: RealHardwareAuthorizationPurpose
    capabilities: RealHardwareCapabilityReadiness
    authorized_at: datetime

    @model_validator(mode="after")
    def validate_grant(self) -> Self:
        _require_aware(self.authorized_at, "authorized_at")
        if not self.session.issued_at <= self.authorized_at < self.session.expires_at:
            raise ValueError("authorization grant must be issued during the operator session")
        if (
            self.confirmation.robot_id != self.session.robot_id
            or self.confirmation.robot_unit_id != self.session.robot_unit_id
            or self.confirmation.variant is not self.session.variant
            or self.confirmation.profile_fingerprint != self.session.profile_fingerprint
            or self.confirmation.calibration_fingerprint != self.session.calibration_fingerprint
            or self.confirmation.field_acceptance_evidence_id
            != self.session.field_acceptance_evidence_id
            or self.confirmation.pre_motion_evidence_id != self.session.pre_motion_evidence_id
            or len(self.confirmation.masked_servo_ids) != len(self.session.allowed_servo_ids)
            or self.confirmation.session_purpose is not self.session.purpose
            or self.device_fingerprint != self.session.device_fingerprint
        ):
            raise ValueError("authorization confirmation must match operator session evidence")
        required = {
            RealHardwareAuthorizationPurpose.DIAGNOSTICS: (
                self.capabilities.commissioning_diagnostics_ready
            ),
            RealHardwareAuthorizationPurpose.CALIBRATION_CAPTURE: (
                self.capabilities.calibration_capture_ready
            ),
            RealHardwareAuthorizationPurpose.COMMISSIONING_SINGLE_JOINT_TEST: (
                self.capabilities.commissioning_motion_test_ready
            ),
            RealHardwareAuthorizationPurpose.RAW_DIRECTION_TEST: (
                self.capabilities.raw_direction_test_ready
            ),
            RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION: (
                self.capabilities.real_joint_motion_ready
            ),
            RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION: (
                self.capabilities.real_cartesian_motion_ready
            ),
            RealHardwareAuthorizationPurpose.REAL_PLAYBACK: (self.capabilities.real_playback_ready),
            RealHardwareAuthorizationPurpose.REAL_VISION_FOLLOW: (
                self.capabilities.real_vision_follow_ready
            ),
        }[self.purpose]
        if not required:
            raise ValueError("authorization purpose requires its matching ready capability")
        required_scope = AUTHORIZATION_PURPOSE_SCOPE[self.purpose]
        if required_scope not in self.session.scopes:
            raise ValueError("authorization purpose is outside the operator session scope")
        return self


class HardwareDependencyStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter_id: str
    state: HardwareDependencyState
    package_name: str | None = None
    license_status: str
    notice: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class HardwareArtifactStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    configured: bool
    fingerprint: Fingerprint | None = None
    verification_status: str | None = None
    template: bool | None = None
    ready_for_real: bool


class ServoDiagnosticRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    joint_id: str
    servo_id: ServoId = Field(repr=False)
    masked_servo_id: str
    ping_responded: bool
    operating_mode: str
    present_raw: int
    logical_value: float | None = None
    raw_bounds: tuple[int, int] | None = None
    torque_enabled: bool | None = None


class DeviceDiagnosticsSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    connected: bool
    captured_at: datetime
    dependency: HardwareDependencyStatus
    hardware_policy: HardwareAccessPolicy
    masked_serial_port: str | None
    masked_servo_ids: tuple[str, ...]
    protocol: str | None
    profile: HardwareArtifactStatus
    calibration: HardwareArtifactStatus
    kinematics: HardwareArtifactStatus
    field_acceptance: FieldAcceptanceStatus
    readiness: RealHardwareReadinessState
    records: tuple[ServoDiagnosticRecord, ...]
    last_error: BoundedDetail = ""

    @field_validator("captured_at")
    @classmethod
    def require_aware_capture_time(cls, value: datetime) -> datetime:
        return _require_aware(value, "captured_at")


def confirmation_text_for(purpose: OperatorSessionPurpose) -> str:
    if purpose is OperatorSessionPurpose.COMMISSIONING_READ_ONLY:
        return REQUIRED_COMMISSIONING_CONFIRMATION_TEXT
    if purpose is OperatorSessionPurpose.COMMISSIONING_MOTION_TEST:
        return REQUIRED_COMMISSIONING_MOTION_CONFIRMATION_TEXT
    if purpose is OperatorSessionPurpose.RAW_DIRECTION_TEST:
        return REQUIRED_RAW_DIRECTION_CONFIRMATION_TEXT
    return REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT


def field_acceptance_evidence_state(
    context: RealHardwareContext,
    evidence: FieldAcceptanceEvidence | None = None,
) -> tuple[FieldAcceptanceEvidenceState, tuple[str, ...]]:
    """Interpret one capability record without trusting legacy global PASSED."""

    evidence = evidence or context.field_acceptance_evidence
    if evidence is None:
        return FieldAcceptanceEvidenceState.MISSING, ("evidence",)
    if evidence.schema_version == 1:
        return FieldAcceptanceEvidenceState.STALE_LEGACY_EVIDENCE, (
            "schema_version",
            "robot_unit_id",
            "capability",
        )
    profile = context.profile
    calibration = context.calibration
    device = context.device
    stale: list[str] = []
    if not context.robot_unit_id or evidence.robot_unit_id != context.robot_unit_id:
        stale.append("robot_unit_id")
    if device is None or not device.robot_unit_id or device.robot_unit_id != context.robot_unit_id:
        stale.append("device_robot_unit_id")
    if profile is None or evidence.robot_variant is not profile.variant:
        stale.append("robot_variant")
    if profile is None or evidence.profile_fingerprint != profile.fingerprint:
        stale.append("profile_fingerprint")
    if calibration is None or evidence.calibration_fingerprint != calibration_fingerprint(
        calibration
    ):
        stale.append("calibration_fingerprint")
    if evidence.kinematics_fingerprint is not None:
        current_kinematics_fingerprint = (
            context.kinematics.fingerprint if context.kinematics is not None else None
        )
        if evidence.kinematics_fingerprint != current_kinematics_fingerprint:
            stale.append("kinematics_fingerprint")
    if device is None or evidence.device_fingerprint != explicit_device_fingerprint(device):
        stale.append("device_fingerprint")
    if evidence.checklist_version != context.field_acceptance_checklist_version:
        stale.append("checklist_version")
    if evidence.software_commit != context.software_commit:
        stale.append("software_commit")
    if stale:
        return FieldAcceptanceEvidenceState.STALE, tuple(stale)
    return FieldAcceptanceEvidenceState.VALID, ()


def effective_field_acceptance_status(context: RealHardwareContext) -> FieldAcceptanceStatus:
    required = frozenset(FieldAcceptanceCapability)
    if required <= context.field_acceptance_bundle.valid_capabilities(context):
        return FieldAcceptanceStatus.PASSED
    if context.field_acceptance_status is FieldAcceptanceStatus.FAILED:
        return FieldAcceptanceStatus.FAILED
    return FieldAcceptanceStatus.PENDING


def kinematics_verification_evidence_state(
    context: RealHardwareContext,
) -> tuple[KinematicsEvidenceState, tuple[str, ...]]:
    evidence = context.kinematics_verification_evidence
    if evidence is None:
        return KinematicsEvidenceState.MISSING, ("evidence",)
    stale: list[str] = []
    profile = context.profile
    calibration = context.calibration
    kinematics = context.kinematics
    if not context.robot_unit_id or evidence.robot_unit_id != context.robot_unit_id:
        stale.append("robot_unit_id")
    if profile is None or evidence.variant is not profile.variant:
        stale.append("variant")
    if profile is None or evidence.profile_fingerprint != profile.fingerprint:
        stale.append("profile_fingerprint")
    if calibration is None or evidence.calibration_fingerprint != calibration_fingerprint(
        calibration
    ):
        stale.append("calibration_fingerprint")
    if context.device is None or evidence.device_fingerprint != explicit_device_fingerprint(
        context.device
    ):
        stale.append("device_fingerprint")
    if kinematics is None or evidence.kinematics_fingerprint != kinematics.fingerprint:
        stale.append("kinematics_fingerprint")
    if kinematics is None or evidence.kinematics_model_schema_version != kinematics.schema_version:
        stale.append("kinematics_model_schema_version")
    if evidence.verification_checklist_version != context.kinematics_verification_checklist_version:
        stale.append("verification_checklist_version")
    if evidence.software_commit != context.software_commit:
        stale.append("software_commit")
    if stale:
        return KinematicsEvidenceState.STALE, tuple(dict.fromkeys(stale))
    return KinematicsEvidenceState.VALID, ()


def calibration_fingerprint(calibration: CalibrationDocument) -> str:
    """Hash all safety-relevant calibration identity/mapping fields."""

    payload = calibration.model_dump(
        mode="json",
        exclude={"generated_at", "notes"},
    )
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def explicit_device_fingerprint(device: ExplicitServoDevice) -> str:
    """Bind a grant to the stable unit plus exact port/protocol/ID allowlist."""

    encoded = json.dumps(
        {
            "robot_unit_id": device.robot_unit_id,
            "serial_port": device.serial_port,
            "protocol": device.protocol,
            "servo_ids": list(device.servo_ids),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return value
