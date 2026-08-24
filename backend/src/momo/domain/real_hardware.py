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
from momo.domain.enums import (
    ControlMode,
    HardwareAccessPolicy,
    RobotVariant,
)
from momo.domain.kinematics.model import KinematicsModel
from momo.domain.robot import RobotProfile

REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT = "I UNDERSTAND REAL HARDWARE CAN MOVE"
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
    READY = "READY"


class RealHardwareBlocker(StrEnum):
    CONTROL_MODE_MUST_BE_REAL = "CONTROL_MODE_MUST_BE_REAL"
    HARDWARE_POLICY_MUST_BE_FULL = "HARDWARE_POLICY_MUST_BE_FULL"
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
    KINEMATICS_MISSING = "KINEMATICS_MISSING"
    KINEMATICS_NOT_VERIFIED_FOR_REAL = "KINEMATICS_NOT_VERIFIED_FOR_REAL"
    KINEMATICS_FINGERPRINT_MISSING = "KINEMATICS_FINGERPRINT_MISSING"
    KINEMATICS_FINGERPRINT_MISMATCH = "KINEMATICS_FINGERPRINT_MISMATCH"
    KINEMATICS_PROFILE_MISMATCH = "KINEMATICS_PROFILE_MISMATCH"
    FIELD_ACCEPTANCE_NOT_PASSED = "FIELD_ACCEPTANCE_NOT_PASSED"
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
    REAL_JOINT_MOTION = "REAL_JOINT_MOTION"
    REAL_CARTESIAN_MOTION = "REAL_CARTESIAN_MOTION"
    REAL_PLAYBACK = "REAL_PLAYBACK"
    REAL_VISION_FOLLOW = "REAL_VISION_FOLLOW"


class ExplicitServoDevice(BaseModel):
    """One explicitly configured device and exact ID allowlist; never a scan range."""

    model_config = ConfigDict(extra="forbid", frozen=True)

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
    variant: RobotVariant | None = None
    profile_fingerprint: Fingerprint | None = None
    calibration_fingerprint: Fingerprint | None = None
    kinematics_fingerprint: Fingerprint | None = None
    masked_serial_port: str | None = None
    masked_servo_ids: tuple[str, ...] = ()
    protocol: str | None = None
    physical_estop_required: Literal[True] = True
    required_confirmation_text: Literal["I UNDERSTAND REAL HARDWARE CAN MOVE"] = (
        "I UNDERSTAND REAL HARDWARE CAN MOVE"
    )


class OperatorSessionEvidence(BaseModel):
    """Token-free authorization evidence shared with later real execution paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID
    robot_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    variant: RobotVariant
    profile_fingerprint: Fingerprint
    calibration_fingerprint: Fingerprint
    allowed_servo_ids: tuple[ServoId, ...]
    issued_at: datetime
    expires_at: datetime
    confirmed: Literal[True] = True
    physical_estop_confirmed: Literal[True] = True
    control_mode: Literal[ControlMode.REAL] = ControlMode.REAL
    hardware_access_policy: Literal[HardwareAccessPolicy.FULL] = HardwareAccessPolicy.FULL

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

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.active is not (self.session_id is not None and self.expires_at is not None):
            raise ValueError("active session status requires identity and expiry")
        if self.expires_at is not None:
            _require_aware(self.expires_at, "expires_at")
        return self


class RealHardwareContext(BaseModel):
    """Pure gate inputs; defaults are deliberately incapable of hardware access."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    control_mode: ControlMode = ControlMode.DRY_RUN
    hardware_access_policy: HardwareAccessPolicy = HardwareAccessPolicy.DISABLED
    real_motion_enabled: bool = False
    startup_hardware_enabled: bool = False
    explicit_local_config: bool = False
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


class RealHardwareGateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    context: RealHardwareContext = Field(repr=False)
    evaluated_at: datetime
    operator_session: OperatorSessionEvidence | None = Field(default=None, repr=False)

    @field_validator("evaluated_at")
    @classmethod
    def require_aware_evaluation_time(cls, value: datetime) -> datetime:
        return _require_aware(value, "evaluated_at")


class RealHardwareCapabilityReadiness(BaseModel):
    """Independent capabilities; joint-only readiness never implies geometry safety."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    real_joint_motion_ready: bool = False
    real_cartesian_motion_ready: bool = False
    real_playback_ready: bool = False
    real_vision_follow_ready: bool = False

    @model_validator(mode="after")
    def validate_dependency_direction(self) -> Self:
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
    blocking_reasons: tuple[RealHardwareBlocker, ...]
    capabilities: RealHardwareCapabilityReadiness
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
        expected_authorizable = (
            self.state is RealHardwareReadinessState.AWAITING_OPERATOR_SESSION
            and RealHardwareBlocker.OPERATOR_SESSION_MISSING in self.blocking_reasons
            and all(
                blocker is RealHardwareBlocker.OPERATOR_SESSION_MISSING
                or blocker.name.startswith("KINEMATICS_")
                for blocker in self.blocking_reasons
            )
        )
        if self.session_authorizable is not expected_authorizable:
            raise ValueError(
                "session_authorizable requires all base gates and a missing operator session"
            )
        any_capability_ready = (
            self.capabilities.real_joint_motion_ready
            or self.capabilities.real_cartesian_motion_ready
            or self.capabilities.real_playback_ready
            or self.capabilities.real_vision_follow_ready
        )
        if any_capability_ready and (self.session is None or not self.session.active):
            raise ValueError("a ready capability requires an active operator session")
        if self.session_authorizable and self.session is not None:
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
            or self.confirmation.variant is not self.session.variant
            or self.confirmation.profile_fingerprint != self.session.profile_fingerprint
            or self.confirmation.calibration_fingerprint != self.session.calibration_fingerprint
            or len(self.confirmation.masked_servo_ids) != len(self.session.allowed_servo_ids)
        ):
            raise ValueError("authorization confirmation must match operator session evidence")
        required = {
            RealHardwareAuthorizationPurpose.DIAGNOSTICS: self.capabilities.real_joint_motion_ready,
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
    logical_value: float
    raw_bounds: tuple[int, int]
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
    """Bind an access grant to the exact raw port, protocol, and ID allowlist."""

    encoded = json.dumps(
        {
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
