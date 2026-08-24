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
from momo.adapters.storage.file_field_acceptance_repository import (
    FileFieldAcceptanceEvidenceRepository,
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
from momo.application.services.field_acceptance_service import FieldAcceptanceService
from momo.application.services.operator_session_service import OperatorSessionTokenError
from momo.application.services.security_service import SecurityService
from momo.domain.calibration import CalibrationDocument
from momo.domain.calibration_workflow import CalibrationWorkflowSource
from momo.domain.real_hardware import (
    REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
    REQUIRED_FIELD_ACCEPTANCE_CONFIRMATION_TEXT,
    FieldAcceptanceEvidenceState,
    FieldAcceptanceStatus,
    OperatorSessionPurpose,
    RealHardwareBlocker,
)
from momo.domain.security import NetworkSecurityPolicy
from tests.stage8_hardware_helpers import (
    commissioning_context,
    device_service,
    fake_bus,
    write_bomb_bus,
)
from tests.stage8_hardware_helpers import (
    real_context as full_motion_context,
)
from tests.stage8_hardware_helpers import (
    recalibration_context as real_context,
)


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


def test_fresh_commissioning_write_bomb_saves_revision_one_without_any_write(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        context = commissioning_context()
        profile = context.profile
        assert profile is not None and context.calibration is None
        bus = write_bomb_bus(context)
        device, clock, factory = device_service(context, bus=bus)
        repository = FileCalibrationWorkflowRepository(tmp_path / "fresh-calibrations")
        coordinator = CalibrationWorkflowCoordinator(
            device=device,
            repository=repository,
            clock=clock,
        )

        before = await device.readiness()
        assert before.commissioning_session_authorizable is True
        assert before.motion_session_authorizable is False
        assert before.capabilities.commissioning_diagnostics_ready is True
        assert before.capabilities.calibration_capture_ready is True
        assert before.capabilities.real_joint_motion_ready is False
        assert before.capabilities.real_cartesian_motion_ready is False

        issued = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
            confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        evidence = issued.evidence
        token = issued.session_token.get_secret_value()
        assert evidence.profile_fingerprint == profile.fingerprint
        assert evidence.device_fingerprint
        assert evidence.calibration_fingerprint is None
        assert evidence.kinematics_fingerprint is None

        connected = await device.connect(token)
        assert connected.connected is True
        assert all(record.logical_value is None for record in connected.records)
        assert all(record.raw_bounds is None for record in connected.records)
        diagnostics = await device.diagnostics(token)
        assert all(record.torque_enabled is False for record in diagnostics.records)
        stopped = await device.stop()
        assert stopped.safety_state_known is False
        assert bus.write_attempts == []

        status = await coordinator.start(
            token,
            source=CalibrationWorkflowSource.EXISTING_REAL,
        )
        assert status.base_revision is None
        assert status.base_calibration_fingerprint is None
        assert all(
            joint.present_raw is None
            and joint.logical_value is None
            and joint.direction is None
            and joint.phase is None
            and joint.raw_bounds is None
            and joint.operating_mode is None
            for joint in status.draft.joints
        )

        for definition in profile.joint_definitions:
            assert definition.raw_bounds is not None
            status = await coordinator.read_selected_joint(
                token,
                status.session_id,
                definition.joint_id,
            )
            preview = await coordinator.preview_joint(
                token,
                status.session_id,
                definition.joint_id,
                logical_value=0.0,
                direction=1,
                phase=0,
                raw_bounds=definition.raw_bounds,
            )
            status = await coordinator.confirm_joint(
                token,
                status.session_id,
                definition.joint_id,
                preview_fingerprint=preview.preview_fingerprint,
                confirmation=CALIBRATION_JOINT_CONFIRMATION,
            )

        assert status.save_preview is not None
        saved = await coordinator.complete(
            token,
            status.session_id,
            proposed_calibration_fingerprint=(status.save_preview.proposed_calibration_fingerprint),
            confirmation=SAVE_CALIBRATION_CONFIRMATION,
        )
        assert saved.revision == 1
        assert saved.previous_calibration_fingerprint is None
        assert saved.calibration.template is False
        assert saved.calibration.profile_fingerprint == profile.fingerprint
        assert tuple(joint.joint_id for joint in saved.calibration.joints) == tuple(
            profile.enabled_joints
        )
        assert repository.get_revision(profile.variant) == saved
        assert device.context.calibration == saved.calibration

        pending_motion_context = full_motion_context(
            calibration=saved.calibration,
            field_acceptance_status=FieldAcceptanceStatus.PENDING,
            field_acceptance_evidence=None,
        )
        pending_motion_device, _, _ = device_service(pending_motion_context)
        blocked = await pending_motion_device.readiness()
        assert blocked.motion_session_authorizable is False
        assert RealHardwareBlocker.FIELD_ACCEPTANCE_NOT_PASSED in blocked.blocking_reasons
        assert blocked.capabilities.real_joint_motion_ready is False
        assert blocked.capabilities.real_cartesian_motion_ready is False
        assert blocked.capabilities.real_playback_ready is False
        assert blocked.capabilities.real_vision_follow_ready is False

        assert device.connected is False
        assert factory.bus.connected is False
        assert (await device.sessions.status()).active is False

        replacement = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
            confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        assert replacement.evidence.session_id != evidence.session_id
        replacement_token = replacement.session_token.get_secret_value()
        await device.connect(replacement_token)
        acceptance = FieldAcceptanceService(
            device=device,
            repository=FileFieldAcceptanceEvidenceRepository(
                tmp_path / "field-acceptance",
                clock,
            ),
            clock=clock,
        )
        accepted = await acceptance.accept(
            replacement_token,
            checklist_version=context.field_acceptance_checklist_version,
            confirmation_text=REQUIRED_FIELD_ACCEPTANCE_CONFIRMATION_TEXT,
            accepted_by="synthetic-first-commissioning",
        )
        assert accepted.state is FieldAcceptanceEvidenceState.VALID
        assert accepted.effective_status is FieldAcceptanceStatus.PASSED
        assert device.context.field_acceptance_evidence is not None
        assert device.connected is False
        assert (await device.sessions.status()).active is False
        assert bus.write_attempts == []
        assert not hasattr(bus, "scan")
        assert all(
            event[0] not in {"write_goal_positions", "stop_or_hold", "scan", "home"}
            for event in bus.events
        )

    asyncio.run(scenario())


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
            purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
            confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
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
        assert (await device.sessions.status()).active is False
        replacement = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
            confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        assert replacement.evidence.session_id != issued.evidence.session_id
        assert replacement.evidence.calibration_fingerprint is None
        current = repository.get_revision(context.calibration.robot_variant)
        assert current is not None
        assert current.revision == 2
        assert device.context.calibration == current.calibration

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
            purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
            confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
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
        current = repository.get_revision(initial.robot_variant)
        assert current is not None
        assert current.revision == 3
        assert device.context.calibration == current.calibration
        assert device.connected is False
        assert factory.bus.connected is False
        assert (await device.sessions.status()).active is False
        replacement_session = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
            confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        assert replacement_session.evidence.session_id != issued.evidence.session_id

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
            purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
            confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
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
            purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
            confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
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

        async def blocking_invalidate(
            persisted_calibration: CalibrationDocument | None = None,
        ) -> None:
            cleanup_started.set()
            await release_cleanup.wait()
            await original_invalidate(persisted_calibration)

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
        assert device.context.calibration == current.calibration
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
                purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
                confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
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
        with pytest.raises(OperatorSessionTokenError):
            await coordinator.status(first_token, first.session_id)
        second_token = (
            await device.issue_operator_session(
                purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
                confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
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
