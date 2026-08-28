"""Fixed-name YAML loader for reviewed V1/V2 provisional models."""

from pathlib import Path
from typing import Any, ClassVar

import yaml

from momo.domain.enums import RobotVariant
from momo.domain.kinematics.model import KinematicsModel


class FileKinematicsModelRepository:
    _filenames: ClassVar[dict[RobotVariant, str]] = {
        RobotVariant.V1: "v1.provisional.yaml",
        RobotVariant.V2: "v2.provisional.yaml",
    }

    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self._cache: dict[RobotVariant, KinematicsModel] = {}

    def get(self, variant: RobotVariant) -> KinematicsModel:
        cached = self._cache.get(variant)
        if cached is not None:
            return cached
        filename = self._filenames[variant]
        candidate = (self.directory / filename).resolve()
        if candidate.parent != self.directory:
            raise ValueError("kinematics model path escapes configured directory")
        with candidate.open(encoding="utf-8") as stream:
            raw: Any = yaml.safe_load(stream)
        if not isinstance(raw, dict):
            raise ValueError(f"kinematics model must be an object: {filename}")
        model = KinematicsModel.model_validate(raw)
        if model.variant is not variant:
            raise ValueError(f"kinematics model {filename} has the wrong variant")
        self._cache[variant] = model
        return model

    def clear_cache(self) -> None:
        self._cache.clear()
