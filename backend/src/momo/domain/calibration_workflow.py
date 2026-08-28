"""Protected, read-only current-position calibration workflow contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Annotated, Literal, Self, cast
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from momo.domain.calibration import CalibrationDocument, Fingerprint
from momo.domain.commissioning import RobotUnitId
from momo.domain.enums import (
    CalibrationOperatingMode,
    ControlMode,
    DomainUnit,
    HardwareAccessPolicy,
    RobotVariant,
)
from momo.domain.immutable import freeze_sequence
from momo.domain.real_hardware import (
    RealHardwareAuthorizationPurpose,
    RealHardwareCapabilityReadiness,
)
from momo.domain.robot import JointId

CALIBRATION_REVISION_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
RobotIdValue = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$"),
]
ServoId = Annotated[int, Field(strict=True, ge=1, le=253)]
Revision = Annotated[int, Field(strict=True, ge=1)]
FiniteLogicalValue = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class CalibrationWorkflowError(RuntimeError):
    """Typed local failure; callers may map ``code`` to a transport error."""

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


class CalibrationWorkflowSource(StrEnum):
    EXISTING_REAL = "EXISTING_REAL"
    EXPLICIT_LEGACY_IMPORT = "EXPLICIT_LEGACY_IMPORT"


class CalibrationWorkflowState(StrEnum):
    ACTIVE = "ACTIVE"
    READY_TO_SAVE = "READY_TO_SAVE"
    SAVED = "SAVED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CalibrationJointDraft(BaseModel):
    """Incomplete commissioning capture for one explicit profile joint.

    Missing observations and operator inputs remain ``None``. In particular, a
    fresh robot is never represented by a fabricated zero-valued calibration.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    joint_id: JointId
    servo_id: ServoId
    present_raw: int | None = Field(default=None, strict=True)
    logical_value: FiniteLogicalValue | None = None
    direction: Literal[-1, 1] | None = None
    phase: int | None = Field(default=None, strict=True)
    raw_bounds: tuple[int, int] | None = None
    operating_mode: CalibrationOperatingMode | None = None

    @model_validator(mode="after")
    def validate_partial_mapping(self) -> Self:
        if self.raw_bounds is not None:
            lower, upper = self.raw_bounds
            if (
                isinstance(lower, bool)
                or isinstance(upper, bool)
                or not isinstance(lower, int)
                or not isinstance(upper, int)
                or lower >= upper
            ):
                raise ValueError("draft raw_bounds must be ordered integers")
        return self


