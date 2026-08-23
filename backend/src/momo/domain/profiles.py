"""Canonical Stage 1 product profiles.

The limits here are explicit Stage 1 placeholders, not migrated hardware or calibration
values. Keeping them in one factory prevents joint-set assumptions from leaking into
motion validation, API routes, or future adapters.
"""

from collections.abc import Mapping

from momo.domain.enums import (
    CalibrationOperatingMode,
    DomainUnit,
    JointType,
    ProfileVerificationStatus,
    RobotVariant,
)
from momo.domain.errors import ProfileResolutionError
from momo.domain.profile_fingerprint import profile_fingerprint
from momo.domain.robot import (
    VARIANT_PRODUCT_CONTRACTS,
    HardwareMappingValue,
    JointDefinition,
    RobotProfile,
)


def _mapping_placeholder() -> dict[str, HardwareMappingValue]:
    return {"status": "unverified-stage-1-placeholder"}


def _revolute(joint_id: str, servo_id: int) -> JointDefinition:
    return JointDefinition(
        joint_id=joint_id,
        joint_type=JointType.REVOLUTE,
        domain_unit=DomainUnit.DEG,
        minimum=-180.0,
        maximum=180.0,
        home=0.0,
        hardware_mapping_placeholder=_mapping_placeholder(),
        servo_id=servo_id,
        motor_degrees_per_domain_unit=1.0,
        raw_counts_per_motor_revolution=4096.0,
        operating_mode=CalibrationOperatingMode.MULTI_TURN,
        raw_bounds=(-30719, 30719),
        raw_reachable=False,
    )


def _prismatic(joint_id: str, servo_id: int) -> JointDefinition:
    return JointDefinition(
        joint_id=joint_id,
        joint_type=JointType.PRISMATIC,
        domain_unit=DomainUnit.MM,
        minimum=0.0,
        maximum=1000.0,
        home=0.0,
        hardware_mapping_placeholder=_mapping_placeholder(),
        servo_id=servo_id,
        # This is a synthetic characterization value for Dry Run only.  It is
        # deliberately not presented as a real hardware calibration.
        motor_degrees_per_domain_unit=28.8,
        raw_counts_per_motor_revolution=4096.0,
        operating_mode=CalibrationOperatingMode.MULTI_TURN,
        raw_bounds=(-30719, 30719),
        raw_reachable=False,
    )


def canonical_robot_profile(variant: RobotVariant) -> RobotProfile:
    """Return a fresh canonical Stage 1 profile for ``variant``.

    Returning a fresh value prevents accidental mutation of a nested list/dict from
    becoming process-global validation state.
    """

    contract = VARIANT_PRODUCT_CONTRACTS[variant]
    joints = list(contract.enabled_joints)
    definitions = [
        _prismatic(joint_id, index + 1)
        if joint_id == contract.linear_rail_joint
        else _revolute(joint_id, index + 1)
        for index, joint_id in enumerate(joints)
    ]
    return RobotProfile(
        variant=variant,
        display_name=f"MOMO {variant.value} (Stage 1 profile)",
        has_linear_rail=contract.has_linear_rail,
        enabled_joints=joints,
        joint_definitions=definitions,
        urdf_reference=None,
        tcp_link="tool0",
        template=True,
        verification_status=ProfileVerificationStatus.VERIFIED_FOR_DRY_RUN,
        source="momo-stage-2-example",
        source_revision="961d5d522ddc6205a3feb480630eb6bbc1ac652e",
        description="Synthetic Stage 2 profile; not verified for real hardware.",
    )


def profile_for_validation(
    variant: RobotVariant,
    context: object = None,
) -> RobotProfile | None:
    """Resolve only an explicitly supplied profile; never consult a global default."""

    if not isinstance(context, Mapping):
        return None

    has_direct = "robot_profile" in context
    has_registry = "robot_profiles" in context
    if has_direct and has_registry:
        raise ProfileResolutionError(
            "validation context must not contain both robot_profile and robot_profiles"
        )
    if has_direct:
        direct = context["robot_profile"]
        if not isinstance(direct, RobotProfile):
            raise ProfileResolutionError("robot_profile must be a validated RobotProfile")
        profile = direct
    elif has_registry:
        registry = context.get("robot_profiles")
        if not isinstance(registry, Mapping):
            raise ProfileResolutionError("robot_profiles must be a profile mapping")
        candidate = registry.get(variant, registry.get(variant.value))
        if not isinstance(candidate, RobotProfile):
            raise ProfileResolutionError(
                f"robot_profiles does not contain a validated {variant.value} profile"
            )
        profile = candidate
    else:
        return None

    if profile.variant is not variant:
        raise ProfileResolutionError(
            f"validation profile {profile.variant.value} does not match snapshot variant "
            f"{variant.value}"
        )
    return profile


__all__ = ["canonical_robot_profile", "profile_fingerprint", "profile_for_validation"]
