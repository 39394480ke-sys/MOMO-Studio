"""Composition root for one FastAPI application instance."""

from __future__ import annotations

from pathlib import Path

from momo.adapters.hardware.dry_run_robot_driver import DryRunRobotDriver
from momo.adapters.storage.file_calibration_repository import FileCalibrationRepository
from momo.adapters.storage.profile_repository import FileProfileRepository
from momo.adapters.storage.runtime_state_repository import FileRuntimeStateRepository
from momo.application.services.calibration_service import CalibrationService
from momo.application.services.profile_service import ProfileService
from momo.application.services.robot_service import RobotApplicationService
from momo.domain.robot import RobotId, RobotProfile
from momo.ports.robot_driver import RobotDriver
from momo.settings import Settings, repository_root


def _resolve_configured_path(value: str, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _build_dry_run_driver(
    robot_id: RobotId,
    profile: RobotProfile,
    positions: dict[str, float] | None,
) -> RobotDriver:
    return DryRunRobotDriver(robot_id, profile, positions)


def build_robot_service(settings: Settings) -> RobotApplicationService:
    """Build fresh repositories/services for a single app, with no device side effects."""

    root = repository_root()
    profile_repository = FileProfileRepository(
        _resolve_configured_path(settings.profile_directory, root)
    )
    calibration_repository = FileCalibrationRepository(
        _resolve_configured_path(settings.calibration_directory, root)
    )
    runtime_repository = FileRuntimeStateRepository(
        _resolve_configured_path(settings.runtime_state_directory, root)
    )
    return RobotApplicationService(
        settings,
        ProfileService(profile_repository),
        CalibrationService(calibration_repository),
        runtime_repository,
        driver_factory=_build_dry_run_driver,
    )
