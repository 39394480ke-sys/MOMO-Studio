"""Regression contract for the final staged real-commissioning boundary.

Every fixture in this module is synthetic.  No adapter may open, enumerate, read,
or write real hardware while these tests run.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from momo.application.services.operator_session_service import (
    OperatorSessionScopeError,
    OperatorSessionService,
)
from momo.application.services.real_hardware_authorization import RealHardwareAuthorization
from momo.domain.commissioning import (
    COMMISSIONING_MOTION_HARD_CAPS,
    CommissioningSafetyEnvelope,
    FieldAcceptanceBundle,
    FieldAcceptanceCapability,
    FieldAcceptanceEvidence,
    FieldAcceptanceEvidenceState,
    ValidatedFieldAcceptanceBundle,
)
from momo.domain.enums import HardwareAccessPolicy, KinematicsVerificationStatus
from momo.domain.real_hardware import (
    REQUIRED_COMMISSIONING_MOTION_CONFIRMATION_TEXT,
    REQUIRED_RAW_DIRECTION_CONFIRMATION_TEXT,
    OperatorSessionPurpose,
    RealHardwareAuthorizationPurpose,
    RealHardwareGateInput,
    field_acceptance_evidence_state,
)
from tests.stage3_helpers import FakeClock
from tests.stage8_hardware_helpers import real_context


def test_commissioning_motion_is_authorizable_before_final_field_acceptance() -> None:
    base = real_context()
    assert base.kinematics is not None
    pre_motion = base.field_acceptance_bundle.newest_for(
        FieldAcceptanceCapability.PRE_MOTION_CHECKS
    )
    assert pre_motion is not None
    context = base.model_copy(
        update={
            "hardware_access_policy": HardwareAccessPolicy.FULL,
            "real_motion_enabled": False,
            "commissioning_motion_test_enabled": True,
            "kinematics": base.kinematics.model_copy(
                update={"verification_status": KinematicsVerificationStatus.PROVISIONAL_DRY_RUN}
            ),
            "expected_kinematics_fingerprint": base.kinematics.fingerprint,
            "field_acceptance_evidence": pre_motion,
            "field_acceptance_bundle": ValidatedFieldAcceptanceBundle(records=(pre_motion,)),
        }
    )

    report = RealHardwareAuthorization().evaluate(
        RealHardwareGateInput(context=context, evaluated_at=datetime(2026, 1, 1, tzinfo=UTC))
    )

    assert report.commissioning_motion_session_authorizable is True
    assert report.motion_session_authorizable is False
    assert report.capabilities.commissioning_motion_test_ready is False
    assert report.capability_details.commissioning_motion_test.blocked_reasons == (
        "COMMISSIONING_MOTION_SESSION_REQUIRED",
    )


def test_three_session_purposes_are_non_upgradeable() -> None:
    async def scenario() -> None:
        base = real_context()
        pre_motion = base.field_acceptance_bundle.newest_for(
            FieldAcceptanceCapability.PRE_MOTION_CHECKS
        )
        assert pre_motion is not None
        context = base.model_copy(
            update={
                "real_motion_enabled": False,
                "commissioning_motion_test_enabled": True,
                "field_acceptance_evidence": pre_motion,
                "field_acceptance_bundle": ValidatedFieldAcceptanceBundle(records=(pre_motion,)),
            }
        )
        clock = FakeClock()
        sessions = OperatorSessionService(clock, RealHardwareAuthorization(), ttl_s=60.0)
        issued = await sessions.issue(
            context,
            purpose=OperatorSessionPurpose.COMMISSIONING_MOTION_TEST,
            confirmation_text=REQUIRED_COMMISSIONING_MOTION_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
            workspace_clear_confirmed=True,
            operator_id="synthetic-commissioning-operator",
        )
        token = issued.session_token.get_secret_value()

        assert issued.evidence.purpose is OperatorSessionPurpose.COMMISSIONING_MOTION_TEST
        assert issued.evidence.commissioning_envelope == context.commissioning_safety_envelope
        await sessions.authorize(
            token,
            context,
            purpose=RealHardwareAuthorizationPurpose.COMMISSIONING_SINGLE_JOINT_TEST,
        )
        for forbidden in (
            RealHardwareAuthorizationPurpose.DIAGNOSTICS,
            RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION,
            RealHardwareAuthorizationPurpose.REAL_PLAYBACK,
            RealHardwareAuthorizationPurpose.REAL_VISION_FOLLOW,
        ):
            with pytest.raises(OperatorSessionScopeError):
                await sessions.authorize(token, context, purpose=forbidden)

    asyncio.run(scenario())


def test_raw_direction_session_is_authorizable_without_calibration_and_cannot_upgrade() -> None:
    async def scenario() -> None:
        context = real_context(
            real_motion_enabled=False,
            raw_direction_test_enabled=True,
            raw_direction_adapter_ready=True,
            calibration=None,
            kinematics=None,
            expected_kinematics_fingerprint=None,
        )
        clock = FakeClock()
        authorization = RealHardwareAuthorization()
        report = authorization.evaluate(
            RealHardwareGateInput(context=context, evaluated_at=clock.now())
        )
        assert report.raw_direction_session_authorizable is True
        assert report.commissioning_motion_session_authorizable is False
        assert report.capability_details.raw_direction_test.blocked_reasons == (
            "RAW_DIRECTION_SESSION_REQUIRED",
        )

        sessions = OperatorSessionService(clock, authorization, ttl_s=60.0)
        issued = await sessions.issue(
            context,
            purpose=OperatorSessionPurpose.RAW_DIRECTION_TEST,
            confirmation_text=REQUIRED_RAW_DIRECTION_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
            workspace_clear_confirmed=True,
            operator_id="synthetic-raw-operator",
        )
        token = issued.session_token.get_secret_value()
        assert issued.evidence.calibration_fingerprint is None
        assert issued.evidence.raw_direction_envelope == context.raw_direction_safety_envelope
        await sessions.authorize(
            token,
            context,
            purpose=RealHardwareAuthorizationPurpose.RAW_DIRECTION_TEST,
        )
        for forbidden in (
            RealHardwareAuthorizationPurpose.DIAGNOSTICS,
            RealHardwareAuthorizationPurpose.COMMISSIONING_SINGLE_JOINT_TEST,
            RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION,
            RealHardwareAuthorizationPurpose.REAL_PLAYBACK,
            RealHardwareAuthorizationPurpose.REAL_VISION_FOLLOW,
        ):
            with pytest.raises(OperatorSessionScopeError):
                await sessions.authorize(token, context, purpose=forbidden)

    asyncio.run(scenario())


def test_local_config_can_shrink_but_cannot_expand_commissioning_hard_caps() -> None:
    narrowed = CommissioningSafetyEnvelope(
        max_active_joints=1,
        max_command_duration_s=COMMISSIONING_MOTION_HARD_CAPS.max_command_duration_s / 2,
        max_session_duration_s=COMMISSIONING_MOTION_HARD_CAPS.max_session_duration_s / 2,
        max_revolute_delta_deg=COMMISSIONING_MOTION_HARD_CAPS.max_revolute_delta_deg / 2,
        max_prismatic_delta_mm=COMMISSIONING_MOTION_HARD_CAPS.max_prismatic_delta_mm / 2,
        max_revolute_speed_deg_s=(COMMISSIONING_MOTION_HARD_CAPS.max_revolute_speed_deg_s / 2),
        max_prismatic_speed_mm_s=(COMMISSIONING_MOTION_HARD_CAPS.max_prismatic_speed_mm_s / 2),
        max_revolute_acceleration_deg_s2=(
            COMMISSIONING_MOTION_HARD_CAPS.max_revolute_acceleration_deg_s2 / 2
        ),
        max_prismatic_acceleration_mm_s2=(
            COMMISSIONING_MOTION_HARD_CAPS.max_prismatic_acceleration_mm_s2 / 2
        ),
        deadman_lease_ms=COMMISSIONING_MOTION_HARD_CAPS.deadman_lease_ms // 2,
        max_commands_per_session=COMMISSIONING_MOTION_HARD_CAPS.max_commands_per_session // 2,
    )
    assert narrowed.max_active_joints == 1

    with pytest.raises(ValidationError, match="max_revolute_delta_deg"):
        CommissioningSafetyEnvelope(
            **{
                **COMMISSIONING_MOTION_HARD_CAPS.model_dump(),
                "max_revolute_delta_deg": (
                    COMMISSIONING_MOTION_HARD_CAPS.max_revolute_delta_deg + 0.01
                ),
            }
        )


def test_legacy_global_passed_evidence_is_stale_and_has_no_capability_authority() -> None:
    context = real_context()
    assert context.profile is not None
    assert context.calibration is not None
    assert context.device is not None
    assert context.kinematics is not None
    legacy = FieldAcceptanceEvidence.model_validate(
        {
            "schema_version": 1,
            "revision": 1,
            "status": "PASSED",
            "robot_variant": context.profile.variant,
            "profile_fingerprint": context.profile.fingerprint,
            "calibration_fingerprint": context.calibration_fingerprint,
            "kinematics_fingerprint": context.kinematics.fingerprint,
            "device_fingerprint": context.device_fingerprint,
            "checklist_version": context.field_acceptance_checklist_version,
            "accepted_at": "2026-01-01T00:00:00Z",
            "accepted_by": "legacy-operator",
        }
    )
    stale_context = context.model_copy(
        update={
            "field_acceptance_evidence": legacy,
            "field_acceptance_bundle": FieldAcceptanceBundle(records=(legacy,)),
        }
    )

    state, stale_fields = field_acceptance_evidence_state(stale_context, legacy)
    assert state is FieldAcceptanceEvidenceState.STALE_LEGACY_EVIDENCE
    assert "robot_unit_id" in stale_fields
    assert FieldAcceptanceCapability.JOINT_MOTION not in (
        stale_context.field_acceptance_bundle.valid_capabilities(stale_context)
    )


def test_robot_unit_change_stales_new_capability_evidence() -> None:
    context = real_context()
    evidence = FieldAcceptanceEvidence.for_capability(
        context=context,
        capability=FieldAcceptanceCapability.JOINT_MOTION,
        checklist_version=context.field_acceptance_checklist_version,
        test_evidence_ids=("00000000-0000-4000-8000-000000000001",),
        accepted_at=datetime(2026, 1, 1, tzinfo=UTC),
        accepted_by="synthetic-reviewer",
        software_commit="synthetic-test-commit",
    )
    changed = context.model_copy(update={"robot_unit_id": "MOMO-V2-UNIT-999"})

    state, stale_fields = field_acceptance_evidence_state(changed, evidence)
    assert state is FieldAcceptanceEvidenceState.STALE
    assert "robot_unit_id" in stale_fields
