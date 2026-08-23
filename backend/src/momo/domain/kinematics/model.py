"""Versioned, mesh-free serial-chain kinematics model."""

from __future__ import annotations

import hashlib
import json
from math import hypot, isfinite
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from momo.domain.enums import JointType, KinematicsVerificationStatus, RobotVariant
from momo.domain.immutable import freeze_sequence
from momo.domain.robot import VARIANT_PRODUCT_CONTRACTS, JointId, RobotProfile

KINEMATICS_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
Finite = Annotated[float, Field(allow_inf_nan=False)]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class KinematicJoint(BaseModel):
    """One ordered joint in a serial chain, expressed entirely in SI units."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    joint_id: JointId
    joint_type: JointType
    axis: tuple[Finite, Finite, Finite]
    origin_translation_m: tuple[Finite, Finite, Finite]
    origin_orientation_quaternion_xyzw: tuple[Finite, Finite, Finite, Finite]
    minimum_si: Finite
    maximum_si: Finite

    @model_validator(mode="after")
    def validate_joint(self) -> Self:
        if self.minimum_si >= self.maximum_si:
            raise ValueError("minimum_si must be less than maximum_si")
        axis_norm = hypot(*self.axis)
        if not isfinite(axis_norm) or axis_norm < 1e-12:
            raise ValueError("joint axis must be finite and non-zero")
        quaternion_norm = hypot(*self.origin_orientation_quaternion_xyzw)
        if not isfinite(quaternion_norm) or quaternion_norm < 1e-12:
            raise ValueError("joint origin quaternion must be finite and non-zero")
        if abs(axis_norm - 1.0) > 1e-9:
            object.__setattr__(self, "axis", tuple(value / axis_norm for value in self.axis))
        if abs(quaternion_norm - 1.0) > 1e-9:
            object.__setattr__(
                self,
                "origin_orientation_quaternion_xyzw",
                tuple(value / quaternion_norm for value in self.origin_orientation_quaternion_xyzw),
            )
        return self


class KinematicsModel(BaseModel):
    """Reviewed serial-chain data; visual metadata never changes its fingerprint."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    schema_version: Literal["1.0.0"] = KINEMATICS_SCHEMA_VERSION
    variant: RobotVariant
    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    source_revision: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    verification_status: KinematicsVerificationStatus
    base_frame: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    tcp_frame: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    joints: Annotated[list[KinematicJoint], Field(min_length=1)]
    display_name: str = ""
    description: str = ""
    kinematics_fingerprint: Fingerprint

    @model_validator(mode="after")
    def validate_model(self) -> Self:
        object.__setattr__(self, "joints", freeze_sequence(self.joints))
        joint_ids = tuple(joint.joint_id for joint in self.joints)
        if len(joint_ids) != len(set(joint_ids)):
            raise ValueError("kinematics joints must be unique")
        expected = VARIANT_PRODUCT_CONTRACTS[self.variant].enabled_joints
        if joint_ids != expected:
            raise ValueError(f"{self.variant.value} kinematics joints must be {list(expected)}")
        linear_joint = VARIANT_PRODUCT_CONTRACTS[self.variant].linear_rail_joint
        for joint in self.joints:
            expected_type = (
                JointType.PRISMATIC if joint.joint_id == linear_joint else JointType.REVOLUTE
            )
            if joint.joint_type is not expected_type:
                raise ValueError(
                    f"{joint.joint_id} must be {expected_type.value} for {self.variant.value}"
                )
        computed_fingerprint = self.fingerprint
        if self.kinematics_fingerprint != computed_fingerprint:
            raise ValueError("kinematics_fingerprint does not match kinematics geometry")
        return self

    @property
    def fingerprint(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "variant": self.variant.value,
            "base_frame": self.base_frame,
            "tcp_frame": self.tcp_frame,
            "joints": [
                {
                    "joint_id": joint.joint_id,
                    "joint_type": joint.joint_type.value,
                    "axis": list(joint.axis),
                    "origin_translation_m": list(joint.origin_translation_m),
                    "origin_orientation_quaternion_xyzw": list(
                        joint.origin_orientation_quaternion_xyzw
                    ),
                    "minimum_si": joint.minimum_si,
                    "maximum_si": joint.maximum_si,
                }
                for joint in self.joints
            ],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def validate_against_profile(self, profile: RobotProfile) -> Self:
        if profile.variant is not self.variant:
            raise ValueError("kinematics model variant does not match profile")
        if tuple(profile.enabled_joints) != tuple(joint.joint_id for joint in self.joints):
            raise ValueError("kinematics joint set does not match profile enabled_joints")
        definitions = profile.definitions_by_id
        for joint in self.joints:
            if definitions[joint.joint_id].joint_type is not joint.joint_type:
                raise ValueError(f"{joint.joint_id} type does not match profile")
        return self
