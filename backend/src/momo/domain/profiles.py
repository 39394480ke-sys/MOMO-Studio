"""Canonical Stage 1 product profiles.

The limits here are explicit Stage 1 placeholders, not migrated hardware or calibration
values. Keeping them in one factory prevents joint-set assumptions from leaking into
motion validation, API routes, or future adapters.
"""

from collections.abc import Mapping

from momo.domain.enums import DomainUnit, JointType, RobotVariant
from momo.domain.errors import ProfileResolutionError
from momo.domain.robot import (
    VARIANT_PRODUCT_CONTRACTS,
    HardwareMappingValue,
    JointDefinition,
    RobotProfile,
)


def _mapping_placeholder() -> dict[str, HardwareMappingValue]:
    return {"status": "unverified-stage-1-placeholder"}


def _revolute(joint_id: str) -> JointDefinition:
    return JointDefinition(
        joint_id=joint_id,
        joint_type=JointType.REVOLUTE,
        domain_unit=DomainUnit.DEG,
        minimum=-180.0,
        maximum=180.0,
        home=0.0,
        hardware_mapping_placeholder=_mapping_placeholder(),
    )


def _prismatic(joint_id: str) -> JointDefinition:
    return JointDefinition(
        joint_id=joint_id,
        joint_type=JointType.PRISMATIC,
        domain_unit=DomainUnit.MM,
        minimum=0.0,
        maximum=1000.0,
        home=0.0,
        hardware_mapping_placeholder=_mapping_placeholder(),
    )


def canonical_robot_profile(variant: RobotVariant) -> RobotProfile:
    """Return a fresh canonical Stage 1 profile for ``variant``.

    Returning a fresh value prevents accidental mutation of a nested list/dict from
    becoming process-global validation state.
    """

    contract = VARIANT_PRODUCT_CONTRACTS[variant]
    joints = list(contract.enabled_joints)
    definitions = [
        _prismatic(joint_id) if joint_id == contract.linear_rail_joint else _revolute(joint_id)
        for joint_id in joints
    ]
    return RobotProfile(
        variant=variant,
        display_name=f"MOMO {variant.value} (Stage 1 profile)",
        has_linear_rail=contract.has_linear_rail,
        enabled_joints=joints,
        joint_definitions=definitions,
        urdf_reference=None,
        tcp_link="tool0",
    )


def profile_for_validation(
    variant: RobotVariant,
    context: object = None,
) -> RobotProfile:
    """Resolve a supplied validation profile, falling back to the product profile."""

    if not isinstance(context, Mapping):
        return canonical_robot_profile(variant)

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
        return canonical_robot_profile(variant)

    if profile.variant is not variant:
        raise ProfileResolutionError(
            f"validation profile {profile.variant.value} does not match snapshot variant "
            f"{variant.value}"
        )
    return profile
