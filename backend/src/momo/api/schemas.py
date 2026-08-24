"""HTTP contracts; application and domain layers do not import this module."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from momo.domain.calibration import CalibrationStatusReport
from momo.domain.enums import ControlMode, HardwareAccessPolicy, RobotVariant
from momo.domain.robot import RobotProfile
from momo.domain.runtime import RobotStatus


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    product: str
    version: str
    stage: Literal[8] = 8
    control_mode: ControlMode
    hardware_access_policy: HardwareAccessPolicy
    real_motion_enabled: bool


class MetaResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: str
    version: str
    api_version: Literal["v1"] = "v1"
    stage: Literal[8] = 8
    release_status: Literal["FIELD_ACCEPTANCE_REQUIRED"] = "FIELD_ACCEPTANCE_REQUIRED"
    dry_run_validated: Literal[True] = True
    real_hardware_field_acceptance: Literal["PENDING"] = "PENDING"
    active_robot_variant: RobotVariant
    supported_robot_variants: list[RobotVariant] = Field(
        default_factory=lambda: [RobotVariant.V1, RobotVariant.V2]
    )
    supported_control_modes: list[ControlMode] = Field(
        default_factory=lambda: [ControlMode.DRY_RUN, ControlMode.REAL]
    )
    active_control_mode: ControlMode
    hardware_access_policy: HardwareAccessPolicy
    real_motion_enabled: bool


class ProductScopeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: str
    release: Literal["first_version"] = "first_version"
    stage: Literal[8] = 8
    stage_3_available: list[str]
    stage_4_available: list[str]
    stage_5_available: list[str]
    stage_6_available: list[str]
    stage_7_available: list[str]
    stage_8_available: list[str]
    included_in_first_version: list[str]
    excluded_from_first_version: list[str]


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: Any = Field(default_factory=dict)
    request_id: str | None = None


class RobotCommandResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: RobotStatus
    hardware_accessed: Literal[False] = False


class VariantSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant: RobotVariant


class ProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: RobotProfile
    fingerprint: str
    kinematics_fingerprint: str
    real_eligible: Literal[False] = False


class DiagnosticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hardware_access_policy: Literal[HardwareAccessPolicy.DISABLED]
    runtime_state_path: str
    runtime_state_valid: bool
    runtime_state_diagnostic: str
    quarantined_runtime_file: str | None
    backend_version: str
    legacy_source_commit: str
    stage_policy: Literal["DRY_RUN_ONLY"]
    active_profile_fingerprint: str
    robot_state_freshness_limit_s: float
    runtime_persistence_error: str | None
    hardware_accessed: Literal[False] = False


CalibrationStatusResponse = CalibrationStatusReport
