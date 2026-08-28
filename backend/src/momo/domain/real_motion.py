"""Token-free authorization and truthful state for bounded Real execution."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
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

from momo.domain.calibration import Fingerprint
from momo.domain.enums import ControlMode, HardwareAccessPolicy, RobotVariant
from momo.domain.immutable import freeze_mapping
from momo.domain.real_hardware import (
    RealHardwareAuthorizationPurpose,
    RealHardwareCapabilityReadiness,
    RealStopOutcome,
)
from momo.domain.robot import JointState

RobotIdValue = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$"),
]
ServoId = Annotated[int, Field(strict=True, ge=1, le=253)]
BoundedDetail = Annotated[str, StringConstraints(max_length=500)]


class RealMotionError(RuntimeError):
    """Typed rejection/failure without exposing adapter or device secrets."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class RealMotionState(StrEnum):
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAULTED = "FAULTED"


class RealMotionFaultCode(StrEnum):
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    AUTHORIZATION_MISMATCH = "AUTHORIZATION_MISMATCH"
    PREPARED_TRAJECTORY_CHANGED = "PREPARED_TRAJECTORY_CHANGED"
    TRAJECTORY_BINDING_MISMATCH = "TRAJECTORY_BINDING_MISMATCH"
    TRAJECTORY_SAMPLE_INVALID = "TRAJECTORY_SAMPLE_INVALID"
    RAW_MAPPING_INVALID = "RAW_MAPPING_INVALID"
    PARTIAL_WRITE = "PARTIAL_WRITE"
    BUS_DISCONNECTED = "BUS_DISCONNECTED"
    BUS_FAULT = "BUS_FAULT"
    READBACK_INVALID = "READBACK_INVALID"
    READBACK_DIVERGENCE = "READBACK_DIVERGENCE"
    STATE_UPDATE_FAILED = "STATE_UPDATE_FAILED"
    SAFETY_STATE_UNCERTAIN = "SAFETY_STATE_UNCERTAIN"
    STOP_NOT_VERIFIED = "STOP_NOT_VERIFIED"
    EXECUTION_CONTEXT_UNAVAILABLE = "EXECUTION_CONTEXT_UNAVAILABLE"
    MOTION_ARTIFACT_CHANGED = "MOTION_ARTIFACT_CHANGED"
    ROBOT_DISCONNECTED = "ROBOT_DISCONNECTED"
    ROBOT_STATE_STALE = "ROBOT_STATE_STALE"
    STOP_CAPABILITY_UNAVAILABLE = "STOP_CAPABILITY_UNAVAILABLE"
    STATE_SEQUENCE_CHANGED = "STATE_SEQUENCE_CHANGED"
    FIRST_SAMPLE_DISCONTINUITY = "FIRST_SAMPLE_DISCONTINUITY"
    CURRENT_STATE_CHANGED = "CURRENT_STATE_CHANGED"


class RealMotionAuditKind(StrEnum):
    ACCEPTED = "ACCEPTED"
    WRITE = "WRITE"
    READBACK = "READBACK"
    STOP = "STOP"
    TERMINAL = "TERMINAL"


