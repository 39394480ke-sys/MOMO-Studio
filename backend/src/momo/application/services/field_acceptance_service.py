"""Evidence-derived staged field acceptance for one explicit robot unit."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from math import isclose
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from momo.application.services.device_diagnostics_service import DeviceDiagnosticsService
from momo.domain.commissioning import (
    CommissioningDirection,
    CommissioningTestEvidence,
    CommissioningTestResult,
    FieldAcceptanceBundle,
    FieldAcceptanceCapability,
    FieldAcceptanceEvidence,
    FieldAcceptanceEvidenceState,
    KinematicsEvidenceState,
    PhysicalStopVerification,
    PreMotionChecksSnapshot,
    PreMotionDiagnosticRecord,
    StopBehavior,
    ValidatedFieldAcceptanceBundle,
)
from momo.domain.enums import DomainUnit, ProfileVerificationStatus
from momo.domain.errors import HardwareMappingError, RobotApplicationError
from momo.domain.hardware_mapping import (
    goal_raw_to_logical,
    mapping_round_trip_tolerance,
    validate_goal_raw,
)
from momo.domain.real_hardware import (
    FieldAcceptanceEvidenceStatus,
    RealHardwareAuthorizationPurpose,
    RealHardwareContext,
    ServoDiagnosticRecord,
    calibration_fingerprint,
    effective_field_acceptance_status,
    explicit_device_fingerprint,
    field_acceptance_evidence_state,
    kinematics_verification_evidence_state,
)
from momo.domain.safety import validate_logical_value
from momo.ports.clock import Clock
from momo.ports.commissioning_evidence_repository import (
    CommissioningTestEvidenceRepository,
)
from momo.ports.field_acceptance_repository import FieldAcceptanceEvidenceRepository

_MAX_ACCEPTED_DIVERGENCE_RAW_COUNTS = 64
_MAX_PRE_MOTION_ACCEPTANCE_DELAY_S = 5.0
_SOFTWARE_STOP_PATH_EVIDENCE = frozenset(
    {
        StopBehavior.SOFTWARE_PATH_VERIFIED,
        StopBehavior.PHYSICAL_BEHAVIOR_PENDING,
    }
)


class FieldAcceptancePrerequisiteError(RobotApplicationError):
    code = "FIELD_ACCEPTANCE_NOT_AUTHORIZABLE"
    status_code = 403


class FieldAcceptanceManualPassForbiddenError(RobotApplicationError):
    """The removed global/manual PASS endpoint is intentionally fail closed."""

    code = "FIELD_ACCEPTANCE_MANUAL_PASS_FORBIDDEN"
    status_code = 403


class FieldAcceptanceIncompleteError(RobotApplicationError):
    code = "FIELD_ACCEPTANCE_INCOMPLETE"
    status_code = 409


class JointTestEvidenceIncompleteError(FieldAcceptanceIncompleteError):
    code = "JOINT_TEST_EVIDENCE_INCOMPLETE"


class FieldAcceptanceStorageError(RobotApplicationError):
    code = "FIELD_ACCEPTANCE_STORAGE_FAILED"
    status_code = 503


class FieldAcceptanceProgressState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    READ_ONLY_COMMISSIONING_COMPLETE = "READ_ONLY_COMMISSIONING_COMPLETE"
    CALIBRATION_COMPLETE = "CALIBRATION_COMPLETE"
    PRE_MOTION_CHECKS_COMPLETE = "PRE_MOTION_CHECKS_COMPLETE"
    JOINT_MOTION_TESTING = "JOINT_MOTION_TESTING"
    JOINT_MOTION_ACCEPTED = "JOINT_MOTION_ACCEPTED"
    KINEMATICS_VERIFICATION_PENDING = "KINEMATICS_VERIFICATION_PENDING"
    CARTESIAN_ACCEPTED = "CARTESIAN_ACCEPTED"
    PLAYBACK_ACCEPTED = "PLAYBACK_ACCEPTED"
    VISION_FOLLOW_ACCEPTED = "VISION_FOLLOW_ACCEPTED"
    FULL_ACCEPTANCE_COMPLETE = "FULL_ACCEPTANCE_COMPLETE"


class JointDirectionAcceptanceProgress(BaseModel):
    """Safe UI projection of the two persisted tests required for one joint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    joint_id: str
    unit: DomainUnit
    positive_evidence_id: UUID | None = None
    negative_evidence_id: UUID | None = None
    complete: bool


