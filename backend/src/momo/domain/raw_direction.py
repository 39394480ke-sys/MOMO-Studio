"""Calibration-independent contracts for bounded Raw +/- direction tests.

Raw direction tests exist only to characterize the sign between one configured
Servo and the URDF joint.  They never claim a logical unit, calibrated zero, or
production-motion authority.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# One comparison step is derived by the backend from the active Profile and equals
# one domain unit (1 mm for J10, 1 deg for J11-J15).  The largest Legacy V2 mapping
# requires 328 counts; keep a small compile-time margin while rejecting arbitrary
# client-supplied Raw distances.
HARD_RAW_MAX_STEP_COUNTS = 384
HARD_RAW_ZERO_ENVELOPE_COUNTS = 384
HARD_RAW_DEADMAN_LEASE_MS = 400
HARD_RAW_SESSION_DURATION_S = 900.0
HARD_RAW_MAX_COMMANDS_PER_SESSION = 24
RAW_DIRECTION_DRAFT_CONFIRMATION = "I CONFIRM RAW ZERO AND DIRECTIONS FOR CALIBRATION DRAFT"
# Candidate only, characterized from the pinned Legacy V2 multi-turn configuration.
LEGACY_V2_MULTI_TURN_PHASE_CANDIDATE = 28


class RawDirection(StrEnum):
    RAW_PLUS = "RAW_PLUS"
    RAW_MINUS = "RAW_MINUS"

    @property
    def sign(self) -> int:
        return 1 if self is RawDirection.RAW_PLUS else -1


class RawDirectionTestState(StrEnum):
    IDLE = "IDLE"
    ZERO_CAPTURED = "ZERO_CAPTURED"
    ARMED = "ARMED"
    MOVING = "MOVING"
    STOPPING = "STOPPING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class RawDirectionSafetyEnvelope(BaseModel):
    """Compile-time-bounded raw-count envelope, independent of Calibration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_active_joints: Literal[1] = 1
    max_step_counts: int = Field(
        default=HARD_RAW_MAX_STEP_COUNTS,
        strict=True,
        ge=1,
        le=HARD_RAW_MAX_STEP_COUNTS,
    )
    max_zero_offset_counts: int = Field(
        default=HARD_RAW_ZERO_ENVELOPE_COUNTS,
        strict=True,
        ge=HARD_RAW_MAX_STEP_COUNTS,
        le=HARD_RAW_ZERO_ENVELOPE_COUNTS,
    )
    deadman_lease_ms: int = Field(
        default=HARD_RAW_DEADMAN_LEASE_MS,
        strict=True,
        ge=100,
        le=HARD_RAW_DEADMAN_LEASE_MS,
    )
    max_session_duration_s: float = Field(
        default=HARD_RAW_SESSION_DURATION_S,
        ge=30.0,
        le=HARD_RAW_SESSION_DURATION_S,
    )
    max_commands_per_session: int = Field(
        default=HARD_RAW_MAX_COMMANDS_PER_SESSION,
        strict=True,
        ge=2,
        le=HARD_RAW_MAX_COMMANDS_PER_SESSION,
    )


RAW_DIRECTION_HARD_CAPS = RawDirectionSafetyEnvelope()