class CalibrationDraft(BaseModel):
    """Profile-bound, non-persisted input state for initial or later calibration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    robot_variant: RobotVariant
    profile_fingerprint: Fingerprint
    enabled_joints: tuple[JointId, ...]
    created_at: datetime
    base_revision: Revision | None = None
    base_calibration_fingerprint: Fingerprint | None = None
    joints: tuple[CalibrationJointDraft, ...]

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("draft created_at must include a timezone offset")
        return value

    @model_validator(mode="after")
    def validate_profile_shape(self) -> Self:
        joint_ids = tuple(joint.joint_id for joint in self.joints)
        if not self.enabled_joints or joint_ids != self.enabled_joints:
            raise ValueError("draft joints must exactly match ordered enabled_joints")
        if len(joint_ids) != len(set(joint_ids)):
            raise ValueError("draft joint IDs must be unique")
        servo_ids = tuple(joint.servo_id for joint in self.joints)
        if len(servo_ids) != len(set(servo_ids)):
            raise ValueError("draft Servo IDs must be unique")
        if (self.base_revision is None) is not (self.base_calibration_fingerprint is None):
            raise ValueError("draft base revision and fingerprint must both be present or absent")
        return self

    @property
    def joints_by_id(self) -> dict[str, CalibrationJointDraft]:
        return {joint.joint_id: joint for joint in self.joints}


class CalibrationAuthorization(BaseModel):
    """Short-lived internal evidence issued only after API token authentication.

    This object deliberately contains no raw token and is never persisted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID
    robot_id: RobotIdValue
    robot_unit_id: RobotUnitId
    variant: RobotVariant
    profile_fingerprint: Fingerprint
    calibration_fingerprint: Fingerprint | None = None
    allowed_servo_ids: tuple[ServoId, ...]
    issued_at: datetime
    expires_at: datetime
    confirmed: Literal[True]
    physical_estop_confirmed: Literal[True]
    control_mode: Literal[ControlMode.REAL] = ControlMode.REAL
    hardware_policy: Literal[HardwareAccessPolicy.READ_ONLY] = HardwareAccessPolicy.READ_ONLY
    purpose: Literal[RealHardwareAuthorizationPurpose.CALIBRATION_CAPTURE]
    capabilities: RealHardwareCapabilityReadiness

    @field_validator("issued_at", "expires_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("authorization timestamps must include a timezone offset")
        return value

    @field_validator("allowed_servo_ids")
    @classmethod
    def require_unique_servo_ids(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if not value:
            raise ValueError("authorization must contain at least one explicit Servo ID")
        if len(value) != len(set(value)):
            raise ValueError("allowed_servo_ids must be unique")
        return value

    @model_validator(mode="after")
    def require_ordered_window(self) -> Self:
        if self.expires_at <= self.issued_at:
            raise ValueError("authorization expiry must follow issue time")
        if not self.capabilities.calibration_capture_ready:
            raise ValueError("calibration requires current read-only capture capability evidence")
        return self

    def active(self, now: datetime) -> bool:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("authorization check time must include a timezone offset")
        return self.issued_at <= now < self.expires_at


class CalibrationJointPreview(BaseModel):
    """Complete mapping preview for one and only one observed joint."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    session_id: UUID
    joint_id: JointId
    servo_id: ServoId
    observed_raw: int = Field(strict=True)
    logical_value: float = Field(strict=True)
    unit: DomainUnit
    operating_mode: CalibrationOperatingMode
    direction: Literal[-1, 1]
    home_present_raw: int = Field(strict=True)
    phase: int | None = Field(default=None, strict=True)
    raw_bounds: tuple[int, int]
    round_trip_logical_value: float = Field(strict=True)
    mapping_error: float = Field(strict=True, ge=0.0)
    preview_fingerprint: Fingerprint

    @classmethod
    def create(
        cls,
        *,
        session_id: UUID,
        joint_id: str,
        servo_id: int,
        observed_raw: int,
        logical_value: float,
        unit: DomainUnit,
        operating_mode: CalibrationOperatingMode,
        direction: int,
        home_present_raw: int,
        phase: int | None,
        raw_bounds: tuple[int, int],
        round_trip_logical_value: float,
        mapping_error: float,
    ) -> Self:
        """Build a preview whose hash covers every visible mapping input."""

        if direction not in {-1, 1}:
            raise ValueError("direction must be -1 or 1")
        direction_sign = cast(Literal[-1, 1], direction)
        unchecked = cls.model_construct(
            session_id=session_id,
            joint_id=joint_id,
            servo_id=servo_id,
            observed_raw=observed_raw,
            logical_value=logical_value,
            unit=unit,
            operating_mode=operating_mode,
            direction=direction_sign,
            home_present_raw=home_present_raw,
            phase=phase,
            raw_bounds=raw_bounds,
            round_trip_logical_value=round_trip_logical_value,
            mapping_error=mapping_error,
            preview_fingerprint="0" * 64,
        )
        return cls(
            session_id=session_id,
            joint_id=joint_id,
            servo_id=servo_id,
            observed_raw=observed_raw,
            logical_value=logical_value,
            unit=unit,
            operating_mode=operating_mode,
            direction=direction_sign,
            home_present_raw=home_present_raw,
            phase=phase,
            raw_bounds=raw_bounds,
            round_trip_logical_value=round_trip_logical_value,
            mapping_error=mapping_error,
            preview_fingerprint=calibration_preview_fingerprint(unchecked),
        )

    @model_validator(mode="after")
    def validate_preview(self) -> Self:
        if not all(
            isfinite(value)
            for value in (self.logical_value, self.round_trip_logical_value, self.mapping_error)
        ):
            raise ValueError("calibration preview values must be finite")
        lower, upper = self.raw_bounds
        if lower >= upper:
            raise ValueError("preview raw_bounds must be ordered")
        if not lower <= self.observed_raw <= upper:
            raise ValueError("observed raw must be within preview raw_bounds")
        if not lower <= self.home_present_raw <= upper:
            raise ValueError("Home raw must be within preview raw_bounds")
        if self.operating_mode is CalibrationOperatingMode.MULTI_TURN and self.phase is None:
            raise ValueError("multi-turn calibration requires an explicit phase")
        if self.preview_fingerprint != calibration_preview_fingerprint(self):
            raise ValueError("calibration preview fingerprint mismatch")
        return self


class CalibrationSavePreview(BaseModel):
    """Exact complete calibration document awaiting one explicit Save confirmation."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    session_id: UUID
    base_revision: Revision | None = None
    base_calibration_fingerprint: Fingerprint | None = None
    source: CalibrationWorkflowSource
    proposed_calibration: CalibrationDocument
    proposed_calibration_fingerprint: Fingerprint

    @model_validator(mode="after")
    def validate_complete_proposal(self) -> Self:
        calibration = self.proposed_calibration
        if calibration.template or not all(joint.complete for joint in calibration.joints):
            raise ValueError("save preview requires a complete non-template calibration")
        if self.proposed_calibration_fingerprint != calibration_document_fingerprint(calibration):
            raise ValueError("save preview calibration fingerprint mismatch")
        if (self.base_revision is None) is not (self.base_calibration_fingerprint is None):
            raise ValueError("save preview base revision and fingerprint must match")
        if (
            self.base_calibration_fingerprint is not None
            and self.proposed_calibration_fingerprint == self.base_calibration_fingerprint
        ):
            raise ValueError("save preview must create a new calibration identity")
        return self


class CalibrationWorkflowStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID
    authorization_session_id: UUID
    robot_id: RobotIdValue
    variant: RobotVariant
    profile_fingerprint: Fingerprint
    base_revision: Revision | None = None
    base_calibration_fingerprint: Fingerprint | None = None
    draft: CalibrationDraft
    source: CalibrationWorkflowSource
    state: CalibrationWorkflowState
    required_joint_ids: tuple[JointId, ...]
    confirmed_joint_ids: tuple[JointId, ...] = ()
    selected_joint_id: JointId | None = None
    observed_raw: int | None = Field(default=None, strict=True)
    preview: CalibrationJointPreview | None = None
    save_preview: CalibrationSavePreview | None = None
    saved_revision: Revision | None = None
    saved_calibration_fingerprint: Fingerprint | None = None
    updated_at: datetime

    @field_validator("required_joint_ids", "confirmed_joint_ids")
    @classmethod
    def freeze_joint_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(freeze_sequence(value))

    @field_validator("updated_at")
    @classmethod
    def require_aware_update(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("updated_at must include a timezone offset")
        return value

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        required = set(self.required_joint_ids)
        confirmed = set(self.confirmed_joint_ids)
        if len(required) != len(self.required_joint_ids):
            raise ValueError("required joints must be unique")
        if len(confirmed) != len(self.confirmed_joint_ids) or not confirmed <= required:
            raise ValueError("confirmed joints must be a unique subset of required joints")
        if self.preview is not None and self.preview.session_id != self.session_id:
            raise ValueError("preview belongs to a different calibration session")
        if (self.base_revision is None) is not (self.base_calibration_fingerprint is None):
            raise ValueError("status base revision and fingerprint must match")
        if (
            self.draft.robot_variant is not self.variant
            or self.draft.profile_fingerprint != self.profile_fingerprint
            or self.draft.enabled_joints != self.required_joint_ids
            or self.draft.base_revision != self.base_revision
            or self.draft.base_calibration_fingerprint != self.base_calibration_fingerprint
        ):
            raise ValueError("status draft does not match workflow identity")
        if self.state is CalibrationWorkflowState.READY_TO_SAVE and confirmed != required:
            raise ValueError("READY_TO_SAVE requires every joint confirmation")
        if self.state is CalibrationWorkflowState.READY_TO_SAVE and self.save_preview is None:
            raise ValueError("READY_TO_SAVE requires a complete aggregate save preview")
        if self.state is CalibrationWorkflowState.ACTIVE and self.save_preview is not None:
            raise ValueError("ACTIVE cannot expose a stale aggregate save preview")
        if self.save_preview is not None and self.save_preview.session_id != self.session_id:
            raise ValueError("save preview belongs to a different calibration session")
        if self.state is CalibrationWorkflowState.SAVED:
            if self.saved_revision is None or self.saved_calibration_fingerprint is None:
                raise ValueError("SAVED status requires saved revision/fingerprint")
        elif self.saved_revision is not None or self.saved_calibration_fingerprint is not None:
            raise ValueError("only SAVED status may expose saved revision/fingerprint")
        return self


class CalibrationRevisionRecord(BaseModel):
    """Forward-only persisted calibration revision with exact content identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["1.0.0"] = CALIBRATION_REVISION_SCHEMA_VERSION
    revision: Revision
    calibration_fingerprint: Fingerprint
    previous_calibration_fingerprint: Fingerprint | None = None
    source: CalibrationWorkflowSource
    calibration: CalibrationDocument
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone offset")
        return value

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        if self.calibration.template:
            raise ValueError("template/example calibration cannot become a workflow revision")
        if not all(joint.complete for joint in self.calibration.joints):
            raise ValueError("calibration revision requires every joint to be complete")
        expected = calibration_document_fingerprint(self.calibration)
        if self.calibration_fingerprint != expected:
            raise ValueError("calibration fingerprint mismatch")
        if self.previous_calibration_fingerprint == self.calibration_fingerprint:
            raise ValueError("a new calibration revision must have a new fingerprint")
        return self


def calibration_document_fingerprint(calibration: CalibrationDocument) -> str:
    """Safety identity shared with the real-hardware authorization gate."""

    payload = calibration.model_dump(mode="json", exclude={"generated_at", "notes"})
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def calibration_preview_fingerprint(preview: CalibrationJointPreview) -> str:
    payload = preview.model_dump(mode="json", exclude={"preview_fingerprint"})
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CalibrationAuthorization",
    "CalibrationDraft",
    "CalibrationJointDraft",
    "CalibrationJointPreview",
    "CalibrationRevisionRecord",
    "CalibrationSavePreview",
    "CalibrationWorkflowError",
    "CalibrationWorkflowSource",
    "CalibrationWorkflowState",
    "CalibrationWorkflowStatus",
    "calibration_document_fingerprint",
    "calibration_preview_fingerprint",
]
