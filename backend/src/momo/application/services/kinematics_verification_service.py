"""Measured-TCP workflow for device-local Kinematics verification evidence."""

from __future__ import annotations

import asyncio
from math import acos, degrees, hypot
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from momo.application.services.device_diagnostics_service import DeviceDiagnosticsService
from momo.application.services.kinematics_service import KinematicsService
from momo.domain.commissioning import (
    FieldAcceptanceCapability,
    KinematicsEvidenceState,
    KinematicsVerificationEvidence,
    KinematicsVerificationPoint,
    KinematicsVerificationThresholds,
)
from momo.domain.errors import RobotApplicationError
from momo.domain.pose import TcpPose
from momo.domain.real_hardware import (
    OperatorSessionEvidence,
    RealHardwareAuthorizationPurpose,
    calibration_fingerprint,
    explicit_device_fingerprint,
    kinematics_verification_evidence_state,
)
from momo.ports.clock import Clock
from momo.ports.kinematics_joint_snapshot import (
    KinematicsJointStateSnapshot,
    KinematicsJointStateSnapshotProvider,
)
from momo.ports.kinematics_verification_repository import (
    KinematicsVerificationEvidenceRepository,
)


class KinematicsVerificationPrerequisiteError(RobotApplicationError):
    code = "KINEMATICS_VERIFICATION_PENDING"
    status_code = 403


class KinematicsVerificationDraftError(RobotApplicationError):
    code = "KINEMATICS_VERIFICATION_DRAFT_INVALID"
    status_code = 409


class KinematicsVerificationThresholdError(RobotApplicationError):
    code = "KINEMATICS_VERIFICATION_THRESHOLD_FAILED"
    status_code = 422


MAX_KINEMATICS_SNAPSHOT_AGE_S = 0.25


class KinematicsVerificationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: KinematicsEvidenceState
    stale_fields: tuple[str, ...] = ()
    evidence_id: UUID | None = None
    point_count: int = Field(default=0, ge=0)


class KinematicsVerificationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    draft_id: UUID = Field(default_factory=uuid4)
    operator_session_id: UUID
    operator_id: str
    robot_unit_id: str
    profile_fingerprint: str
    calibration_fingerprint: str
    device_fingerprint: str
    kinematics_fingerprint: str
    software_commit: str
    verification_checklist_version: str
    thresholds: KinematicsVerificationThresholds
    points: tuple[KinematicsVerificationPoint, ...] = ()


