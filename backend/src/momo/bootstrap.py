"""Composition root for one FastAPI application instance."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from momo.adapters.hardware.dry_run_robot_driver import DryRunRobotDriver
from momo.adapters.kinematics.model_repository import FileKinematicsModelRepository
from momo.adapters.kinematics.serial_chain import SerialChainKinematics
from momo.adapters.motion.dry_run_motion_executor import DryRunMotionExecutor
from momo.adapters.playback.latest_value_observer import LatestValuePlaybackObserver
from momo.adapters.storage.file_calibration_repository import FileCalibrationRepository
from momo.adapters.storage.file_motion_draft_repository import FileMotionDraftRepository
from momo.adapters.storage.file_motion_repository import FileMotionRepository
from momo.adapters.storage.file_pose_repository import FilePoseRepository
from momo.adapters.storage.profile_repository import FileProfileRepository
from momo.adapters.storage.runtime_state_repository import FileRuntimeStateRepository
from momo.adapters.time.system_clock import SystemClock
from momo.application.services.calibration_service import CalibrationService
from momo.application.services.jog_service import JogLeaseService
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.library_service import LibraryApplicationService
from momo.application.services.motion_safety_gateway import MotionSafetyGateway
from momo.application.services.motion_service import MotionApplicationService
from momo.application.services.playback_service import PlaybackService
from momo.application.services.profile_service import ProfileService
from momo.application.services.robot_service import RobotApplicationService
from momo.application.services.studio_service import StudioApplicationService
from momo.application.services.trajectory_compiler import TrajectoryCompiler
from momo.application.services.trajectory_service import (
    PlaybackSafetyValidator,
    TrajectoryApplicationService,
)
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
        clock=SystemClock(),
    )


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    kinematics: KinematicsService
    motion: MotionApplicationService
    jog: JogLeaseService
    library: LibraryApplicationService
    trajectory: TrajectoryApplicationService
    playback: PlaybackService
    studio: StudioApplicationService
    playback_observer: LatestValuePlaybackObserver


def build_application_services(
    settings: Settings,
    robot_service: RobotApplicationService,
) -> ApplicationServices:
    """Compose Dry Run motion services without opening any external capability."""

    root = repository_root()
    clock = SystemClock()
    kinematics = KinematicsService(
        FileKinematicsModelRepository(
            _resolve_configured_path(settings.kinematics_model_directory, root)
        ),
        SerialChainKinematics(),
    )
    executor = DryRunMotionExecutor(
        clock,
        robot_service,
        update_hz=settings.motion_update_hz,
    )
    gateway = MotionSafetyGateway(
        robot_service,
        kinematics,
        robot_service.calibration_service,
        executor,
    )
    motion = MotionApplicationService(robot_service, gateway, executor)
    jog = JogLeaseService(
        motion,
        clock,
        lease_ttl_ms=settings.jog_lease_ttl_ms,
    )
    motion.register_stop_hook(jog.stop_all)
    motion_repository = FileMotionRepository(
        _resolve_configured_path(settings.motion_library_directory, root), clock
    )
    library = LibraryApplicationService(
        FilePoseRepository(_resolve_configured_path(settings.pose_directory, root), clock),
        motion_repository,
        robot_service,
        kinematics,
        motion,
        clock,
    )
    playback_observer = LatestValuePlaybackObserver()
    playback = PlaybackService(
        clock,
        robot_service,
        PlaybackSafetyValidator(library, gateway),
        playback_observer,
    )
    gateway.register_external_motion_guard(lambda: playback.motion_active)
    compiler = TrajectoryCompiler(kinematics)
    trajectory = TrajectoryApplicationService(
        library,
        robot_service,
        kinematics,
        compiler,
        playback,
        gateway.motion_admission,
    )
    motion.register_stop_hook(trajectory.shutdown)
    studio = StudioApplicationService(
        FileMotionDraftRepository(
            _resolve_configured_path(settings.motion_draft_directory, root), clock
        ),
        library,
        robot_service,
        kinematics,
        compiler,
        motion,
        clock,
    )
    return ApplicationServices(
        kinematics=kinematics,
        motion=motion,
        jog=jog,
        library=library,
        trajectory=trajectory,
        playback=playback,
        studio=studio,
        playback_observer=playback_observer,
    )
