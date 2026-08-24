"""Dry-run-only vision Follow configuration, lease, and status contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from momo.domain.enums import ControlMode, ProfileVerificationStatus
from momo.domain.pose import utc_now
from momo.domain.robot import JointId


class FollowState(StrEnum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    STOPPED = "STOPPED"


class FollowStopReason(StrEnum):
    OPERATOR_STOP = "OPERATOR_STOP"
    BROWSER_DISCONNECTED = "BROWSER_DISCONNECTED"
    BACKEND_SHUTDOWN = "BACKEND_SHUTDOWN"
    FRAME_STALE = "FRAME_STALE"
    TARGET_LOST = "TARGET_LOST"
    CONFIDENCE_LOW = "CONFIDENCE_LOW"
    CAMERA_DISCONNECTED = "CAMERA_DISCONNECTED"
    TRACKER_FAULT = "TRACKER_FAULT"
    ROBOT_DISCONNECTED = "ROBOT_DISCONNECTED"
    ROBOT_FAULTED = "ROBOT_FAULTED"
    ROBOT_STATE_STALE = "ROBOT_STATE_STALE"
    MOTION_CONFLICT = "MOTION_CONFLICT"
    MOTION_REJECTED = "MOTION_REJECTED"
    LEASE_EXPIRED = "LEASE_EXPIRED"
    GLOBAL_STOP = "GLOBAL_STOP"


class FollowActuatorMapping(BaseModel):
    """Profile-bound mapping from normalized image error to joint increments."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    pan_joint: JointId
    tilt_joint: JointId
    pan_sign: Literal[-1, 1]
    tilt_sign: Literal[-1, 1]
    verification_status: Literal[ProfileVerificationStatus.VERIFIED_FOR_DRY_RUN] = (
        ProfileVerificationStatus.VERIFIED_FOR_DRY_RUN
    )

    @model_validator(mode="after")
    def require_distinct_joints(self) -> Self:
        if self.pan_joint == self.tilt_joint:
            raise ValueError("pan_joint and tilt_joint must be distinct")
        return self


class FollowConfiguration(BaseModel):
    """Complete, bounded controller tuning supplied by explicit operator intent."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    dead_zone_x: Annotated[float, Field(strict=True, ge=0.0, le=0.49)] = 0.05
    dead_zone_y: Annotated[float, Field(strict=True, ge=0.0, le=0.49)] = 0.05
    ema_alpha: Annotated[float, Field(strict=True, gt=0.0, le=1.0)] = 0.35
    gain: Annotated[float, Field(strict=True, gt=0.0, le=360.0)] = 20.0
    max_step: Annotated[float, Field(strict=True, gt=0.0, le=90.0)] = 2.0
    max_rate: Annotated[float, Field(strict=True, gt=0.0, le=360.0)] = 20.0
    confidence_threshold: Annotated[float, Field(strict=True, ge=0.0, le=1.0)] = 0.5
    frame_freshness_limit_s: Annotated[float, Field(strict=True, ge=0.05, le=5.0)] = 0.5
    target_lost_limit_s: Annotated[float, Field(strict=True, ge=0.05, le=10.0)] = 0.5
    lease_ttl_s: Annotated[float, Field(strict=True, ge=0.25, le=10.0)] = 1.0
    mapping: FollowActuatorMapping

    @model_validator(mode="after")
    def rate_can_honor_maximum_step(self) -> Self:
        if self.max_step / self.max_rate > 60.0:
            raise ValueError("max_step/max_rate must fit the bounded motion duration")
        return self


class FollowOperatorIntent(BaseModel):
    """One explicit request to start a Dry Run Follow lease."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent_id: UUID = Field(default_factory=uuid4)
    confirmed: Literal[True]
    requested_mode: Literal[ControlMode.DRY_RUN] = ControlMode.DRY_RUN
    configuration: FollowConfiguration
    issued_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def require_aware_issued_at(self) -> Self:
        _require_aware(self.issued_at, "issued_at")
        return self


