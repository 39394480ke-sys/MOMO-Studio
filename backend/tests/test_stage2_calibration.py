"""Calibration integrity, compatibility, and Stage 2 readiness gates."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from momo.adapters.storage.file_calibration_repository import FileCalibrationRepository
from momo.application.services.calibration_service import CalibrationService
from momo.domain.calibration import (
    CalibrationDocument,
    CalibrationJoint,
    CalibrationStatusReport,
)
from momo.domain.enums import CalibrationStatus, RealReadiness, RobotVariant
from momo.domain.errors import CalibrationInvalidError
from momo.domain.profiles import canonical_robot_profile
from momo.domain.robot import RobotProfile
from momo.ports.calibration_repository import CalibrationRepository
from tests.stage2_helpers import make_calibration


class StaticCalibrationRepository(CalibrationRepository):
    def __init__(self, document: CalibrationDocument | None) -> None:
        self.document = document

    def get_for_variant(self, variant: RobotVariant) -> CalibrationDocument | None:
        del variant
        return self.document


def status_for(
    profile: RobotProfile,
    document: CalibrationDocument | None,
) -> CalibrationStatusReport:
    return CalibrationService(StaticCalibrationRepository(document)).status(profile)


def test_complete_non_template_calibration_is_valid_but_never_real_ready() -> None:
    profile = canonical_robot_profile(RobotVariant.V2)
    report = status_for(profile, make_calibration(profile, template=False))
    assert report.status is CalibrationStatus.VALID_FOR_DRY_RUN
    assert report.calibration_valid is True
    assert report.mapping_match is True
    assert report.real_readiness is RealReadiness.BLOCKED_BY_STAGE_POLICY


def test_template_calibration_cannot_authorize_real_hardware() -> None:
    profile = canonical_robot_profile(RobotVariant.V1)
    report = status_for(profile, make_calibration(profile, template=True))
    assert report.status is CalibrationStatus.TEMPLATE_ONLY
    assert report.calibration_valid is True
    assert report.real_readiness is RealReadiness.BLOCKED_BY_STAGE_POLICY
    assert any("Template" in reason for reason in report.blocking_reasons)


def test_missing_calibration_does_not_block_dry_run() -> None:
    profile = canonical_robot_profile(RobotVariant.V2)
    report = status_for(profile, None)
    assert report.status is CalibrationStatus.NOT_CONFIGURED
    assert report.configured is False
    assert report.calibration_valid is False
    assert report.real_readiness is RealReadiness.BLOCKED_BY_STAGE_POLICY


def test_variant_and_profile_fingerprint_mismatches_are_distinguished() -> None:
    v1 = canonical_robot_profile(RobotVariant.V1)
    v2 = canonical_robot_profile(RobotVariant.V2)
    assert status_for(v2, make_calibration(v1)).status is CalibrationStatus.VARIANT_MISMATCH

    data = make_calibration(v2).model_dump(mode="json")
    data["profile_fingerprint"] = "0" * 64
    mismatch = CalibrationDocument.model_validate(data)
    assert status_for(v2, mismatch).status is CalibrationStatus.PROFILE_MISMATCH


@pytest.mark.parametrize("mutation", ["extra_j10", "missing", "unknown"])
def test_joint_set_must_exactly_match_enabled_joints(mutation: str) -> None:
    profile = canonical_robot_profile(RobotVariant.V1)
    data = make_calibration(profile).model_dump(mode="json")
    if mutation == "extra_j10":
        data["joints"].append(
            {
                **data["joints"][0],
                "joint_id": "j10",
                "servo_id": 10,
            }
        )
    elif mutation == "missing":
        data["joints"].pop()
    else:
        data["joints"][-1]["joint_id"] = "j99"
    document = CalibrationDocument.model_validate(data)
    report = status_for(profile, document)
    assert report.status is CalibrationStatus.JOINT_SET_MISMATCH
    assert report.joint_set_match is False
    assert report.calibration_valid is False


def test_duplicate_joint_and_servo_ids_are_rejected() -> None:
    profile = canonical_robot_profile(RobotVariant.V1)
    data = make_calibration(profile).model_dump(mode="json")
    data["joints"][1]["servo_id"] = data["joints"][0]["servo_id"]
    with pytest.raises(ValidationError, match="servo IDs must be unique"):
        CalibrationDocument.model_validate(data)

    data = make_calibration(profile).model_dump(mode="json")
    data["joints"][1]["joint_id"] = data["joints"][0]["joint_id"]
    with pytest.raises(ValidationError, match="joint IDs must be unique"):
        CalibrationDocument.model_validate(data)


@pytest.mark.parametrize("direction", [0, 2, -2, True, 1.0])
def test_direction_must_be_a_strict_positive_or_negative_one(direction: object) -> None:
    with pytest.raises(ValidationError, match="direction"):
        CalibrationJoint.model_validate(
            {
                "joint_id": "j11",
                "servo_id": 11,
                "operating_mode": "MULTI_TURN",
                "direction": direction,
                "home_present_raw": 0,
                "phase": 0,
            }
        )


@pytest.mark.parametrize("missing_field", ["home_present_raw", "phase"])
def test_multi_turn_home_and_phase_must_be_complete(missing_field: str) -> None:
    profile = canonical_robot_profile(RobotVariant.V1)
    data = make_calibration(profile).model_dump(mode="json")
    data["joints"][0][missing_field] = None
    report = status_for(profile, CalibrationDocument.model_validate(data))
    assert report.status is CalibrationStatus.INCOMPLETE
    assert report.complete is False
    assert report.calibration_valid is False


@pytest.mark.parametrize("field", ["servo_id", "home_present_raw", "phase"])
@pytest.mark.parametrize("invalid", [1.25, True, "1"])
def test_raw_and_servo_values_are_strict_integers(
    field: str,
    invalid: object,
) -> None:
    data = {
        "joint_id": "j11",
        "servo_id": 11,
        "operating_mode": "MULTI_TURN",
        "direction": 1,
        "home_present_raw": 0,
        "phase": 0,
    }
    data[field] = invalid
    with pytest.raises(ValidationError, match="valid integer"):
        CalibrationJoint.model_validate(data)


def test_calibration_json_round_trip_and_optional_field_spellings() -> None:
    profile = canonical_robot_profile(RobotVariant.V2)
    document = make_calibration(profile)
    assert CalibrationDocument.model_validate_json(document.model_dump_json()) == document

    alias_joint = CalibrationJoint.model_validate(
        {
            "joint_id": "j10",
            "servo_id": 10,
            "mode": "MULTI_TURN",
            "direction": 1,
            "home_present_raw": 0,
            "phase_optional": 0,
            "raw_bounds_optional": [-100, 100],
        }
    )
    assert alias_joint.phase == 0
    assert alias_joint.raw_bounds == (-100, 100)


@pytest.mark.parametrize("mismatch", ["servo", "mode", "raw_bounds", "home"])
def test_hardware_mapping_mismatch_is_not_calibration_valid(mismatch: str) -> None:
    profile = canonical_robot_profile(RobotVariant.V2)
    data = make_calibration(profile).model_dump(mode="json")
    if mismatch == "servo":
        data["joints"][0]["servo_id"] = 99
    elif mismatch == "mode":
        data["joints"][0]["operating_mode"] = "SINGLE_TURN"
    elif mismatch == "raw_bounds":
        data["joints"][0]["raw_bounds"] = [40000, 41000]
        data["joints"][0]["home_present_raw"] = 40500
    else:
        data["joints"][0]["raw_bounds"] = [-100000, 100000]
        data["joints"][0]["home_present_raw"] = 50000
    report = status_for(profile, CalibrationDocument.model_validate(data))
    assert report.status is CalibrationStatus.INCOMPLETE
    assert report.mapping_match is False
    assert report.calibration_valid is False


def test_file_repository_rejects_non_utf8_calibration(tmp_path: Path) -> None:
    (tmp_path / "v1.example.json").write_bytes(b"\xff\xfe")
    repository = FileCalibrationRepository(tmp_path)
    with pytest.raises(CalibrationInvalidError, match="calibration document for V1 is invalid"):
        repository.get_for_variant(RobotVariant.V1)
