"""Evaluate calibration compatibility without granting real-hardware readiness."""

from __future__ import annotations

from momo.domain.calibration import CalibrationDocument, CalibrationStatusReport
from momo.domain.enums import CalibrationStatus, RealReadiness, RobotVariant
from momo.domain.errors import HardwareMappingError
from momo.domain.hardware_mapping import effective_raw_bounds
from momo.domain.robot import RobotProfile
from momo.ports.calibration_repository import CalibrationRepository


class CalibrationService:
    def __init__(self, repository: CalibrationRepository) -> None:
        self.repository = repository

    def get_for_variant(self, variant: RobotVariant) -> CalibrationDocument | None:
        return self.repository.get_for_variant(variant)

    def status(
        self,
        profile: RobotProfile,
        document: CalibrationDocument | None = None,
    ) -> CalibrationStatusReport:
        calibration = document if document is not None else self.get_for_variant(profile.variant)
        if calibration is None:
            return CalibrationStatusReport(
                status=CalibrationStatus.NOT_CONFIGURED,
                configured=False,
                template=None,
                variant_match=None,
                profile_match=None,
                joint_set_match=None,
                mapping_match=None,
                complete=None,
                calibration_valid=False,
                real_readiness=RealReadiness.BLOCKED_BY_STAGE_POLICY,
                blocking_reasons=[
                    "No calibration document is configured",
                    "Stage 3 hardware access policy is DISABLED",
                ],
            )

        variant_match = calibration.robot_variant is profile.variant
        profile_match = calibration.profile_fingerprint == profile.fingerprint
        expected = set(profile.enabled_joints)
        actual = {joint.joint_id for joint in calibration.joints}
        joint_set_match = actual == expected
        mapping_match = joint_set_match and self._hardware_mapping_matches(profile, calibration)
        complete = all(joint.complete for joint in calibration.joints)

        if not variant_match:
            status = CalibrationStatus.VARIANT_MISMATCH
        elif not profile_match:
            status = CalibrationStatus.PROFILE_MISMATCH
        elif not joint_set_match:
            status = CalibrationStatus.JOINT_SET_MISMATCH
        elif not mapping_match or not complete:
            status = CalibrationStatus.INCOMPLETE
        elif calibration.template:
            status = CalibrationStatus.TEMPLATE_ONLY
        else:
            status = CalibrationStatus.VALID_FOR_DRY_RUN

        reasons = ["Stage 3 hardware access policy is DISABLED"]
        if calibration.template:
            reasons.append("Template calibration cannot authorize real hardware")
        if not variant_match:
            reasons.append("Calibration robot variant does not match the active profile")
        if not profile_match:
            reasons.append("Calibration profile fingerprint does not match")
        if not joint_set_match:
            reasons.append("Calibration joint set does not exactly match enabled_joints")
        if joint_set_match and not mapping_match:
            reasons.append("Calibration servo, mode, or raw bounds do not match the profile")
        if not complete:
            reasons.append("Calibration has incomplete Home or multi-turn Phase data")

        return CalibrationStatusReport(
            status=status,
            configured=True,
            template=calibration.template,
            variant_match=variant_match,
            profile_match=profile_match,
            joint_set_match=joint_set_match,
            mapping_match=mapping_match,
            complete=complete,
            calibration_valid=(
                variant_match and profile_match and joint_set_match and mapping_match and complete
            ),
            real_readiness=RealReadiness.BLOCKED_BY_STAGE_POLICY,
            blocking_reasons=reasons,
        )

    @staticmethod
    def _hardware_mapping_matches(
        profile: RobotProfile,
        calibration: CalibrationDocument,
    ) -> bool:
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
