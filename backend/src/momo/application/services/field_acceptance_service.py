"""Safe creation and current-context interpretation of field acceptance evidence."""

from __future__ import annotations

import asyncio
import secrets

from momo.application.services.device_diagnostics_service import DeviceDiagnosticsService
from momo.domain.errors import RobotApplicationError
from momo.domain.real_hardware import (
    REQUIRED_FIELD_ACCEPTANCE_CONFIRMATION_TEXT,
    FieldAcceptanceEvidence,
    FieldAcceptanceEvidenceState,
    FieldAcceptanceEvidenceStatus,
    RealHardwareAuthorizationPurpose,
    RealHardwareContext,
    calibration_fingerprint,
    effective_field_acceptance_status,
    explicit_device_fingerprint,
    field_acceptance_evidence_state,
)
from momo.ports.clock import Clock
from momo.ports.field_acceptance_repository import FieldAcceptanceEvidenceRepository


class FieldAcceptancePrerequisiteError(RobotApplicationError):
    code = "FIELD_ACCEPTANCE_NOT_AUTHORIZABLE"
    status_code = 403


class FieldAcceptanceConfirmationError(RobotApplicationError):
    code = "FIELD_ACCEPTANCE_CONFIRMATION_INVALID"
    status_code = 422


class FieldAcceptanceStorageError(RobotApplicationError):
    code = "FIELD_ACCEPTANCE_STORAGE_FAILED"
    status_code = 503


def select_current_field_acceptance_evidence(
    context: RealHardwareContext,
    repository: FieldAcceptanceEvidenceRepository,
) -> FieldAcceptanceEvidence | None:
    """Prefer a valid historical record, otherwise expose the newest as stale."""

    records = repository.list_evidence()
    for evidence in records:
        prospective = context.model_copy(update={"field_acceptance_evidence": evidence})
        state, _ = field_acceptance_evidence_state(prospective)
        if state is FieldAcceptanceEvidenceState.VALID:
            return evidence
    return records[0] if records else None


class FieldAcceptanceService:
    """Acceptance requires an active read-only session and never grants motion itself."""

    def __init__(
        self,
        *,
        device: DeviceDiagnosticsService,
        repository: FieldAcceptanceEvidenceRepository,
        clock: Clock,
    ) -> None:
        self.device = device
        self.repository = repository
        self.clock = clock
        self._guard = asyncio.Lock()

    def status(self) -> FieldAcceptanceEvidenceStatus:
        context = self.device.context
        evidence = context.field_acceptance_evidence
        state, stale_fields = field_acceptance_evidence_state(context)
        return FieldAcceptanceEvidenceStatus(
            state=state,
            effective_status=effective_field_acceptance_status(context),
            checklist_version=context.field_acceptance_checklist_version,
            stale_fields=stale_fields if evidence is not None else (),
            evidence_id=evidence.evidence_id if evidence is not None else None,
            accepted_at=evidence.accepted_at if evidence is not None else None,
            accepted_by=evidence.accepted_by if evidence is not None else None,
        )

    async def accept(
        self,
        token: str,
        *,
        checklist_version: str,
        confirmation_text: str,
        accepted_by: str | None,
    ) -> FieldAcceptanceEvidenceStatus:
        async with self._guard:
            await self.device.authorize_operator_purpose(
                token,
                purpose=RealHardwareAuthorizationPurpose.DIAGNOSTICS,
            )
            if not self.device.connected:
                raise FieldAcceptancePrerequisiteError(
                    "Field acceptance requires the explicitly connected read-only device"
                )
            if not isinstance(confirmation_text, str) or not secrets.compare_digest(
                confirmation_text.encode("utf-8"),
                REQUIRED_FIELD_ACCEPTANCE_CONFIRMATION_TEXT.encode("utf-8"),
            ):
                raise FieldAcceptanceConfirmationError(
                    "The field-acceptance confirmation text did not match exactly"
                )
            context = self.device.context
            if checklist_version != context.field_acceptance_checklist_version:
                raise FieldAcceptancePrerequisiteError(
                    "The field-acceptance checklist version is not current",
                    details={
                        "expected_checklist_version": (context.field_acceptance_checklist_version)
                    },
                )
            profile = context.profile
            calibration = context.calibration
            device = context.device
            if profile is None or calibration is None or device is None:
                raise FieldAcceptancePrerequisiteError(
                    "Profile, complete Calibration, and explicit Device are required"
                )
            calibration_blockers = self.device.authorization.calibration_blockers(context)
            if calibration_blockers:
                raise FieldAcceptancePrerequisiteError(
                    "Calibration is not valid for field acceptance",
                    details={"blocking_reasons": [item.value for item in calibration_blockers]},
                )
            if context.kinematics is not None:
                try:
                    context.kinematics.validate_against_profile(profile)
                except ValueError as error:
                    raise FieldAcceptancePrerequisiteError(
                        "Kinematics does not match the active Profile"
                    ) from error
                if (
                    context.expected_kinematics_fingerprint is not None
                    and context.kinematics.fingerprint != context.expected_kinematics_fingerprint
                ):
                    raise FieldAcceptancePrerequisiteError(
                        "Kinematics fingerprint is not the configured current artifact"
                    )
            evidence = FieldAcceptanceEvidence(
                robot_variant=profile.variant,
                profile_fingerprint=profile.fingerprint,
                calibration_fingerprint=calibration_fingerprint(calibration),
                kinematics_fingerprint=(
                    context.kinematics.fingerprint if context.kinematics is not None else None
                ),
                device_fingerprint=explicit_device_fingerprint(device),
                checklist_version=checklist_version,
                accepted_at=self.clock.now(),
                accepted_by=accepted_by,
            )
            try:
                await asyncio.to_thread(self.repository.save, evidence)
            except OSError as error:
                raise FieldAcceptanceStorageError(
                    "Field acceptance evidence could not be persisted atomically"
                ) from error
            await self.device.apply_field_acceptance_evidence(evidence)
            return self.status()


__all__ = [
    "FieldAcceptanceConfirmationError",
    "FieldAcceptancePrerequisiteError",
    "FieldAcceptanceService",
    "FieldAcceptanceStorageError",
    "select_current_field_acceptance_evidence",
]
