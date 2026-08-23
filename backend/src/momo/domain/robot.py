"""Robot identity, profile, and keyed joint-state domain models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StringConstraints,
    field_validator,
    model_validator,
)

from momo.domain.enums import DomainUnit, JointType, RobotVariant
from momo.domain.errors import JointStateValidationError
from momo.domain.immutable import FrozenDict, freeze_mapping, freeze_sequence

SCHEMA_VERSION: Final = "1.0.0"
JointId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^j[1-9][0-9]*$"),
]
FiniteNumber = Annotated[float, Field(allow_inf_nan=False)]
HardwareMappingValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class VariantProductContract:
    """The single authoritative joint-set contract for a product variant."""

    has_linear_rail: bool
    enabled_joints: tuple[str, ...]
    linear_rail_joint: str | None


VARIANT_PRODUCT_CONTRACTS: Final = FrozenDict(
    {
        RobotVariant.V1: VariantProductContract(
            has_linear_rail=False,
            enabled_joints=("j11", "j12", "j13", "j14", "j15"),
            linear_rail_joint=None,
        ),
        RobotVariant.V2: VariantProductContract(
            has_linear_rail=True,
            enabled_joints=("j10", "j11", "j12", "j13", "j14", "j15"),
            linear_rail_joint="j10",
        ),
    }
)


class RobotId(RootModel[UUID]):
    """Stable identity for one robot instance without assuming a global arm."""

    model_config = ConfigDict(frozen=True)


class JointDefinition(BaseModel):
    """One joint's canonical domain limits and eventual hardware mapping slot."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    joint_id: JointId
    joint_type: JointType
    domain_unit: DomainUnit
    minimum: FiniteNumber
    maximum: FiniteNumber
    home: FiniteNumber
    hardware_mapping_placeholder: dict[str, HardwareMappingValue] | None = None

    @field_validator("hardware_mapping_placeholder")
    @classmethod
    def freeze_hardware_mapping(
        cls, value: dict[str, HardwareMappingValue] | None
    ) -> dict[str, HardwareMappingValue] | None:
        return freeze_mapping(value) if value is not None else None

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        if self.minimum >= self.maximum:
            raise ValueError("minimum must be less than maximum")
        if not self.minimum <= self.home <= self.maximum:
            raise ValueError("home must be within the inclusive joint range")
        expected_unit = DomainUnit.DEG if self.joint_type is JointType.REVOLUTE else DomainUnit.MM
        if self.domain_unit is not expected_unit:
            raise ValueError(
                f"{self.joint_type.value} joints must use {expected_unit.value} domain units"
            )
        return self


