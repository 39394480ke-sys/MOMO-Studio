"""Redacted Stage 8 HTTP contracts for explicit device authorization."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from momo.domain.commissioning import FieldAcceptanceEvidenceState
from momo.domain.enums import HardwareAccessPolicy, RobotVariant
from momo.domain.real_hardware import (
    FieldAcceptanceStatus,
    HardwareDependencyState,
    OperatorSessionPurpose,
    OperatorSessionScope,
    RealHardwareReadinessState,
    RealStopResult,
)


class HardwareConfirmationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    robot_id: str | None
    robot_unit_id: str | None
    variant: RobotVariant | None
    profile_fingerprint: str | None
    calibration_fingerprint: str | None
    kinematics_fingerprint: str | None
    field_acceptance_evidence_id: UUID | None
    pre_motion_evidence_id: UUID | None
    masked_serial_port: str | None
    masked_servo_ids: list[str]
    protocol: str | None
    session_purpose: OperatorSessionPurpose
    physical_estop_required: Literal[True]
    workspace_clear_required: bool
    required_confirmation_text: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200),
    ]


class OperatorSessionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool
    session_id: UUID | None
    expires_at: datetime | None
    purpose: OperatorSessionPurpose | None
    scopes: list[OperatorSessionScope]


class RealHardwareCapabilityReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commissioning_read_only_ready: bool
    commissioning_diagnostics_ready: bool
    calibration_capture_ready: bool
    commissioning_motion_test_ready: bool
    real_joint_motion_ready: bool
    real_cartesian_motion_ready: bool
    real_playback_ready: bool
    real_vision_follow_ready: bool


class CapabilityReadinessDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready: bool
    authorized: bool
    blocked_reasons: list[str]
    required_evidence: list[str]


class RealHardwareCapabilityDetailsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commissioning_read_only: CapabilityReadinessDetailResponse
    commissioning_motion_test: CapabilityReadinessDetailResponse
    real_joint_motion: CapabilityReadinessDetailResponse
    real_cartesian_motion: CapabilityReadinessDetailResponse
    real_playback: CapabilityReadinessDetailResponse
    real_vision_follow: CapabilityReadinessDetailResponse


class OperatorSessionAuthorizationOptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: OperatorSessionPurpose
    authorizable: bool
    confirmation: HardwareConfirmationResponse


class RealHardwareReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: RealHardwareReadinessState
    ready: bool
    session_authorizable: bool
    commissioning_session_authorizable: bool
    commissioning_motion_session_authorizable: bool
    motion_session_authorizable: bool
    blocking_reasons: list[str]
    capabilities: RealHardwareCapabilityReadinessResponse
    capability_details: RealHardwareCapabilityDetailsResponse
    authorization_options: list[OperatorSessionAuthorizationOptionResponse]
    confirmation: HardwareConfirmationResponse
    session: OperatorSessionStatusResponse | None
    calibration_configured: bool
    connected: bool


class OperatorSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: OperatorSessionPurpose
    confirmation_text: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200),
    ]
    physical_estop_confirmed: Literal[True]
    workspace_clear_confirmed: bool = False
    operator_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
    ] = "operator"


class OperatorSessionCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    issued_at: datetime
    expires_at: datetime
    purpose: OperatorSessionPurpose
    scopes: list[OperatorSessionScope]
    evidence: HardwareConfirmationResponse


class FieldAcceptanceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checklist_version: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ]
    confirmation_text: Literal["I CONFIRM THE FIELD ACCEPTANCE CHECKLIST IS COMPLETE"]
    accepted_by: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
        ]
        | None
    ) = None


class FieldAcceptanceChecklistRequest(BaseModel):
    """Select the configured checklist; it never carries an acceptance verdict."""

    model_config = ConfigDict(extra="forbid")

    checklist_version: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ]


class FieldAcceptanceStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: FieldAcceptanceEvidenceState
    effective_status: FieldAcceptanceStatus
    checklist_version: str
    stale_fields: list[str]
    evidence_id: UUID | None
    accepted_at: datetime | None
    accepted_by: str | None
    required_confirmation_text: Literal["I CONFIRM THE FIELD ACCEPTANCE CHECKLIST IS COMPLETE"]


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
    logical_value: float | None
    raw_bounds: tuple[int, int] | None
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
