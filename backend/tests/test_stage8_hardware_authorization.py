"""Stage 8 fail-closed real-hardware authorization and session tests."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from pydantic import ValidationError

from momo.application.services.operator_session_service import (
    OperatorConfirmationError,
    OperatorSessionPrerequisiteError,
    OperatorSessionScopeError,
    OperatorSessionService,
    OperatorSessionTokenError,
)
from momo.application.services.real_hardware_authorization import (
    RealHardwareAuthorization,
)
from momo.domain.enums import (
    ControlMode,
    HardwareAccessPolicy,
    KinematicsVerificationStatus,
    ProfileVerificationStatus,
)
from momo.domain.real_hardware import (
    REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
    REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
    ExplicitServoDevice,
    FieldAcceptanceStatus,
    HardwareDependencyState,
    OperatorSessionPurpose,
    RealHardwareAuthorizationPurpose,
    RealHardwareBlocker,
    RealHardwareContext,
    RealHardwareGateInput,
    RealHardwareReadinessReport,
    RealHardwareReadinessState,
)
from tests.stage3_helpers import FakeClock
from tests.stage8_hardware_helpers import real_calibration, real_context, real_profile


def evaluate(
    context: RealHardwareContext,
    clock: FakeClock,
    *,
    session: object | None = None,
) -> RealHardwareReadinessReport:
    return RealHardwareAuthorization().evaluate(
        RealHardwareGateInput.model_validate(
            {
                "context": context,
                "evaluated_at": clock.now(),
                "operator_session": session,
            }
        )
    )


def test_safe_defaults_are_not_session_authorizable() -> None:
    report = evaluate(RealHardwareContext(), FakeClock())

    assert report.ready is False
    assert report.session_authorizable is False
    assert report.state is RealHardwareReadinessState.BLOCKED_BY_CONTROL_MODE
    assert RealHardwareBlocker.CONTROL_MODE_MUST_BE_REAL in report.blocking_reasons
    assert RealHardwareBlocker.HARDWARE_POLICY_MUST_BE_FULL in report.blocking_reasons
    assert RealHardwareBlocker.REAL_MOTION_NOT_ENABLED in report.blocking_reasons
    assert RealHardwareBlocker.STARTUP_HARDWARE_FLAG_MISSING in report.blocking_reasons
    assert RealHardwareBlocker.EXPLICIT_LOCAL_CONFIG_MISSING in report.blocking_reasons
    assert report.confirmation.masked_serial_port is None
    assert report.confirmation.masked_servo_ids == ()
    assert report.capabilities.real_joint_motion_ready is False
    assert report.capabilities.real_cartesian_motion_ready is False
    assert report.capabilities.real_playback_ready is False
    assert report.capabilities.real_vision_follow_ready is False


@pytest.mark.parametrize(
    ("updates", "blocker"),
    [
        ({"control_mode": ControlMode.DRY_RUN}, RealHardwareBlocker.CONTROL_MODE_MUST_BE_REAL),
        (
            {"hardware_access_policy": HardwareAccessPolicy.DISABLED},
            RealHardwareBlocker.HARDWARE_POLICY_MUST_BE_FULL,
        ),
        ({"real_motion_enabled": False}, RealHardwareBlocker.REAL_MOTION_NOT_ENABLED),
        (
            {"startup_hardware_enabled": False},
            RealHardwareBlocker.STARTUP_HARDWARE_FLAG_MISSING,
        ),
        (
            {"explicit_local_config": False},
            RealHardwareBlocker.EXPLICIT_LOCAL_CONFIG_MISSING,
        ),
        ({"profile": None}, RealHardwareBlocker.PROFILE_MISSING),
        ({"calibration": None}, RealHardwareBlocker.CALIBRATION_MISSING),
        ({"kinematics": None}, RealHardwareBlocker.KINEMATICS_MISSING),
        (
            {"expected_kinematics_fingerprint": None},
            RealHardwareBlocker.KINEMATICS_FINGERPRINT_MISSING,
        ),
        (
            {"field_acceptance_status": FieldAcceptanceStatus.PENDING},
            RealHardwareBlocker.FIELD_ACCEPTANCE_NOT_PASSED,
        ),
        (
            {"dependency_state": HardwareDependencyState.PENDING_ADAPTER_VERIFICATION},
            RealHardwareBlocker.SERVO_BUS_DEPENDENCY_UNAVAILABLE,
        ),
        (
            {"dependency_adapter_id": None},
            RealHardwareBlocker.SERVO_BUS_DEPENDENCY_IDENTITY_MISSING,
        ),
        ({"device": None}, RealHardwareBlocker.EXPLICIT_DEVICE_MISSING),
    ],
)
def test_no_single_gate_can_make_hardware_ready(
    updates: dict[str, object],
    blocker: RealHardwareBlocker,
) -> None:
    report = evaluate(real_context(**updates), FakeClock())

    assert report.ready is False
    assert blocker in report.blocking_reasons


def test_profile_calibration_kinematics_and_explicit_ids_must_match() -> None:
    clock = FakeClock()
    good = real_context()
    profile = real_profile()
    unverified_profile = profile.model_copy(
        update={"verification_status": ProfileVerificationStatus.VERIFIED_FOR_DRY_RUN}
    )
    report = evaluate(real_context(profile=unverified_profile), clock)
    assert RealHardwareBlocker.PROFILE_NOT_VERIFIED_FOR_REAL in report.blocking_reasons

    changed_profile_data = profile.model_dump(mode="python")
    changed_profile_data["joint_definitions"][0]["raw_counts_per_motor_revolution"] += 1.0
    changed_profile = type(profile).model_validate(changed_profile_data)
    report = evaluate(real_context(profile=changed_profile), clock)
    assert RealHardwareBlocker.CALIBRATION_PROFILE_MISMATCH in report.blocking_reasons

    calibration = real_calibration(profile).model_copy(update={"template": True})
    report = evaluate(real_context(profile=profile, calibration=calibration), clock)
    assert RealHardwareBlocker.CALIBRATION_IS_TEMPLATE in report.blocking_reasons

    assert good.kinematics is not None
    provisional = good.kinematics.model_copy(
        update={"verification_status": KinematicsVerificationStatus.PROVISIONAL_DRY_RUN}
    )
    report = evaluate(real_context(kinematics=provisional), clock)
    assert RealHardwareBlocker.KINEMATICS_NOT_VERIFIED_FOR_REAL in report.blocking_reasons
    report = evaluate(real_context(expected_kinematics_fingerprint="f" * 64), clock)
    assert RealHardwareBlocker.KINEMATICS_FINGERPRINT_MISMATCH in report.blocking_reasons

    assert good.calibration is not None
    incomplete_joint = good.calibration.joints[0].model_copy(update={"home_present_raw": None})
    incomplete = good.calibration.model_copy(
        update={"joints": [incomplete_joint, *good.calibration.joints[1:]]}
    )
    report = evaluate(real_context(calibration=incomplete), clock)
    assert RealHardwareBlocker.CALIBRATION_INCOMPLETE in report.blocking_reasons

    assert good.device is not None
    mismatched_device = ExplicitServoDevice(
        serial_port=good.device.serial_port,
        protocol=good.device.protocol,
        servo_ids=tuple(reversed(good.device.servo_ids)),
    )
    report = evaluate(real_context(device=mismatched_device), clock)
    assert RealHardwareBlocker.DEVICE_SERVO_IDS_MISMATCH in report.blocking_reasons


def test_explicit_device_rejects_scan_like_or_invalid_id_contracts() -> None:
    with pytest.raises(ValidationError, match="at least one explicit servo ID"):
        ExplicitServoDevice(serial_port="/dev/fake", protocol="SCS", servo_ids=())
    with pytest.raises(ValidationError, match="must be unique"):
        ExplicitServoDevice(serial_port="/dev/fake", protocol="SCS", servo_ids=(1, 1))
    with pytest.raises(ValidationError):
        ExplicitServoDevice(serial_port="/dev/fake", protocol="SCS", servo_ids=(0,))
    short = ExplicitServoDevice(serial_port="COM3", protocol="SCS", servo_ids=(1,))
    assert short.masked_serial_port != short.serial_port
    assert "COM3" not in short.masked_serial_port


def test_all_nonoperator_gates_yield_exact_authorizable_state_and_confirmation() -> None:
    context = real_context()
    assert context.device is not None
    report = evaluate(context, FakeClock())

    assert report.state is RealHardwareReadinessState.AWAITING_OPERATOR_SESSION
    assert report.ready is False
    assert report.session_authorizable is True
    assert report.blocking_reasons == (RealHardwareBlocker.OPERATOR_SESSION_MISSING,)
    assert report.confirmation.required_confirmation_text == (
        REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT
    )
    assert report.confirmation.physical_estop_required is True
    assert report.confirmation.masked_serial_port != context.device.serial_port
    assert all(str(servo_id) not in report.confirmation.masked_servo_ids for servo_id in (1, 2))


def test_fresh_robot_commissioning_is_read_only_without_calibration_or_acceptance() -> None:
    async def scenario() -> None:
        base = real_context()
        assert base.kinematics is not None
        context = base.model_copy(
            update={
                "hardware_access_policy": HardwareAccessPolicy.READ_ONLY,
                "real_motion_enabled": False,
                "calibration": None,
                "kinematics": base.kinematics.model_copy(
                    update={
                        "verification_status": (KinematicsVerificationStatus.PROVISIONAL_DRY_RUN)
                    }
                ),
                "field_acceptance_status": FieldAcceptanceStatus.PENDING,
                "field_acceptance_evidence": None,
            }
        )
        clock = FakeClock()
        authorization = RealHardwareAuthorization()
        before = evaluate(context, clock)

        assert before.commissioning_session_authorizable is True
        assert before.motion_session_authorizable is False
        assert before.capabilities.commissioning_diagnostics_ready is True
        assert before.capabilities.calibration_capture_ready is True
        assert before.capabilities.real_joint_motion_ready is False
        assert before.capabilities.real_cartesian_motion_ready is False
        assert before.capabilities.real_playback_ready is False
        assert before.capabilities.real_vision_follow_ready is False

        sessions = OperatorSessionService(clock, authorization, ttl_s=60.0)
        issued = await sessions.issue(
            context,
            purpose=OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
            confirmation_text=REQUIRED_COMMISSIONING_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        token = issued.session_token.get_secret_value()
        assert issued.evidence.purpose is OperatorSessionPurpose.COMMISSIONING_READ_ONLY
        assert issued.evidence.calibration_fingerprint is None
        assert issued.evidence.kinematics_fingerprint is None
        assert issued.evidence.device_fingerprint
        await sessions.authorize(
            token,
            context,
            purpose=RealHardwareAuthorizationPurpose.DIAGNOSTICS,
        )
        with pytest.raises(OperatorSessionScopeError):
            await sessions.authorize(
                token,
                context,
                purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            )

        # Later artifacts cannot upgrade the immutable commissioning scope.
        with pytest.raises(OperatorSessionScopeError):
            await sessions.authorize(
                token,
                real_context(),
                purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            )
        clock.elapse(61.0)
        with pytest.raises(OperatorSessionTokenError, match="expired"):
            await sessions.authorize(
                token,
                context,
                purpose=RealHardwareAuthorizationPurpose.DIAGNOSTICS,
            )

    asyncio.run(scenario())


def test_operator_confirmation_must_be_exact_and_estop_explicit() -> None:
    async def scenario() -> None:
        context = real_context()
        clock = FakeClock()
        sessions = OperatorSessionService(clock, RealHardwareAuthorization(), ttl_s=60.0)

        with pytest.raises(OperatorConfirmationError):
            await sessions.issue(
                context,
                confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT.lower(),
                physical_estop_confirmed=True,
            )
        with pytest.raises(OperatorConfirmationError):
            await sessions.issue(
                context,
                confirmation_text="我确认真实硬件可以移动",
                physical_estop_confirmed=True,
            )
        with pytest.raises(OperatorConfirmationError):
            await sessions.issue(
                context,
                confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
                physical_estop_confirmed=False,
            )
        with pytest.raises(OperatorSessionPrerequisiteError):
            await sessions.issue(
                context.model_copy(update={"startup_hardware_enabled": False}),
                confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
                physical_estop_confirmed=True,
            )

    asyncio.run(scenario())


def test_token_is_in_memory_single_active_short_lived_and_never_in_evidence() -> None:
    async def scenario() -> None:
        context = real_context()
        clock = FakeClock()
        authorization = RealHardwareAuthorization()
        sessions = OperatorSessionService(clock, authorization, ttl_s=60.0)

        first = await sessions.issue(
            context,
            confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        first_token = first.session_token.get_secret_value()
        assert first_token not in repr(first)
        assert "session_token" not in first.evidence.model_dump()
        assert first_token not in first.model_dump_json()
        assert first.evidence.control_mode is ControlMode.REAL
        assert first.evidence.hardware_access_policy is HardwareAccessPolicy.FULL
        assert first.evidence.field_acceptance_evidence_id == (
            context.field_acceptance_evidence.evidence_id
            if context.field_acceptance_evidence is not None
            else None
        )

        second = await sessions.issue(
            context,
            confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        second_token = second.session_token.get_secret_value()
        assert second_token != first_token
        with pytest.raises(OperatorSessionTokenError):
            await sessions.authorize(
                first_token,
                context,
                purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            )

        evidence = await sessions.authorize(
            second_token,
            context,
            purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
        )
        report = authorization.evaluate(
            RealHardwareGateInput(
                context=context,
                evaluated_at=clock.now(),
                operator_session=evidence,
            )
        )
        assert report.ready is True
        assert report.session_authorizable is False
        assert report.state is RealHardwareReadinessState.READY

        restarted = OperatorSessionService(clock, authorization, ttl_s=60.0)
        with pytest.raises(OperatorSessionTokenError):
            await restarted.authorize(
                second_token,
                context,
                purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            )

        clock.elapse(61.0)
        expired_report = authorization.evaluate(
            RealHardwareGateInput(
                context=context,
                evaluated_at=clock.now(),
                operator_session=second.evidence,
            )
        )
        assert RealHardwareBlocker.OPERATOR_SESSION_EXPIRED in (expired_report.blocking_reasons)
        assert (await sessions.status()).active is False
        with pytest.raises(OperatorSessionTokenError):
            await sessions.authorize(
                second_token,
                context,
                purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            )

    asyncio.run(scenario())


def test_context_drift_revokes_effective_authorization() -> None:
    async def scenario() -> None:
        context = real_context()
        clock = FakeClock()
        sessions = OperatorSessionService(clock, RealHardwareAuthorization(), ttl_s=60.0)
        issued = await sessions.issue(
            context,
            confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        token = issued.session_token.get_secret_value()

        assert context.calibration is not None
        changed_joint = context.calibration.joints[0].model_copy(update={"home_present_raw": 1})
        changed_calibration = context.calibration.model_copy(
            update={"joints": [changed_joint, *context.calibration.joints[1:]]}
        )
        changed_context = context.model_copy(update={"calibration": changed_calibration})
        mismatch = RealHardwareAuthorization().evaluate(
            RealHardwareGateInput(
                context=changed_context,
                evaluated_at=clock.now(),
                operator_session=issued.evidence,
            )
        )
        assert RealHardwareBlocker.OPERATOR_SESSION_MISMATCH in mismatch.blocking_reasons
        with pytest.raises(OperatorSessionTokenError, match="context changed"):
            await sessions.authorize(
                token,
                changed_context,
                purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            )

        assert context.device is not None
        changed_device = context.device.model_copy(
            update={"serial_port": "/another/synthetic/path/ened"}
        )
        port_drift = context.model_copy(update={"device": changed_device})
        assert changed_device.masked_serial_port == context.device.masked_serial_port
        with pytest.raises(OperatorSessionTokenError, match="context changed"):
            await sessions.authorize(
                token,
                port_drift,
                purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            )
        assert await sessions.current_evidence(port_drift) is None

        assert context.field_acceptance_evidence is not None
        replacement_acceptance = context.field_acceptance_evidence.model_copy(
            update={"evidence_id": uuid4()}
        )
        acceptance_drift = context.model_copy(
            update={"field_acceptance_evidence": replacement_acceptance}
        )
        mismatch = RealHardwareAuthorization().evaluate(
            RealHardwareGateInput(
                context=acceptance_drift,
                evaluated_at=clock.now(),
                operator_session=issued.evidence,
            )
        )
        assert RealHardwareBlocker.OPERATOR_SESSION_MISMATCH in mismatch.blocking_reasons
        with pytest.raises(OperatorSessionTokenError, match="context changed"):
            await sessions.authorize(
                token,
                acceptance_drift,
                purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            )

        with pytest.raises(OperatorSessionTokenError, match="context changed"):
            await sessions.authorize(
                token,
                context.model_copy(
                    update={"field_acceptance_status": FieldAcceptanceStatus.FAILED}
                ),
                purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            )

    asyncio.run(scenario())


def test_provisional_kinematics_allows_joint_only_but_blocks_geometry_capabilities() -> None:
    async def scenario() -> None:
        context = real_context()
        assert context.kinematics is not None
        provisional = context.kinematics.model_copy(
            update={"verification_status": KinematicsVerificationStatus.PROVISIONAL_DRY_RUN}
        )
        context = context.model_copy(update={"kinematics": provisional})
        clock = FakeClock()
        authorization = RealHardwareAuthorization()
        sessions = OperatorSessionService(clock, authorization, ttl_s=60.0)

        before = await sessions.issue(
            context,
            confirmation_text=REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
            physical_estop_confirmed=True,
        )
        token = before.session_token.get_secret_value()
        evidence = await sessions.authorize(
            token,
            context,
            purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
        )
        report = authorization.evaluate(
            RealHardwareGateInput(
                context=context,
                evaluated_at=clock.now(),
                operator_session=evidence,
            )
        )

        assert report.ready is False
        assert report.state is RealHardwareReadinessState.BLOCKED_BY_KINEMATICS
        assert report.capabilities.real_joint_motion_ready is True
        assert report.capabilities.real_cartesian_motion_ready is False
        assert report.capabilities.real_playback_ready is False
        assert report.capabilities.real_vision_follow_ready is False
        for purpose in (
            RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION,
            RealHardwareAuthorizationPurpose.REAL_PLAYBACK,
            RealHardwareAuthorizationPurpose.REAL_VISION_FOLLOW,
        ):
            with pytest.raises(OperatorSessionScopeError):
                await sessions.authorize(token, context, purpose=purpose)

        upgraded_kinematics = provisional.model_copy(
            update={"verification_status": KinematicsVerificationStatus.VERIFIED_FOR_REAL}
        )
        upgraded_context = context.model_copy(update={"kinematics": upgraded_kinematics})
        with pytest.raises(OperatorSessionScopeError):
            await sessions.authorize(
                token,
                upgraded_context,
                purpose=RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION,
            )
        assert await sessions.current_evidence(upgraded_context) is None

    asyncio.run(scenario())
