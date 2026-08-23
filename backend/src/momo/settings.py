"""Stage 1 configuration loading with an enforced real-motion safety lock."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from momo import __version__
from momo.domain.enums import ControlMode, RobotVariant


class Settings(BaseSettings):
    """Runtime settings.

    Environment variables use the ``MOMO_`` prefix and outrank YAML/init values.
    Stage 1 deliberately makes ``real_motion_enabled=true`` a configuration error.
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

    @field_validator("real_motion_enabled")
    @classmethod
    def enforce_stage_one_safety_lock(cls, value: bool) -> bool:
        if value:
            raise ValueError("real_motion_enabled is locked to false throughout Stage 1")
        return False


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
    final authority except that the Stage 1 real-motion lock can never be overridden.
    """

    root = repository_root()
    default_path = default_config_path or root / "config" / "default.yaml"
    local_path = local_config_path or root / "config" / "local.yaml"
    values = _read_yaml(default_path)
    values.update(_read_yaml(local_path))
    return Settings.model_validate(values)