class RealExecutionAuthorization(BaseModel):
    """Narrow internal authorization issued after authenticating an operator token."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID
    robot_id: RobotIdValue
    variant: RobotVariant
    profile_fingerprint: Fingerprint
    calibration_fingerprint: Fingerprint
    allowed_servo_ids: tuple[ServoId, ...]
    issued_at: datetime
    expires_at: datetime
    confirmed: Literal[True]
    control_mode: Literal[ControlMode.REAL] = ControlMode.REAL
    hardware_policy: Literal[HardwareAccessPolicy.FULL] = HardwareAccessPolicy.FULL
    purpose: RealHardwareAuthorizationPurpose
    capabilities: RealHardwareCapabilityReadiness

    @field_validator("issued_at", "expires_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("authorization timestamps must include a timezone offset")
        return value

    @field_validator("allowed_servo_ids")
    @classmethod
    def require_unique_ids(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if not value:
            raise ValueError("authorization requires explicit Servo IDs")
        if len(value) != len(set(value)):
            raise ValueError("allowed_servo_ids must be unique")
        return value

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.expires_at <= self.issued_at:
            raise ValueError("authorization expiry must follow issuance")
        required_capability = {
            RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION: (
                self.capabilities.real_joint_motion_ready
            ),
            RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION: (
                self.capabilities.real_cartesian_motion_ready
            ),
            RealHardwareAuthorizationPurpose.REAL_PLAYBACK: (self.capabilities.real_playback_ready),
        }.get(self.purpose)
        if required_capability is not True:
            raise ValueError("execution purpose requires its matching ready capability")
        return self

    def active(self, now: datetime) -> bool:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("authorization check time must include a timezone offset")
        return self.issued_at <= now < self.expires_at


class RealMotionAuditEvent(BaseModel):
    """Bounded event suitable for a structured audit sink."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    sequence: Annotated[int, Field(strict=True, ge=1)]
    execution_id: UUID
    authorization_session_id: UUID
    trajectory_digest: Fingerprint
    execution_purpose: RealHardwareAuthorizationPurpose
    kind: RealMotionAuditKind
    occurred_at: datetime
    monotonic_s: Annotated[float, Field(strict=True, ge=0.0, allow_inf_nan=False)]
    sample_index: Annotated[int, Field(strict=True, ge=0)] | None = None
    requested_ids: tuple[ServoId, ...] = ()
    affected_ids: tuple[ServoId, ...] = ()
    safety_state_known: bool
    detail: BoundedDetail = ""
    physical_estop_claimed: Literal[False] = False

    @field_validator("occurred_at")
    @classmethod
    def require_aware_occurrence(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("audit timestamp must include a timezone offset")
        return value

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        if not isfinite(self.monotonic_s):
            raise ValueError("audit monotonic time must be finite")
        if len(self.requested_ids) != len(set(self.requested_ids)):
            raise ValueError("audit requested IDs must be unique")
        if len(self.affected_ids) != len(set(self.affected_ids)):
            raise ValueError("audit affected IDs must be unique")
        if not set(self.affected_ids) <= set(self.requested_ids):
            raise ValueError("audit affected IDs must be requested")
        return self


class RealMotionStatus(BaseModel):
    """Truthful execution state; no state implies a physical E-stop."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    execution_id: UUID
    authorization_session_id: UUID
    robot_id: RobotIdValue
    variant: RobotVariant
    profile_fingerprint: Fingerprint
    calibration_fingerprint: Fingerprint
    trajectory_digest: Fingerprint
    execution_purpose: RealHardwareAuthorizationPurpose
    state: RealMotionState
    progress: Annotated[float, Field(strict=True, ge=0.0, le=1.0, allow_inf_nan=False)]
    sample_index: Annotated[int, Field(strict=True, ge=0)] | None = None
    sample_count: Annotated[int, Field(strict=True, ge=2, le=20_000)]
    expected_state_sequence: Annotated[int, Field(strict=True, ge=0)]
    last_goal_raw: dict[ServoId, int] = Field(default_factory=dict)
    last_readback_raw: dict[ServoId, int] = Field(default_factory=dict)
    last_logical_positions: dict[str, float] = Field(default_factory=dict)
    hardware_accessed: bool
    safety_state_known: bool
    fault_code: RealMotionFaultCode | None = None
    detail: BoundedDetail = ""
    stop_outcome: RealStopOutcome | None = None
    accepted_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    physical_estop_claimed: Literal[False] = False

    @field_validator("last_goal_raw", "last_readback_raw")
    @classmethod
    def freeze_goal_raw(cls, value: dict[int, int]) -> dict[int, int]:
        if any(isinstance(raw, bool) or not isinstance(raw, int) for raw in value.values()):
            raise ValueError("goal raw values must be integers")
        return freeze_mapping(value)

    @field_validator("last_logical_positions")
    @classmethod
    def freeze_logical_positions(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not isfinite(position) for position in value.values()):
            raise ValueError("logical positions must be finite")
        return freeze_mapping(value)

    @field_validator("accepted_at", "updated_at", "started_at", "finished_at")
    @classmethod
    def require_aware_status_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("status timestamps must include a timezone offset")
        return value

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        terminal = self.state in {
            RealMotionState.COMPLETED,
            RealMotionState.CANCELLED,
            RealMotionState.FAULTED,
        }
        if terminal is not (self.finished_at is not None):
            raise ValueError("only terminal states require finished_at")
        if self.state is RealMotionState.FAULTED and self.fault_code is None:
            raise ValueError("FAULTED state requires a fault code")
        if self.state is not RealMotionState.FAULTED and self.fault_code is not None:
            raise ValueError("only FAULTED state may expose a fault code")
        if self.state is RealMotionState.COMPLETED and (
            self.progress != 1.0 or not self.safety_state_known
        ):
            raise ValueError("COMPLETED requires full progress and known safety state")
        if self.stop_outcome is not None and self.state not in {
            RealMotionState.CANCELLED,
            RealMotionState.FAULTED,
        }:
            raise ValueError("Stop outcomes are exposed only on cancellation/fault")
        return self


class RealExecutionContext(BaseModel):
    """Fresh token-free mutable evidence supplied immediately before each write."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    robot_id: RobotIdValue
    variant: RobotVariant
    connected: bool
    state_fresh: bool
    stop_capable: bool
    state_sequence: Annotated[int, Field(strict=True, ge=0)]
    joint_state: JointState
    motion_id: UUID
    motion_revision: Annotated[int, Field(strict=True, ge=1)]
    trajectory_digest: Fingerprint
    profile_fingerprint: Fingerprint
    calibration_fingerprint: Fingerprint
    kinematics_fingerprint: Fingerprint
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_aware_observation(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("execution context timestamp must include a timezone offset")
        return value


__all__ = [
    "RealExecutionAuthorization",
    "RealExecutionContext",
    "RealMotionAuditEvent",
    "RealMotionAuditKind",
    "RealMotionError",
    "RealMotionFaultCode",
    "RealMotionState",
    "RealMotionStatus",
]
