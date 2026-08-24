"""Protected calibration HTTP integration over one explicit Fake ServoBus."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from momo.adapters.storage.file_calibration_workflow_repository import (
    CalibrationReplaceCommittedError,
    FileCalibrationWorkflowRepository,
)
from momo.api.error_handlers import install_error_handlers
from momo.api.routes.device_calibration import router as calibration_router
from momo.application.services.calibration_workflow_coordinator import (
    CalibrationWorkflowCoordinator,
)
from momo.application.services.calibration_workflow_service import (
    CALIBRATION_JOINT_CONFIRMATION,
    ROLLBACK_CONFIRMATION,
    SAVE_CALIBRATION_CONFIRMATION,
)
from momo.application.services.operator_session_service import (
    OperatorSessionPrerequisiteError,
)
from momo.application.services.security_service import SecurityService
from momo.domain.calibration_workflow import CalibrationWorkflowSource
from momo.domain.real_hardware import REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT
from momo.domain.security import NetworkSecurityPolicy
from tests.stage8_hardware_helpers import device_service, fake_bus, real_context


async def request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    token: str,
    json_data: object | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(
            method,
            path,
            json=json_data,
            headers={"X-MOMO-Operator-Session": token},
        )


def test_calibration_api_reads_selected_ids_and_saves_one_revision_without_motion(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        context = real_context()
        assert context.calibration is not None
        device, clock, factory = device_service(context)
        repository = FileCalibrationWorkflowRepository(tmp_path / "calibrations")
        repository.save_new(
            context.calibration,
            expected_revision=None,
            source=CalibrationWorkflowSource.EXISTING_REAL,
            created_at=clock.now(),
        )
        coordinator = CalibrationWorkflowCoordinator(
            device=device,
            repository=repository,
            clock=clock,
        )
        app = FastAPI()
        install_error_handlers(app)
        app.state.security_service = SecurityService(
            NetworkSecurityPolicy(),
            lan_token=None,
            monotonic=time.monotonic,
            control_rate_limit=100,
        )
        app.state.calibration_workflow_coordinator = coordinator
        app.include_router(calibration_router, prefix="/api/v1")

        issued = await device.issue_operator_session(
            confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        token = issued.session_token.get_secret_value()
        await device.connect(token)

        started = await request(
            app,
            "POST",
            "/api/v1/device/calibration/sessions",
            token=token,
            json_data={"source": "EXISTING_REAL"},
        )
        assert started.status_code == 200, started.text
        status = started.json()
        session_id = status["session_id"]
        assert status["base_revision"] == 1
        assert status["save_preview"] is None

        for joint_id in status["required_joint_ids"]:
            read = await request(
                app,
                "POST",
                f"/api/v1/device/calibration/sessions/{session_id}/read",
                token=token,
                json_data={"joint_id": joint_id},
            )
            assert read.status_code == 200, read.text
            preview = await request(
                app,
                "POST",
                f"/api/v1/device/calibration/sessions/{session_id}/preview",
                token=token,
                json_data={
                    "joint_id": joint_id,
                    "logical_value": 0.0,
                    "direction": 1,
                    "phase": 0,
                    "raw_bounds": [-30719, 30719],
                },
            )
            assert preview.status_code == 200, preview.text
            confirmed = await request(
                app,
                "POST",
                f"/api/v1/device/calibration/sessions/{session_id}/confirm",
                token=token,
                json_data={
                    "joint_id": joint_id,
                    "preview_fingerprint": preview.json()["preview_fingerprint"],
                    "confirmation": CALIBRATION_JOINT_CONFIRMATION,
                },
            )
            assert confirmed.status_code == 200, confirmed.text
            status = confirmed.json()

        assert status["state"] == "READY_TO_SAVE"
        save_preview = status["save_preview"]
        assert save_preview["proposed_calibration"]["template"] is False
        proposed_fingerprint = save_preview["proposed_calibration_fingerprint"]
        wrong = await request(
            app,
            "POST",
            f"/api/v1/device/calibration/sessions/{session_id}/complete",
            token=token,
            json_data={
                "proposed_calibration_fingerprint": "0" * 64,
                "confirmation": SAVE_CALIBRATION_CONFIRMATION,
            },
        )
        assert wrong.status_code == 409

        completed = await request(
            app,
            "POST",
            f"/api/v1/device/calibration/sessions/{session_id}/complete",
            token=token,
            json_data={
                "proposed_calibration_fingerprint": proposed_fingerprint,
                "confirmation": SAVE_CALIBRATION_CONFIRMATION,
            },
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["revision"] == 2
        assert completed.json()["variant"] == "V2"
        assert device.connected is False
        assert device.context.calibration is None
        assert (await device.sessions.status()).active is False
        with pytest.raises(OperatorSessionPrerequisiteError):
            await device.issue_operator_session(
                confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
                physical_estop_confirmed=True,
            )
        current = repository.get_revision(context.calibration.robot_variant)
        assert current is not None
        assert current.revision == 2

        bus = factory.bus
        calibration_reads = [event for event in bus.events if event[0] == "read_present_positions"]
        assert len(calibration_reads) == len(status["required_joint_ids"]) + 1
        assert all(
            isinstance(event[1], tuple) and len(event[1]) == 1 for event in calibration_reads[1:]
        )
        assert all(
            event[0] not in {"write_goal_positions", "stop_or_hold", "scan", "home"}
            for event in bus.events
        )

    asyncio.run(scenario())


def test_calibration_rollback_invalidates_loaded_identity_and_operator_session(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        initial_context = real_context()
        initial = initial_context.calibration
        assert initial is not None
        replacement = initial.model_copy(
            update={
                "id": uuid4(),
                "joints": [
                    joint.model_copy(update={"home_present_raw": 5}) for joint in initial.joints
                ],
            }
        )
        context = real_context(calibration=replacement)
        assert context.device is not None
        bus = fake_bus(
            context,
            present_positions={servo_id: 5 for servo_id in context.device.servo_ids},
        )
        device, clock, factory = device_service(context, bus=bus)
        repository = FileCalibrationWorkflowRepository(tmp_path / "calibrations")
        repository.save_new(
            initial,
            expected_revision=None,
            source=CalibrationWorkflowSource.EXISTING_REAL,
            created_at=clock.now(),
        )
        repository.save_new(
            replacement,
            expected_revision=1,
            source=CalibrationWorkflowSource.EXISTING_REAL,
            created_at=clock.now(),
        )
        coordinator = CalibrationWorkflowCoordinator(
            device=device,
            repository=repository,
            clock=clock,
        )
        app = FastAPI()
        install_error_handlers(app)
        app.state.security_service = SecurityService(
            NetworkSecurityPolicy(),
            lan_token=None,
            monotonic=time.monotonic,
            control_rate_limit=100,
        )
        app.state.calibration_workflow_coordinator = coordinator
        app.include_router(calibration_router, prefix="/api/v1")
        issued = await device.issue_operator_session(
            confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        token = issued.session_token.get_secret_value()
        await device.connect(token)

        rolled_back = await request(
            app,
            "POST",
            "/api/v1/device/calibration/rollback",
            token=token,
            json_data={
                "target_revision": 1,
                "confirmation": ROLLBACK_CONFIRMATION,
            },
        )

        assert rolled_back.status_code == 200, rolled_back.text
        assert rolled_back.json()["revision"] == 3
        assert device.context.calibration is None
        assert device.connected is False
        assert factory.bus.connected is False
        assert (await device.sessions.status()).active is False
        with pytest.raises(OperatorSessionPrerequisiteError):
            await device.issue_operator_session(
                confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
                physical_estop_confirmed=True,
            )

    asyncio.run(scenario())


def test_post_replace_fsync_failure_still_invalidates_stale_hardware_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        context = real_context()
        calibration = context.calibration
        assert calibration is not None
        device, clock, factory = device_service(context)
        repository = FileCalibrationWorkflowRepository(tmp_path / "calibrations")
        repository.save_new(
            calibration,
            expected_revision=None,
            source=CalibrationWorkflowSource.EXISTING_REAL,
            created_at=clock.now(),
        )
        coordinator = CalibrationWorkflowCoordinator(
            device=device,
            repository=repository,
            clock=clock,
        )
        issued = await device.issue_operator_session(
            confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        token = issued.session_token.get_secret_value()
        await device.connect(token)
        status = await coordinator.start(
            token,
            source=CalibrationWorkflowSource.EXISTING_REAL,
        )
        for joint_id in status.required_joint_ids:
            await coordinator.read_selected_joint(token, status.session_id, joint_id)
            preview = await coordinator.preview_joint(
                token,
                status.session_id,
                joint_id,
                logical_value=0.0,
                direction=1,
                phase=0,
                raw_bounds=(-30_719, 30_719),
            )
            status = await coordinator.confirm_joint(
                token,
                status.session_id,
                joint_id,
                preview_fingerprint=preview.preview_fingerprint,
                confirmation=CALIBRATION_JOINT_CONFIRMATION,
            )
        assert status.save_preview is not None
        proposed_fingerprint = status.save_preview.proposed_calibration_fingerprint
        original_fsync = repository._fsync_directory
        repository._ensure_backup_directory(
            repository._variant_backup_directory(calibration.robot_variant)
        )

        def fail_current_directory_fsync(directory: Path) -> None:
            if directory == repository.directory:
                raise OSError("synthetic directory fsync failure after replace")
            original_fsync(directory)

        monkeypatch.setattr(repository, "_fsync_directory", fail_current_directory_fsync)
        with pytest.raises(CalibrationReplaceCommittedError):
            await coordinator.complete(
                token,
                status.session_id,
                proposed_calibration_fingerprint=proposed_fingerprint,
                confirmation=SAVE_CALIBRATION_CONFIRMATION,
            )

        current = repository.get_revision(calibration.robot_variant)
        assert current is not None
        assert current.revision == 2
        assert device.context.calibration is None
        assert device.connected is False
        assert factory.bus.connected is False
        assert (await device.sessions.status()).active is False

    asyncio.run(scenario())


def test_repeated_cancellation_waits_for_calibration_invalidation_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        context = real_context()
        calibration = context.calibration
        assert calibration is not None
        device, clock, factory = device_service(context)
        repository = FileCalibrationWorkflowRepository(tmp_path / "calibrations")
        repository.save_new(
            calibration,
            expected_revision=None,
            source=CalibrationWorkflowSource.EXISTING_REAL,
            created_at=clock.now(),
        )
        coordinator = CalibrationWorkflowCoordinator(
            device=device,
            repository=repository,
            clock=clock,
        )
        issued = await device.issue_operator_session(
            confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        token = issued.session_token.get_secret_value()
        await device.connect(token)
        status = await coordinator.start(
            token,
            source=CalibrationWorkflowSource.EXISTING_REAL,
        )
        for joint_id in status.required_joint_ids:
            await coordinator.read_selected_joint(token, status.session_id, joint_id)
            preview = await coordinator.preview_joint(
                token,
                status.session_id,
                joint_id,
                logical_value=0.0,
                direction=1,
                phase=0,
                raw_bounds=(-30_719, 30_719),
            )
            status = await coordinator.confirm_joint(
                token,
                status.session_id,
                joint_id,
                preview_fingerprint=preview.preview_fingerprint,
                confirmation=CALIBRATION_JOINT_CONFIRMATION,
            )
        assert status.save_preview is not None
        original_invalidate = device.invalidate_calibration_authorization
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()

        async def blocking_invalidate() -> None:
            cleanup_started.set()
            await release_cleanup.wait()
            await original_invalidate()

        monkeypatch.setattr(
            device,
            "invalidate_calibration_authorization",
            blocking_invalidate,
        )
        completion = asyncio.create_task(
            coordinator.complete(
                token,
                status.session_id,
                proposed_calibration_fingerprint=(
                    status.save_preview.proposed_calibration_fingerprint
                ),
                confirmation=SAVE_CALIBRATION_CONFIRMATION,
            )
        )
        await cleanup_started.wait()

        completion.cancel()
        await asyncio.sleep(0)
        assert completion.done() is False
        completion.cancel()
        await asyncio.sleep(0)
        assert completion.done() is False
        release_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await completion

        current = repository.get_revision(calibration.robot_variant)
        assert current is not None
        assert current.revision == 2
        assert device.context.calibration is None
        assert device.connected is False
        assert factory.bus.connected is False
        assert (await device.sessions.status()).active is False

    asyncio.run(scenario())


def test_expired_workflow_owner_does_not_block_fresh_confirmed_session(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        context = real_context()
        calibration = context.calibration
        assert calibration is not None
        device, clock, _factory = device_service(context)
        repository = FileCalibrationWorkflowRepository(tmp_path / "calibrations")
        repository.save_new(
            calibration,
            expected_revision=None,
            source=CalibrationWorkflowSource.EXISTING_REAL,
            created_at=clock.now(),
        )
        coordinator = CalibrationWorkflowCoordinator(
            device=device,
            repository=repository,
            clock=clock,
        )
        first_token = (
            await device.issue_operator_session(
                confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
                physical_estop_confirmed=True,
            )
        ).session_token.get_secret_value()
        await device.connect(first_token)
        first = await coordinator.start(
            first_token,
            source=CalibrationWorkflowSource.EXISTING_REAL,
        )

        clock.elapse(61.0)
        await clock.settle()
        assert device.connected is False
        second_token = (
            await device.issue_operator_session(
                confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
                physical_estop_confirmed=True,
            )
        ).session_token.get_secret_value()
        await device.connect(second_token)
        second = await coordinator.start(
            second_token,
            source=CalibrationWorkflowSource.EXISTING_REAL,
        )

        assert second.session_id != first.session_id
        await coordinator.cancel(second_token, second.session_id)
        await device.shutdown()

    asyncio.run(scenario())
