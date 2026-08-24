"""Stage 8 release services composed without opening hardware or binding a socket."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from momo.adapters.storage.file_backup_restore_journal import FileBackupRestoreJournal
from momo.adapters.storage.file_calibration_workflow_repository import (
    FileCalibrationWorkflowRepository,
)
from momo.adapters.time.system_clock import SystemClock
from momo.application.services.backup_service import BackupApplicationService
from momo.application.services.calibration_workflow_coordinator import (
    CalibrationWorkflowCoordinator,
)
from momo.application.services.device_diagnostics_service import DeviceDiagnosticsService
from momo.application.services.operator_session_service import OperatorSessionService
from momo.application.services.real_hardware_authorization import RealHardwareAuthorization
from momo.application.services.robot_service import PRIMARY_ROBOT_ID, RobotApplicationService
from momo.application.services.security_service import SecurityService
from momo.bootstrap import ApplicationServices
from momo.domain.backup import BackupRestoreCalibrationTarget
from momo.domain.calibration import CalibrationDocument
from momo.domain.calibration_workflow import CalibrationWorkflowError
from momo.domain.real_hardware import (
    ExplicitServoDevice,
    FieldAcceptanceStatus,
    RealHardwareContext,
)
from momo.domain.security import NetworkExposureMode, NetworkSecurityPolicy
from momo.settings import Settings, repository_root


@dataclass(frozen=True, slots=True)
class ReleaseServices:
    security: SecurityService
    backup: BackupApplicationService
    device: DeviceDiagnosticsService
    real_calibrations: FileCalibrationWorkflowRepository
    calibration: CalibrationWorkflowCoordinator


async def commit_calibration_import(
    repository: FileCalibrationWorkflowRepository,
    values: tuple[CalibrationDocument, ...],
    *,
    created_at: datetime,
) -> None:
    """Commit the bounded calibration batch through repeated caller cancellation."""

    transaction = asyncio.create_task(
        asyncio.to_thread(
            repository.import_new_bundle,
            values,
            created_at=created_at,
        ),
        name="calibration-backup-import",
    )
    while True:
        try:
            await asyncio.shield(transaction)
            return
        except asyncio.CancelledError:
            # The worker thread cannot be cancelled. Keep the parent restore alive
            # until the batch either commits completely or compensates completely.
            continue


async def commit_calibration_rollback(
    repository: FileCalibrationWorkflowRepository,
    targets: tuple[BackupRestoreCalibrationTarget, ...],
) -> None:
    """Finish exact calibration compensation despite repeated caller cancellation."""

    transaction = asyncio.create_task(
        asyncio.to_thread(repository.remove_imported_bundle_exact, targets),
        name="calibration-backup-rollback",
    )
    while True:
        try:
            await asyncio.shield(transaction)
            return
        except asyncio.CancelledError:
            continue


def _configured_path(value: str, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def build_network_policy(settings: Settings) -> NetworkSecurityPolicy:
    """Turn validated settings into a pure bind/auth/origin decision."""

    lan = settings.lan_enabled
    return NetworkSecurityPolicy(
        exposure_mode=NetworkExposureMode.LAN if lan else NetworkExposureMode.LOCAL_ONLY,
        bind_host=settings.server_host,
        lan_enabled=lan,
        allowed_origins=(settings.lan_allowed_origins if lan else settings.local_allowed_origins),
        require_authentication=lan,
        max_request_body_bytes=settings.api_body_max_bytes,
    )


def _real_hardware_context(
    settings: Settings,
    robot: RobotApplicationService,
    application: ApplicationServices,
    calibrations: FileCalibrationWorkflowRepository,
) -> RealHardwareContext:
    """Load capability-bearing artifacts only after explicit local authorization.

    The default branch uses no Real calibration path and no hardware adapter. An
    explicitly supplied ignored local config may ask the field application to read its
    fixed Real calibration/model/profile files for readiness; this still performs no
    port open, enumeration, scan, Home, torque, or movement.
    """

    common = {
        "control_mode": settings.control_mode,
        "hardware_access_policy": settings.hardware_access_policy,
        "real_motion_enabled": settings.real_motion_enabled,
        "startup_hardware_enabled": settings.hardware_startup_enabled,
        "explicit_local_config": settings.hardware_local_config_enabled,
        "field_acceptance_status": FieldAcceptanceStatus(settings.field_acceptance_status),
    }
    if not settings.hardware_local_config_enabled:
        return RealHardwareContext.model_validate(common)

    profile = robot.manager.get_active().profile
    try:
        calibration = calibrations.get_for_variant(profile.variant)
    except CalibrationWorkflowError:
        calibration = None
    try:
        kinematics = application.kinematics.model_for(profile)
    except (OSError, ValueError):
        kinematics = None
    device = None
    if settings.serial_port and settings.servo_ids and settings.servo_protocol:
        device = ExplicitServoDevice(
            serial_port=settings.serial_port,
            servo_ids=settings.servo_ids,
            protocol=settings.servo_protocol,
        )
    return RealHardwareContext.model_validate(
        {
            **common,
            "robot_id": PRIMARY_ROBOT_ID,
            "profile": profile,
            "calibration": calibration,
            "kinematics": kinematics,
            "expected_kinematics_fingerprint": (
                kinematics.fingerprint if kinematics is not None else None
            ),
            "device": device,
        }
    )


def build_release_services(
    settings: Settings,
    robot: RobotApplicationService,
    application: ApplicationServices,
) -> ReleaseServices:
    """Compose bounded Stage 8 services; the real bus factory stays absent by default."""

    root = repository_root()
    clock = SystemClock()
    policy = build_network_policy(settings)
    raw_lan_token = settings.lan_auth_token.get_secret_value() or None
    security = SecurityService(
        policy,
        lan_token=raw_lan_token,
        now=clock.now,
        monotonic=clock.monotonic,
        control_rate_limit=settings.control_rate_limit_per_minute,
        control_rate_window_seconds=60.0,
    )
    # The raw token is not retained by SecurityService; only a keyed digest remains.
    del raw_lan_token

    real_calibrations = FileCalibrationWorkflowRepository(
        _configured_path(settings.real_calibration_directory, root)
    )
    authorization = RealHardwareAuthorization()
    sessions = OperatorSessionService(
        clock,
        authorization,
        ttl_s=float(settings.operator_session_ttl_s),
    )
    device = DeviceDiagnosticsService(
        context=_real_hardware_context(
            settings,
            robot,
            application,
            real_calibrations,
        ),
        authorization=authorization,
        sessions=sessions,
        bus_factory=None,
        clock=clock,
    )
    calibration = CalibrationWorkflowCoordinator(
        device=device,
        repository=real_calibrations,
        clock=clock,
    )

    async def import_calibrations(
        values: tuple[CalibrationDocument, ...],
    ) -> None:
        # The callback is typed precisely by BackupApplicationService at the call
        # boundary. Shield the bounded two-file transaction; once commit starts,
        # request cancellation cannot strand a half-applied calibration batch.
        await commit_calibration_import(
            real_calibrations,
            values,
            created_at=clock.now(),
        )

    async def rollback_calibrations(
        targets: tuple[BackupRestoreCalibrationTarget, ...],
    ) -> None:
        await commit_calibration_rollback(real_calibrations, targets)
        if targets:
            # Compensation may remove the exact calibration that was loaded while
            # this service graph was being composed. Invalidate that in-memory
            # authority before startup yields or another operator session is issued.
            await device.invalidate_calibration_authorization()

    backup = BackupApplicationService(
        poses=application.library.poses,
        motions=application.library.motions,
        drafts=application.studio.drafts,
        calibrations=real_calibrations,
        calibration_importer=import_calibrations,
        calibration_rollback=rollback_calibrations,
        restore_journal=FileBackupRestoreJournal(
            _configured_path(settings.backup_restore_journal_directory, root)
        ),
        maintenance_lock=application.maintenance_gate,
    )
    return ReleaseServices(
        security=security,
        backup=backup,
        device=device,
        real_calibrations=real_calibrations,
        calibration=calibration,
    )


__all__ = [
    "ReleaseServices",
    "build_network_policy",
    "build_release_services",
    "commit_calibration_import",
    "commit_calibration_rollback",
]