class FollowLease(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lease_id: UUID = Field(default_factory=uuid4)
    issued_at: datetime
    heartbeat_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        _require_aware(self.issued_at, "issued_at")
        _require_aware(self.heartbeat_at, "heartbeat_at")
        _require_aware(self.expires_at, "expires_at")
        if self.heartbeat_at < self.issued_at:
            raise ValueError("heartbeat_at cannot precede issued_at")
        if self.expires_at <= self.heartbeat_at:
            raise ValueError("expires_at must be after heartbeat_at")
        return self


class FollowMetrics(BaseModel):
    """Auditable controller inputs and bounded output for the latest frame."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    frame_id: str
    source_id: str
    captured_at: datetime
    frame_age_s: Annotated[float, Field(ge=0.0)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    error_x: Annotated[float, Field(ge=-0.5, le=0.5)]
    error_y: Annotated[float, Field(ge=-0.5, le=0.5)]
    ema_error_x: Annotated[float, Field(ge=-0.5, le=0.5)]
    ema_error_y: Annotated[float, Field(ge=-0.5, le=0.5)]
    pan_step: float = Field(allow_inf_nan=False)
    tilt_step: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def require_aware_capture_time(self) -> Self:
        _require_aware(self.captured_at, "captured_at")
        return self


@dataclass(frozen=True, slots=True)
class FollowControllerState:
    """Internal pure-controller memory; all external values were already validated."""

    ema_error_x: float | None = None
    ema_error_y: float | None = None
    last_dispatch_monotonic: float | None = None


@dataclass(frozen=True, slots=True)
class FollowControlDecision:
    state: FollowControllerState
    metrics: FollowMetrics


class FollowController:
    """Pure normalized-error → EMA → dead-zone → bounded-step calculation."""

    @staticmethod
    def update(
        configuration: FollowConfiguration,
        state: FollowControllerState,
        *,
        frame_id: str,
        source_id: str,
        captured_at: datetime,
        frame_age_s: float,
        confidence: float,
        center_x: float,
        center_y: float,
        now_monotonic: float,
    ) -> FollowControlDecision:
        error_x = center_x - 0.5
        error_y = center_y - 0.5
        alpha = configuration.ema_alpha
        ema_x = (
            error_x
            if state.ema_error_x is None
            else alpha * error_x + (1.0 - alpha) * state.ema_error_x
        )
        ema_y = (
            error_y
            if state.ema_error_y is None
            else alpha * error_y + (1.0 - alpha) * state.ema_error_y
        )
        pan_input = 0.0 if abs(ema_x) <= configuration.dead_zone_x else ema_x
        tilt_input = 0.0 if abs(ema_y) <= configuration.dead_zone_y else ema_y
        step_limit = configuration.max_step
        if state.last_dispatch_monotonic is not None:
            elapsed = max(0.0, now_monotonic - state.last_dispatch_monotonic)
            step_limit = min(step_limit, configuration.max_rate * elapsed)
        mapping = configuration.mapping
        pan_step = clamp(
            mapping.pan_sign * configuration.gain * pan_input,
            -step_limit,
            step_limit,
        )
        tilt_step = clamp(
            mapping.tilt_sign * configuration.gain * tilt_input,
            -step_limit,
            step_limit,
        )
        updated = FollowControllerState(
            ema_error_x=ema_x,
            ema_error_y=ema_y,
            last_dispatch_monotonic=state.last_dispatch_monotonic,
        )
        return FollowControlDecision(
            state=updated,
            metrics=FollowMetrics(
                frame_id=frame_id,
                source_id=source_id,
                captured_at=captured_at,
                frame_age_s=max(0.0, frame_age_s),
                confidence=confidence,
                error_x=error_x,
                error_y=error_y,
                ema_error_x=ema_x,
                ema_error_y=ema_y,
                pan_step=pan_step,
                tilt_step=tilt_step,
            ),
        )

    @staticmethod
    def mark_dispatched(
        state: FollowControllerState,
        at_monotonic: float,
    ) -> FollowControllerState:
        return FollowControllerState(
            ema_error_x=state.ema_error_x,
            ema_error_y=state.ema_error_y,
            last_dispatch_monotonic=at_monotonic,
        )


class FollowStatus(BaseModel):
    """Latest-value Follow state; observers must not construct an event queue."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    follow_id: UUID | None = None
    operator_intent_id: UUID | None = None
    state: FollowState = FollowState.IDLE
    configuration: FollowConfiguration | None = None
    lease: FollowLease | None = None
    metrics: FollowMetrics | None = None
    active_command_id: UUID | None = None
    stop_reason: FollowStopReason | None = None
    updated_at: datetime = Field(default_factory=utc_now)
    control_mode: Literal[ControlMode.DRY_RUN] = ControlMode.DRY_RUN
    real_follow_allowed: Literal[False] = False
    real_follow_blocked_reason: Literal["FIELD_VERIFICATION_REQUIRED"] = (
        "FIELD_VERIFICATION_REQUIRED"
    )
    hardware_accessed: Literal[False] = False

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        _require_aware(self.updated_at, "updated_at")
        if self.state is FollowState.IDLE:
            if any(
                value is not None
                for value in (
                    self.follow_id,
                    self.operator_intent_id,
                    self.configuration,
                    self.lease,
                    self.stop_reason,
                )
            ):
                raise ValueError("IDLE Follow status cannot contain session state")
        elif any(
            value is None
            for value in (
                self.follow_id,
                self.operator_intent_id,
                self.configuration,
                self.lease,
            )
        ):
            raise ValueError("non-IDLE Follow status requires complete session state")
        if self.state is FollowState.ACTIVE and self.stop_reason is not None:
            raise ValueError("ACTIVE Follow status cannot have a stop reason")
        if self.state is FollowState.STOPPED and self.stop_reason is None:
            raise ValueError("STOPPED Follow status requires a stop reason")
        return self


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
