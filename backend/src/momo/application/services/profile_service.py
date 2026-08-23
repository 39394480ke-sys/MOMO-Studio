"""Profile loading and compatibility diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

from momo.domain.enums import HardwareAccessPolicy, ProfileVerificationStatus, RobotVariant
from momo.domain.errors import ProfileInvalidError
from momo.domain.robot import RobotProfile
from momo.ports.profile_repository import ProfileRepository


@dataclass(frozen=True, slots=True)
class ProfileDiagnostics:
    profile: RobotProfile
    fingerprint: str
    real_eligible: bool
    reasons: tuple[str, ...]


class ProfileService:
    def __init__(self, repository: ProfileRepository) -> None:
        self.repository = repository

    def get_profile(self, variant: RobotVariant) -> RobotProfile:
        try:
            profile = self.repository.get(variant)
            # Re-validate the returned value to fail closed for custom repositories.
            return RobotProfile.model_validate(profile.model_dump(mode="python"))
        except Exception as error:
            if isinstance(error, ProfileInvalidError):
                raise
            raise ProfileInvalidError(f"profile {variant.value} is invalid") from error

    def diagnostics(
        self,
        variant: RobotVariant,
        *,
        hardware_access_policy: HardwareAccessPolicy = HardwareAccessPolicy.DISABLED,
    ) -> ProfileDiagnostics:
        profile = self.get_profile(variant)
        reasons: list[str] = []
        if profile.template:
            reasons.append("Example/template profiles cannot authorize real hardware")
        if profile.verification_status is not ProfileVerificationStatus.VERIFIED_FOR_REAL:
            reasons.append("Profile is not verified for real hardware")
        incomplete_mapping = [
            definition.joint_id
            for definition in profile.joint_definitions
            if definition.motor_degrees_per_domain_unit is None
            or definition.raw_bounds is None
            or not definition.raw_reachable
        ]
        if incomplete_mapping:
            reasons.append(
                "Profile mapping is incomplete or not raw-reachability verified for: "
                + ", ".join(incomplete_mapping)
            )
        if hardware_access_policy is not HardwareAccessPolicy.FULL:
            reasons.append("Hardware access policy is not FULL")
        return ProfileDiagnostics(
            profile=profile,
            fingerprint=profile.fingerprint,
            real_eligible=not reasons,
            reasons=tuple(reasons),
        )
