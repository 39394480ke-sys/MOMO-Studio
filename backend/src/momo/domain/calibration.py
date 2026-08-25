"""Immutable calibration documents and structured readiness diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from momo.domain.enums import (
    CalibrationOperatingMode,
    CalibrationStatus,
    RealReadiness,
    RobotVariant,
)
from momo.domain.immutable import freeze_sequence
from momo.domain.robot import JointId

CALIBRATION_SCHEMA_VERSION = "1.0.0"
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PositiveStrictInt = Annotated[StrictInt, Field(ge=1)]
RobotUnitId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]


def utc_now() -> datetime:
    return datetime.now(UTC)


class CalibrationJoint(BaseModel):
    """One joint's hardware-local reference without joint-name assumptions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    joint_id: JointId
    servo_id: PositiveStrictInt
    operating_mode: CalibrationOperatingMode
    direction: StrictInt
    home_present_raw: StrictInt | None = None
    phase: StrictInt | None = None
    raw_bounds: tuple[StrictInt, StrictInt] | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_field_names(cls, value: object) -> object:
        """Accept the documented optional-name spellings without dynamic aliases."""

        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        aliases = {
            "mode": "operating_mode",
            "phase_optional": "phase",
            "raw_bounds_optional": "raw_bounds",
        }
        for alias, canonical in aliases.items():
            if alias in normalized and canonical not in normalized:
                normalized[canonical] = normalized.pop(alias)
        return normalized

    @field_validator("direction")
    @classmethod
    def require_direction_sign(cls, value: int) -> int:
        if value not in {-1, 1}:
            raise ValueError("direction must be -1 or 1")
        return value

    @model_validator(mode="after")
    def validate_raw_bounds(self) -> Self:
        if self.raw_bounds is not None and self.raw_bounds[0] >= self.raw_bounds[1]:
            raise ValueError("raw_bounds lower bound must be less than upper bound")
        if (
            self.home_present_raw is not None
            and self.raw_bounds is not None
            and not self.raw_bounds[0] <= self.home_present_raw <= self.raw_bounds[1]
        ):
            raise ValueError("home_present_raw must be within raw_bounds")
        return self

    @property
    def complete(self) -> bool:
        if self.home_present_raw is None:
            return False
        return not (
            self.operating_mode is CalibrationOperatingMode.MULTI_TURN and self.phase is None
        )


class CalibrationDocument(BaseModel):
    """Versioned calibration keyed to an exact variant and profile fingerprint."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    id: UUID = Field(default_factory=uuid4)
    # ``None`` keeps generic templates and existing 1.0 documents readable.
    # Newly captured Real calibrations always bind the physical unit explicitly.
    robot_unit_id: RobotUnitId | None = None
    robot_variant: RobotVariant
    profile_fingerprint: Fingerprint
    template: bool
    generated_at: datetime = Field(default_factory=utc_now)
    notes: str = ""
    joints: Annotated[list[CalibrationJoint], Field(min_length=1)]

    @field_validator("generated_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include a timezone offset")
        return value

    @field_validator("joints")
    @classmethod
    def freeze_joints(cls, value: list[CalibrationJoint]) -> list[CalibrationJoint]:
        return freeze_sequence(value)

    @model_validator(mode="after")
    def validate_unique_joint_and_servo_ids(self) -> Self:
        joint_ids = [joint.joint_id for joint in self.joints]
        if len(joint_ids) != len(set(joint_ids)):
            raise ValueError("calibration joint IDs must be unique")
        servo_ids = [joint.servo_id for joint in self.joints]
        if len(servo_ids) != len(set(servo_ids)):
            raise ValueError("calibration servo IDs must be unique")
        return self

    @property
    def joints_by_id(self) -> dict[str, CalibrationJoint]:
        return {joint.joint_id: joint for joint in self.joints}


class CalibrationStatusReport(BaseModel):
    """Stable, UI-safe explanation of calibration compatibility."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: CalibrationStatus
    configured: bool
    template: bool | None
    variant_match: bool | None
    profile_match: bool | None
    joint_set_match: bool | None
    mapping_match: bool | None
    complete: bool | None
    calibration_valid: bool
    real_readiness: RealReadiness = RealReadiness.BLOCKED_BY_STAGE_POLICY
    blocking_reasons: list[str]

    @field_validator("blocking_reasons")
    @classmethod
    def freeze_reasons(cls, value: list[str]) -> list[str]:
        return freeze_sequence(value)
