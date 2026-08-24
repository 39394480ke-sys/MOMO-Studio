"""Configuration loading with independent robot-hardware and camera safety gates."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from unicodedata import normalize
from urllib.parse import urlsplit

import yaml
from pydantic import Field, SecretStr, StringConstraints, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from momo import __version__
from momo.domain.enums import ControlMode, HardwareAccessPolicy, RobotVariant
from momo.domain.security import is_loopback_host, normalize_origin
from momo.domain.vision import CameraAccessPolicy

_STORAGE_DIRECTORY_FIELDS = (
    "runtime_state_directory",
    "profile_directory",
    "calibration_directory",
    "real_calibration_directory",
    "field_acceptance_directory",
    "kinematics_model_directory",
    "pose_directory",
    "motion_library_directory",
    "motion_draft_directory",
    "backup_restore_journal_directory",
    "audit_directory",
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
    Stage 8 accepts capability-bearing values for readiness evaluation, but the
    composition root remains deny-by-default and no single setting can construct a
    hardware adapter.
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
    serial_port: Annotated[str, StringConstraints(strip_whitespace=True, max_length=256)] = ""
    active_robot_variant: RobotVariant = RobotVariant.V2
    hardware_access_policy: HardwareAccessPolicy = HardwareAccessPolicy.DISABLED
    hardware_startup_enabled: bool = False
    hardware_local_config_enabled: bool = False
    servo_ids: tuple[int, ...] = ()
    servo_protocol: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=32, pattern=r"^[A-Za-z0-9._-]*$"),
    ] = ""
    field_acceptance_status: Literal["PENDING", "PASSED"] = "PENDING"
    operator_session_ttl_s: int = Field(default=300, strict=True, ge=30, le=900)
    camera_access_policy: CameraAccessPolicy = CameraAccessPolicy.SYNTHETIC_ONLY
    live_camera_device_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=128),
    ] = ""
    runtime_state_directory: str = "data/runtime/robots"
    profile_directory: str = "robot_profiles"
    calibration_directory: str = "calibration/examples"
    real_calibration_directory: str = "data/calibration"
    field_acceptance_directory: str = "data/field-acceptance"
    field_acceptance_checklist_version: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ] = "1"
    kinematics_model_directory: str = "kinematics_models"
    pose_directory: str = "data/poses"
    motion_library_directory: str = "data/motions"
    motion_draft_directory: str = "data/drafts"
    backup_restore_journal_directory: str = "data/restore"
    audit_directory: str = "data/audit"
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
    server_host: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = (
        "127.0.0.1"
    )
    server_port: int = Field(default=8000, strict=True, ge=1024, le=65535)
    lan_enabled: bool = False
    lan_auth_token: SecretStr = Field(default_factory=lambda: SecretStr(""), repr=False)
    local_allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    )
    lan_allowed_origins: tuple[str, ...] = ()
    api_body_max_bytes: int = Field(
        default=32 * 1024 * 1024,
        strict=True,
        ge=1024,
        le=32 * 1024 * 1024,
    )
    control_rate_limit_per_minute: int = Field(default=120, strict=True, ge=1, le=600)
    serve_frontend_static: bool = False
    frontend_dist_directory: str = "frontend/dist"

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

    @field_validator("servo_ids", mode="before")
    @classmethod
    def normalize_servo_ids(cls, value: object) -> object:
        if value is None or value == "":
            return ()
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("servo_ids")
    @classmethod
    def validate_servo_ids(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if len(value) > 32:
            raise ValueError("servo_ids accepts at most 32 explicit IDs")
        if any(isinstance(item, bool) or item < 1 or item > 253 for item in value):
            raise ValueError("servo_ids must contain integers from 1 to 253")
        if len(set(value)) != len(value):
            raise ValueError("servo_ids must be unique")
        return value

    @field_validator("local_allowed_origins", "lan_allowed_origins", mode="before")
    @classmethod
    def normalize_origins(cls, value: object) -> object:
        if value is None or value == "":
            return ()
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_release_candidate_settings(self) -> Self:
        if (
            self.camera_access_policy is CameraAccessPolicy.LIVE_CAMERA_ALLOWED
            and not self.live_camera_device_id
        ):
            raise ValueError(
                "LIVE_CAMERA_ALLOWED requires an explicit non-empty live_camera_device_id"
            )
        if self.vision_frame_width_px * self.vision_frame_height_px > 1280 * 720:
            raise ValueError("Synthetic vision resolution must not exceed 1280x720 pixels")
        if self.lan_enabled:
            token = self.lan_auth_token.get_secret_value()
            if len(token) < 32:
                raise ValueError("LAN mode requires a strong token of at least 32 characters")
            if not self.lan_allowed_origins:
                raise ValueError("LAN mode requires at least one strict allowed Origin")
            if any(
                origin == "*" or "*" in origin or not origin.startswith(("http://", "https://"))
                for origin in self.lan_allowed_origins
            ):
                raise ValueError("LAN Origins must be explicit HTTP(S) origins without wildcards")
        elif self.server_host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("A non-loopback server_host requires explicit LAN mode")
        if not self.local_allowed_origins or any(
            not is_loopback_host(urlsplit(normalize_origin(origin)).hostname or "")
            for origin in self.local_allowed_origins
        ):
            raise ValueError("Local Origins must be explicit loopback HTTP origins")
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
        if self.serve_frontend_static:
            frontend_path = Path(self.frontend_dist_directory)
            frontend = (
                frontend_path.resolve()
                if frontend_path.is_absolute()
                else (root / frontend_path).resolve()
            )
            for storage_name, storage in resolved.items():
                if _storage_paths_overlap(frontend, storage):
                    raise ValueError(
                        "frontend_dist_directory must not overlap a private storage "
                        f"directory: {storage_name}"
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
    if settings.hardware_local_config_enabled:
        local_ids = local_values.get("servo_ids")
        if isinstance(local_ids, list):
            local_ids = tuple(local_ids)
        if (
            local_values.get("hardware_local_config_enabled") is not True
            or local_values.get("serial_port") != settings.serial_port
            or local_ids != settings.servo_ids
            or local_values.get("servo_protocol") != settings.servo_protocol
        ):
            raise ValueError(
                "Hardware local authorization requires the exact device, explicit IDs, "
                "and protocol in the explicitly supplied local config"
            )
    if settings.lan_enabled and local_values.get("lan_enabled") is not True:
        raise ValueError("LAN mode must be explicitly enabled by the supplied local config")
    return settings
