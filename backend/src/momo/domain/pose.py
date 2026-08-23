"""Canonical TCP pose, reproducible snapshots, and named pose entities."""

from __future__ import annotations

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

from momo.domain.enums import RobotVariant
from momo.domain.immutable import deep_freeze_json, freeze_sequence
from momo.domain.profiles import profile_for_validation
from momo.domain.robot import SCHEMA_VERSION, JointState

if TYPE_CHECKING:
    from momo.domain.robot import RobotProfile

FiniteCoordinate = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


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


class PoseSnapshot(BaseModel):
    """An embedded, reproducible capture independent of named Pose files."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    robot_variant: RobotVariant
    joint_state: JointState
    tcp_pose: TcpPose
    hardware_snapshot: dict[str, JsonValue] | None = None
    calibration_fingerprint: str | None = None
    captured_at: datetime = Field(default_factory=utc_now)

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

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    id: UUID = Field(default_factory=uuid4)
    name: Name
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    snapshot: PoseSnapshot
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    revision: Annotated[int, Field(ge=1)] = 1

    @field_validator("schema_version")
    @classmethod
    def require_supported_schema_version(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(f"unsupported pose schema_version: {value}")
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
