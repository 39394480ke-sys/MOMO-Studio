"""Pure, deterministic all-gates matrix for Stage 8 real hardware."""

from __future__ import annotations

from momo.domain.commissioning import (
    FieldAcceptanceCapability,
    KinematicsEvidenceState,
    PhysicalStopVerification,
)
from momo.domain.enums import ControlMode, HardwareAccessPolicy, ProfileVerificationStatus
from momo.domain.errors import HardwareMappingError, RobotApplicationError
from momo.domain.hardware_mapping import effective_raw_bounds
from momo.domain.real_hardware import (
    AUTHORIZATION_PURPOSE_SCOPE,
    CapabilityReadinessDetail,
    HardwareConfirmationEvidence,
    HardwareDependencyState,
    OperatorSessionPurpose,
    OperatorSessionStatus,
    RealHardwareAccessGrant,
    RealHardwareAuthorizationPurpose,
    RealHardwareBlocker,
    RealHardwareCapabilityDetails,
    RealHardwareCapabilityReadiness,
    RealHardwareContext,
    RealHardwareGateInput,
    RealHardwareReadinessReport,
    RealHardwareReadinessState,
    calibration_fingerprint,
    confirmation_text_for,
    explicit_device_fingerprint,
    kinematics_verification_evidence_state,
)


class RealHardwareAuthorizationError(RobotApplicationError):
    code = "REAL_HARDWARE_NOT_AUTHORIZED"
    status_code = 403


