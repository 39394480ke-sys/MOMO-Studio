"""Read-only JSON calibration repository for Stage 2 diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

from pydantic import ValidationError

from momo.domain.calibration import CalibrationDocument
from momo.domain.enums import RobotVariant
from momo.domain.errors import CalibrationInvalidError


class FileCalibrationRepository:
    _filenames: ClassVar[dict[RobotVariant, str]] = {
        RobotVariant.V1: "v1.example.json",
        RobotVariant.V2: "v2.example.json",
    }

    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()

    def get_for_variant(self, variant: RobotVariant) -> CalibrationDocument | None:
        path = self.directory / self._filenames[variant]
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return CalibrationDocument.model_validate(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
            raise CalibrationInvalidError(
                f"calibration document for {variant.value} is invalid"
            ) from error
