"""Storage boundary for calibration documents."""

from typing import Protocol, runtime_checkable

from momo.domain.calibration import CalibrationDocument
from momo.domain.enums import RobotVariant


@runtime_checkable
class CalibrationRepository(Protocol):
    def get_for_variant(self, variant: RobotVariant) -> CalibrationDocument | None: ...
