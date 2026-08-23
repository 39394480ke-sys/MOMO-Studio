"""YAML profile repository restricted to the reviewed example directory."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import yaml

from momo.domain.enums import RobotVariant
from momo.domain.errors import ProfileResolutionError
from momo.domain.profiles import canonical_robot_profile
from momo.domain.robot import RobotProfile


class FileProfileRepository:
    """Load V1/V2 profile documents without accepting arbitrary client paths."""

    _filenames: ClassVar[dict[RobotVariant, str]] = {
        RobotVariant.V1: "v1.example.yaml",
        RobotVariant.V2: "v2.example.yaml",
    }

    def __init__(self, directory: Path, *, allow_fallback: bool = False) -> None:
        self.directory = directory.resolve()
        self.allow_fallback = allow_fallback
        self._cache: dict[RobotVariant, RobotProfile] = {}

    def get(self, variant: RobotVariant) -> RobotProfile:
        if variant in self._cache:
            return self._cache[variant]
        path = self.directory / self._filenames[variant]
        try:
            raw = self._read_yaml(path)
            profile = RobotProfile.model_validate(raw)
        except (OSError, ValueError, yaml.YAMLError) as error:
            if not self.allow_fallback:
                raise ProfileResolutionError(f"invalid profile {variant.value}: {error}") from error
            profile = canonical_robot_profile(variant)
        self._cache[variant] = profile
        return profile

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise FileNotFoundError(path)
        with path.open(encoding="utf-8") as stream:
            value = yaml.safe_load(stream)
        if not isinstance(value, dict):
            raise ValueError("profile YAML must contain an object")
        return value

    def clear_cache(self) -> None:
        self._cache.clear()