class RobotProfile(BaseModel):
    """Versioned product profile with an explicit, ordered joint set."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    variant: RobotVariant
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    has_linear_rail: bool
    enabled_joints: Annotated[list[JointId], Field(min_length=1)]
    joint_definitions: Annotated[list[JointDefinition], Field(min_length=1)]
    urdf_reference: str | None
    tcp_link: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

    @field_validator("enabled_joints")
    @classmethod
    def freeze_enabled_joints(cls, value: list[JointId]) -> list[JointId]:
        return freeze_sequence(value)

    @field_validator("joint_definitions")
    @classmethod
    def freeze_joint_definitions(cls, value: list[JointDefinition]) -> list[JointDefinition]:
        return freeze_sequence(value)

    @field_validator("schema_version")
    @classmethod
    def require_supported_schema_version(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(f"unsupported robot profile schema_version: {value}")
        return value

    @model_validator(mode="after")
    def validate_profile_contract(self) -> Self:
        enabled = tuple(self.enabled_joints)
        if len(enabled) != len(set(enabled)):
            raise ValueError("enabled_joints contains duplicate joint IDs")

        definition_ids = tuple(item.joint_id for item in self.joint_definitions)
        if len(definition_ids) != len(set(definition_ids)):
            raise ValueError("joint_definitions contains duplicate joint IDs")
        if definition_ids != enabled:
            raise ValueError(
                "joint_definitions must contain each enabled joint exactly once "
                "and in the same order"
            )

        product_contract = VARIANT_PRODUCT_CONTRACTS[self.variant]
        if enabled != product_contract.enabled_joints:
            raise ValueError(
                f"{self.variant.value} enabled_joints must be "
                f"{list(product_contract.enabled_joints)}"
            )
        if self.has_linear_rail is not product_contract.has_linear_rail:
            raise ValueError(
                f"{self.variant.value} has_linear_rail must be {product_contract.has_linear_rail}"
            )

        for definition in self.joint_definitions:
            is_linear_rail = definition.joint_id == product_contract.linear_rail_joint
            expected_type = JointType.PRISMATIC if is_linear_rail else JointType.REVOLUTE
            expected_unit = DomainUnit.MM if is_linear_rail else DomainUnit.DEG
            if definition.joint_type is not expected_type:
                raise ValueError(
                    f"{self.variant.value} {definition.joint_id} joint_type must be "
                    f"{expected_type.value}"
                )
            if definition.domain_unit is not expected_unit:
                raise ValueError(
                    f"{self.variant.value} {definition.joint_id} domain_unit must be "
                    f"{expected_unit.value}"
                )
        return self

    @property
    def definitions_by_id(self) -> dict[str, JointDefinition]:
        return {definition.joint_id: definition for definition in self.joint_definitions}


class JointState(BaseModel):
    """Joint positions keyed by semantic joint ID, never by anonymous index.

    Positions are stored in each joint definition's ``domain_unit``. ``units`` may be
    supplied at an external boundary for an explicit unit check; when omitted, values
    are already asserted to be in the profile's canonical domain units.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    positions: dict[JointId, FiniteNumber]
    units: dict[JointId, DomainUnit] | None = None

    @field_validator("positions", mode="before")
    @classmethod
    def reject_boolean_positions(cls, value: object) -> object:
        if isinstance(value, Mapping):
            boolean_keys = [str(key) for key, item in value.items() if isinstance(item, bool)]
            if boolean_keys:
                raise ValueError(f"boolean joint positions are invalid: {sorted(boolean_keys)}")
        return value

    @field_validator("positions")
    @classmethod
    def freeze_positions(cls, value: dict[JointId, FiniteNumber]) -> dict[JointId, FiniteNumber]:
        return freeze_mapping(value)

    @field_validator("units")
    @classmethod
    def freeze_units(
        cls, value: dict[JointId, DomainUnit] | None
    ) -> dict[JointId, DomainUnit] | None:
        return freeze_mapping(value) if value is not None else None

    def validate_against(self, profile: RobotProfile) -> Self:
        """Validate membership, units, finiteness, and limits against ``profile``."""

        expected = set(profile.enabled_joints)
        actual = set(self.positions)
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        if missing:
            raise JointStateValidationError(f"missing enabled joints: {missing}")
        if unknown:
            raise JointStateValidationError(f"unknown joints: {unknown}")

        if self.units is not None:
            unit_ids = set(self.units)
            missing_units = sorted(expected - unit_ids)
            unknown_units = sorted(unit_ids - expected)
            if missing_units:
                raise JointStateValidationError(f"missing joint units: {missing_units}")
            if unknown_units:
                raise JointStateValidationError(f"unknown joint units: {unknown_units}")

        definitions = profile.definitions_by_id
        for joint_id in profile.enabled_joints:
            position = self.positions[joint_id]
            if not isfinite(position):
                raise JointStateValidationError(f"{joint_id} position must be finite")
            definition = definitions[joint_id]
            if self.units is not None and self.units[joint_id] is not definition.domain_unit:
                raise JointStateValidationError(
                    f"{joint_id} unit must be {definition.domain_unit.value}"
                )
            if not definition.minimum <= position <= definition.maximum:
                raise JointStateValidationError(
                    f"{joint_id} position {position} {definition.domain_unit.value} is outside "
                    f"[{definition.minimum}, {definition.maximum}]"
                )
        return self

    @classmethod
    def validate_for_profile(
        cls,
        value: Self | Mapping[str, object],
        profile: RobotProfile,
    ) -> Self:
        """Parse a state and immediately bind its validation to a profile."""

        state = value if isinstance(value, cls) else cls.model_validate(value)
        return state.validate_against(profile)
