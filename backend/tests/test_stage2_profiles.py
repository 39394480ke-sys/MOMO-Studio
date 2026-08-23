"""Formal Stage 2 profile repository and fingerprint behavior."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from momo.adapters.storage.profile_repository import FileProfileRepository
from momo.application.services.profile_service import ProfileService
from momo.domain.enums import (
    DomainUnit,
    HardwareAccessPolicy,
    JointType,
    ProfileVerificationStatus,
    RobotVariant,
)
from momo.domain.errors import ProfileResolutionError
from momo.domain.robot import RobotProfile
from momo.settings import repository_root


@pytest.fixture
def profiles() -> FileProfileRepository:
    return FileProfileRepository(repository_root() / "robot_profiles")


def test_committed_profiles_encode_the_two_product_variants(
    profiles: FileProfileRepository,
) -> None:
    v1 = profiles.get(RobotVariant.V1)
    v2 = profiles.get(RobotVariant.V2)
    assert list(v1.enabled_joints) == ["j11", "j12", "j13", "j14", "j15"]
    assert list(v2.enabled_joints) == ["j10", "j11", "j12", "j13", "j14", "j15"]
    assert v1.has_linear_rail is False
    assert v2.has_linear_rail is True
    assert v2.definitions_by_id["j10"].joint_type is JointType.PRISMATIC
    assert v2.definitions_by_id["j10"].domain_unit is DomainUnit.MM


def test_profile_rejects_missing_v2_rail_and_duplicate_servo(
    profiles: FileProfileRepository,
) -> None:
    data = profiles.get(RobotVariant.V2).model_dump(mode="json")
    data["enabled_joints"].pop(0)
    data["joint_definitions"].pop(0)
    with pytest.raises(ValidationError, match="V2 enabled_joints"):
        RobotProfile.model_validate(data)

    data = profiles.get(RobotVariant.V1).model_dump(mode="json")
    data["joint_definitions"][1]["servo_id"] = data["joint_definitions"][0]["servo_id"]
    with pytest.raises(ValidationError, match="duplicate servo IDs"):
        RobotProfile.model_validate(data)


def test_fingerprint_is_deterministic_and_ignores_ui_fields(
    profiles: FileProfileRepository,
) -> None:
    profile = profiles.get(RobotVariant.V2)
    assert (
        profile.fingerprint
        == RobotProfile.model_validate_json(profile.model_dump_json()).fingerprint
    )

    data = profile.model_dump(mode="json")
    data.update(display_name="Renamed", description="Different UI copy")
    assert RobotProfile.model_validate(data).fingerprint == profile.fingerprint
    data["joint_definitions"][0]["motor_degrees_per_domain_unit"] = 29.0
    assert RobotProfile.model_validate(data).fingerprint != profile.fingerprint


def test_template_profile_can_never_claim_real_verification(
    profiles: FileProfileRepository,
) -> None:
    data = profiles.get(RobotVariant.V2).model_dump(mode="json")
    data["verification_status"] = ProfileVerificationStatus.VERIFIED_FOR_REAL.value
    with pytest.raises(ValidationError, match="template profiles"):
        RobotProfile.model_validate(data)

    diagnostics = ProfileService(profiles).diagnostics(
        RobotVariant.V2,
        hardware_access_policy=HardwareAccessPolicy.DISABLED,
    )
    assert diagnostics.real_eligible is False
    assert any("template" in reason.lower() for reason in diagnostics.reasons)


def test_real_eligibility_requires_complete_reviewed_mapping(
    profiles: FileProfileRepository,
) -> None:
    data = profiles.get(RobotVariant.V2).model_dump(mode="json")
    data["template"] = False
    data["verification_status"] = ProfileVerificationStatus.VERIFIED_FOR_REAL.value
    data["joint_definitions"][0]["motor_degrees_per_domain_unit"] = None
    data["joint_definitions"][0]["raw_bounds"] = None
    data["joint_definitions"][0]["raw_reachable"] = False
    profile = RobotProfile.model_validate(data)

    class Repository:
        def get(self, variant: RobotVariant) -> RobotProfile:
            del variant
            return profile

    diagnostics = ProfileService(Repository()).diagnostics(
        RobotVariant.V2,
        hardware_access_policy=HardwareAccessPolicy.FULL,
    )
    assert diagnostics.real_eligible is False
    assert any("mapping is incomplete" in reason for reason in diagnostics.reasons)


def test_repository_fails_closed_for_malformed_or_unknown_profiles(tmp_path: Path) -> None:
    (tmp_path / "v1.example.yaml").write_text("variant: UNKNOWN\n", encoding="utf-8")
    repository = FileProfileRepository(tmp_path)
    with pytest.raises(ProfileResolutionError, match="invalid profile V1"):
        repository.get(RobotVariant.V1)
    with pytest.raises(ValueError):
        RobotVariant("V3")
