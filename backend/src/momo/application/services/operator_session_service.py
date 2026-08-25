"""Short-lived, in-memory, single-owner operator authorization tokens."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import timedelta
from math import isfinite
from uuid import uuid4

from pydantic import SecretStr

from momo.application.services.real_hardware_authorization import (
    RealHardwareAuthorization,
)
from momo.domain.commissioning import FieldAcceptanceCapability
from momo.domain.enums import ControlMode, HardwareAccessPolicy
from momo.domain.errors import RobotApplicationError
from momo.domain.real_hardware import (
    AUTHORIZATION_PURPOSE_SCOPE,
    COMMISSIONING_MOTION_SCOPES,
    COMMISSIONING_SCOPES,
    IssuedOperatorSession,
    OperatorSessionEvidence,
    OperatorSessionPurpose,
    OperatorSessionScope,
    OperatorSessionStatus,
    RealHardwareAuthorizationPurpose,
    RealHardwareContext,
    RealHardwareGateInput,
    calibration_fingerprint,
    confirmation_text_for,
    explicit_device_fingerprint,
)
from momo.ports.clock import Clock


class OperatorSessionPrerequisiteError(RobotApplicationError):
    code = "OPERATOR_SESSION_NOT_AUTHORIZABLE"
    status_code = 403


class OperatorConfirmationError(RobotApplicationError):
    code = "OPERATOR_CONFIRMATION_INVALID"
    status_code = 422


class OperatorSessionTokenError(RobotApplicationError):
    code = "OPERATOR_SESSION_UNAUTHORIZED"
    status_code = 401


class OperatorSessionScopeError(RobotApplicationError):
    code = "OPERATOR_SESSION_SCOPE_INSUFFICIENT"
    status_code = 403


@dataclass(frozen=True, slots=True)
class _ActiveOperatorSession:
    token_digest: bytes
    context_digest: bytes
    evidence: OperatorSessionEvidence


class OperatorSessionService:
    """Tokens live only in this instance; a Backend restart invalidates all of them."""

    def __init__(
        self,
        clock: Clock,
        authorization: RealHardwareAuthorization,
        *,
        ttl_s: float = 300.0,
    ) -> None:
        if not isfinite(ttl_s) or ttl_s < 30.0 or ttl_s > 900.0:
            raise ValueError("operator session ttl_s must be between 30 and 900 seconds")
        self.clock = clock
        self.authorization = authorization
        self.ttl_s = float(ttl_s)
        self._guard = asyncio.Lock()
        self._active: _ActiveOperatorSession | None = None

    async def issue(
        self,
        context: RealHardwareContext,
        *,
        purpose: OperatorSessionPurpose | None = None,
        confirmation_text: str,
        physical_estop_confirmed: bool,
        workspace_clear_confirmed: bool = False,
        operator_id: str = "operator",
    ) -> IssuedOperatorSession:
        """Replace any prior token only after every non-operator gate passes."""

        now = self.clock.now()
        if purpose is not None:
            resolved_purpose = purpose
        elif context.hardware_access_policy is HardwareAccessPolicy.READ_ONLY:
            resolved_purpose = OperatorSessionPurpose.COMMISSIONING_READ_ONLY
        elif context.commissioning_motion_test_enabled and (
            FieldAcceptanceCapability.JOINT_MOTION
            not in context.field_acceptance_bundle.valid_capabilities(context)
        ):
            resolved_purpose = OperatorSessionPurpose.COMMISSIONING_MOTION_TEST
        else:
            resolved_purpose = OperatorSessionPurpose.REAL_MOTION
        report = self.authorization.evaluate(
            RealHardwareGateInput(context=context, evaluated_at=now)
        )
        purpose_authorizable = {
            OperatorSessionPurpose.COMMISSIONING_READ_ONLY: (
                report.commissioning_session_authorizable
            ),
            OperatorSessionPurpose.COMMISSIONING_MOTION_TEST: (
                report.commissioning_motion_session_authorizable
            ),
            OperatorSessionPurpose.REAL_MOTION: report.motion_session_authorizable,
        }[resolved_purpose]
        if not purpose_authorizable:
            raise OperatorSessionPrerequisiteError(
                "Operator session prerequisites are not satisfied",
                details={
                    "state": report.state.value,
                    "blocking_reasons": [item.value for item in report.blocking_reasons],
                },
            )
        expected_confirmation = confirmation_text_for(resolved_purpose)
        if not isinstance(confirmation_text, str) or not secrets.compare_digest(
            confirmation_text.encode("utf-8"),
            expected_confirmation.encode("utf-8"),
        ):
            raise OperatorConfirmationError(
                "The required operator-session confirmation text did not match exactly"
            )
        if physical_estop_confirmed is not True:
            raise OperatorConfirmationError(
                "Physical E-stop readiness must be explicitly confirmed"
            )
        if (
            resolved_purpose is OperatorSessionPurpose.COMMISSIONING_MOTION_TEST
            and workspace_clear_confirmed is not True
        ):
            raise OperatorConfirmationError(
                "Commissioning motion tests require explicit workspace-clear confirmation"
            )
        if not isinstance(operator_id, str) or not operator_id.strip() or len(operator_id) > 128:
            raise OperatorConfirmationError("An explicit bounded operator identity is required")

        profile = context.profile
        calibration = context.calibration
        device = context.device
        if profile is None or device is None or context.robot_id is None:
            raise OperatorSessionPrerequisiteError(
                "Operator session identity evidence is incomplete"
            )
        if (
            resolved_purpose
            in {
                OperatorSessionPurpose.COMMISSIONING_MOTION_TEST,
                OperatorSessionPurpose.REAL_MOTION,
            }
            and calibration is None
        ):
            raise OperatorSessionPrerequisiteError(
                "Motion-session calibration evidence is incomplete"
            )
        raw_token = secrets.token_urlsafe(32)
        issued_at = now
        session_ttl_s = self.ttl_s
        if resolved_purpose is OperatorSessionPurpose.COMMISSIONING_MOTION_TEST:
            session_ttl_s = min(
                session_ttl_s,
                context.commissioning_safety_envelope.max_session_duration_s,
            )
        expires_at = now + timedelta(seconds=session_ttl_s)
        scopes = {
            OperatorSessionPurpose.COMMISSIONING_READ_ONLY: COMMISSIONING_SCOPES,
            OperatorSessionPurpose.COMMISSIONING_MOTION_TEST: COMMISSIONING_MOTION_SCOPES,
            OperatorSessionPurpose.REAL_MOTION: frozenset({OperatorSessionScope.REAL_JOINT_MOTION}),
        }[resolved_purpose]
        joint_acceptance = context.field_acceptance_bundle.newest_for(
            FieldAcceptanceCapability.JOINT_MOTION
        )
        pre_motion = context.field_acceptance_bundle.newest_for(
            FieldAcceptanceCapability.PRE_MOTION_CHECKS
        )
        evidence = OperatorSessionEvidence(
            session_id=uuid4(),
            purpose=resolved_purpose,
            scopes=scopes,
            robot_id=context.robot_id,
            robot_unit_id=context.robot_unit_id,
            operator_id=operator_id.strip(),
            variant=profile.variant,
            profile_fingerprint=profile.fingerprint,
            calibration_fingerprint=(
                calibration_fingerprint(calibration)
                if calibration is not None
                and resolved_purpose
                in {
                    OperatorSessionPurpose.COMMISSIONING_MOTION_TEST,
                    OperatorSessionPurpose.REAL_MOTION,
                }
                else None
            ),
            kinematics_fingerprint=(
                context.kinematics.fingerprint
                if context.kinematics is not None
                and resolved_purpose is OperatorSessionPurpose.REAL_MOTION
                else None
            ),
            field_acceptance_evidence_id=(
                joint_acceptance.evidence_id
                if joint_acceptance is not None
                and resolved_purpose is OperatorSessionPurpose.REAL_MOTION
                else None
            ),
            pre_motion_evidence_id=(
                pre_motion.evidence_id
                if pre_motion is not None
                and resolved_purpose is OperatorSessionPurpose.COMMISSIONING_MOTION_TEST
                else None
            ),
            commissioning_envelope=(
                context.commissioning_safety_envelope
                if resolved_purpose is OperatorSessionPurpose.COMMISSIONING_MOTION_TEST
                else None
            ),
            device_fingerprint=explicit_device_fingerprint(device),
            allowed_servo_ids=device.servo_ids,
            issued_at=issued_at,
            expires_at=expires_at,
            confirmed=True,
            physical_estop_confirmed=True,
            workspace_clear_confirmed=(
                resolved_purpose is OperatorSessionPurpose.COMMISSIONING_MOTION_TEST
            ),
            control_mode=ControlMode.REAL,
            hardware_access_policy=context.hardware_access_policy,
        )
        issued_report = self.authorization.evaluate(
            RealHardwareGateInput(
                context=context,
                evaluated_at=now,
                operator_session=evidence,
            )
        )
        if resolved_purpose is OperatorSessionPurpose.REAL_MOTION:
            expanded_scopes = {OperatorSessionScope.REAL_JOINT_MOTION}
            if issued_report.capabilities.real_cartesian_motion_ready:
                expanded_scopes.add(OperatorSessionScope.REAL_CARTESIAN_MOTION)
            if issued_report.capabilities.real_playback_ready:
                expanded_scopes.add(OperatorSessionScope.REAL_PLAYBACK)
            if issued_report.capabilities.real_vision_follow_ready:
                expanded_scopes.add(OperatorSessionScope.REAL_VISION_FOLLOW)
            evidence = evidence.model_copy(update={"scopes": frozenset(expanded_scopes)})
            # Re-evaluate the exact final immutable evidence before publishing it.
            self.authorization.evaluate(
                RealHardwareGateInput(
                    context=context,
                    evaluated_at=now,
                    operator_session=evidence,
                )
            )
        active = _ActiveOperatorSession(
            token_digest=_digest(raw_token),
            context_digest=_context_digest(context, resolved_purpose),
            evidence=evidence,
        )
        async with self._guard:
            self._active = active
        return IssuedOperatorSession(
            session_token=SecretStr(raw_token),
            evidence=evidence,
        )

    async def authorize(
        self,
        token: str,
        context: RealHardwareContext,
        *,
        purpose: RealHardwareAuthorizationPurpose,
    ) -> OperatorSessionEvidence:
        if not token:
            raise OperatorSessionTokenError("Operator session token is required")
        now = self.clock.now()
        async with self._guard:
            active = self._active
            if active is None:
                raise OperatorSessionTokenError("Operator session is not active")
            if now >= active.evidence.expires_at:
                raise OperatorSessionTokenError("Operator session has expired")
            if not secrets.compare_digest(_digest(token), active.token_digest):
                raise OperatorSessionTokenError("Operator session token is invalid")
            evidence = active.evidence
            required_scope = AUTHORIZATION_PURPOSE_SCOPE[purpose]
            if required_scope not in evidence.scopes:
                raise OperatorSessionScopeError(
                    "Operator session scope does not authorize this hardware capability",
                    details={
                        "session_purpose": evidence.purpose.value,
                        "required_scope": required_scope.value,
                    },
                )
            if not secrets.compare_digest(
                _context_digest(context, evidence.purpose),
                active.context_digest,
            ):
                raise OperatorSessionTokenError(
                    "Operator session context changed; a new confirmation is required"
                )
            # Context drift (Profile, calibration, IDs, mode, policy, acceptance)
            # is checked on every use. Keeping the pure check inside the guard
            # prevents a replaced token from winning an authorization race.
            self.authorization.require_authorized(
                RealHardwareGateInput(
                    context=context,
                    evaluated_at=now,
                    operator_session=evidence,
                ),
                purpose=purpose,
            )
            return evidence

    async def status(self) -> OperatorSessionStatus:
        now = self.clock.now()
        async with self._guard:
            active = self._active
            if active is None:
                return OperatorSessionStatus(active=False)
            if now >= active.evidence.expires_at:
                return OperatorSessionStatus(active=False)
            return OperatorSessionStatus(
                active=True,
                session_id=active.evidence.session_id,
                expires_at=active.evidence.expires_at,
                purpose=active.evidence.purpose,
                scopes=active.evidence.scopes,
            )

    async def current_evidence(
        self,
        context: RealHardwareContext,
    ) -> OperatorSessionEvidence | None:
        """Return token-free evidence for readiness display, never for control."""

        now = self.clock.now()
        async with self._guard:
            active = self._active
            if active is None:
                return None
            if now >= active.evidence.expires_at:
                return None
            if not secrets.compare_digest(
                _context_digest(context, active.evidence.purpose),
                active.context_digest,
            ):
                return None
            return active.evidence

    async def revoke(self, token: str) -> None:
        if not token:
            raise OperatorSessionTokenError("Operator session token is required")
        async with self._guard:
            active = self._active
            if active is None:
                return
            if not secrets.compare_digest(_digest(token), active.token_digest):
                raise OperatorSessionTokenError("Operator session token is invalid")
            self._active = None

    async def invalidate(self) -> None:
        """Fail-closed internal cleanup for connect failure, disconnect, and shutdown."""

        async with self._guard:
            self._active = None


def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def _context_digest(
    context: RealHardwareContext,
    purpose: OperatorSessionPurpose,
) -> bytes:
    """Bind a session to exact safety inputs without retaining raw device config."""

    profile = context.profile
    calibration = context.calibration
    kinematics = context.kinematics
    device = context.device
    payload: dict[str, object] = {
        "session_purpose": purpose.value,
        "control_mode": context.control_mode.value,
        "hardware_access_policy": context.hardware_access_policy.value,
        "startup_hardware_enabled": context.startup_hardware_enabled,
        "explicit_local_config": context.explicit_local_config,
        "robot_id": context.robot_id,
        "robot_unit_id": context.robot_unit_id,
        "profile_fingerprint": profile.fingerprint if profile is not None else None,
        "profile_template": profile.template if profile is not None else None,
        "profile_verification": (
            profile.verification_status.value if profile is not None else None
        ),
        "dependency_state": context.dependency_state.value,
        "dependency_adapter_id": context.dependency_adapter_id,
        "device": (
            {
                "serial_port": device.serial_port,
                "protocol": device.protocol,
                "servo_ids": list(device.servo_ids),
            }
            if device is not None
            else None
        ),
    }
    if purpose is OperatorSessionPurpose.COMMISSIONING_MOTION_TEST:
        pre_motion = context.field_acceptance_bundle.newest_for(
            FieldAcceptanceCapability.PRE_MOTION_CHECKS
        )
        payload.update(
            {
                "commissioning_motion_test_enabled": context.commissioning_motion_test_enabled,
                "calibration_fingerprint": (
                    calibration_fingerprint(calibration) if calibration is not None else None
                ),
                "pre_motion_evidence": (
                    pre_motion.model_dump(mode="json") if pre_motion is not None else None
                ),
                "commissioning_safety_envelope": (
                    context.commissioning_safety_envelope.model_dump(mode="json")
                ),
            }
        )
    elif purpose is OperatorSessionPurpose.REAL_MOTION:
        payload.update(
            {
                "real_motion_enabled": context.real_motion_enabled,
                "calibration_fingerprint": (
                    calibration_fingerprint(calibration) if calibration is not None else None
                ),
                "kinematics_fingerprint": (
                    kinematics.fingerprint if kinematics is not None else None
                ),
                "kinematics_verification": (
                    kinematics.verification_status.value if kinematics is not None else None
                ),
                "expected_kinematics_fingerprint": context.expected_kinematics_fingerprint,
                "field_acceptance_status": context.field_acceptance_status.value,
                "field_acceptance_bundle": context.field_acceptance_bundle.model_dump(mode="json"),
                "kinematics_verification_evidence": (
                    context.kinematics_verification_evidence.model_dump(mode="json")
                    if context.kinematics_verification_evidence is not None
                    else None
                ),
                "field_acceptance_checklist_version": (context.field_acceptance_checklist_version),
            }
        )
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).digest()
