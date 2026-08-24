"""Fingerprint-bound local field acceptance; synthetic adapters only."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi import Depends, FastAPI

from momo.adapters.storage.file_field_acceptance_repository import (
    FileFieldAcceptanceEvidenceRepository,
)
from momo.api.app import create_app
from momo.api.dependencies import authorize_real_joint_motion_request
from momo.api.error_handlers import install_error_handlers
from momo.application.services.field_acceptance_service import FieldAcceptanceService
from momo.application.services.operator_session_service import OperatorSessionTokenError
from momo.application.services.real_hardware_authorization import RealHardwareAuthorization
from momo.domain.enums import HardwareAccessPolicy
from momo.domain.kinematics.model import KinematicsModel
from momo.domain.real_hardware import (
    REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
    REQUIRED_FIELD_ACCEPTANCE_CONFIRMATION_TEXT,
    REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
    FieldAcceptanceEvidenceState,
    FieldAcceptanceStatus,
    OperatorSessionPurpose,
    RealHardwareAuthorizationPurpose,
    RealHardwareBlocker,
    RealHardwareGateInput,
    effective_field_acceptance_status,
    field_acceptance_evidence_state,
)
from momo.settings import Settings
from tests.stage3_helpers import FakeClock
from tests.stage8_hardware_helpers import device_service, real_context


def isolated_app_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Settings:
    """Ignore ambient MOMO_* capability settings and isolate every private store."""

    for field_name in Settings.model_fields:
        monkeypatch.delenv(f"MOMO_{field_name.upper()}", raising=False)
    monkeypatch.delenv("MOMO_HARDWARE_ACCESS", raising=False)
    return Settings(
        runtime_state_directory=str(tmp_path / "runtime"),
        real_calibration_directory=str(tmp_path / "real-calibration"),
        field_acceptance_directory=str(tmp_path / "field-acceptance"),
        pose_directory=str(tmp_path / "poses"),
        motion_library_directory=str(tmp_path / "motions"),
        motion_draft_directory=str(tmp_path / "drafts"),
        backup_restore_journal_directory=str(tmp_path / "restore"),
        audit_directory=str(tmp_path / "audit"),
    )


def test_acceptance_evidence_invalidates_on_every_bound_context_change() -> None:
    context = real_context()
    assert context.field_acceptance_evidence is not None
    assert context.profile is not None
    assert context.calibration is not None
    assert context.device is not None
    assert context.kinematics is not None
    assert field_acceptance_evidence_state(context) == (
        FieldAcceptanceEvidenceState.VALID,
        (),
    )

    profile_data = context.profile.model_dump(mode="python")
    profile_data["joint_definitions"][0]["raw_counts_per_motor_revolution"] += 1.0
    changed_profile = type(context.profile).model_validate(profile_data)
    state, stale = field_acceptance_evidence_state(
        context.model_copy(update={"profile": changed_profile})
    )
    assert state is FieldAcceptanceEvidenceState.STALE
    assert "profile_fingerprint" in stale

    changed_joint = context.calibration.joints[0].model_copy(update={"home_present_raw": 1})
    changed_calibration = context.calibration.model_copy(
        update={"joints": [changed_joint, *context.calibration.joints[1:]]}
    )
    assert (
        "calibration_fingerprint"
        in field_acceptance_evidence_state(
            context.model_copy(update={"calibration": changed_calibration})
        )[1]
    )

    changed_device = context.device.model_copy(update={"serial_port": "/dev/other-synthetic"})
    assert (
        "device_fingerprint"
        in field_acceptance_evidence_state(context.model_copy(update={"device": changed_device}))[1]
    )

    kinematics_data = context.kinematics.model_dump(mode="python")
    translation = list(kinematics_data["joints"][0]["origin_translation_m"])
    translation[0] += 0.001
    kinematics_data["joints"][0]["origin_translation_m"] = translation
    kinematics_data["joints"] = [
        type(context.kinematics.joints[0]).model_validate(item)
        for item in kinematics_data["joints"]
    ]
    candidate = KinematicsModel.model_construct(**kinematics_data)
    kinematics_data["kinematics_fingerprint"] = candidate.fingerprint
    changed_kinematics = KinematicsModel.model_validate(kinematics_data)
    assert (
        "kinematics_fingerprint"
        in field_acceptance_evidence_state(
            context.model_copy(update={"kinematics": changed_kinematics})
        )[1]
    )

    assert (
        "checklist_version"
        in field_acceptance_evidence_state(
            context.model_copy(update={"field_acceptance_checklist_version": "2"})
        )[1]
    )

    opposite_variant = (
        type(context.profile.variant).V1
        if context.profile.variant.value == "V2"
        else type(context.profile.variant).V2
    )
    changed_variant_evidence = context.field_acceptance_evidence.model_copy(
        update={"robot_variant": opposite_variant}
    )
    assert (
        "robot_variant"
        in field_acceptance_evidence_state(
            context.model_copy(update={"field_acceptance_evidence": changed_variant_evidence})
        )[1]
    )


def test_bare_passed_setting_without_evidence_is_pending_and_cannot_authorize_motion() -> None:
    context = real_context(field_acceptance_evidence=None)
    assert context.field_acceptance_status is FieldAcceptanceStatus.PASSED
    assert effective_field_acceptance_status(context) is FieldAcceptanceStatus.PENDING
    report = RealHardwareAuthorization().evaluate(
        RealHardwareGateInput(
            context=context,
            evaluated_at=FakeClock().now(),
        )
    )
    assert RealHardwareBlocker.FIELD_ACCEPTANCE_EVIDENCE_MISSING in report.blocking_reasons
    assert report.motion_session_authorizable is False
    assert report.capabilities.real_joint_motion_ready is False


def test_safe_acceptance_persists_uuid_record_and_ends_commissioning_session(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        context = real_context(
            hardware_access_policy=HardwareAccessPolicy.READ_ONLY,
            real_motion_enabled=False,
            field_acceptance_status=FieldAcceptanceStatus.PENDING,
            field_acceptance_evidence=None,
        )
        clock = FakeClock()
        device, _, _ = device_service(context, clock=clock)
        repository = FileFieldAcceptanceEvidenceRepository(tmp_path, clock)
        service = FieldAcceptanceService(
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

        result = await service.accept(
            token,
            checklist_version=context.field_acceptance_checklist_version,
            confirmation_text=REQUIRED_FIELD_ACCEPTANCE_CONFIRMATION_TEXT,
            accepted_by="synthetic-operator",
        )

        assert result.state is FieldAcceptanceEvidenceState.VALID
        assert result.effective_status is FieldAcceptanceStatus.PASSED
        assert device.connected is False
        assert (await device.sessions.status()).active is False
        records = repository.list_evidence()
        assert len(records) == 1
        assert records[0].evidence_id == result.evidence_id
        evidence_path = tmp_path / f"{records[0].evidence_id}.json"
        assert evidence_path.is_file()
        persisted = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert persisted["schema_version"] == 1
        assert persisted["revision"] == 1
        with pytest.raises(OperatorSessionTokenError):
            await device.authorize_operator_purpose(
                token,
                purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            )

        reloaded = FileFieldAcceptanceEvidenceRepository(tmp_path, clock)
        assert reloaded.list_evidence() == records

    asyncio.run(scenario())


def test_commissioning_token_is_structured_403_on_motion_api() -> None:
    async def scenario() -> None:
        context = real_context(
            hardware_access_policy=HardwareAccessPolicy.READ_ONLY,
            real_motion_enabled=False,
            field_acceptance_status=FieldAcceptanceStatus.PENDING,
            field_acceptance_evidence=None,
        )
        device, _, _ = device_service(context)
        issued = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
            confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        app = FastAPI()
        install_error_handlers(app)
        app.state.device_diagnostics_service = device

        @app.post(
            "/synthetic-real-move",
            dependencies=[Depends(authorize_real_joint_motion_request)],
        )
        async def synthetic_real_move() -> dict[str, bool]:
            return {"moved": True}

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/synthetic-real-move",
                headers={"X-MOMO-Operator-Session": (issued.session_token.get_secret_value())},
            )
        assert response.status_code == 403
        assert response.json()["code"] == "OPERATOR_SESSION_SCOPE_INSUFFICIENT"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/motion/joints"),
        ("POST", "/api/v1/motion/jog-step"),
        ("POST", "/api/v1/motion/home"),
        ("POST", "/api/v1/motion/jog/start"),
        (
            "POST",
            "/api/v1/motion/jog/11111111-1111-4111-8111-111111111111/heartbeat",
        ),
        ("POST", "/api/v1/motion/cartesian-jog"),
        ("POST", "/api/v1/motion/pose"),
        (
            "POST",
            "/api/v1/motions/11111111-1111-4111-8111-111111111111/play",
        ),
        ("POST", "/api/v1/playback/pause"),
        ("POST", "/api/v1/playback/resume"),
        ("PUT", "/api/v1/playback/rate"),
        ("PUT", "/api/v1/playback/loop"),
        (
            "POST",
            "/api/v1/poses/11111111-1111-4111-8111-111111111111/goto",
        ),
        (
            "POST",
            "/api/v1/studio/drafts/11111111-1111-4111-8111-111111111111/"
            "keyframes/22222222-2222-4222-8222-222222222222/goto",
        ),
        ("POST", "/api/v1/vision/follow/start"),
        (
            "POST",
            "/api/v1/vision/follow/11111111-1111-4111-8111-111111111111/heartbeat",
        ),
    ],
)
def test_actual_motion_routes_reject_commissioning_token_before_command_execution(
    method: str,
    path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        context = real_context(
            hardware_access_policy=HardwareAccessPolicy.READ_ONLY,
            real_motion_enabled=False,
            field_acceptance_status=FieldAcceptanceStatus.PENDING,
            field_acceptance_evidence=None,
        )
        device, _, _ = device_service(context)
        issued = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
            confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        app = create_app(isolated_app_settings(tmp_path, monkeypatch))
        app.state.device_diagnostics_service = device
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.request(
                method,
                path,
                json={},
                headers={"X-MOMO-Operator-Session": (issued.session_token.get_secret_value())},
            )
        assert response.status_code == 403
        assert response.json()["code"] == "OPERATOR_SESSION_SCOPE_INSUFFICIENT"

    asyncio.run(scenario())


def test_field_acceptance_api_requires_commissioning_token_and_full_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        context = real_context(
            hardware_access_policy=HardwareAccessPolicy.READ_ONLY,
            real_motion_enabled=False,
            field_acceptance_status=FieldAcceptanceStatus.PENDING,
            field_acceptance_evidence=None,
        )
        clock = FakeClock()
        device, _, _ = device_service(context, clock=clock)
        repository = FileFieldAcceptanceEvidenceRepository(tmp_path, clock)
        acceptance = FieldAcceptanceService(
            device=device,
            repository=repository,
            clock=clock,
        )
        app = create_app(isolated_app_settings(tmp_path / "app", monkeypatch))
        app.state.device_diagnostics_service = device
        app.state.field_acceptance_service = acceptance
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            before = await client.get("/api/v1/device/field-acceptance")
            assert before.status_code == 200
            assert before.json()["state"] == "MISSING"

            issued = await device.issue_operator_session(
                purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
                confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
                physical_estop_confirmed=True,
            )
            token = issued.session_token.get_secret_value()
            await device.connect(token)
            request_body = {
                "checklist_version": context.field_acceptance_checklist_version,
                "confirmation_text": REQUIRED_FIELD_ACCEPTANCE_CONFIRMATION_TEXT,
                "accepted_by": "synthetic-api-operator",
            }
            missing_token = await client.post(
                "/api/v1/device/field-acceptance",
                json=request_body,
            )
            assert missing_token.status_code == 422
            assert missing_token.json()["code"] == "REQUEST_VALIDATION_ERROR"

            wrong_token = await client.post(
                "/api/v1/device/field-acceptance",
                json=request_body,
                headers={"X-MOMO-Operator-Session": "wrong-token-material-000"},
            )
            assert wrong_token.status_code == 401
            assert wrong_token.json()["code"] == "OPERATOR_SESSION_UNAUTHORIZED"

            wrong_confirmation = await client.post(
                "/api/v1/device/field-acceptance",
                json={**request_body, "confirmation_text": "NOT CONFIRMED"},
                headers={"X-MOMO-Operator-Session": token},
            )
            assert wrong_confirmation.status_code == 422
            assert wrong_confirmation.json()["code"] == "REQUEST_VALIDATION_ERROR"

            stale_checklist = await client.post(
                "/api/v1/device/field-acceptance",
                json={**request_body, "checklist_version": "stale"},
                headers={"X-MOMO-Operator-Session": token},
            )
            assert stale_checklist.status_code == 403
            assert stale_checklist.json()["code"] == "FIELD_ACCEPTANCE_NOT_AUTHORIZABLE"

            accepted = await client.post(
                "/api/v1/device/field-acceptance",
                json=request_body,
                headers={"X-MOMO-Operator-Session": token},
            )
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["state"] == "VALID"
            assert accepted.json()["effective_status"] == "PASSED"
            assert accepted.json()["evidence_id"]

    asyncio.run(scenario())


def test_variant_switch_revokes_old_motion_identity_and_stales_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        context = real_context()
        old_acceptance = context.field_acceptance_evidence
        assert old_acceptance is not None
        device, _, factory = device_service(context)
        issued = await device.issue_operator_session(
            purpose=OperatorSessionPurpose.REAL_MOTION,
            confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        token = issued.session_token.get_secret_value()
        app = create_app(isolated_app_settings(tmp_path, monkeypatch))
        app.state.device_diagnostics_service = device
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            unchanged = await client.put(
                "/api/v1/robot/variant",
                json={"variant": "V2"},
            )
            assert unchanged.status_code == 200, unchanged.text
            assert unchanged.json()["status"]["variant"] == "V2"
            assert (await device.sessions.status()).active is True
            assert device.context.profile == context.profile

            connected = await client.post("/api/v1/robot/connect")
            assert connected.status_code == 200, connected.text
            rejected = await client.put(
                "/api/v1/robot/variant",
                json={"variant": "V1"},
            )
            assert rejected.status_code == 409, rejected.text
            assert (await device.sessions.status()).active is True
            assert device.context.profile == context.profile
            disconnected = await client.post("/api/v1/robot/disconnect")
            assert disconnected.status_code == 200, disconnected.text

            switched = await client.put(
                "/api/v1/robot/variant",
                json={"variant": "V1"},
            )
            assert switched.status_code == 200, switched.text
            assert switched.json()["status"]["variant"] == "V1"

            denied = await client.post(
                "/api/v1/motion/joints",
                json={},
                headers={"X-MOMO-Operator-Session": token},
            )
        assert denied.status_code == 401
        assert denied.json()["code"] == "OPERATOR_SESSION_UNAUTHORIZED"
        assert (await device.sessions.status()).active is False
        assert device.context.profile is None
        assert device.context.calibration is None
        assert device.context.kinematics is None
        assert device.context.device is None
        assert device.context.field_acceptance_evidence == old_acceptance
        state, stale_fields = field_acceptance_evidence_state(device.context)
        assert state is FieldAcceptanceEvidenceState.STALE
        assert {
            "robot_variant",
            "profile_fingerprint",
            "calibration_fingerprint",
            "kinematics_fingerprint",
            "device_fingerprint",
        } <= set(stale_fields)
        assert factory.bus.events == ()

    asyncio.run(scenario())
