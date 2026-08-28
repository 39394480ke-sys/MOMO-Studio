"""Canonical TCP pose, reproducible snapshots, and named pose entities."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from math import hypot, isfinite
from typing import TYPE_CHECKING, Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from momo.domain.enums import DomainUnit, RobotVariant
from momo.domain.immutable import deep_freeze_json, freeze_sequence
from momo.domain.profiles import profile_for_validation
from momo.domain.robot import VARIANT_PRODUCT_CONTRACTS, JointId, JointState

if TYPE_CHECKING:
    from momo.domain.robot import RobotProfile

FiniteCoordinate = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(max_length=5000)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
POSE_SCHEMA_VERSION: Literal["2.0.0"] = "2.0.0"


def utc_now() -> datetime:
    return datetime.now(UTC)


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return value


def _require_finite_json(value: JsonValue, path: str = "hardware_snapshot") -> JsonValue:
    """Reject non-finite numbers recursively before they can serialize as JSON null."""

    if isinstance(value, float) and not isfinite(value):
        raise ValueError(f"{path} numeric values must be finite")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _require_finite_json(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            _require_finite_json(item, f"{path}.{key}")
    return value


def _require_bounded_json(
    value: JsonValue,
    path: str,
    *,
    maximum_depth: int = 8,
    maximum_nodes: int = 2048,
    maximum_bytes: int = 65536,
) -> JsonValue:
    nodes = 0

    def visit(item: JsonValue, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > maximum_nodes:
            raise ValueError(f"{path} contains too many values")
        if depth > maximum_depth:
            raise ValueError(f"{path} nesting is too deep")
        if isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
        elif isinstance(item, dict):
            for key, child in item.items():
                if len(key) > 200:
                    raise ValueError(f"{path} contains an oversized key")
                visit(child, depth + 1)

    visit(value, 0)
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"{path} exceeds its encoded size limit")
    return value


class Vector3(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    x: FiniteCoordinate
    y: FiniteCoordinate
    z: FiniteCoordinate


class QuaternionXYZW(BaseModel):
    """Finite, non-zero quaternion normalized into canonical storage form."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    x: FiniteCoordinate
    y: FiniteCoordinate
    z: FiniteCoordinate
    w: FiniteCoordinate

    @model_validator(mode="after")
    def normalize(self) -> Self:
        values = (self.x, self.y, self.z, self.w)
        if not all(isfinite(value) for value in values):
            raise ValueError("quaternion components must be finite")
        # ``hypot`` remains stable for very large finite components where a naïve
        # sum-of-squares can overflow before normalization.
        norm = hypot(*values)
        if norm < 1e-12:
            raise ValueError("quaternion norm must be non-zero")
        # Avoid introducing round-trip drift for an already normalized value.
        if abs(norm - 1.0) <= 1e-12:
            return self
        # A top-level model validator must return ``self`` when construction uses
        # ``__init__``. ``object.__setattr__`` is confined to this canonicalization
        # step; the completed value remains frozen to callers.
        object.__setattr__(self, "x", self.x / norm)
        object.__setattr__(self, "y", self.y / norm)
        object.__setattr__(self, "z", self.z / norm)
        object.__setattr__(self, "w", self.w / norm)
        return self


class TcpPose(BaseModel):
    """Canonical TCP pose: millimetres and a normalized XYZW quaternion."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    frame: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = "base"
    position_mm: Vector3
    orientation_quaternion_xyzw: QuaternionXYZW


class SnapshotJointState(JointState):
    """Persisted snapshot state with explicit, non-null domain units."""

    units: dict[JointId, DomainUnit]


class PoseSnapshot(BaseModel):
    """An embedded, reproducible capture independent of named Pose files."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    robot_variant: RobotVariant
    joint_state: SnapshotJointState
    tcp_pose: TcpPose
    profile_fingerprint: Fingerprint
    kinematics_fingerprint: Fingerprint
    # Live captures always record a sequence. Explicit legacy imports may use
    # ``null`` when the source format contains no coherent observation counter.
    state_sequence: Annotated[int, Field(strict=True, ge=0)] | None
    hardware_snapshot: dict[str, JsonValue] | None = None
    calibration_fingerprint: Fingerprint | None = None
    captured_at: datetime = Field(default_factory=utc_now)

    @field_validator("joint_state", mode="before")
    @classmethod
    def detach_and_require_snapshot_joint_state(cls, value: object) -> object:
        if isinstance(value, JointState):
            return value.model_dump(mode="python", round_trip=True)
        return value

    @field_validator("captured_at")
    @classmethod
    def captured_at_must_be_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "captured_at")

    @field_validator("hardware_snapshot")
    @classmethod
    def hardware_snapshot_numbers_must_be_finite(
        cls, value: dict[str, JsonValue] | None
    ) -> dict[str, JsonValue] | None:
        if value is not None:
            _require_finite_json(value)
            _require_bounded_json(value, "hardware_snapshot")
            frozen = deep_freeze_json(value)
            if not isinstance(frozen, dict):  # pragma: no cover - field type guarantees this
                raise TypeError("hardware_snapshot must be an object")
            return frozen
        return None

    @model_validator(mode="after")
    def validate_joint_state_for_snapshot(self, info: ValidationInfo) -> Self:
        profile = profile_for_validation(self.robot_variant, info.context)
        if profile is None:
            try:
                self.joint_state.validate_structure_for_variant(self.robot_variant)
            except ValueError as error:
                raise ValueError(f"snapshot joint state is invalid: {error}") from error
            contract = VARIANT_PRODUCT_CONTRACTS[self.robot_variant]
            expected_units = {
                joint_id: (
                    DomainUnit.MM if joint_id == contract.linear_rail_joint else DomainUnit.DEG
                )
                for joint_id in contract.enabled_joints
            }
            if dict(self.joint_state.units) != expected_units:
                raise ValueError("snapshot joint_state units must exactly match the robot variant")
            return self
        try:
            self.joint_state.validate_against(profile)
        except ValueError as error:
            raise ValueError(f"snapshot joint state is invalid: {error}") from error
        return self

    def validate_against(self, profile: RobotProfile) -> Self:
        """Bind environment-dependent joint validation to an explicit profile."""

        if profile.variant is not self.robot_variant:
            raise ValueError(
                f"profile {profile.variant.value} does not match snapshot variant "
                f"{self.robot_variant.value}"
            )
        self.joint_state.validate_against(profile)
        return self


class Pose(BaseModel):
    """A named, versioned entity whose UUID—not its mutable name—is its identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    schema_version: Literal["2.0.0"] = POSE_SCHEMA_VERSION
    id: UUID = Field(default_factory=uuid4)
    name: Name
    description: Description = ""
    tags: Annotated[list[Tag], Field(max_length=32)] = Field(default_factory=list)
    snapshot: PoseSnapshot
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    revision: Annotated[int, Field(strict=True, ge=1)] = 1

    @field_validator("schema_version")
    @classmethod
    def require_supported_schema_version(cls, value: str) -> str:
        if value != POSE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported pose schema_version: {value}; explicit migration is required"
            )
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_must_be_aware(cls, value: datetime, info: object) -> datetime:
        field_name = getattr(info, "field_name", "timestamp")
        return _require_aware(value, field_name)

    @field_validator("tags")
    @classmethod
    def tags_must_be_unique(cls, value: list[str]) -> list[str]:
        normalized = [tag.strip() for tag in value]
        if any(not tag for tag in normalized):
            raise ValueError("tags must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("tags must be unique")
        return freeze_sequence(normalized)

    @model_validator(mode="after")
    def updated_at_cannot_precede_created_at(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        return self
