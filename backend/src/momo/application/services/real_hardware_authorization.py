"""Pure, deterministic all-gates matrix for Stage 8 real hardware."""

from __future__ import annotations

from momo.domain.enums import (
    ControlMode,
    HardwareAccessPolicy,
    KinematicsVerificationStatus,
    ProfileVerificationStatus,
)
from momo.domain.errors import HardwareMappingError, RobotApplicationError
from momo.domain.hardware_mapping import effective_raw_bounds
from momo.domain.real_hardware import (
    FieldAcceptanceStatus,
    HardwareConfirmationEvidence,
    HardwareDependencyState,
    OperatorSessionStatus,
    RealHardwareAccessGrant,
    RealHardwareAuthorizationPurpose,
    RealHardwareBlocker,
    RealHardwareCapabilityReadiness,
    RealHardwareContext,
    RealHardwareGateInput,
    RealHardwareReadinessReport,
    RealHardwareReadinessState,
    calibration_fingerprint,
    explicit_device_fingerprint,
)


class RealHardwareAuthorizationError(RobotApplicationError):
    code = "REAL_HARDWARE_NOT_AUTHORIZED"
    status_code = 403


class RealHardwareAuthorization:
    """Evaluate only explicit inputs; this service performs no I/O or mutation."""

    def evaluate(self, gate: RealHardwareGateInput) -> RealHardwareReadinessReport:
        context = gate.context
        blockers: list[RealHardwareBlocker] = []

        if context.control_mode is not ControlMode.REAL:
            blockers.append(RealHardwareBlocker.CONTROL_MODE_MUST_BE_REAL)
        if context.hardware_access_policy is not HardwareAccessPolicy.FULL:
            blockers.append(RealHardwareBlocker.HARDWARE_POLICY_MUST_BE_FULL)
        if context.real_motion_enabled is not True:
            blockers.append(RealHardwareBlocker.REAL_MOTION_NOT_ENABLED)
        if context.startup_hardware_enabled is not True:
            blockers.append(RealHardwareBlocker.STARTUP_HARDWARE_FLAG_MISSING)
        if context.explicit_local_config is not True:
            blockers.append(RealHardwareBlocker.EXPLICIT_LOCAL_CONFIG_MISSING)

        profile = context.profile
        if profile is None:
            blockers.append(RealHardwareBlocker.PROFILE_MISSING)
        else:
            if profile.template:
                blockers.append(RealHardwareBlocker.PROFILE_IS_TEMPLATE)
            if profile.verification_status is not ProfileVerificationStatus.VERIFIED_FOR_REAL:
                blockers.append(RealHardwareBlocker.PROFILE_NOT_VERIFIED_FOR_REAL)

        calibration = context.calibration
        if calibration is None:
            blockers.append(RealHardwareBlocker.CALIBRATION_MISSING)
        elif profile is not None:
            blockers.extend(self._calibration_blockers(context))

        kinematics = context.kinematics
        if kinematics is None:
            blockers.append(RealHardwareBlocker.KINEMATICS_MISSING)
        else:
            if kinematics.verification_status is not KinematicsVerificationStatus.VERIFIED_FOR_REAL:
                blockers.append(RealHardwareBlocker.KINEMATICS_NOT_VERIFIED_FOR_REAL)
            if context.expected_kinematics_fingerprint is None:
                blockers.append(RealHardwareBlocker.KINEMATICS_FINGERPRINT_MISSING)
            elif kinematics.fingerprint != context.expected_kinematics_fingerprint:
                blockers.append(RealHardwareBlocker.KINEMATICS_FINGERPRINT_MISMATCH)
            if profile is None:
                blockers.append(RealHardwareBlocker.KINEMATICS_PROFILE_MISMATCH)
            else:
                try:
                    kinematics.validate_against_profile(profile)
                except ValueError:
                    blockers.append(RealHardwareBlocker.KINEMATICS_PROFILE_MISMATCH)

        if context.field_acceptance_status is not FieldAcceptanceStatus.PASSED:
            blockers.append(RealHardwareBlocker.FIELD_ACCEPTANCE_NOT_PASSED)

        if context.dependency_state is not HardwareDependencyState.AVAILABLE:
            blockers.append(RealHardwareBlocker.SERVO_BUS_DEPENDENCY_UNAVAILABLE)
        elif context.dependency_adapter_id is None:
            blockers.append(RealHardwareBlocker.SERVO_BUS_DEPENDENCY_IDENTITY_MISSING)

        if context.device is None:
            blockers.append(RealHardwareBlocker.EXPLICIT_DEVICE_MISSING)
        elif profile is not None:
            expected_ids = tuple(
                definition.servo_id
                for definition in profile.joint_definitions
                if definition.servo_id is not None
            )
            if context.device.servo_ids != expected_ids:
                blockers.append(RealHardwareBlocker.DEVICE_SERVO_IDS_MISMATCH)

        session = gate.operator_session
        if session is None:
            blockers.append(RealHardwareBlocker.OPERATOR_SESSION_MISSING)
        elif gate.evaluated_at >= session.expires_at:
            blockers.append(RealHardwareBlocker.OPERATOR_SESSION_EXPIRED)
        elif not self._session_matches_context(context, session):
            blockers.append(RealHardwareBlocker.OPERATOR_SESSION_MISMATCH)

        unique_blockers = tuple(dict.fromkeys(blockers))
        base_blockers = tuple(
            blocker for blocker in unique_blockers if not blocker.name.startswith("KINEMATICS_")
        )
        joint_ready = not base_blockers
        geometry_ready = joint_ready and not any(
            blocker.name.startswith("KINEMATICS_") for blocker in unique_blockers
        )
        capabilities = RealHardwareCapabilityReadiness(
            real_joint_motion_ready=joint_ready,
            real_cartesian_motion_ready=geometry_ready,
            # V1 playback is conservatively treated as potentially Cartesian.
            real_playback_ready=geometry_ready,
            real_vision_follow_ready=geometry_ready,
        )
        session_authorizable = base_blockers == (RealHardwareBlocker.OPERATOR_SESSION_MISSING,)
        state = self._state_for(
            unique_blockers,
            session_authorizable=session_authorizable,
            capabilities=capabilities,
        )
        active_session = (
            OperatorSessionStatus(
                active=True,
                session_id=session.session_id,
                expires_at=session.expires_at,
            )
            if session is not None
            and gate.evaluated_at < session.expires_at
            and RealHardwareBlocker.OPERATOR_SESSION_MISMATCH not in unique_blockers
            else None
        )
        return RealHardwareReadinessReport(
            state=state,
            ready=capabilities.all_ready,
            session_authorizable=session_authorizable,
            blocking_reasons=unique_blockers,
            capabilities=capabilities,
            confirmation=self.confirmation_for(context),
            session=active_session,
        )

    def require_authorized(
        self,
        gate: RealHardwareGateInput,
        *,
        purpose: RealHardwareAuthorizationPurpose,
    ) -> RealHardwareAccessGrant:
        report = self.evaluate(gate)
        session = gate.operator_session
        purpose_ready = {
            RealHardwareAuthorizationPurpose.DIAGNOSTICS: (
                report.capabilities.real_joint_motion_ready
            ),
            RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION: (
                report.capabilities.real_joint_motion_ready
            ),
            RealHardwareAuthorizationPurpose.REAL_CARTESIAN_MOTION: (
                report.capabilities.real_cartesian_motion_ready
            ),
            RealHardwareAuthorizationPurpose.REAL_PLAYBACK: (
                report.capabilities.real_playback_ready
            ),
            RealHardwareAuthorizationPurpose.REAL_VISION_FOLLOW: (
                report.capabilities.real_vision_follow_ready
            ),
        }[purpose]
        if not purpose_ready or session is None:
            raise RealHardwareAuthorizationError(
                "Real hardware access purpose is blocked by the authorization matrix",
                details={
                    "purpose": purpose.value,
                    "state": report.state.value,
                    "blocking_reasons": [item.value for item in report.blocking_reasons],
                },
            )
        device = gate.context.device
        adapter_id = gate.context.dependency_adapter_id
        if (
            device is None or adapter_id is None
        ):  # pragma: no cover - purpose readiness already rejects this
            raise RealHardwareAuthorizationError(
                "Real hardware device or adapter identity is missing from the authorization matrix"
            )
        return RealHardwareAccessGrant(
            session=session,
            confirmation=report.confirmation,
            adapter_id=adapter_id,
            device_fingerprint=explicit_device_fingerprint(device),
            purpose=purpose,
            capabilities=report.capabilities,
            authorized_at=gate.evaluated_at,
        )

    @staticmethod
    def confirmation_for(context: RealHardwareContext) -> HardwareConfirmationEvidence:
        profile = context.profile
        calibration = context.calibration
        kinematics = context.kinematics
        device = context.device
        return HardwareConfirmationEvidence(
            robot_id=context.robot_id,
            variant=profile.variant if profile is not None else None,
            profile_fingerprint=profile.fingerprint if profile is not None else None,
            calibration_fingerprint=(
                calibration_fingerprint(calibration) if calibration is not None else None
            ),
            kinematics_fingerprint=kinematics.fingerprint if kinematics is not None else None,
            masked_serial_port=device.masked_serial_port if device is not None else None,
            masked_servo_ids=device.masked_servo_ids if device is not None else (),
            protocol=device.protocol if device is not None else None,
        )

    @staticmethod
    def _calibration_blockers(context: RealHardwareContext) -> tuple[RealHardwareBlocker, ...]:
        profile = context.profile
        calibration = context.calibration
        if profile is None or calibration is None:
            return ()
        blockers: list[RealHardwareBlocker] = []
        if calibration.template:
            blockers.append(RealHardwareBlocker.CALIBRATION_IS_TEMPLATE)
        if calibration.robot_variant is not profile.variant:
            blockers.append(RealHardwareBlocker.CALIBRATION_VARIANT_MISMATCH)
        if calibration.profile_fingerprint != profile.fingerprint:
            blockers.append(RealHardwareBlocker.CALIBRATION_PROFILE_MISMATCH)
        expected_joints = tuple(profile.enabled_joints)
        actual_joints = tuple(joint.joint_id for joint in calibration.joints)
        if set(actual_joints) != set(expected_joints) or len(actual_joints) != len(expected_joints):
            blockers.append(RealHardwareBlocker.CALIBRATION_JOINT_SET_MISMATCH)
        if not all(joint.complete for joint in calibration.joints):
            blockers.append(RealHardwareBlocker.CALIBRATION_INCOMPLETE)
        if not RealHardwareAuthorization._calibration_mapping_matches(context):
            blockers.append(RealHardwareBlocker.CALIBRATION_MAPPING_MISMATCH)
        return tuple(blockers)

    @staticmethod
    def _calibration_mapping_matches(context: RealHardwareContext) -> bool:
        profile = context.profile
        calibration = context.calibration
        if profile is None or calibration is None:
            return False
        definitions = profile.definitions_by_id
        for joint in calibration.joints:
            definition = definitions.get(joint.joint_id)
            if definition is None:
                return False
            if joint.servo_id != definition.servo_id:
                return False
            if joint.operating_mode is not definition.operating_mode:
                return False
            try:
                lower, upper = effective_raw_bounds(definition, joint)
            except HardwareMappingError:
                return False
            if joint.home_present_raw is None or not lower <= joint.home_present_raw <= upper:
                return False
        return True

    @staticmethod
    def _session_matches_context(context: RealHardwareContext, session: object) -> bool:
        # Kept structural so later execution authorizations can consume the same
        # token-free evidence without importing this application service.
        profile = context.profile
        calibration = context.calibration
        device = context.device
        if profile is None or calibration is None or device is None or context.robot_id is None:
            return False
        return bool(
            getattr(session, "robot_id", None) == context.robot_id
            and getattr(session, "variant", None) is profile.variant
            and getattr(session, "profile_fingerprint", None) == profile.fingerprint
            and getattr(session, "calibration_fingerprint", None)
            == calibration_fingerprint(calibration)
            and tuple(getattr(session, "allowed_servo_ids", ())) == device.servo_ids
            and getattr(session, "confirmed", False) is True
            and getattr(session, "physical_estop_confirmed", False) is True
            and getattr(session, "control_mode", None) is ControlMode.REAL
            and getattr(session, "hardware_access_policy", None) is HardwareAccessPolicy.FULL
        )

    @staticmethod
    def _state_for(
        blockers: tuple[RealHardwareBlocker, ...],
        *,
        session_authorizable: bool,
        capabilities: RealHardwareCapabilityReadiness,
    ) -> RealHardwareReadinessState:
        if capabilities.all_ready:
            return RealHardwareReadinessState.READY
        if session_authorizable:
            return RealHardwareReadinessState.AWAITING_OPERATOR_SESSION
        first = blockers[0]
        if first is RealHardwareBlocker.CONTROL_MODE_MUST_BE_REAL:
            return RealHardwareReadinessState.BLOCKED_BY_CONTROL_MODE
        if first is RealHardwareBlocker.HARDWARE_POLICY_MUST_BE_FULL:
            return RealHardwareReadinessState.BLOCKED_BY_HARDWARE_POLICY
        if first in {
            RealHardwareBlocker.REAL_MOTION_NOT_ENABLED,
            RealHardwareBlocker.STARTUP_HARDWARE_FLAG_MISSING,
            RealHardwareBlocker.EXPLICIT_LOCAL_CONFIG_MISSING,
        }:
            return RealHardwareReadinessState.BLOCKED_BY_STAGE_POLICY
        if first.name.startswith("PROFILE_"):
            return RealHardwareReadinessState.BLOCKED_BY_PROFILE
        if first.name.startswith("CALIBRATION_"):
            return RealHardwareReadinessState.BLOCKED_BY_CALIBRATION
        if first.name.startswith("KINEMATICS_"):
            return RealHardwareReadinessState.BLOCKED_BY_KINEMATICS
        if first is RealHardwareBlocker.FIELD_ACCEPTANCE_NOT_PASSED:
            return RealHardwareReadinessState.BLOCKED_BY_FIELD_ACCEPTANCE
        if first in {
            RealHardwareBlocker.SERVO_BUS_DEPENDENCY_UNAVAILABLE,
            RealHardwareBlocker.SERVO_BUS_DEPENDENCY_IDENTITY_MISSING,
            RealHardwareBlocker.EXPLICIT_DEVICE_MISSING,
            RealHardwareBlocker.DEVICE_SERVO_IDS_MISMATCH,
            RealHardwareBlocker.DEVICE_SAFETY_STATE_UNCERTAIN,
        }:
            return RealHardwareReadinessState.BLOCKED_BY_DEVICE
        return RealHardwareReadinessState.BLOCKED_BY_OPERATOR_AUTHORIZATION