class PreparedRawDirectionCommand(BaseModel):
    """One backend-prepared raw step; clients never provide a Servo target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    robot_unit_id: str = Field(min_length=3, max_length=64)
    joint_id: str = Field(min_length=1, max_length=32)
    servo_id: int = Field(strict=True, ge=1, le=253)
    direction: RawDirection
    step_counts: int = Field(strict=True, ge=1, le=HARD_RAW_MAX_STEP_COUNTS)
    zero_raw: int = Field(strict=True)
    start_raw: int = Field(strict=True)
    target_raw: int = Field(strict=True)
    prepared_at: datetime
    readback_fresh_until: datetime
    envelope: RawDirectionSafetyEnvelope

    @field_validator("prepared_at", "readback_fresh_until")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("raw-direction timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if self.readback_fresh_until <= self.prepared_at:
            raise ValueError("raw-direction readback freshness must extend beyond preparation")
        if self.step_counts > self.envelope.max_step_counts:
            raise ValueError("raw-direction step exceeds the fixed comparison envelope")
        if self.target_raw - self.start_raw != self.direction.sign * self.step_counts:
            raise ValueError("raw-direction target must be exactly one bounded raw step")
        if abs(self.target_raw - self.zero_raw) > self.envelope.max_zero_offset_counts:
            raise ValueError("raw-direction target exceeds the captured-zero envelope")
        return self


class RawDirectionZeroSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID
    robot_unit_id: str = Field(min_length=3, max_length=64)
    captured_at: datetime
    raw_by_joint: dict[str, int]

    @field_validator("captured_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("raw-direction zero timestamp must be timezone-aware")
        return value

    @field_validator("raw_by_joint")
    @classmethod
    def require_snapshot(cls, value: dict[str, int]) -> dict[str, int]:
        if not value:
            raise ValueError("raw-direction zero snapshot cannot be empty")
        if any(isinstance(raw, bool) or not isinstance(raw, int) for raw in value.values()):
            raise TypeError("raw-direction zero values must be integers")
        return value


class RawDirectionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command_id: UUID
    joint_id: str
    servo_id: int = Field(strict=True, ge=1, le=253)
    direction: RawDirection
    zero_raw: int = Field(strict=True)
    start_raw: int = Field(strict=True)
    target_raw: int = Field(strict=True)
    final_raw: int = Field(strict=True)
    completed_at: datetime
    software_only_adapter: bool

    @field_validator("completed_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("raw-direction observation timestamp must be timezone-aware")
        return value


class RawDirectionJointDraft(BaseModel):
    """One non-persisted candidate assembled from Legacy and field observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    joint_id: str
    servo_id: int = Field(strict=True, ge=1, le=253)
    home_present_raw: int = Field(strict=True)
    profile_direction_candidate: int = Field(strict=True, ge=-1, le=1)
    matches_urdf: bool | None = None
    resolved_calibration_direction: int | None = Field(default=None, strict=True, ge=-1, le=1)
    phase_candidate: int = Field(strict=True)
    raw_bounds_candidate: tuple[int, int]

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        if self.profile_direction_candidate not in {-1, 1}:
            raise ValueError("profile direction candidate must be a sign")
        if self.resolved_calibration_direction not in {None, -1, 1}:
            raise ValueError("resolved calibration direction must be a sign")
        if (self.matches_urdf is None) is not (self.resolved_calibration_direction is None):
            raise ValueError("direction resolution requires one explicit URDF observation")
        if self.raw_bounds_candidate[0] >= self.raw_bounds_candidate[1]:
            raise ValueError("candidate Raw bounds are invalid")
        if (
            not self.raw_bounds_candidate[0]
            <= self.home_present_raw
            <= self.raw_bounds_candidate[1]
        ):
            raise ValueError("captured Raw zero is outside the candidate bounds")
        return self


class RawDirectionCalibrationDraft(BaseModel):
    """Session-only review draft; never persisted or promoted automatically."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    robot_unit_id: str
    profile_fingerprint: str
    source: str
    source_revision: str
    complete_for_review: bool
    confirmed_for_review: bool = False
    confirmed_at: datetime | None = None
    joints: tuple[RawDirectionJointDraft, ...]

    @field_validator("confirmed_at")
    @classmethod
    def require_aware_confirmation_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Raw direction confirmation timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_completion(self) -> Self:
        resolved = all(joint.resolved_calibration_direction is not None for joint in self.joints)
        if self.complete_for_review is not resolved:
            raise ValueError("Raw direction draft completion must match all joint observations")
        if self.confirmed_for_review is not (self.confirmed_at is not None):
            raise ValueError("Raw direction draft confirmation fields are incoherent")
        if self.confirmed_for_review and not self.complete_for_review:
            raise ValueError("incomplete Raw direction draft cannot be confirmed")
        return self


__all__ = [
    "LEGACY_V2_MULTI_TURN_PHASE_CANDIDATE",
    "RAW_DIRECTION_DRAFT_CONFIRMATION",
    "RAW_DIRECTION_HARD_CAPS",
    "PreparedRawDirectionCommand",
    "RawDirection",
    "RawDirectionCalibrationDraft",
    "RawDirectionJointDraft",
    "RawDirectionObservation",
    "RawDirectionSafetyEnvelope",
    "RawDirectionTestState",
    "RawDirectionZeroSnapshot",
]
