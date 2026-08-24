"""Bounded request and redacted response contracts for protected calibration."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from momo.domain.calibration import CalibrationDocument, Fingerprint
from momo.domain.calibration_workflow import CalibrationWorkflowSource
from momo.domain.enums import RobotVariant
from momo.domain.robot import JointId

Confirmation = Annotated[
    str,
    StringConstraints(strip_whitespace=False, min_length=1, max_length=128),
]


class CalibrationSessionStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: CalibrationWorkflowSource = CalibrationWorkflowSource.EXISTING_REAL
    explicit_legacy_calibration: CalibrationDocument | None = None
    legacy_confirmation: Confirmation | None = None

    @model_validator(mode="after")
    def require_source_specific_fields(self) -> CalibrationSessionStartRequest:
        legacy = self.source is CalibrationWorkflowSource.EXPLICIT_LEGACY_IMPORT
        if legacy is not (
            self.explicit_legacy_calibration is not None and self.legacy_confirmation is not None
        ):
            raise ValueError("Legacy calibration fields must exactly match Legacy source mode")
        return self


class CalibrationJointReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    joint_id: JointId


class CalibrationJointPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    joint_id: JointId
    logical_value: float = Field(strict=True)
    direction: Annotated[int, Field(strict=True, ge=-1, le=1)] | None = None
    phase: int | None = Field(default=None, strict=True)
    raw_bounds: tuple[int, int] | None = None

    @model_validator(mode="after")
    def validate_direction_and_bounds(self) -> CalibrationJointPreviewRequest:
        if self.direction not in {None, -1, 1}:
            raise ValueError("direction must be -1 or 1")
        if self.raw_bounds is not None and self.raw_bounds[0] >= self.raw_bounds[1]:
            raise ValueError("raw_bounds must be ordered")
        return self


class CalibrationJointConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    joint_id: JointId
    preview_fingerprint: Fingerprint
    confirmation: Confirmation


class CalibrationCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposed_calibration_fingerprint: Fingerprint
    confirmation: Confirmation


class CalibrationRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_revision: Annotated[int, Field(strict=True, ge=1)]
    confirmation: Confirmation


class CalibrationRevisionSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: int
    calibration_fingerprint: Fingerprint
    previous_calibration_fingerprint: Fingerprint | None
    variant: RobotVariant
    created_at: str


__all__ = [
    "CalibrationCompleteRequest",
    "CalibrationJointConfirmRequest",
    "CalibrationJointPreviewRequest",
    "CalibrationJointReadRequest",
    "CalibrationRevisionSummaryResponse",
    "CalibrationRollbackRequest",
    "CalibrationSessionStartRequest",
]