class KinematicsVerificationService:
    """Accumulate multiple backend-predicted points, then atomically commit evidence."""

    def __init__(
        self,
        *,
        device: DeviceDiagnosticsService,
        kinematics: KinematicsService,
        repository: KinematicsVerificationEvidenceRepository,
        clock: Clock,
        joint_state_snapshot_provider: KinematicsJointStateSnapshotProvider | None = None,
        max_snapshot_age_s: float = MAX_KINEMATICS_SNAPSHOT_AGE_S,
    ) -> None:
        if not 0.0 < max_snapshot_age_s <= MAX_KINEMATICS_SNAPSHOT_AGE_S:
            raise ValueError("max_snapshot_age_s must be positive and cannot exceed the hard cap")
        self.device = device
        self.kinematics = kinematics
        self.repository = repository
        self.clock = clock
        self.joint_state_snapshot_provider = joint_state_snapshot_provider
        self.max_snapshot_age_s = max_snapshot_age_s
        self._drafts: dict[UUID, KinematicsVerificationDraft] = {}
        self._guard = asyncio.Lock()

    def status(self) -> KinematicsVerificationStatus:
        state, stale_fields = kinematics_verification_evidence_state(self.device.context)
        evidence = self.device.context.kinematics_verification_evidence
        return KinematicsVerificationStatus(
            state=state,
            stale_fields=stale_fields,
            evidence_id=evidence.id if evidence is not None else None,
            point_count=len(evidence.test_points) if evidence is not None else 0,
        )

    async def start_draft(
        self,
        token: str,
        *,
        thresholds: KinematicsVerificationThresholds | None = None,
    ) -> KinematicsVerificationDraft:
        session = await self._authorize(token)
        context = self.device.context
        profile = context.profile
        calibration = context.calibration
        model = context.kinematics
        device = context.device
        if (
            profile is None
            or calibration is None
            or model is None
            or device is None
            or not context.robot_unit_id
        ):
            raise KinematicsVerificationPrerequisiteError(
                "Current unit, Profile, Calibration, and Kinematics model are required"
            )
        if len(context.software_commit) < 7 or context.software_commit == "unknown":
            raise KinematicsVerificationPrerequisiteError(
                "An explicit software commit is required for Kinematics evidence"
            )
        if (
            FieldAcceptanceCapability.JOINT_MOTION
            not in context.field_acceptance_bundle.valid_capabilities(context)
        ):
            raise KinematicsVerificationPrerequisiteError(
                "Joint Motion acceptance is required before Kinematics verification"
            )
        draft = KinematicsVerificationDraft(
            operator_session_id=session.session_id,
            operator_id=session.operator_id,
            robot_unit_id=context.robot_unit_id,
            profile_fingerprint=profile.fingerprint,
            calibration_fingerprint=calibration_fingerprint(calibration),
            device_fingerprint=explicit_device_fingerprint(device),
            kinematics_fingerprint=model.fingerprint,
            software_commit=context.software_commit,
            verification_checklist_version=context.kinematics_verification_checklist_version,
            thresholds=thresholds or KinematicsVerificationThresholds(),
        )
        async with self._guard:
            self._drafts[draft.draft_id] = draft
        return draft

    async def add_measurement(
        self,
        token: str,
        draft_id: UUID,
        *,
        label: str,
        measured_tcp: TcpPose,
    ) -> KinematicsVerificationDraft:
        session = await self._authorize(token)
        context = self.device.context
        profile = context.profile
        if profile is None:
            raise KinematicsVerificationPrerequisiteError("Current Profile is required")
        if self.joint_state_snapshot_provider is None:
            raise KinematicsVerificationPrerequisiteError(
                "A field-verified server-owned joint-state snapshot provider is required"
            )
        async with self._guard:
            self._require_current_draft(draft_id, session)
        snapshot = await self.joint_state_snapshot_provider.capture()
        self._validate_snapshot(snapshot, session)
        joint_state = snapshot.joint_state.validate_against(profile)
        current_session = await self._authorize(token)
        if current_session.session_id != session.session_id:
            raise KinematicsVerificationDraftError(
                "The operator session changed while capturing the joint state"
            )
        predicted = await self.kinematics.forward(
            profile,
            joint_state,
            state_sequence=snapshot.state_sequence,
            robot_id=context.robot_id or "primary",
        )
        point = KinematicsVerificationPoint(
            label=label,
            joint_state=joint_state,
            joint_state_sequence=snapshot.state_sequence,
            joint_state_captured_at=snapshot.captured_at,
            snapshot_session_id=snapshot.operator_session_id,
            predicted_tcp=predicted.tcp_pose,
            measured_tcp=measured_tcp,
            position_error_mm=_position_error_mm(predicted.tcp_pose, measured_tcp),
            orientation_error_deg=_orientation_error_deg(predicted.tcp_pose, measured_tcp),
            measured_at=self.clock.now(),
        )
        async with self._guard:
            current = self._require_current_draft(draft_id, session)
            updated = current.model_copy(update={"points": (*current.points, point)})
            self._drafts[draft_id] = updated
            return updated

    async def commit(
        self,
        token: str,
        draft_id: UUID,
    ) -> KinematicsVerificationEvidence:
        session = await self._authorize(token)
        context = self.device.context
        profile = context.profile
        calibration = context.calibration
        model = context.kinematics
        device = context.device
        if profile is None or calibration is None or model is None or device is None:
            raise KinematicsVerificationPrerequisiteError(
                "Kinematics verification context is incomplete"
            )
        async with self._guard:
            draft = self._require_current_draft(draft_id, session)
        try:
            evidence = KinematicsVerificationEvidence(
                robot_unit_id=context.robot_unit_id,
                variant=profile.variant,
                profile_fingerprint=profile.fingerprint,
                calibration_fingerprint=calibration_fingerprint(calibration),
                device_fingerprint=explicit_device_fingerprint(device),
                kinematics_fingerprint=model.fingerprint,
                kinematics_model_schema_version=model.schema_version,
                verification_checklist_version=(context.kinematics_verification_checklist_version),
                test_points=draft.points,
                thresholds=draft.thresholds,
                accepted_at=self.clock.now(),
                accepted_by=session.operator_id,
                software_commit=context.software_commit,
            )
        except ValueError as error:
            raise KinematicsVerificationThresholdError(
                "At least three measured points must pass both configured residual thresholds"
            ) from error
        await self.repository.save(evidence)
        current_session = await self._authorize(token)
        if current_session.session_id != session.session_id:
            raise KinematicsVerificationDraftError(
                "The operator session changed while persisting Kinematics evidence"
            )
        await self.device.apply_kinematics_verification_evidence(
            evidence,
            token=token,
            expected_session_id=session.session_id,
        )
        async with self._guard:
            self._drafts.pop(draft_id, None)
        return evidence

    async def _authorize(self, token: str) -> OperatorSessionEvidence:
        return await self.device.authorize_operator_purpose(
            token,
            purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
        )

    def _validate_snapshot(
        self,
        snapshot: KinematicsJointStateSnapshot,
        session: OperatorSessionEvidence,
    ) -> None:
        if not isinstance(snapshot, KinematicsJointStateSnapshot):
            raise KinematicsVerificationPrerequisiteError(
                "The joint-state snapshot provider returned an invalid value"
            )
        context = self.device.context
        profile = context.profile
        calibration = context.calibration
        device = context.device
        if profile is None or calibration is None or device is None:
            raise KinematicsVerificationPrerequisiteError(
                "The current unit identity is incomplete for joint-state capture"
            )
        stale_fields: list[str] = []
        if snapshot.robot_unit_id != context.robot_unit_id:
            stale_fields.append("robot_unit_id")
        if snapshot.profile_fingerprint != profile.fingerprint:
            stale_fields.append("profile_fingerprint")
        if snapshot.calibration_fingerprint != calibration_fingerprint(calibration):
            stale_fields.append("calibration_fingerprint")
        if snapshot.device_fingerprint != explicit_device_fingerprint(device):
            stale_fields.append("device_fingerprint")
        if snapshot.operator_session_id != session.session_id:
            stale_fields.append("operator_session_id")
        age_s = (self.clock.now() - snapshot.captured_at).total_seconds()
        if age_s < 0.0 or age_s > self.max_snapshot_age_s:
            stale_fields.append("captured_at")
        if stale_fields:
            raise KinematicsVerificationPrerequisiteError(
                "The server-owned joint-state snapshot is stale or belongs to another unit/session",
                details={"stale_fields": tuple(stale_fields)},
            )

    def _require_current_draft(
        self,
        draft_id: UUID,
        session: OperatorSessionEvidence,
    ) -> KinematicsVerificationDraft:
        draft = self._drafts.get(draft_id)
        if draft is None:
            raise KinematicsVerificationDraftError("Kinematics verification draft was not found")
        context = self.device.context
        calibration = context.calibration
        model = context.kinematics
        if (
            draft.operator_session_id != session.session_id
            or draft.robot_unit_id != context.robot_unit_id
            or context.profile is None
            or draft.profile_fingerprint != context.profile.fingerprint
            or calibration is None
            or draft.calibration_fingerprint != calibration_fingerprint(calibration)
            or context.device is None
            or draft.device_fingerprint != explicit_device_fingerprint(context.device)
            or model is None
            or draft.kinematics_fingerprint != model.fingerprint
            or draft.software_commit != context.software_commit
            or draft.verification_checklist_version
            != context.kinematics_verification_checklist_version
        ):
            raise KinematicsVerificationDraftError(
                "Kinematics verification draft is stale for the current unit"
            )
        return draft


def _position_error_mm(predicted: TcpPose, measured: TcpPose) -> float:
    if predicted.frame != measured.frame:
        raise KinematicsVerificationDraftError("Measured TCP frame must match predicted frame")
    left = predicted.position_mm
    right = measured.position_mm
    return hypot(left.x - right.x, left.y - right.y, left.z - right.z)


def _orientation_error_deg(predicted: TcpPose, measured: TcpPose) -> float:
    left = predicted.orientation_quaternion_xyzw
    right = measured.orientation_quaternion_xyzw
    dot = abs(left.x * right.x + left.y * right.y + left.z * right.z + left.w * right.w)
    return degrees(2.0 * acos(min(1.0, max(-1.0, dot))))


__all__ = [
    "KinematicsVerificationDraft",
    "KinematicsVerificationDraftError",
    "KinematicsVerificationPrerequisiteError",
    "KinematicsVerificationService",
    "KinematicsVerificationStatus",
    "KinematicsVerificationThresholdError",
]