class FieldAcceptanceProgress(BaseModel):
    """Backend-derived acceptance progress; no field is client authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: FieldAcceptanceProgressState
    robot_unit_id: str
    checklist_version: str
    valid_capabilities: tuple[FieldAcceptanceCapability, ...]
    pre_motion_checks_complete: bool
    joint_motion_tests_complete: bool
    joint_motion_accepted: bool
    ready_to_accept_joint_motion: bool
    completed_joint_directions: int
    required_joint_directions: int
    joints: tuple[JointDirectionAcceptanceProgress, ...]
    selected_test_evidence_ids: tuple[UUID, ...]
    rejected_test_evidence_ids: tuple[UUID, ...]
    stale_field_acceptance_evidence_ids: tuple[UUID, ...]
    legacy_field_acceptance_evidence_ids: tuple[UUID, ...]
    physical_stop_verification: PhysicalStopVerification = PhysicalStopVerification.PENDING
    full_acceptance_complete: bool


def select_current_field_acceptance_bundle(
    context: RealHardwareContext,
    repository: FieldAcceptanceEvidenceRepository,
) -> FieldAcceptanceBundle:
    """Load the full immutable audit history without upgrading legacy records."""

    del context
    return FieldAcceptanceBundle(records=repository.list_evidence())


def select_current_field_acceptance_evidence(
    context: RealHardwareContext,
    repository: FieldAcceptanceEvidenceRepository,
) -> FieldAcceptanceEvidence | None:
    """Prefer the newest current v2 record; legacy v1 remains stale audit data."""

    records = repository.list_evidence()
    current = [
        evidence
        for evidence in records
        if field_acceptance_evidence_state(context, evidence)[0]
        is FieldAcceptanceEvidenceState.VALID
    ]
    if current:
        return max(current, key=lambda item: item.accepted_at)
    return max(records, key=lambda item: item.accepted_at, default=None)


def validated_field_acceptance_bundle(
    context: RealHardwareContext,
    field_records: tuple[FieldAcceptanceEvidence, ...],
    commissioning_records: tuple[CommissioningTestEvidence, ...],
) -> ValidatedFieldAcceptanceBundle:
    """Resolve persisted audit records into a transient authorization projection.

    PRE_MOTION contains a semantically checked diagnostic snapshot. JOINT_MOTION
    additionally has a complete cross-repository proof: every linked
    UUID must resolve to a current PASS for every enabled joint in both directions.
    Later capability records remain audit-only until their own typed field-test
    repositories and resolvers exist.
    """

    validated: list[FieldAcceptanceEvidence] = []
    for evidence in field_records:
        state, _ = field_acceptance_evidence_state(context, evidence)
        if state is not FieldAcceptanceEvidenceState.VALID:
            continue
        if (
            evidence.capability is FieldAcceptanceCapability.PRE_MOTION_CHECKS
            and _pre_motion_chain_is_complete(context, evidence)
        ) or (
            evidence.capability is FieldAcceptanceCapability.JOINT_MOTION
            and _joint_acceptance_chain_is_complete(context, evidence, commissioning_records)
        ):
            validated.append(evidence)
    return ValidatedFieldAcceptanceBundle(records=tuple(validated))


class FieldAcceptanceService:
    """Derive scoped acceptance only from current, persisted commissioning facts."""

    def __init__(
        self,
        *,
        device: DeviceDiagnosticsService,
        repository: FieldAcceptanceEvidenceRepository,
        clock: Clock,
        commissioning_repository: CommissioningTestEvidenceRepository | None = None,
    ) -> None:
        self.device = device
        self.repository = repository
        self.commissioning_repository = commissioning_repository
        self.clock = clock
        self._guard = asyncio.Lock()

    def status(self) -> FieldAcceptanceEvidenceStatus:
        """Compatibility summary for the existing read-only status route."""

        context, records = self._context_with_persisted_acceptance()
        evidence = _select_summary_evidence(context, records)
        state, stale_fields = field_acceptance_evidence_state(context, evidence)
        return FieldAcceptanceEvidenceStatus(
            state=state,
            effective_status=effective_field_acceptance_status(context),
            checklist_version=context.field_acceptance_checklist_version,
            stale_fields=stale_fields if evidence is not None else (),
            evidence_id=evidence.evidence_id if evidence is not None else None,
            accepted_at=evidence.accepted_at if evidence is not None else None,
            accepted_by=evidence.accepted_by if evidence is not None else None,
        )

    async def progress(self) -> FieldAcceptanceProgress:
        """Return per-capability and per-joint evidence progress for API projection."""

        context, field_records = self._context_with_persisted_acceptance()
        commissioning_records = await self._list_commissioning_evidence()
        return self._progress_from(context, field_records, commissioning_records)

    async def accept(
        self,
        token: str,
        *,
        checklist_version: str,
        confirmation_text: str,
        accepted_by: str | None,
    ) -> FieldAcceptanceEvidenceStatus:
        """Retained only to make the removed global/manual PASS fail explicitly."""

        del checklist_version, confirmation_text, accepted_by
        await self.device.authorize_operator_purpose(
            token,
            purpose=RealHardwareAuthorizationPurpose.DIAGNOSTICS,
        )
        raise FieldAcceptanceManualPassForbiddenError(
            "Field acceptance cannot be manually marked PASSED; complete each "
            "capability from persisted commissioning evidence"
        )

    async def complete_pre_motion_checks(
        self,
        token: str,
        *,
        checklist_version: str,
    ) -> FieldAcceptanceProgress:
        """Persist PRE_MOTION only after a fresh connected read-only checklist."""

        async with self._guard:
            session = await self.device.authorize_operator_purpose(
                token,
                purpose=RealHardwareAuthorizationPurpose.DIAGNOSTICS,
            )
            context = self.device.context
            self._require_current_checklist(context, checklist_version)
            self._require_current_identity(context)
            if not self.device.connected:
                raise FieldAcceptancePrerequisiteError(
                    "Pre-motion checks require the explicitly connected read-only device"
                )

            # These reads are the checklist evidence. They re-authorize the same
            # session and validate exact pings, modes, positions, bounds, and torque.
            snapshot = await self.device.diagnostics(token, include_torque=True)
            self._validate_pre_motion_snapshot(context, snapshot.records)
            current_session = await self.device.authorize_operator_purpose(
                token,
                purpose=RealHardwareAuthorizationPurpose.DIAGNOSTICS,
            )
            if current_session.session_id != session.session_id:
                raise FieldAcceptancePrerequisiteError(
                    "The read-only operator session changed during pre-motion checks"
                )
            typed_records: list[PreMotionDiagnosticRecord] = []
            for record in snapshot.records:
                if record.logical_value is None or record.raw_bounds is None:
                    raise FieldAcceptancePrerequisiteError(
                        "Pre-motion diagnostics lost required position or bounds data"
                    )
                typed_records.append(
                    PreMotionDiagnosticRecord(
                        joint_id=record.joint_id,
                        servo_id=record.servo_id,
                        ping_responded=True,
                        operating_mode=record.operating_mode,
                        present_raw=record.present_raw,
                        logical_value=record.logical_value,
                        raw_bounds=record.raw_bounds,
                        torque_enabled=False,
                    )
                )
            evidence = FieldAcceptanceEvidence.for_capability(
                context=context,
                capability=FieldAcceptanceCapability.PRE_MOTION_CHECKS,
                checklist_version=checklist_version,
                test_evidence_ids=(),
                accepted_at=self.clock.now(),
                accepted_by=session.operator_id,
                software_commit=self._software_commit(context),
                pre_motion_snapshot=PreMotionChecksSnapshot(
                    operator_session_id=session.session_id,
                    captured_at=snapshot.captured_at,
                    records=tuple(typed_records),
                ),
            )
            await self._persist_and_apply(
                evidence,
                token=token,
                expected_session_id=session.session_id,
            )
            return await self.progress()

    async def accept_joint_motion(
        self,
        token: str,
        *,
        checklist_version: str,
    ) -> FieldAcceptanceProgress:
        """Persist JOINT_MOTION only from every enabled joint in both directions."""

        async with self._guard:
            if self.commissioning_repository is None:
                raise FieldAcceptancePrerequisiteError(
                    "A persisted commissioning evidence repository is required"
                )
            session = await self.device.authorize_operator_purpose(
                token,
                purpose=(RealHardwareAuthorizationPurpose.COMMISSIONING_SINGLE_JOINT_TEST),
            )
            context, field_records = self._context_with_persisted_acceptance()
            self._require_current_checklist(context, checklist_version)
            self._require_current_identity(context)
            valid_capabilities = context.field_acceptance_bundle.valid_capabilities(context)
            if FieldAcceptanceCapability.PRE_MOTION_CHECKS not in valid_capabilities:
                raise FieldAcceptanceIncompleteError(
                    "Current pre-motion acceptance is required before joint acceptance",
                    details={"missing_capability": "PRE_MOTION_CHECKS"},
                )
            commissioning_records = await self._list_commissioning_evidence()
            progress = self._progress_from(context, field_records, commissioning_records)
            if not progress.joint_motion_tests_complete:
                raise JointTestEvidenceIncompleteError(
                    "Every enabled joint requires current positive and negative test evidence",
                    details=progress.model_dump(mode="json"),
                )

            current_session = await self.device.authorize_operator_purpose(
                token,
                purpose=(RealHardwareAuthorizationPurpose.COMMISSIONING_SINGLE_JOINT_TEST),
            )
            if current_session.session_id != session.session_id:
                raise FieldAcceptancePrerequisiteError(
                    "The commissioning-motion session changed during evidence review"
                )
            evidence = FieldAcceptanceEvidence.for_capability(
                context=context,
                capability=FieldAcceptanceCapability.JOINT_MOTION,
                checklist_version=checklist_version,
                test_evidence_ids=progress.selected_test_evidence_ids,
                accepted_at=self.clock.now(),
                accepted_by=session.operator_id,
                software_commit=self._software_commit(context),
            )
            await self._persist_and_apply(
                evidence,
                token=token,
                expected_session_id=session.session_id,
            )
            return await self.progress()

    async def _persist_and_apply(
        self,
        evidence: FieldAcceptanceEvidence,
        *,
        token: str,
        expected_session_id: UUID,
    ) -> None:
        context_records = self.device.context.field_acceptance_bundle.records
        commissioning_records = await self._list_commissioning_evidence()
        resolved_bundle = validated_field_acceptance_bundle(
            self.device.context,
            _merge_field_records(context_records, (evidence,)),
            commissioning_records,
        )
        if evidence.evidence_id not in {item.evidence_id for item in resolved_bundle.records}:
            raise FieldAcceptancePrerequisiteError(
                "Field acceptance did not resolve to a complete evidence chain"
            )

        async def persist() -> None:
            try:
                await asyncio.to_thread(self.repository.save, evidence)
            except OSError as error:
                raise FieldAcceptanceStorageError(
                    "Field acceptance evidence could not be persisted atomically"
                ) from error

        try:
            await self.device.apply_field_acceptance_evidence(
                evidence,
                validated_bundle=resolved_bundle,
                token=token,
                expected_session_id=expected_session_id,
                persist=persist,
            )
        except ValueError as error:
            raise FieldAcceptancePrerequisiteError(
                "Hardware identity or session changed while applying acceptance evidence"
            ) from error

    def _context_with_persisted_acceptance(
        self,
    ) -> tuple[RealHardwareContext, tuple[FieldAcceptanceEvidence, ...]]:
        try:
            stored = self.repository.list_evidence()
        except OSError as error:
            raise FieldAcceptanceStorageError(
                "Field acceptance evidence could not be loaded"
            ) from error
        current_pointer = self.device.context.field_acceptance_evidence
        context_records = self.device.context.field_acceptance_bundle.records + (
            (current_pointer,) if current_pointer is not None else ()
        )
        records = _merge_field_records(context_records, stored)
        return self.device.context, records

    async def _list_commissioning_evidence(self) -> tuple[CommissioningTestEvidence, ...]:
        if self.commissioning_repository is None:
            return ()
        try:
            return await self.commissioning_repository.list_evidence()
        except OSError as error:
            raise FieldAcceptanceStorageError(
                "Commissioning test evidence could not be loaded"
            ) from error

    def _progress_from(
        self,
        context: RealHardwareContext,
        field_records: tuple[FieldAcceptanceEvidence, ...],
        commissioning_records: tuple[CommissioningTestEvidence, ...],
    ) -> FieldAcceptanceProgress:
        profile = context.profile
        enabled_joints = tuple(profile.enabled_joints) if profile is not None else ()
        definitions = profile.definitions_by_id if profile is not None else {}
        eligible: dict[
            tuple[str, CommissioningDirection],
            CommissioningTestEvidence,
        ] = {}
        rejected: list[UUID] = []
        for test_evidence in commissioning_records:
            if not _commissioning_evidence_is_current(context, test_evidence):
                rejected.append(test_evidence.id)
                continue
            key = (test_evidence.joint_id, test_evidence.direction_expected)
            previous = eligible.get(key)
            if previous is None or test_evidence.completed_at > previous.completed_at:
                eligible[key] = test_evidence

        joints = tuple(
            JointDirectionAcceptanceProgress(
                joint_id=joint_id,
                unit=definitions[joint_id].domain_unit,
                positive_evidence_id=(
                    eligible[(joint_id, CommissioningDirection.POSITIVE)].id
                    if (joint_id, CommissioningDirection.POSITIVE) in eligible
                    else None
                ),
                negative_evidence_id=(
                    eligible[(joint_id, CommissioningDirection.NEGATIVE)].id
                    if (joint_id, CommissioningDirection.NEGATIVE) in eligible
                    else None
                ),
                complete=(
                    (joint_id, CommissioningDirection.POSITIVE) in eligible
                    and (joint_id, CommissioningDirection.NEGATIVE) in eligible
                ),
            )
            for joint_id in enabled_joints
        )
        selected_ids = tuple(
            selected_evidence.id
            for joint_id in enabled_joints
            for direction in (
                CommissioningDirection.POSITIVE,
                CommissioningDirection.NEGATIVE,
            )
            if (selected_evidence := eligible.get((joint_id, direction))) is not None
        )
        completed_directions = len(selected_ids)
        required_directions = len(enabled_joints) * 2
        tests_complete = bool(enabled_joints) and completed_directions == required_directions

        valid_capabilities = context.field_acceptance_bundle.valid_capabilities(context)
        ordered_capabilities = tuple(
            capability
            for capability in FieldAcceptanceCapability
            if capability in valid_capabilities
        )
        pre_motion_complete = FieldAcceptanceCapability.PRE_MOTION_CHECKS in valid_capabilities
        joint_accepted = FieldAcceptanceCapability.JOINT_MOTION in valid_capabilities
        stale_ids: list[UUID] = []
        legacy_ids: list[UUID] = []
        for field_evidence in field_records:
            evidence_state, _ = field_acceptance_evidence_state(context, field_evidence)
            if evidence_state is FieldAcceptanceEvidenceState.STALE_LEGACY_EVIDENCE:
                legacy_ids.append(field_evidence.evidence_id)
            elif evidence_state is FieldAcceptanceEvidenceState.STALE:
                stale_ids.append(field_evidence.evidence_id)

        full_complete = frozenset(FieldAcceptanceCapability) <= valid_capabilities
        progress_state = _progress_state(
            context,
            valid_capabilities=valid_capabilities,
            completed_directions=completed_directions,
            full_complete=full_complete,
        )
        return FieldAcceptanceProgress(
            state=progress_state,
            robot_unit_id=context.robot_unit_id,
            checklist_version=context.field_acceptance_checklist_version,
            valid_capabilities=ordered_capabilities,
            pre_motion_checks_complete=pre_motion_complete,
            joint_motion_tests_complete=tests_complete,
            joint_motion_accepted=joint_accepted,
            ready_to_accept_joint_motion=(
                pre_motion_complete and tests_complete and not joint_accepted
            ),
            completed_joint_directions=completed_directions,
            required_joint_directions=required_directions,
            joints=joints,
            selected_test_evidence_ids=selected_ids,
            rejected_test_evidence_ids=tuple(dict.fromkeys(rejected)),
            stale_field_acceptance_evidence_ids=tuple(dict.fromkeys(stale_ids)),
            legacy_field_acceptance_evidence_ids=tuple(dict.fromkeys(legacy_ids)),
            physical_stop_verification=context.physical_stop_verification,
            full_acceptance_complete=full_complete,
        )

    def _require_current_identity(self, context: RealHardwareContext) -> None:
        profile = context.profile
        calibration = context.calibration
        device = context.device
        if profile is None or calibration is None or device is None:
            raise FieldAcceptancePrerequisiteError(
                "Current Profile, complete Calibration, and explicit Device are required"
            )
        if (
            not context.robot_unit_id
            or device.robot_unit_id != context.robot_unit_id
            or calibration.robot_unit_id != context.robot_unit_id
        ):
            raise FieldAcceptancePrerequisiteError(
                "Profile-independent robot unit identity is missing or inconsistent"
            )
        if (
            profile.template
            or profile.verification_status is not ProfileVerificationStatus.VERIFIED_FOR_REAL
        ):
            raise FieldAcceptancePrerequisiteError(
                "The current Profile is not reviewed for Real commissioning"
            )
        blockers = self.device.authorization.calibration_blockers(context)
        if blockers:
            raise FieldAcceptancePrerequisiteError(
                "Calibration is not valid for staged field acceptance",
                details={"blocking_reasons": [item.value for item in blockers]},
            )
        self._software_commit(context)

    @staticmethod
    def _require_current_checklist(
        context: RealHardwareContext,
        checklist_version: str,
    ) -> None:
        if checklist_version != context.field_acceptance_checklist_version:
            raise FieldAcceptancePrerequisiteError(
                "The field-acceptance checklist version is not current",
                details={"expected_checklist_version": context.field_acceptance_checklist_version},
            )

    @staticmethod
    def _software_commit(context: RealHardwareContext) -> str:
        commit = context.software_commit.strip()
        if not 7 <= len(commit) <= 64:
            raise FieldAcceptancePrerequisiteError(
                "A current 7-to-64-character software commit identity is required"
            )
        return commit

    @staticmethod
    def _validate_pre_motion_snapshot(
        context: RealHardwareContext,
        records: tuple[ServoDiagnosticRecord, ...],
    ) -> None:
        profile = context.profile
        if profile is None:
            raise FieldAcceptancePrerequisiteError("A current Profile is required")
        if len(records) != len(profile.enabled_joints):
            raise FieldAcceptancePrerequisiteError(
                "Pre-motion diagnostics did not cover every enabled joint"
            )
        by_joint = {record.joint_id: record for record in records}
        if set(by_joint) != set(profile.enabled_joints):
            raise FieldAcceptancePrerequisiteError(
                "Pre-motion diagnostics did not exactly match enabled joints"
            )
        blockers: list[str] = []
        for joint_id in profile.enabled_joints:
            record = by_joint[joint_id]
            if record.ping_responded is not True:
                blockers.append(f"{joint_id}:PING")
            if record.logical_value is None:
                blockers.append(f"{joint_id}:LOGICAL_POSITION")
            if record.raw_bounds is None:
                blockers.append(f"{joint_id}:RAW_BOUNDS")
            if record.torque_enabled is not False:
                blockers.append(f"{joint_id}:TORQUE_NOT_CONFIRMED_DISABLED")
        if blockers:
            raise FieldAcceptancePrerequisiteError(
                "The connected read-only pre-motion checklist is incomplete",
                details={"blocking_checks": blockers},
            )


def _merge_field_records(
    first: tuple[FieldAcceptanceEvidence, ...],
    second: tuple[FieldAcceptanceEvidence, ...],
) -> tuple[FieldAcceptanceEvidence, ...]:
    merged: dict[UUID, FieldAcceptanceEvidence] = {}
    for evidence in (*first, *second):
        merged[evidence.evidence_id] = evidence
    return tuple(merged.values())


def _select_summary_evidence(
    context: RealHardwareContext,
    records: tuple[FieldAcceptanceEvidence, ...],
) -> FieldAcceptanceEvidence | None:
    current = [
        evidence
        for evidence in records
        if field_acceptance_evidence_state(context, evidence)[0]
        is FieldAcceptanceEvidenceState.VALID
    ]
    if current:
        return max(current, key=lambda item: item.accepted_at)
    return max(records, key=lambda item: item.accepted_at, default=None)


def _pre_motion_chain_is_complete(
    context: RealHardwareContext,
    acceptance: FieldAcceptanceEvidence,
) -> bool:
    profile = context.profile
    calibration = context.calibration
    device = context.device
    snapshot = acceptance.pre_motion_snapshot
    if (
        acceptance.capability is not FieldAcceptanceCapability.PRE_MOTION_CHECKS
        or profile is None
        or calibration is None
        or device is None
        or snapshot is None
        or acceptance.test_evidence_ids
    ):
        return False
    capture_delay_s = (acceptance.accepted_at - snapshot.captured_at).total_seconds()
    if not 0.0 <= capture_delay_s <= _MAX_PRE_MOTION_ACCEPTANCE_DELAY_S:
        return False
    by_joint = {record.joint_id: record for record in snapshot.records}
    if set(by_joint) != set(profile.enabled_joints):
        return False
    if {record.servo_id for record in snapshot.records} != set(device.servo_ids):
        return False
    for joint_id in profile.enabled_joints:
        definition = profile.definitions_by_id[joint_id]
        calibration_joint = calibration.joints_by_id.get(joint_id)
        record = by_joint[joint_id]
        if (
            calibration_joint is None
            or definition.servo_id is None
            or calibration_joint.raw_bounds is None
            or record.servo_id != definition.servo_id
            or record.servo_id != calibration_joint.servo_id
            or record.operating_mode != calibration_joint.operating_mode.value
            or record.raw_bounds != calibration_joint.raw_bounds
        ):
            return False
        try:
            validate_goal_raw(joint_id, record.present_raw, profile, calibration_joint)
            logical_value = goal_raw_to_logical(
                joint_id,
                record.present_raw,
                profile,
                calibration_joint,
            )
            tolerance = mapping_round_trip_tolerance(definition)
        except (HardwareMappingError, KeyError):
            return False
        if not isclose(record.logical_value, logical_value, abs_tol=tolerance):
            return False
    return True


def _commissioning_evidence_is_current(
    context: RealHardwareContext,
    evidence: CommissioningTestEvidence,
) -> bool:
    profile = context.profile
    calibration = context.calibration
    device = context.device
    if profile is None or calibration is None or device is None:
        return False
    prepared = evidence.prepared_command
    if (
        evidence.result is not CommissioningTestResult.PASSED
        or prepared is None
        or prepared.envelope != context.commissioning_safety_envelope
        or evidence.failure_reason_optional is not None
        or evidence.robot_unit_id != context.robot_unit_id
        or calibration.robot_unit_id != context.robot_unit_id
        or device.robot_unit_id != context.robot_unit_id
        or evidence.robot_variant is not profile.variant
        or evidence.profile_fingerprint != profile.fingerprint
        or evidence.calibration_fingerprint != calibration_fingerprint(calibration)
        or evidence.device_fingerprint != explicit_device_fingerprint(device)
        or evidence.joint_id not in profile.enabled_joints
        or evidence.stop_behavior not in _SOFTWARE_STOP_PATH_EVIDENCE
        or not evidence.request_id.strip()
        or not evidence.measured_or_observed_result.strip()
    ):
        return False
    definition = profile.definitions_by_id[evidence.joint_id]
    calibration_joint = calibration.joints_by_id.get(evidence.joint_id)
    if calibration_joint is None or evidence.unit is not definition.domain_unit:
        return False
    expected_direction = (
        CommissioningDirection.POSITIVE
        if evidence.requested_delta > 0.0
        else CommissioningDirection.NEGATIVE
        if evidence.requested_delta < 0.0
        else None
    )
    observed_delta = evidence.final_value - evidence.start_value
    observed_direction = (
        CommissioningDirection.POSITIVE
        if observed_delta > 0.0
        else CommissioningDirection.NEGATIVE
        if observed_delta < 0.0
        else None
    )
    if (
        expected_direction is None
        or evidence.direction_expected is not expected_direction
        or evidence.direction_observed is not expected_direction
        or observed_direction is not expected_direction
        or evidence.start_raw == evidence.final_raw
        or evidence.start_raw == evidence.prepared_target_raw
        or abs(evidence.final_raw - evidence.prepared_target_raw)
        > _MAX_ACCEPTED_DIVERGENCE_RAW_COUNTS
    ):
        return False
    try:
        for raw_value in (
            evidence.start_raw,
            evidence.prepared_target_raw,
            evidence.final_raw,
        ):
            validate_goal_raw(evidence.joint_id, raw_value, profile, calibration_joint)
        for logical_value in (
            evidence.start_value,
            evidence.target_value,
            evidence.final_value,
        ):
            validate_logical_value(
                evidence.joint_id,
                logical_value,
                profile,
                calibration_joint,
            )
        mapped_start = goal_raw_to_logical(
            evidence.joint_id,
            evidence.start_raw,
            profile,
            calibration_joint,
        )
        mapped_target = goal_raw_to_logical(
            evidence.joint_id,
            evidence.prepared_target_raw,
            profile,
            calibration_joint,
        )
        mapped_final = goal_raw_to_logical(
            evidence.joint_id,
            evidence.final_raw,
            profile,
            calibration_joint,
        )
        tolerance = mapping_round_trip_tolerance(definition)
    except (HardwareMappingError, KeyError):
        return False
    return all(
        (
            isclose(evidence.start_value, mapped_start, abs_tol=tolerance),
            isclose(evidence.target_value, mapped_target, abs_tol=tolerance),
            isclose(evidence.final_value, mapped_final, abs_tol=tolerance),
            isclose(
                evidence.target_value,
                evidence.start_value + evidence.requested_delta,
                abs_tol=tolerance,
            ),
            isclose(
                evidence.divergence,
                abs(evidence.final_value - evidence.target_value),
                abs_tol=tolerance,
            ),
            evidence.divergence <= tolerance * (_MAX_ACCEPTED_DIVERGENCE_RAW_COUNTS + 1),
        )
    )


def _joint_acceptance_chain_is_complete(
    context: RealHardwareContext,
    acceptance: FieldAcceptanceEvidence,
    commissioning_records: tuple[CommissioningTestEvidence, ...],
) -> bool:
    profile = context.profile
    if profile is None or acceptance.capability is not FieldAcceptanceCapability.JOINT_MOTION:
        return False
    by_id = {record.id: record for record in commissioning_records}
    try:
        linked = tuple(by_id[evidence_id] for evidence_id in acceptance.test_evidence_ids)
    except KeyError:
        return False
    required_keys = {
        (joint_id, direction)
        for joint_id in profile.enabled_joints
        for direction in (
            CommissioningDirection.POSITIVE,
            CommissioningDirection.NEGATIVE,
        )
    }
    if len(linked) != len(required_keys):
        return False
    actual_keys: set[tuple[str, CommissioningDirection]] = set()
    for evidence in linked:
        if (
            not _commissioning_evidence_is_current(context, evidence)
            or evidence.software_commit != context.software_commit
            or evidence.software_commit != acceptance.software_commit
            or evidence.completed_at > acceptance.accepted_at
        ):
            return False
        actual_keys.add((evidence.joint_id, evidence.direction_expected))
    return actual_keys == required_keys


def _progress_state(
    context: RealHardwareContext,
    *,
    valid_capabilities: frozenset[FieldAcceptanceCapability],
    completed_directions: int,
    full_complete: bool,
) -> FieldAcceptanceProgressState:
    if full_complete:
        return FieldAcceptanceProgressState.FULL_ACCEPTANCE_COMPLETE
    if FieldAcceptanceCapability.VISION_FOLLOW in valid_capabilities:
        return FieldAcceptanceProgressState.VISION_FOLLOW_ACCEPTED
    if FieldAcceptanceCapability.PLAYBACK in valid_capabilities:
        return FieldAcceptanceProgressState.PLAYBACK_ACCEPTED
    if FieldAcceptanceCapability.CARTESIAN in valid_capabilities:
        return FieldAcceptanceProgressState.CARTESIAN_ACCEPTED
    if FieldAcceptanceCapability.JOINT_MOTION in valid_capabilities:
        kinematics_state, _ = kinematics_verification_evidence_state(context)
        if kinematics_state is not KinematicsEvidenceState.VALID:
            return FieldAcceptanceProgressState.KINEMATICS_VERIFICATION_PENDING
        return FieldAcceptanceProgressState.JOINT_MOTION_ACCEPTED
    if completed_directions:
        return FieldAcceptanceProgressState.JOINT_MOTION_TESTING
    if FieldAcceptanceCapability.PRE_MOTION_CHECKS in valid_capabilities:
        return FieldAcceptanceProgressState.PRE_MOTION_CHECKS_COMPLETE
    if context.calibration is not None:
        return FieldAcceptanceProgressState.CALIBRATION_COMPLETE
    if context.profile is not None and context.device is not None:
        return FieldAcceptanceProgressState.READ_ONLY_COMMISSIONING_COMPLETE
    return FieldAcceptanceProgressState.NOT_STARTED


__all__ = [
    "FieldAcceptanceIncompleteError",
    "FieldAcceptanceManualPassForbiddenError",
    "FieldAcceptancePrerequisiteError",
    "FieldAcceptanceProgress",
    "FieldAcceptanceProgressState",
    "FieldAcceptanceService",
    "FieldAcceptanceStorageError",
    "JointDirectionAcceptanceProgress",
    "JointTestEvidenceIncompleteError",
    "select_current_field_acceptance_bundle",
    "select_current_field_acceptance_evidence",
    "validated_field_acceptance_bundle",
]