class RealHardwareAuthorization:
    """Evaluate only explicit inputs; this service performs no I/O or mutation."""

    def evaluate(self, gate: RealHardwareGateInput) -> RealHardwareReadinessReport:
        context = gate.context
        shared: list[RealHardwareBlocker] = []
        if context.control_mode is not ControlMode.REAL:
            shared.append(RealHardwareBlocker.CONTROL_MODE_MUST_BE_REAL)
        if context.startup_hardware_enabled is not True:
            shared.append(RealHardwareBlocker.STARTUP_HARDWARE_FLAG_MISSING)
        if context.explicit_local_config is not True:
            shared.append(RealHardwareBlocker.EXPLICIT_LOCAL_CONFIG_MISSING)
        if not context.robot_unit_id:
            shared.append(RealHardwareBlocker.ROBOT_UNIT_ID_REQUIRED)
        profile = context.profile
        if profile is None:
            shared.append(RealHardwareBlocker.PROFILE_MISSING)
        verified_profile_blockers: list[RealHardwareBlocker] = []
        if profile is not None:
            if profile.template:
                verified_profile_blockers.append(RealHardwareBlocker.PROFILE_IS_TEMPLATE)
            if profile.verification_status is not ProfileVerificationStatus.VERIFIED_FOR_REAL:
                verified_profile_blockers.append(RealHardwareBlocker.PROFILE_NOT_VERIFIED_FOR_REAL)

        if context.dependency_state is not HardwareDependencyState.AVAILABLE:
            shared.append(RealHardwareBlocker.SERVO_BUS_DEPENDENCY_UNAVAILABLE)
        elif context.dependency_adapter_id is None:
            shared.append(RealHardwareBlocker.SERVO_BUS_DEPENDENCY_IDENTITY_MISSING)

        if context.device is None:
            shared.append(RealHardwareBlocker.EXPLICIT_DEVICE_MISSING)
        else:
            if (
                not context.device.robot_unit_id
                or context.device.robot_unit_id != context.robot_unit_id
            ):
                shared.append(RealHardwareBlocker.ROBOT_UNIT_MISMATCH)
        if context.device is not None and profile is not None:
            expected_ids = tuple(
                definition.servo_id
                for definition in profile.joint_definitions
                if definition.servo_id is not None
            )
            if context.device.servo_ids != expected_ids:
                shared.append(RealHardwareBlocker.DEVICE_SERVO_IDS_MISMATCH)

        commissioning_base = list(shared)
        if context.hardware_access_policy is not HardwareAccessPolicy.READ_ONLY:
            commissioning_base.insert(1, RealHardwareBlocker.HARDWARE_POLICY_MUST_BE_READ_ONLY)

        calibration = context.calibration
        calibration_blockers: list[RealHardwareBlocker] = []
        if calibration is None:
            calibration_blockers.append(RealHardwareBlocker.CALIBRATION_MISSING)
        elif profile is not None:
            calibration_blockers.extend(self._calibration_blockers(context))

        # Commissioning is the bounded path used to verify a provisional Profile
        # against a non-template, unit-bound Calibration. Requiring the Profile to
        # be VERIFIED_FOR_REAL before that test creates a circular dependency.
        # Production motion below still requires the verified Profile and accepted
        # field evidence.
        motion_test_base = [*shared, *calibration_blockers]
        if context.hardware_access_policy is not HardwareAccessPolicy.FULL:
            motion_test_base.insert(1, RealHardwareBlocker.HARDWARE_POLICY_MUST_BE_FULL)
        if context.commissioning_motion_test_enabled is not True:
            motion_test_base.append(RealHardwareBlocker.COMMISSIONING_MOTION_NOT_ENABLED)
        if len(context.software_commit) < 7 or context.software_commit == "unknown":
            motion_test_base.append(RealHardwareBlocker.SOFTWARE_COMMIT_REQUIRED)

        valid_acceptance = context.field_acceptance_bundle.valid_capabilities(context)

        # Raw direction exists to verify profile sign candidates, so it requires
        # an explicit complete Profile but does not require VERIFIED_FOR_REAL yet.
        raw_direction_base = list(shared)
        if context.hardware_access_policy is not HardwareAccessPolicy.FULL:
            raw_direction_base.insert(1, RealHardwareBlocker.HARDWARE_POLICY_MUST_BE_FULL)
        if context.raw_direction_test_enabled is not True:
            raw_direction_base.append(RealHardwareBlocker.RAW_DIRECTION_TEST_NOT_ENABLED)
        if context.raw_direction_adapter_ready is not True:
            raw_direction_base.append(RealHardwareBlocker.RAW_DIRECTION_ADAPTER_UNAVAILABLE)
        if len(context.software_commit) < 7 or context.software_commit == "unknown":
            raw_direction_base.append(RealHardwareBlocker.SOFTWARE_COMMIT_REQUIRED)

        # Manual REAL control and Studio playback share one operator session and
        # the same runtime safety entry point. Stored motion still passes the
        # trajectory compiler and playback intent checks; it does not require a
        # second field-acceptance session before using that reviewed executor.
        manual_motion_base = [*shared, *calibration_blockers]
        if context.hardware_access_policy is not HardwareAccessPolicy.FULL:
            manual_motion_base.insert(1, RealHardwareBlocker.HARDWARE_POLICY_MUST_BE_FULL)
        if context.real_motion_enabled is not True:
            manual_motion_base.insert(2, RealHardwareBlocker.REAL_MOTION_NOT_ENABLED)

        production_base = [*manual_motion_base, *verified_profile_blockers]
        if FieldAcceptanceCapability.JOINT_MOTION not in valid_acceptance:
            production_base.append(RealHardwareBlocker.JOINT_MOTION_ACCEPTANCE_PENDING)
        if context.physical_stop_verification is not PhysicalStopVerification.VERIFIED_FOR_UNIT:
            production_base.append(RealHardwareBlocker.PHYSICAL_STOP_NOT_VERIFIED)

        kinematics_model_blockers: list[RealHardwareBlocker] = []
        kinematics = context.kinematics
        if kinematics is None:
            kinematics_model_blockers.append(RealHardwareBlocker.KINEMATICS_MISSING)
        else:
            if context.expected_kinematics_fingerprint is None:
                kinematics_model_blockers.append(RealHardwareBlocker.KINEMATICS_FINGERPRINT_MISSING)
            elif kinematics.fingerprint != context.expected_kinematics_fingerprint:
                kinematics_model_blockers.append(
                    RealHardwareBlocker.KINEMATICS_FINGERPRINT_MISMATCH
                )
            if profile is None:
                kinematics_model_blockers.append(RealHardwareBlocker.KINEMATICS_PROFILE_MISMATCH)
            else:
                try:
                    kinematics.validate_against_profile(profile)
                except ValueError:
                    kinematics_model_blockers.append(
                        RealHardwareBlocker.KINEMATICS_PROFILE_MISMATCH
                    )
        kinematics_evidence_blockers: list[RealHardwareBlocker] = []
        kinematics_state, _ = kinematics_verification_evidence_state(context)
        if kinematics_state is KinematicsEvidenceState.MISSING:
            kinematics_evidence_blockers.append(RealHardwareBlocker.KINEMATICS_VERIFICATION_PENDING)
        elif kinematics_state is KinematicsEvidenceState.STALE:
            kinematics_evidence_blockers.append(RealHardwareBlocker.KINEMATICS_EVIDENCE_STALE)

        joint_blockers = list(manual_motion_base)
        cartesian_blockers = [*manual_motion_base, *kinematics_model_blockers]
        playback_blockers = [*manual_motion_base, *kinematics_model_blockers]
        vision_blockers = [
            *production_base,
            *kinematics_model_blockers,
            *kinematics_evidence_blockers,
        ]
        if FieldAcceptanceCapability.VISION_FOLLOW not in valid_acceptance:
            vision_blockers.append(RealHardwareBlocker.VISION_FOLLOW_ACCEPTANCE_PENDING)

        session = gate.operator_session
        commissioning_session_valid = self._session_valid_for(
            gate,
            OperatorSessionPurpose.COMMISSIONING_READ_ONLY,
        )
        motion_test_session_valid = self._session_valid_for(
            gate, OperatorSessionPurpose.COMMISSIONING_MOTION_TEST
        )
        raw_direction_session_valid = self._session_valid_for(
            gate, OperatorSessionPurpose.RAW_DIRECTION_TEST
        )
        motion_session_valid = self._session_valid_for(gate, OperatorSessionPurpose.REAL_MOTION)
        commissioning_base = list(dict.fromkeys(commissioning_base))
        motion_test_base = list(dict.fromkeys(motion_test_base))
        raw_direction_base = list(dict.fromkeys(raw_direction_base))
        joint_blockers = list(dict.fromkeys(joint_blockers))
        cartesian_blockers = list(dict.fromkeys(cartesian_blockers))
        production_base = list(dict.fromkeys(production_base))
        playback_blockers = list(dict.fromkeys(playback_blockers))
        vision_blockers = list(dict.fromkeys(vision_blockers))

        commissioning_ready = not commissioning_base
        motion_test_ready = not motion_test_base and motion_test_session_valid
        raw_direction_ready = not raw_direction_base and raw_direction_session_valid
        joint_ready = not joint_blockers and motion_session_valid
        cartesian_ready = not cartesian_blockers and motion_session_valid
        playback_ready = not playback_blockers and motion_session_valid
        vision_ready = not vision_blockers and motion_session_valid
        capabilities = RealHardwareCapabilityReadiness(
            commissioning_read_only_ready=commissioning_ready,
            commissioning_diagnostics_ready=commissioning_ready,
            calibration_capture_ready=commissioning_ready,
            commissioning_motion_test_ready=motion_test_ready,
            raw_direction_test_ready=raw_direction_ready,
            real_joint_motion_ready=joint_ready,
            real_cartesian_motion_ready=cartesian_ready,
            real_playback_ready=playback_ready,
            real_vision_follow_ready=vision_ready,
        )
        commissioning_authorizable = commissioning_ready and session is None
        motion_test_authorizable = not motion_test_base and session is None
        raw_direction_authorizable = not raw_direction_base and session is None
        motion_authorizable = not joint_blockers and session is None

        def detail(
            blockers: list[RealHardwareBlocker],
            *,
            session_valid: bool,
            session_blocker: RealHardwareBlocker,
            evidence: tuple[str, ...],
        ) -> CapabilityReadinessDetail:
            reasons = list(dict.fromkeys(blockers))
            if not reasons and not session_valid:
                reasons.append(session_blocker)
            return CapabilityReadinessDetail(
                ready=not reasons and session_valid,
                authorized=not reasons and session_valid,
                blocked_reasons=tuple(item.value for item in reasons),
                required_evidence=evidence,
            )

        capability_details = RealHardwareCapabilityDetails(
            commissioning_read_only=detail(
                commissioning_base,
                session_valid=commissioning_session_valid,
                session_blocker=RealHardwareBlocker.OPERATOR_SESSION_MISSING,
                evidence=("EXPLICIT_DEVICE", "PROFILE_JOINT_IDENTITY"),
            ),
            commissioning_motion_test=detail(
                motion_test_base,
                session_valid=motion_test_session_valid,
                session_blocker=RealHardwareBlocker.COMMISSIONING_MOTION_SESSION_REQUIRED,
                evidence=("CALIBRATION", "EXPLICIT_OPERATOR_SESSION"),
            ),
            raw_direction_test=detail(
                raw_direction_base,
                session_valid=raw_direction_session_valid,
                session_blocker=RealHardwareBlocker.RAW_DIRECTION_SESSION_REQUIRED,
                evidence=("PROFILE_JOINT_IDENTITY", "ZERO_RAW_SNAPSHOT", "PHYSICAL_ESTOP"),
            ),
            real_joint_motion=detail(
                joint_blockers,
                session_valid=motion_session_valid,
                session_blocker=RealHardwareBlocker.OPERATOR_SESSION_MISSING,
                evidence=("CALIBRATION", "EXPLICIT_OPERATOR_SESSION"),
            ),
            real_cartesian_motion=detail(
                cartesian_blockers,
                session_valid=motion_session_valid,
                session_blocker=RealHardwareBlocker.OPERATOR_SESSION_MISSING,
                evidence=(
                    "CALIBRATION",
                    "KINEMATICS_MODEL",
                    "EXPLICIT_OPERATOR_SESSION",
                ),
            ),
            real_playback=detail(
                playback_blockers,
                session_valid=motion_session_valid,
                session_blocker=RealHardwareBlocker.OPERATOR_SESSION_MISSING,
                evidence=(
                    "CALIBRATION",
                    "KINEMATICS_MODEL",
                    "TRAJECTORY_PREFLIGHT",
                    "EXPLICIT_OPERATOR_SESSION",
                ),
            ),
            real_vision_follow=detail(
                vision_blockers,
                session_valid=motion_session_valid,
                session_blocker=RealHardwareBlocker.OPERATOR_SESSION_MISSING,
                evidence=(
                    "JOINT_MOTION_ACCEPTANCE",
                    "KINEMATICS_VERIFICATION",
                    "VISION_FOLLOW_ACCEPTANCE",
                ),
            ),
        )

        if context.hardware_access_policy is HardwareAccessPolicy.READ_ONLY:
            blockers = list(commissioning_base)
            relevant_session_valid = commissioning_session_valid
        elif (
            context.raw_direction_test_enabled
            and FieldAcceptanceCapability.JOINT_MOTION not in valid_acceptance
        ):
            blockers = list(raw_direction_base)
            relevant_session_valid = raw_direction_session_valid
        elif (
            context.commissioning_motion_test_enabled
            and FieldAcceptanceCapability.JOINT_MOTION not in valid_acceptance
        ):
            blockers = list(motion_test_base)
            relevant_session_valid = motion_test_session_valid
        else:
            blockers = [*joint_blockers, *cartesian_blockers, *playback_blockers, *vision_blockers]
            relevant_session_valid = motion_session_valid
        if session is None:
            blockers.append(RealHardwareBlocker.OPERATOR_SESSION_MISSING)
        elif gate.evaluated_at >= session.expires_at:
            blockers.append(RealHardwareBlocker.OPERATOR_SESSION_EXPIRED)
        elif not relevant_session_valid:
            blockers.append(RealHardwareBlocker.OPERATOR_SESSION_MISMATCH)
        unique_blockers = tuple(dict.fromkeys(blockers))
        state = self._state_for(
            unique_blockers,
            session_authorizable=(
                commissioning_authorizable
                or raw_direction_authorizable
                or motion_test_authorizable
                or motion_authorizable
            ),
            # The state machine treats all three independent new-session gates as
            # authorizable; no active token is ever upgraded in place.
            capabilities=capabilities,
            commissioning_session_active=(
                (
                    commissioning_session_valid
                    and context.hardware_access_policy is HardwareAccessPolicy.READ_ONLY
                )
                or motion_test_session_valid
                or raw_direction_session_valid
            ),
        )
        active_session = (
            OperatorSessionStatus(
                active=True,
                session_id=session.session_id,
                expires_at=session.expires_at,
                purpose=session.purpose,
                scopes=session.scopes,
            )
            if session is not None
            and gate.evaluated_at < session.expires_at
            and relevant_session_valid
            else None
        )
        return RealHardwareReadinessReport(
            state=state,
            ready=capabilities.all_ready,
            session_authorizable=(
                commissioning_authorizable
                or raw_direction_authorizable
                or motion_test_authorizable
                or motion_authorizable
            ),
            commissioning_session_authorizable=commissioning_authorizable,
            commissioning_motion_session_authorizable=motion_test_authorizable,
            raw_direction_session_authorizable=raw_direction_authorizable,
            motion_session_authorizable=motion_authorizable,
            blocking_reasons=unique_blockers,
            capabilities=capabilities,
            capability_details=capability_details,
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
                report.capabilities.commissioning_diagnostics_ready
            ),
            RealHardwareAuthorizationPurpose.CALIBRATION_CAPTURE: (
                report.capabilities.calibration_capture_ready
            ),
            RealHardwareAuthorizationPurpose.COMMISSIONING_SINGLE_JOINT_TEST: (
                report.capabilities.commissioning_motion_test_ready
            ),
            RealHardwareAuthorizationPurpose.RAW_DIRECTION_TEST: (
                report.capabilities.raw_direction_test_ready
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
        required_scope = AUTHORIZATION_PURPOSE_SCOPE[purpose]
        if (
            not purpose_ready
            or session is None
            or required_scope not in session.scopes
            or not self._session_matches_context(gate.context, session, session.purpose)
        ):
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
            confirmation=self.confirmation_for(gate.context, purpose=session.purpose),
            adapter_id=adapter_id,
            device_fingerprint=explicit_device_fingerprint(device),
            purpose=purpose,
            capabilities=report.capabilities,
            authorized_at=gate.evaluated_at,
        )

    @staticmethod
    def confirmation_for(
        context: RealHardwareContext,
        *,
        purpose: OperatorSessionPurpose | None = None,
    ) -> HardwareConfirmationEvidence:
        profile = context.profile
        calibration = context.calibration
        kinematics = context.kinematics
        device = context.device
        valid_capabilities = context.field_acceptance_bundle.valid_capabilities(context)
        if purpose is not None:
            resolved_purpose = purpose
        elif context.hardware_access_policy is HardwareAccessPolicy.READ_ONLY:
            resolved_purpose = OperatorSessionPurpose.COMMISSIONING_READ_ONLY
        elif (
            context.raw_direction_test_enabled
            and FieldAcceptanceCapability.JOINT_MOTION not in valid_capabilities
        ):
            resolved_purpose = OperatorSessionPurpose.RAW_DIRECTION_TEST
        elif (
            context.commissioning_motion_test_enabled
            and FieldAcceptanceCapability.JOINT_MOTION not in valid_capabilities
        ):
            resolved_purpose = OperatorSessionPurpose.COMMISSIONING_MOTION_TEST
        else:
            resolved_purpose = OperatorSessionPurpose.REAL_MOTION
        joint_acceptance = context.field_acceptance_bundle.newest_for(
            FieldAcceptanceCapability.JOINT_MOTION
        )
        pre_motion = context.field_acceptance_bundle.newest_for(
            FieldAcceptanceCapability.PRE_MOTION_CHECKS
        )
        return HardwareConfirmationEvidence(
            robot_id=context.robot_id,
            robot_unit_id=context.robot_unit_id or None,
            variant=profile.variant if profile is not None else None,
            profile_fingerprint=profile.fingerprint if profile is not None else None,
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
                kinematics.fingerprint
                if kinematics is not None and resolved_purpose is OperatorSessionPurpose.REAL_MOTION
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
            masked_serial_port=device.masked_serial_port if device is not None else None,
            masked_servo_ids=device.masked_servo_ids if device is not None else (),
            protocol=device.protocol if device is not None else None,
            session_purpose=resolved_purpose,
            workspace_clear_required=(
                resolved_purpose
                in {
                    OperatorSessionPurpose.COMMISSIONING_MOTION_TEST,
                    OperatorSessionPurpose.RAW_DIRECTION_TEST,
                }
            ),
            required_confirmation_text=confirmation_text_for(resolved_purpose),
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
        if (
            not context.robot_unit_id
            or calibration.robot_unit_id is None
            or calibration.robot_unit_id != context.robot_unit_id
        ):
            blockers.append(RealHardwareBlocker.CALIBRATION_ROBOT_UNIT_MISMATCH)
        expected_joints = tuple(profile.enabled_joints)
        actual_joints = tuple(joint.joint_id for joint in calibration.joints)
        if set(actual_joints) != set(expected_joints) or len(actual_joints) != len(expected_joints):
            blockers.append(RealHardwareBlocker.CALIBRATION_JOINT_SET_MISMATCH)
        if not all(joint.complete for joint in calibration.joints):
            blockers.append(RealHardwareBlocker.CALIBRATION_INCOMPLETE)
        if not RealHardwareAuthorization._calibration_mapping_matches(context):
            blockers.append(RealHardwareBlocker.CALIBRATION_MAPPING_MISMATCH)
        return tuple(blockers)

    def calibration_blockers(
        self,
        context: RealHardwareContext,
    ) -> tuple[RealHardwareBlocker, ...]:
        """Expose the same complete calibration gate to acceptance workflows."""

        return self._calibration_blockers(context)

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

    def _session_valid_for(
        self,
        gate: RealHardwareGateInput,
        purpose: OperatorSessionPurpose,
    ) -> bool:
        session = gate.operator_session
        return bool(
            session is not None
            and gate.evaluated_at < session.expires_at
            and self._session_matches_context(gate.context, session, purpose)
        )

    @staticmethod
    def _session_matches_context(
        context: RealHardwareContext,
        session: object,
        purpose: OperatorSessionPurpose,
    ) -> bool:
        # Kept structural so later execution authorizations can consume the same
        # token-free evidence without importing this application service.
        profile = context.profile
        device = context.device
        if profile is None or device is None or context.robot_id is None:
            return False
        shared_matches = bool(
            getattr(session, "purpose", None) is purpose
            and getattr(session, "robot_id", None) == context.robot_id
            and getattr(session, "robot_unit_id", None) == context.robot_unit_id
            and getattr(session, "variant", None) is profile.variant
            and getattr(session, "profile_fingerprint", None) == profile.fingerprint
            and getattr(session, "device_fingerprint", None) == explicit_device_fingerprint(device)
            and tuple(getattr(session, "allowed_servo_ids", ())) == device.servo_ids
            and getattr(session, "confirmed", False) is True
            and getattr(session, "physical_estop_confirmed", False) is True
            and getattr(session, "control_mode", None) is ControlMode.REAL
        )
        if not shared_matches:
            return False
        if purpose is OperatorSessionPurpose.COMMISSIONING_READ_ONLY:
            return bool(
                getattr(session, "hardware_access_policy", None) is HardwareAccessPolicy.READ_ONLY
                and getattr(session, "calibration_fingerprint", None) is None
                and getattr(session, "kinematics_fingerprint", None) is None
            )
        if purpose is OperatorSessionPurpose.RAW_DIRECTION_TEST:
            return bool(
                context.raw_direction_test_enabled
                and context.raw_direction_adapter_ready
                and getattr(session, "hardware_access_policy", None) is HardwareAccessPolicy.FULL
                and getattr(session, "calibration_fingerprint", None) is None
                and getattr(session, "kinematics_fingerprint", None) is None
                and getattr(session, "pre_motion_evidence_id", None) is None
                and getattr(session, "raw_direction_envelope", None)
                == context.raw_direction_safety_envelope
                and getattr(session, "workspace_clear_confirmed", False) is True
                and getattr(session, "field_acceptance_evidence_id", None) is None
            )
        calibration = context.calibration
        if calibration is None:
            return False
        if purpose is OperatorSessionPurpose.COMMISSIONING_MOTION_TEST:
            return bool(
                context.commissioning_motion_test_enabled
                and getattr(session, "hardware_access_policy", None) is HardwareAccessPolicy.FULL
                and getattr(session, "calibration_fingerprint", None)
                == calibration_fingerprint(calibration)
                and getattr(session, "commissioning_envelope", None)
                == context.commissioning_safety_envelope
                and getattr(session, "workspace_clear_confirmed", False) is True
                and getattr(session, "field_acceptance_evidence_id", None) is None
            )
        acceptance = context.field_acceptance_bundle.newest_for(
            FieldAcceptanceCapability.JOINT_MOTION
        )
        current_acceptance_id = (
            acceptance.evidence_id
            if acceptance is not None
            and FieldAcceptanceCapability.JOINT_MOTION
            in context.field_acceptance_bundle.valid_capabilities(context)
            else None
        )
        session_kinematics_fingerprint = getattr(session, "kinematics_fingerprint", None)
        current_kinematics_fingerprint = (
            context.kinematics.fingerprint if context.kinematics is not None else None
        )
        return bool(
            getattr(session, "hardware_access_policy", None) is HardwareAccessPolicy.FULL
            and getattr(session, "calibration_fingerprint", None)
            == calibration_fingerprint(calibration)
            and getattr(session, "field_acceptance_evidence_id", None) == current_acceptance_id
            and (
                session_kinematics_fingerprint is None
                or session_kinematics_fingerprint == current_kinematics_fingerprint
            )
        )

    @staticmethod
    def _state_for(
        blockers: tuple[RealHardwareBlocker, ...],
        *,
        session_authorizable: bool,
        capabilities: RealHardwareCapabilityReadiness,
        commissioning_session_active: bool,
    ) -> RealHardwareReadinessState:
        if capabilities.all_ready:
            return RealHardwareReadinessState.READY
        if commissioning_session_active:
            return RealHardwareReadinessState.COMMISSIONING_READY
        if session_authorizable:
            return RealHardwareReadinessState.AWAITING_OPERATOR_SESSION
        first = blockers[0]
        if first is RealHardwareBlocker.CONTROL_MODE_MUST_BE_REAL:
            return RealHardwareReadinessState.BLOCKED_BY_CONTROL_MODE
        if first in {
            RealHardwareBlocker.HARDWARE_POLICY_MUST_BE_FULL,
            RealHardwareBlocker.HARDWARE_POLICY_MUST_BE_READ_ONLY,
        }:
            return RealHardwareReadinessState.BLOCKED_BY_HARDWARE_POLICY
        if first in {
            RealHardwareBlocker.REAL_MOTION_NOT_ENABLED,
            RealHardwareBlocker.RAW_DIRECTION_TEST_NOT_ENABLED,
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
        if first in {
            RealHardwareBlocker.FIELD_ACCEPTANCE_NOT_PASSED,
            RealHardwareBlocker.FIELD_ACCEPTANCE_EVIDENCE_MISSING,
            RealHardwareBlocker.FIELD_ACCEPTANCE_EVIDENCE_STALE,
        }:
            return RealHardwareReadinessState.BLOCKED_BY_FIELD_ACCEPTANCE
        if first in {
            RealHardwareBlocker.SERVO_BUS_DEPENDENCY_UNAVAILABLE,
            RealHardwareBlocker.SERVO_BUS_DEPENDENCY_IDENTITY_MISSING,
            RealHardwareBlocker.EXPLICIT_DEVICE_MISSING,
            RealHardwareBlocker.DEVICE_SERVO_IDS_MISMATCH,
            RealHardwareBlocker.DEVICE_SAFETY_STATE_UNCERTAIN,
            RealHardwareBlocker.RAW_DIRECTION_ADAPTER_UNAVAILABLE,
        }:
            return RealHardwareReadinessState.BLOCKED_BY_DEVICE
        return RealHardwareReadinessState.BLOCKED_BY_OPERATOR_AUTHORIZATION
