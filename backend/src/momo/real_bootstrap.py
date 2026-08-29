"""Side-effect-free outer composition for the reviewed product REAL runtime."""

from __future__ import annotations

from dataclasses import dataclass

from momo.adapters.hardware.real_robot_driver import (
    AuthorizedServoBusBinding,
    RealRobotDriver,
)
from momo.adapters.motion.real_command_executor import RealCommandMotionExecutor
from momo.adapters.playback.real_playback_service import RealPlaybackService
from momo.adapters.storage.file_calibration_workflow_repository import (
    FileCalibrationWorkflowRepository,
)
from momo.adapters.storage.profile_repository import FileProfileRepository
from momo.adapters.storage.runtime_state_repository import FileRuntimeStateRepository
from momo.adapters.time.system_clock import SystemClock
from momo.application.services.calibration_service import CalibrationService
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.library_service import LibraryApplicationService
from momo.application.services.profile_service import ProfileService
from momo.application.services.robot_service import RobotApplicationService
from momo.bootstrap import ProductServices, _resolve_configured_path, build_product_services
from momo.domain.robot import RobotId, RobotProfile
from momo.ports.playback import PlaybackExecutionValidator, PlaybackObserver
from momo.ports.robot_driver import RobotDriver
from momo.settings import Settings, repository_root


@dataclass(frozen=True, slots=True)
class RealProductComposition:
    robot: RobotApplicationService
    services: ProductServices
    binding: AuthorizedServoBusBinding


def build_real_product_composition(settings: Settings) -> RealProductComposition:
    """Compose REAL ports without importing an SDK, opening a port, or moving."""

    if not settings.feetech_production_motion_adapter_enabled:
        raise ValueError("REAL product composition requires the production motion adapter")
    root = repository_root()
    profiles = ProfileService(
        FileProfileRepository(_resolve_configured_path(settings.profile_directory, root))
    )
    calibrations = CalibrationService(
        FileCalibrationWorkflowRepository(
            _resolve_configured_path(settings.real_calibration_directory, root)
        )
    )
    runtime = FileRuntimeStateRepository(
        _resolve_configured_path(settings.runtime_state_directory, root)
    )
    binding = AuthorizedServoBusBinding()

    def driver_factory(
        robot_id: RobotId,
        profile: RobotProfile,
        positions: dict[str, float] | None,
    ) -> RobotDriver:
        del positions
        calibration = calibrations.get_for_variant(profile.variant)
        if calibration is None:
            raise ValueError(f"REAL Calibration is missing for {profile.variant.value}")
        return RealRobotDriver(robot_id, profile, calibration, binding)

    robot = RobotApplicationService(
        settings,
        profiles,
        calibrations,
        runtime,
        driver_factory=driver_factory,
        clock=SystemClock(),
    )

    def executor_factory(
        clock: SystemClock,
        robot_service: RobotApplicationService,
        kinematics: KinematicsService,
    ) -> RealCommandMotionExecutor:
        return RealCommandMotionExecutor(
            robot_service,
            kinematics,
            binding,
            clock,
            update_hz=settings.motion_update_hz,
        )

    def playback_factory(
        clock: SystemClock,
        robot_service: RobotApplicationService,
        library: LibraryApplicationService,
        kinematics: KinematicsService,
        validator: PlaybackExecutionValidator,
        observer: PlaybackObserver,
    ) -> RealPlaybackService:
        return RealPlaybackService(
            clock,
            robot_service,
            library,
            kinematics,
            validator,
            observer,
            binding,
        )

    services = build_product_services(
        settings,
        robot,
        executor_factory=executor_factory,
        playback_factory=playback_factory,
    )
    return RealProductComposition(robot=robot, services=services, binding=binding)


__all__ = ["RealProductComposition", "build_real_product_composition"]
