"""Redacted Stage 8 HTTP contracts for explicit device authorization."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from momo.domain.enums import HardwareAccessPolicy, RobotVariant
from momo.domain.real_hardware import (
    FieldAcceptanceStatus,
    HardwareDependencyState,
    RealHardwareReadinessState,
    RealStopResult,
)


class HardwareConfirmationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    robot_id: str | None
    variant: RobotVariant | None
    profile_fingerprint: str | None
    calibration_fingerprint: str | None
    kinematics_fingerprint: str | None
    masked_serial_port: str | None
    masked_servo_ids: list[str]
    protocol: str | None
    physical_estop_required: Literal[True]
    required_confirmation_text: Literal["I UNDERSTAND REAL HARDWARE CAN MOVE"]


class OperatorSessionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool
    session_id: UUID | None
    expires_at: datetime | None


class RealHardwareCapabilityReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    real_joint_motion_ready: bool
    real_cartesian_motion_ready: bool
    real_playback_ready: bool
    real_vision_follow_ready: bool


class RealHardwareReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: RealHardwareReadinessState
    ready: bool
    session_authorizable: bool
    blocking_reasons: list[str]
    capabilities: RealHardwareCapabilityReadinessResponse
    confirmation: HardwareConfirmationResponse
    session: OperatorSessionStatusResponse | None
    connected: bool


class OperatorSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_text: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200),
    ]
    physical_estop_confirmed: Literal[True]


class OperatorSessionCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_token: Annotated[
        str,
        StringConstraints(min_length=20, max_length=200),
    ] = Field(repr=False)
    session_id: UUID
    issued_at: datetime
    expires_at: datetime
    evidence: HardwareConfirmationResponse


class HardwareDependencyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter_id: str
    state: HardwareDependencyState
    package_name: str | None
    license_status: str
    notice: str


class HardwareArtifactResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: bool
    fingerprint: str | None
    verification_status: str | None
    template: bool | None
    ready_for_real: bool


class ServoDiagnosticResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    joint_id: str
    masked_servo_id: str
    ping_responded: bool
    operating_mode: str
    present_raw: int
    logical_value: float
    raw_bounds: tuple[int, int]
    torque_enabled: bool | None


class DeviceDiagnosticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connected: bool
    captured_at: datetime
    dependency: HardwareDependencyResponse
    hardware_policy: HardwareAccessPolicy
    masked_serial_port: str | None
    masked_servo_ids: list[str]
    protocol: str | None
    profile: HardwareArtifactResponse
    calibration: HardwareArtifactResponse
    kinematics: HardwareArtifactResponse
    field_acceptance: FieldAcceptanceStatus
    readiness: RealHardwareReadinessState
    records: list[ServoDiagnosticResponse]
    last_error: str


class RealStopOutcomeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: RealStopResult
    connected: bool
    safety_state_known: bool
    requested_count: Annotated[int, Field(ge=0, le=32)]
    affected_count: Annotated[int, Field(ge=0, le=32)]
    detail: str
    physical_estop_required: Literal[True] = True
