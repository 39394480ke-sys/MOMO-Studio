"""Configuration loading with independent robot-hardware and camera safety gates."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Self
from unicodedata import normalize

import yaml
from pydantic import Field, StringConstraints, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from momo import __version__
from momo.domain.enums import ControlMode, HardwareAccessPolicy, RobotVariant
from momo.domain.vision import CameraAccessPolicy

_STORAGE_DIRECTORY_FIELDS = (
    "runtime_state_directory",
    "profile_directory",
    "calibration_directory",
    "kinematics_model_directory",
    "pose_directory",
    "motion_library_directory",
    "motion_draft_directory",
)


def _portable_path_key(path: Path) -> tuple[str, ...]:
    """Conservatively identify aliases on the supported macOS filesystem.

    APFS is commonly case-insensitive and Unicode-normalizing. Rejecting those
    aliases on every platform is safer than allowing two repositories to
    quarantine each other's documents after their directories are created.
    """

    return tuple(normalize("NFC", part).casefold() for part in path.parts)


def _storage_paths_overlap(left: Path, right: Path) -> bool:
    left_key = _portable_path_key(left)
    right_key = _portable_path_key(right)
    portable_overlap = (
        left_key == right_key
        or left_key == right_key[: len(left_key)]
        or right_key == left_key[: len(right_key)]
    )
    if portable_overlap:
        return True
    try:
        return left.exists() and right.exists() and left.samefile(right)
    except OSError:
        return False


class Settings(BaseSettings):
    """Runtime settings.

    Environment variables use the ``MOMO_`` prefix and outrank YAML/init values.
    Stage 3 rejects both real motion and every non-disabled hardware access policy.
    """

    model_config = SettingsConfigDict(
        env_prefix="MOMO_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    product_name: str = "MOMO Studio"
    version: str = __version__
    control_mode: ControlMode = ControlMode.DRY_RUN
    real_motion_enabled: bool = False
    serial_port: str = ""
    active_robot_variant: RobotVariant = RobotVariant.V2
    hardware_access_policy: HardwareAccessPolicy = HardwareAccessPolicy.DISABLED
    camera_access_policy: CameraAccessPolicy = CameraAccessPolicy.SYNTHETIC_ONLY
    live_camera_device_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=128),
    ] = ""
    runtime_state_directory: str = "data/runtime/robots"
    profile_directory: str = "robot_profiles"
    calibration_directory: str = "calibration/examples"
    kinematics_model_directory: str = "kinematics_models"
    pose_directory: str = "data/poses"
    motion_library_directory: str = "data/motions"
    motion_draft_directory: str = "data/drafts"
    motion_update_hz: float = Field(default=25.0, ge=20, le=100)
    jog_lease_ttl_ms: int = Field(default=400, ge=250, le=500)
    robot_state_freshness_limit_s: float = Field(default=5.0, gt=0, le=60)
    vision_source_id: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        ),
    ] = "synthetic-stage7"
    vision_frame_width_px: int = Field(default=640, strict=True, ge=64, le=1280)
    vision_frame_height_px: int = Field(default=360, strict=True, ge=64, le=720)
    vision_max_fps: float = Field(default=12.0, gt=0.0, le=30.0)
    vision_max_stream_clients: int = Field(default=4, strict=True, ge=1, le=16)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del cls, settings_cls, dotenv_settings
        # Earlier sources have higher priority in pydantic-settings.
        return env_settings, init_settings, file_secret_settings

    @model_validator(mode="before")
    @classmethod
    def accept_hardware_access_compatibility_key(cls, value: object) -> object:
        if isinstance(value, dict) and "hardware_access_policy" not in value:
            value = dict(value)
            if "hardware_access" in value:
                value["hardware_access_policy"] = value.pop("hardware_access")
        return value

    @field_validator("control_mode", mode="before")
    @classmethod
    def normalize_control_mode(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().replace("-", "_").replace(" ", "_").upper()
        return value

    @field_validator("active_robot_variant", mode="before")
    @classmethod
    def normalize_variant(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("hardware_access_policy", mode="before")
    @classmethod
    def normalize_hardware_access(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().replace("-", "_").replace(" ", "_").upper()
        return value

    @field_validator("camera_access_policy", mode="before")
    @classmethod
    def normalize_camera_access(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().replace("-", "_").replace(" ", "_").upper()
        return value

    @field_validator("real_motion_enabled")
    @classmethod
    def enforce_stage_three_safety_lock(cls, value: bool) -> bool:
        if value:
            raise ValueError("real_motion_enabled is locked to false throughout Stage 3")
        return False

    @model_validator(mode="after")
    def enforce_stage_three_capability_gate(self) -> Self:
        if self.control_mode is not ControlMode.DRY_RUN:
            raise ValueError("Stage 3 requires control_mode=DRY_RUN")
        if self.hardware_access_policy is not HardwareAccessPolicy.DISABLED:
            raise ValueError(
                "Stage 3 requires hardware_access=DISABLED; no hardware adapter is available"
            )
        if (
            self.camera_access_policy is CameraAccessPolicy.LIVE_CAMERA_ALLOWED
            and not self.live_camera_device_id
        ):
            raise ValueError(
                "LIVE_CAMERA_ALLOWED requires an explicit non-empty live_camera_device_id"
            )
        if self.vision_frame_width_px * self.vision_frame_height_px > 1280 * 720:
            raise ValueError("Synthetic vision resolution must not exceed 1280x720 pixels")
        root = repository_root()
        resolved = {
            field: (
                path.resolve()
                if (path := Path(getattr(self, field))).is_absolute()
                else (root / path).resolve()
            )
            for field in _STORAGE_DIRECTORY_FIELDS
        }
        fields = tuple(resolved)
        for index, left_name in enumerate(fields):
            left = resolved[left_name]
            for right_name in fields[index + 1 :]:
                right = resolved[right_name]
                if _storage_paths_overlap(left, right):
                    raise ValueError(
                        "Configured storage directories must not overlap: "
                        f"{left_name} and {right_name}"
                    )
        return self

    @property
    def hardware_access(self) -> HardwareAccessPolicy:
        """Backwards-compatible name used by internal callers."""

        return self.hardware_access_policy


def repository_root() -> Path:
    """Resolve the source checkout root without depending on the process CWD."""

    # backend/src/momo/settings.py -> backend/src/momo -> backend/src -> backend -> root
    return Path(__file__).resolve().parents[3]


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as stream:
        raw = yaml.safe_load(stream)
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"settings YAML must contain a top-level mapping: {path}")
    return {str(key): value for key, value in raw.items()}


def load_settings(
    default_config_path: Path | None = None,
    local_config_path: Path | None = None,
) -> Settings:
    """Load default YAML, then optional local YAML, then ``MOMO_*`` environment values.

    A missing YAML file is allowed for installed packages. The environment remains the
    final authority except that the Stage 3 safety gates can never be overridden.
    """

    root = repository_root()
    default_path = default_config_path or root / "config" / "default.yaml"
    values = _read_yaml(default_path)
    local_values: dict[str, Any] = {}
    # Ignored/local configuration is capability-bearing and must never be inspected
    # implicitly. A caller must provide the exact path deliberately.
    if local_config_path is not None:
        local_values = _read_yaml(local_config_path)
        values.update(local_values)
    settings = Settings.model_validate(values)
    if settings.camera_access_policy is CameraAccessPolicy.LIVE_CAMERA_ALLOWED:
        local_policy = local_values.get("camera_access_policy")
        normalized_policy = (
            local_policy.strip().replace("-", "_").replace(" ", "_").upper()
            if isinstance(local_policy, str)
            else local_policy
        )
        local_device = local_values.get("live_camera_device_id")
        if (
            normalized_policy != CameraAccessPolicy.LIVE_CAMERA_ALLOWED.value
            or not isinstance(local_device, str)
            or local_device.strip() != settings.live_camera_device_id
        ):
            raise ValueError(
                "Live camera capability requires camera policy and device identifier "
                "from the explicitly supplied local config"
            )
    return settings
