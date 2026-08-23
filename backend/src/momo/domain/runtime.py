"""Runtime state/status contracts shared by adapters, services, and API schemas."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from momo.domain.enums import (
    CalibrationStatus,
    ControlMode,
    HardwareAccessPolicy,
    ProfileVerificationStatus,
    RobotConnectionState,
    RobotVariant,
)
from momo.domain.immutable import freeze_mapping
from momo.domain.robot import JointId

RUNTIME_SCHEMA_VERSION = "1.0.0"


def utc_now() -> datetime:
    return datetime.now(UTC)


class RuntimeState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal["1.0.0"] = "1.0.0"
    robot_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
    variant: RobotVariant
    profile_fingerprint: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    positions: dict[JointId, float]
    units: dict[JointId, str]
    connection_state: RobotConnectionState = RobotConnectionState.DISCONNECTED
    updated_at: datetime = Field(default_factory=utc_now)
    state_sequence: int = Field(default=0, ge=0)

    @field_validator("positions", mode="before")
    @classmethod
    def reject_boolean_positions(cls, value: object) -> object:
        if isinstance(value, Mapping):
            boolean_keys = [str(key) for key, item in value.items() if isinstance(item, bool)]
            if boolean_keys:
                raise ValueError(f"boolean runtime positions are invalid: {sorted(boolean_keys)}")
        return value

    @field_validator("updated_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("updated_at must include a timezone offset")
        return value

    @field_validator("positions", "units")
    @classmethod
    def freeze_runtime_mappings(cls, value: dict[str, object]) -> dict[str, object]:
        return freeze_mapping(value)


class RobotStatus(BaseModel):
    """Read-only status payload; no movement command fields are present."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    robot_id: str
    variant: RobotVariant
    control_mode: ControlMode
    hardware_access_policy: HardwareAccessPolicy
    connection_state: RobotConnectionState
    connected: bool
    profile_fingerprint: str
    profile_verification_status: ProfileVerificationStatus
    calibration_status: CalibrationStatus
    positions: dict[JointId, float]
    units: dict[JointId, str]
    raw_positions: dict[JointId, int] | None = None
    last_error: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)
    state_sequence: int = Field(default=0, ge=0)
    hardware_accessed: Literal[False] = False
    stale: bool = False

    @field_validator("positions", "units", "raw_positions")
    @classmethod
    def freeze_status_mappings(
        cls,
        value: dict[str, object] | None,
    ) -> dict[str, object] | None:
        return freeze_mapping(value) if value is not None else None


class StopResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: Literal["STOPPED", "NOT_CONNECTED", "FAILED", "SAFETY_STATE_UNCERTAIN"]
    status: RobotStatus
    hardware_accessed: Literal[False] = False


# Name used by the application contract and ADRs.
RobotRuntimeState = RuntimeState
