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
from momo.domain.enums import ControlMode, HardwareAccessPolicy
from momo.domain.errors import RobotApplicationError
from momo.domain.real_hardware import (
    REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT,
    IssuedOperatorSession,
    OperatorSessionEvidence,
    OperatorSessionStatus,
    RealHardwareAuthorizationPurpose,
    RealHardwareContext,
    RealHardwareGateInput,
    calibration_fingerprint,
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


@dataclass(frozen=True, slots=True)
class _ActiveOperatorSession:
    token_digest: bytes
    context_digest: bytes
    allowed_purposes: frozenset[RealHardwareAuthorizationPurpose]
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
        confirmation_text: str,
        physical_estop_confirmed: bool,
    ) -> IssuedOperatorSession:
        """Replace any prior token only after every non-operator gate passes."""

        now = self.clock.now()
        report = self.authorization.evaluate(
            RealHardwareGateInput(context=context, evaluated_at=now)
        )
        if not report.session_authorizable:
            raise OperatorSessionPrerequisiteError(
                "Operator session prerequisites are not satisfied",
                details={
                    "state": report.state.value,
                    "blocking_reasons": [item.value for item in report.blocking_reasons],
                },
            )
        if not isinstance(confirmation_text, str) or not secrets.compare_digest(
            confirmation_text.encode("utf-8"),
            REQUIRED_REAL_HARDWARE_CONFIRMATION_TEXT.encode("utf-8"),
        ):
            raise OperatorConfirmationError(
                "The required real-hardware confirmation text did not match exactly"
            )
        if physical_estop_confirmed is not True:
            raise OperatorConfirmationError(
                "Physical E-stop readiness must be explicitly confirmed"
            )

        profile = context.profile
        calibration = context.calibration
        device = context.device
        if profile is None or calibration is None or device is None or context.robot_id is None:
            raise OperatorSessionPrerequisiteError(
                "Operator session identity evidence is incomplete"
            )
        raw_token = secrets.token_urlsafe(32)
        evidence = OperatorSessionEvidence(
            session_id=uuid4(),
            robot_id=context.robot_id,
            variant=profile.variant,
            profile_fingerprint=profile.fingerprint,
            calibration_fingerprint=calibration_fingerprint(calibration),
            allowed_servo_ids=device.servo_ids,
            issued_at=now,
            expires_at=now + timedelta(seconds=self.ttl_s),
            confirmed=True,
            physical_estop_confirmed=True,
            control_mode=ControlMode.REAL,
            hardware_access_policy=HardwareAccessPolicy.FULL,
        )
        issued_report = self.authorization.evaluate(
            RealHardwareGateInput(
                context=context,
                evaluated_at=now,
                operator_session=evidence,
            )
        )
        allowed_purposes: set[RealHardwareAuthorizationPurpose] = set()
        if issued_report.capabilities.real_joint_motion_ready:
            allowed_purposes.update(
                {
                    RealHardwareAuthorizationPurpose.DIAGNOSTICS,
                    RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
                }
            )
        if issued_report.capabilities.real_cartesian_motion_ready:
            allowed_purposes.add(RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION)
        if issued_report.capabilities.real_playback_ready:
            allowed_purposes.add(RealHardwareAuthorizationPurpose.REAL_PLAYBACK)
        if issued_report.capabilities.real_vision_follow_ready:
            allowed_purposes.add(RealHardwareAuthorizationPurpose.REAL_VISION_FOLLOW)
        active = _ActiveOperatorSession(
            token_digest=_digest(raw_token),
            context_digest=_context_digest(context),
            allowed_purposes=frozenset(allowed_purposes),
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
            if not secrets.compare_digest(
                _context_digest(context),
                active.context_digest,
            ):
                raise OperatorSessionTokenError(
                    "Operator session context changed; a new confirmation is required"
                )
            if purpose not in active.allowed_purposes:
                raise OperatorSessionTokenError(
                    "Operator session was not issued for this hardware capability"
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
                _context_digest(context),
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


def _context_digest(context: RealHardwareContext) -> bytes:
    """Bind a session to exact safety inputs without retaining raw device config."""

    profile = context.profile
    calibration = context.calibration
    kinematics = context.kinematics
    device = context.device
    payload = {
        "control_mode": context.control_mode.value,
        "hardware_access_policy": context.hardware_access_policy.value,
        "real_motion_enabled": context.real_motion_enabled,
        "startup_hardware_enabled": context.startup_hardware_enabled,
        "explicit_local_config": context.explicit_local_config,
        "robot_id": context.robot_id,
        "profile_fingerprint": profile.fingerprint if profile is not None else None,
        "profile_template": profile.template if profile is not None else None,
        "profile_verification": (
            profile.verification_status.value if profile is not None else None
        ),
        "calibration_fingerprint": (
            calibration_fingerprint(calibration) if calibration is not None else None
        ),
        "kinematics_fingerprint": (kinematics.fingerprint if kinematics is not None else None),
        "kinematics_verification": (
            kinematics.verification_status.value if kinematics is not None else None
        ),
        "expected_kinematics_fingerprint": context.expected_kinematics_fingerprint,
        "field_acceptance_status": context.field_acceptance_status.value,
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
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).digest()
