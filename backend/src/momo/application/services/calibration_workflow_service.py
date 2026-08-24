"""Explicit, read-only calibration workflow orchestration."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from typing import Literal, Protocol, cast
from uuid import UUID, uuid4

from momo.domain.calibration import CalibrationDocument, CalibrationJoint
from momo.domain.calibration_workflow import (
    CalibrationAuthorization,
    CalibrationDraft,
    CalibrationJointDraft,
    CalibrationJointPreview,
    CalibrationRevisionRecord,
    CalibrationSavePreview,
    CalibrationWorkflowError,
    CalibrationWorkflowSource,
    CalibrationWorkflowState,
    CalibrationWorkflowStatus,
    calibration_document_fingerprint,
)
from momo.domain.enums import CalibrationOperatingMode, ProfileVerificationStatus, RobotVariant
from momo.domain.errors import HardwareMappingError
from momo.domain.hardware_mapping import (
    effective_raw_bounds,
    goal_raw_to_logical,
    logical_to_relative_raw,
    mapping_round_trip_tolerance,
)
from momo.domain.real_hardware import RealHardwareAuthorizationPurpose
from momo.domain.robot import JointDefinition, RobotProfile
from momo.ports.clock import Clock
from momo.ports.servo_bus import ReadOnlyServoBus, ReadOnlyServoBusFacade

CALIBRATION_JOINT_CONFIRMATION = "CONFIRM CALIBRATION JOINT"
LEGACY_IMPORT_CONFIRMATION = "IMPORT LEGACY CALIBRATION"
ROLLBACK_CONFIRMATION = "ROLL BACK CALIBRATION"
SAVE_CALIBRATION_CONFIRMATION = "SAVE CALIBRATION"
_MAX_SESSIONS = 32


class CalibrationWorkflowRepository(Protocol):
    def get_revision(self, variant: RobotVariant) -> CalibrationRevisionRecord | None: ...

    def save_new(
        self,
        calibration: CalibrationDocument,
        *,
        expected_revision: int | None,
        source: CalibrationWorkflowSource,
        created_at: datetime,
    ) -> CalibrationRevisionRecord: ...

    def rollback(
        self,
        variant: RobotVariant,
        *,
        target_revision: int,
        expected_revision: int,
        created_at: datetime,
    ) -> CalibrationRevisionRecord: ...


@dataclass(slots=True)
class _CalibrationSession:
    session_id: UUID
    authorization: CalibrationAuthorization
    profile: RobotProfile
    base_record: CalibrationRevisionRecord | None
    source: CalibrationWorkflowSource
    draft: CalibrationDraft
    state: CalibrationWorkflowState
    updated_at: datetime
    generation: int = 0
    selected_joint_id: str | None = None
    observed_raw: int | None = None
    preview: CalibrationJointPreview | None = None
    save_preview: CalibrationSavePreview | None = None
    confirmed: dict[str, CalibrationJoint] = field(default_factory=dict)
    saved_record: CalibrationRevisionRecord | None = None


class CalibrationWorkflowService:
    """Read exactly one selected Servo ID and build a forward-only revision.

    The only ServoBus method called by this service is
    ``read_present_positions((selected_servo_id,))``. It cannot write, change an
    operating mode, toggle torque, scan, home, or otherwise move hardware.
    """

    def __init__(
        self,
        repository: CalibrationWorkflowRepository,
        servo_bus: ReadOnlyServoBus,
        clock: Clock,
    ) -> None:
        self.repository = repository
        self.servo_bus: ReadOnlyServoBus = ReadOnlyServoBusFacade(servo_bus)
        self.clock = clock
        self._guard = asyncio.Lock()
        self._bus_guard = asyncio.Lock()
        self._sessions: dict[UUID, _CalibrationSession] = {}
        self._active_session_id: UUID | None = None

    async def start(
        self,
        authorization: CalibrationAuthorization,
        profile: RobotProfile,
        *,
        source: CalibrationWorkflowSource = CalibrationWorkflowSource.EXISTING_REAL,
        explicit_legacy_calibration: CalibrationDocument | None = None,
        legacy_confirmation: str | None = None,
    ) -> CalibrationWorkflowStatus:
        now = self.clock.now()
        self._validate_authorization(authorization, profile, now)
        base = self.repository.get_revision(profile.variant)
        if base is not None:
            self._validate_calibration(base.calibration, profile)
        if (base is None and authorization.calibration_fingerprint is not None) or (
            base is not None
            and base.calibration_fingerprint != authorization.calibration_fingerprint
        ):
            raise CalibrationWorkflowError(
                "CALIBRATION_AUTHORIZATION_MISMATCH",
                "Authorization is bound to a different calibration fingerprint",
            )

        seed = base.calibration if base is not None else None
        if source is CalibrationWorkflowSource.EXPLICIT_LEGACY_IMPORT:
            if not secrets.compare_digest(
                legacy_confirmation or "",
                LEGACY_IMPORT_CONFIRMATION,
            ):
                raise CalibrationWorkflowError(
                    "LEGACY_IMPORT_CONFIRMATION_REQUIRED",
                    "Legacy calibration import requires the exact explicit confirmation",
                )
            if explicit_legacy_calibration is None:
                raise CalibrationWorkflowError(
                    "LEGACY_CALIBRATION_REQUIRED",
                    "Explicit Legacy import requires an explicit calibration document",
                )
            self._validate_calibration(explicit_legacy_calibration, profile)
            seed = explicit_legacy_calibration
        elif explicit_legacy_calibration is not None or legacy_confirmation is not None:
            raise CalibrationWorkflowError(
                "UNEXPECTED_LEGACY_INPUT",
                "Legacy inputs are accepted only in EXPLICIT_LEGACY_IMPORT mode",
            )

        async with self._guard:
            active = self._active_locked()
            if active is not None:
                raise CalibrationWorkflowError(
                    "CALIBRATION_WORKFLOW_CONFLICT",
                    "Another calibration workflow is active",
                    details={"active_session_id": str(active.session_id)},
                )
            session = _CalibrationSession(
                session_id=uuid4(),
                authorization=authorization,
                profile=profile,
                base_record=base,
                source=source,
                draft=self._build_draft(profile, now, base=base, seed=seed),
                state=CalibrationWorkflowState.ACTIVE,
                updated_at=now,
            )
            self._sessions[session.session_id] = session
            self._active_session_id = session.session_id
            self._prune_locked()
            return self._status_locked(session)

    async def read_selected_joint(
        self,
        session_id: UUID,
        authorization: CalibrationAuthorization,
        joint_id: str,
    ) -> CalibrationWorkflowStatus:
        """Read one explicit Servo ID; a concurrent cancel/selection wins the race."""

        async with self._guard:
            session = self._require_session_locked(session_id, authorization)
            definition = self._definition(session.profile, joint_id)
            servo_id = self._servo_id(definition)
            if servo_id not in authorization.allowed_servo_ids:
                raise CalibrationWorkflowError(
                    "SERVO_ID_NOT_AUTHORIZED",
                    "Selected joint Servo ID is not explicitly authorized",
                )
            session.generation += 1
            generation = session.generation
            session.selected_joint_id = joint_id
            session.observed_raw = None
            session.preview = None
            session.save_preview = None
            session.confirmed.pop(joint_id, None)
            session.state = CalibrationWorkflowState.ACTIVE
            session.updated_at = self.clock.now()

        try:
            async with self._bus_guard:
                positions = await self.servo_bus.read_present_positions((servo_id,))
        except Exception as error:
            raise CalibrationWorkflowError(
                "CALIBRATION_POSITION_READ_FAILED",
                "The selected joint position could not be read",
                details={"error_type": type(error).__name__},
            ) from error

        if set(positions) != {servo_id}:
            raise CalibrationWorkflowError(
                "CALIBRATION_POSITION_RESPONSE_INVALID",
                "Position response must contain exactly the selected Servo ID",
            )
        observed = positions[servo_id]
        if isinstance(observed, bool) or not isinstance(observed, int):
            raise CalibrationWorkflowError(
                "CALIBRATION_POSITION_RESPONSE_INVALID",
                "Present position must be an integer raw value",
            )

        async with self._guard:
            session = self._require_session_locked(session_id, authorization)
            if session.generation != generation or session.selected_joint_id != joint_id:
                raise CalibrationWorkflowError(
                    "CALIBRATION_SELECTION_CHANGED",
                    "A newer calibration selection superseded this read",
                )
            session.observed_raw = observed
            session.draft = self._replace_draft_joint(
                session.draft,
                joint_id,
                present_raw=observed,
            )
            session.updated_at = self.clock.now()
            return self._status_locked(session)

    async def preview_joint(
        self,
        session_id: UUID,
        authorization: CalibrationAuthorization,
        joint_id: str,
        *,
        logical_value: float,
        direction: int | None = None,
        phase: int | None = None,
        raw_bounds: tuple[int, int] | None = None,
    ) -> CalibrationJointPreview:
        async with self._guard:
            session = self._require_session_locked(session_id, authorization)
            if session.selected_joint_id != joint_id or session.observed_raw is None:
                raise CalibrationWorkflowError(
                    "CALIBRATION_OBSERVATION_REQUIRED",
                    "Read this selected joint before creating a preview",
                )
            if isinstance(logical_value, bool) or not isinstance(logical_value, (int, float)):
                raise CalibrationWorkflowError(
                    "CALIBRATION_LOGICAL_VALUE_INVALID",
                    "Logical value must be a finite number",
                )
            resolved_logical = float(logical_value)
            if not isfinite(resolved_logical):
                raise CalibrationWorkflowError(
                    "CALIBRATION_LOGICAL_VALUE_INVALID",
                    "Logical value must be a finite number",
                )
            definition = self._definition(session.profile, joint_id)
            if not definition.minimum <= resolved_logical <= definition.maximum:
                raise CalibrationWorkflowError(
                    "CALIBRATION_LOGICAL_VALUE_OUT_OF_RANGE",
                    "Logical value is outside the reviewed profile limits",
                )
            draft_joint = session.draft.joints_by_id[joint_id]
            resolved_direction = draft_joint.direction if direction is None else direction
            if resolved_direction not in {-1, 1}:
                raise CalibrationWorkflowError(
                    "CALIBRATION_DIRECTION_INVALID",
                    "Direction must be -1 or 1",
                )
            resolved_phase = draft_joint.phase if phase is None else phase
            if (
                definition.operating_mode is CalibrationOperatingMode.MULTI_TURN
                and resolved_phase is None
            ):
                raise CalibrationWorkflowError(
                    "CALIBRATION_PHASE_REQUIRED",
                    "Multi-turn calibration requires an explicit phase",
                )
            resolved_bounds = raw_bounds or draft_joint.raw_bounds
            self._validate_selected_bounds(definition, resolved_bounds)
            assert resolved_bounds is not None
            observed = session.observed_raw
            assert observed is not None

            try:
                temporary = CalibrationJoint(
                    joint_id=joint_id,
                    servo_id=self._servo_id(definition),
                    operating_mode=definition.operating_mode,
                    direction=resolved_direction,
                    home_present_raw=observed,
                    phase=resolved_phase,
                    raw_bounds=resolved_bounds,
                )
                relative = logical_to_relative_raw(
                    resolved_logical,
                    definition,
                    temporary,
                )
                calibration = temporary.model_copy(update={"home_present_raw": observed - relative})
                # Revalidate after model_copy because Pydantic does not do so by default.
                calibration = CalibrationJoint.model_validate(calibration.model_dump())
                effective_raw_bounds(definition, calibration)
                round_trip = goal_raw_to_logical(
                    joint_id,
                    observed,
                    session.profile,
                    calibration,
                )
                mapping_error = abs(round_trip - resolved_logical)
                if mapping_error > mapping_round_trip_tolerance(definition):
                    raise HardwareMappingError("preview round trip exceeded one-half raw count")
            except (HardwareMappingError, ValueError) as error:
                raise CalibrationWorkflowError(
                    "CALIBRATION_PREVIEW_INVALID",
                    "Calibration mapping preview is invalid",
                    details={"error_type": type(error).__name__},
                ) from error

            assert calibration.home_present_raw is not None
            preview = CalibrationJointPreview.create(
                session_id=session.session_id,
                joint_id=joint_id,
                servo_id=calibration.servo_id,
                observed_raw=observed,
                logical_value=resolved_logical,
                unit=definition.domain_unit,
                operating_mode=definition.operating_mode,
                direction=resolved_direction,
                home_present_raw=calibration.home_present_raw,
                phase=resolved_phase,
                raw_bounds=resolved_bounds,
                round_trip_logical_value=round_trip,
                mapping_error=mapping_error,
            )
            session.generation += 1
            session.preview = preview
            session.draft = self._replace_draft_joint(
                session.draft,
                joint_id,
                present_raw=observed,
                logical_value=resolved_logical,
                direction=resolved_direction,
                phase=resolved_phase,
                raw_bounds=resolved_bounds,
                operating_mode=definition.operating_mode,
            )
            session.save_preview = None
            session.confirmed.pop(joint_id, None)
            session.state = CalibrationWorkflowState.ACTIVE
            session.updated_at = self.clock.now()
            return preview

    async def confirm_joint(
        self,
        session_id: UUID,
        authorization: CalibrationAuthorization,
        joint_id: str,
        *,
        preview_fingerprint: str,
        confirmation: str,
    ) -> CalibrationWorkflowStatus:
        if not secrets.compare_digest(confirmation, CALIBRATION_JOINT_CONFIRMATION):
            raise CalibrationWorkflowError(
                "CALIBRATION_JOINT_CONFIRMATION_REQUIRED",
                "Joint calibration requires the exact explicit confirmation",
            )
        async with self._guard:
            session = self._require_session_locked(session_id, authorization)
            preview = session.preview
            if (
                preview is None
                or preview.joint_id != joint_id
                or not secrets.compare_digest(
                    preview.preview_fingerprint,
                    preview_fingerprint,
                )
            ):
                raise CalibrationWorkflowError(
                    "CALIBRATION_PREVIEW_CHANGED",
                    "The confirmed preview is not the current selected-joint preview",
                )
            session.confirmed[joint_id] = CalibrationJoint(
                joint_id=joint_id,
                servo_id=preview.servo_id,
                operating_mode=preview.operating_mode,
                direction=preview.direction,
                home_present_raw=preview.home_present_raw,
                phase=preview.phase,
                raw_bounds=preview.raw_bounds,
            )
            required = set(session.profile.enabled_joints)
            if set(session.confirmed) == required:
                session.state = CalibrationWorkflowState.READY_TO_SAVE
                session.save_preview = self._build_save_preview_locked(session)
            else:
                session.state = CalibrationWorkflowState.ACTIVE
                session.save_preview = None
            session.generation += 1
            session.updated_at = self.clock.now()
            return self._status_locked(session)

    async def complete(
        self,
        session_id: UUID,
        authorization: CalibrationAuthorization,
        *,
        proposed_calibration_fingerprint: str,
        confirmation: str,
        before_persist: Callable[[], None] | None = None,
    ) -> CalibrationRevisionRecord:
        if not secrets.compare_digest(confirmation, SAVE_CALIBRATION_CONFIRMATION):
            raise CalibrationWorkflowError(
                "CALIBRATION_SAVE_CONFIRMATION_REQUIRED",
                "Saving calibration requires the exact explicit confirmation",
            )
        async with self._guard:
            session = self._require_session_locked(session_id, authorization)
            save_preview = session.save_preview
            if session.state is not CalibrationWorkflowState.READY_TO_SAVE or save_preview is None:
                raise CalibrationWorkflowError(
                    "CALIBRATION_CONFIRMATIONS_INCOMPLETE",
                    "Every enabled joint must be previewed and explicitly confirmed",
                )
            if not secrets.compare_digest(
                save_preview.proposed_calibration_fingerprint,
                proposed_calibration_fingerprint,
            ):
                raise CalibrationWorkflowError(
                    "CALIBRATION_SAVE_PREVIEW_CHANGED",
                    "Save confirmation does not match the complete proposed calibration",
                )
            current = self.repository.get_revision(session.profile.variant)
            base = session.base_record
            if (base is None and current is not None) or (
                base is not None
                and (
                    current is None
                    or current.revision != base.revision
                    or current.calibration_fingerprint != base.calibration_fingerprint
                )
            ):
                raise CalibrationWorkflowError(
                    "CALIBRATION_REVISION_CONFLICT",
                    "Calibration changed before workflow completion",
                )
            created_at = self.clock.now()
            calibration = save_preview.proposed_calibration
            if before_persist is not None:
                before_persist()
            record = self.repository.save_new(
                calibration,
                expected_revision=base.revision if base is not None else None,
                source=session.source,
                created_at=created_at,
            )
            session.state = CalibrationWorkflowState.SAVED
            session.saved_record = record
            session.generation += 1
            session.updated_at = created_at
            self._active_session_id = None
            return record

    async def status(
        self,
        session_id: UUID,
        authorization: CalibrationAuthorization,
    ) -> CalibrationWorkflowStatus:
        async with self._guard:
            session = self._sessions.get(session_id)
            if session is None:
                raise CalibrationWorkflowError(
                    "CALIBRATION_SESSION_NOT_FOUND",
                    "Calibration workflow session was not found",
                )
            self._require_matching_authorization(session, authorization)
            active = session.state in {
                CalibrationWorkflowState.ACTIVE,
                CalibrationWorkflowState.READY_TO_SAVE,
            }
            if active:
                if not authorization.active(self.clock.now()):
                    self._expire_locked(session)
                else:
                    self._require_base_unchanged(session)
            return self._status_locked(session)

    async def cancel(
        self,
        session_id: UUID,
        authorization: CalibrationAuthorization,
    ) -> CalibrationWorkflowStatus:
        """Cancel local workflow state; calibration cancellation performs no bus action."""

        async with self._guard:
            session = self._sessions.get(session_id)
            if session is None:
                raise CalibrationWorkflowError(
                    "CALIBRATION_SESSION_NOT_FOUND",
                    "Calibration workflow session was not found",
                )
            self._require_matching_authorization(session, authorization)
            if session.state in {
                CalibrationWorkflowState.ACTIVE,
                CalibrationWorkflowState.READY_TO_SAVE,
            }:
                session.state = CalibrationWorkflowState.CANCELLED
                session.save_preview = None
                session.generation += 1
                session.updated_at = self.clock.now()
                if self._active_session_id == session.session_id:
                    self._active_session_id = None
            return self._status_locked(session)

    async def rollback(
        self,
        authorization: CalibrationAuthorization,
        profile: RobotProfile,
        *,
        target_revision: int,
        confirmation: str,
        before_persist: Callable[[], None] | None = None,
    ) -> CalibrationRevisionRecord:
        now = self.clock.now()
        self._validate_authorization(authorization, profile, now)
        if not secrets.compare_digest(confirmation, ROLLBACK_CONFIRMATION):
            raise CalibrationWorkflowError(
                "CALIBRATION_ROLLBACK_CONFIRMATION_REQUIRED",
                "Calibration rollback requires the exact explicit confirmation",
            )
        async with self._guard:
            if self._active_locked() is not None:
                raise CalibrationWorkflowError(
                    "CALIBRATION_WORKFLOW_CONFLICT",
                    "Cannot roll back while a calibration workflow is active",
                )
            current = self.repository.get_revision(profile.variant)
            if current is None:
                raise CalibrationWorkflowError(
                    "CALIBRATION_NOT_CONFIGURED",
                    "Cannot roll back an unconfigured calibration",
                )
            if current.calibration_fingerprint != authorization.calibration_fingerprint:
                raise CalibrationWorkflowError(
                    "CALIBRATION_AUTHORIZATION_MISMATCH",
                    "Authorization is bound to a different calibration fingerprint",
                )
            if before_persist is not None:
                before_persist()
            return self.repository.rollback(
                profile.variant,
                target_revision=target_revision,
                expected_revision=current.revision,
                created_at=now,
            )

    async def shutdown(self) -> None:
        """Invalidate in-memory workflow state without touching the ServoBus."""

        async with self._guard:
            session = self._active_locked()
            if session is not None:
                session.state = CalibrationWorkflowState.CANCELLED
                session.save_preview = None
                session.generation += 1
                session.updated_at = self.clock.now()
            self._active_session_id = None

    def _require_session_locked(
        self,
        session_id: UUID,
        authorization: CalibrationAuthorization,
    ) -> _CalibrationSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise CalibrationWorkflowError(
                "CALIBRATION_SESSION_NOT_FOUND",
                "Calibration workflow session was not found",
            )
        self._require_matching_authorization(session, authorization)
        if session.state not in {
            CalibrationWorkflowState.ACTIVE,
            CalibrationWorkflowState.READY_TO_SAVE,
        }:
            raise CalibrationWorkflowError(
                "CALIBRATION_SESSION_NOT_ACTIVE",
                "Calibration workflow session is no longer active",
            )
        if not authorization.active(self.clock.now()):
            self._expire_locked(session)
            raise CalibrationWorkflowError(
                "CALIBRATION_AUTHORIZATION_EXPIRED",
                "Calibration authorization expired",
            )
        self._require_base_unchanged(session)
        return session

    def _require_base_unchanged(self, session: _CalibrationSession) -> None:
        """Fail every active step when the repository identity drifts.

        The coordinator separately re-authorizes the current hardware context on
        each call. This repository check closes the other race: an external
        calibration replacement cannot leave a still-active draft operating on a
        stale base and will also be rejected atomically at persistence time.
        """

        current = self.repository.get_revision(session.profile.variant)
        base = session.base_record
        unchanged = (base is None and current is None) or (
            base is not None
            and current is not None
            and current.revision == base.revision
            and current.calibration_fingerprint == base.calibration_fingerprint
        )
        if not unchanged:
            raise CalibrationWorkflowError(
                "CALIBRATION_REVISION_CONFLICT",
                "Calibration changed while the workflow was active",
            )

    @staticmethod
    def _require_matching_authorization(
        session: _CalibrationSession,
        authorization: CalibrationAuthorization,
    ) -> None:
        if authorization != session.authorization:
            raise CalibrationWorkflowError(
                "CALIBRATION_AUTHORIZATION_MISMATCH",
                "Authorization does not own this calibration workflow",
            )

    def _expire_locked(self, session: _CalibrationSession) -> None:
        session.state = CalibrationWorkflowState.EXPIRED
        session.save_preview = None
        session.generation += 1
        session.updated_at = self.clock.now()
        if self._active_session_id == session.session_id:
            self._active_session_id = None

    def _active_locked(self) -> _CalibrationSession | None:
        if self._active_session_id is None:
            return None
        session = self._sessions.get(self._active_session_id)
        if session is None:
            self._active_session_id = None
            return None
        if not session.authorization.active(self.clock.now()):
            self._expire_locked(session)
            return None
        if session.state not in {
            CalibrationWorkflowState.ACTIVE,
            CalibrationWorkflowState.READY_TO_SAVE,
        }:
            self._active_session_id = None
            return None
        return session

    @staticmethod
    def _validate_authorization(
        authorization: CalibrationAuthorization,
        profile: RobotProfile,
        now: datetime,
    ) -> None:
        if not authorization.active(now):
            raise CalibrationWorkflowError(
                "CALIBRATION_AUTHORIZATION_EXPIRED",
                "Calibration authorization is not active",
            )
        if profile.template:
            raise CalibrationWorkflowError(
                "TEMPLATE_PROFILE_FORBIDDEN",
                "Template/example profiles cannot authorize Real calibration",
            )
        if profile.verification_status is not ProfileVerificationStatus.VERIFIED_FOR_REAL:
            raise CalibrationWorkflowError(
                "PROFILE_NOT_VERIFIED_FOR_REAL",
                "Profile is not verified for Real hardware",
            )
        expected_ids = tuple(
            CalibrationWorkflowService._servo_id(definition)
            for definition in profile.joint_definitions
            if definition.joint_id in profile.enabled_joints
        )
        if (
            authorization.variant is not profile.variant
            or authorization.profile_fingerprint != profile.fingerprint
            or authorization.allowed_servo_ids != expected_ids
            or authorization.physical_estop_confirmed is not True
            or authorization.purpose is not RealHardwareAuthorizationPurpose.CALIBRATION_CAPTURE
            or not authorization.capabilities.calibration_capture_ready
        ):
            raise CalibrationWorkflowError(
                "CALIBRATION_AUTHORIZATION_MISMATCH",
                "Authorization does not match the explicit profile and Servo IDs",
            )

    @staticmethod
    def _validate_calibration(
        calibration: CalibrationDocument,
        profile: RobotProfile,
    ) -> None:
        if calibration.template:
            raise CalibrationWorkflowError(
                "TEMPLATE_CALIBRATION_FORBIDDEN",
                "Template/example calibration can never become a Real calibration",
            )
        if (
            calibration.robot_variant is not profile.variant
            or calibration.profile_fingerprint != profile.fingerprint
            or tuple(joint.joint_id for joint in calibration.joints)
            != tuple(profile.enabled_joints)
            or not all(joint.complete for joint in calibration.joints)
        ):
            raise CalibrationWorkflowError(
                "CALIBRATION_PROFILE_MISMATCH",
                "Calibration does not exactly match the reviewed profile",
            )
        for joint in calibration.joints:
            definition = profile.definitions_by_id[joint.joint_id]
            if (
                joint.servo_id != definition.servo_id
                or joint.operating_mode is not definition.operating_mode
            ):
                raise CalibrationWorkflowError(
                    "CALIBRATION_MAPPING_MISMATCH",
                    "Calibration mapping does not match the explicit profile",
                )
            try:
                effective_raw_bounds(definition, joint)
            except HardwareMappingError as error:
                raise CalibrationWorkflowError(
                    "CALIBRATION_MAPPING_MISMATCH",
                    "Calibration raw bounds do not match the reviewed profile",
                ) from error

    @staticmethod
    def _validate_selected_bounds(
        definition: JointDefinition,
        bounds: tuple[int, int] | None,
    ) -> None:
        profile_bounds = definition.raw_bounds
        if bounds is None or profile_bounds is None:
            raise CalibrationWorkflowError(
                "CALIBRATION_RAW_BOUNDS_REQUIRED",
                "Calibration requires explicit reviewed raw bounds",
            )
        if (
            len(bounds) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in bounds)
            or bounds[0] >= bounds[1]
            or bounds[0] < profile_bounds[0]
            or bounds[1] > profile_bounds[1]
        ):
            raise CalibrationWorkflowError(
                "CALIBRATION_RAW_BOUNDS_INVALID",
                "Calibration raw bounds must be ordered inside profile bounds",
            )

    @staticmethod
    def _definition(profile: RobotProfile, joint_id: str) -> JointDefinition:
        if joint_id not in profile.enabled_joints:
            raise CalibrationWorkflowError(
                "CALIBRATION_JOINT_NOT_ENABLED",
                "Selected joint is not in the profile's explicit enabled_joints",
            )
        definition = profile.definitions_by_id.get(joint_id)
        if definition is None:
            raise CalibrationWorkflowError(
                "CALIBRATION_JOINT_NOT_ENABLED",
                "Selected joint has no reviewed profile definition",
            )
        return definition

    @staticmethod
    def _servo_id(definition: JointDefinition) -> int:
        servo_id = definition.servo_id
        if servo_id is None or not 1 <= servo_id <= 253:
            raise CalibrationWorkflowError(
                "CALIBRATION_SERVO_ID_INVALID",
                "Enabled joint has no valid explicit Servo ID",
            )
        return servo_id

    @staticmethod
    def _status_locked(session: _CalibrationSession) -> CalibrationWorkflowStatus:
        saved = session.saved_record
        base = session.base_record
        return CalibrationWorkflowStatus(
            session_id=session.session_id,
            authorization_session_id=session.authorization.session_id,
            robot_id=session.authorization.robot_id,
            variant=session.profile.variant,
            profile_fingerprint=session.profile.fingerprint,
            base_revision=base.revision if base is not None else None,
            base_calibration_fingerprint=(
                base.calibration_fingerprint if base is not None else None
            ),
            draft=session.draft,
            source=session.source,
            state=session.state,
            required_joint_ids=tuple(session.profile.enabled_joints),
            confirmed_joint_ids=tuple(
                joint_id
                for joint_id in session.profile.enabled_joints
                if joint_id in session.confirmed
            ),
            selected_joint_id=session.selected_joint_id,
            observed_raw=session.observed_raw,
            preview=session.preview,
            save_preview=session.save_preview,
            saved_revision=saved.revision if saved is not None else None,
            saved_calibration_fingerprint=(
                saved.calibration_fingerprint if saved is not None else None
            ),
            updated_at=session.updated_at,
        )

    def _prune_locked(self) -> None:
        if len(self._sessions) <= _MAX_SESSIONS:
            return
        for session_id in tuple(self._sessions):
            if len(self._sessions) <= _MAX_SESSIONS:
                break
            if session_id != self._active_session_id:
                self._sessions.pop(session_id, None)

    def _build_save_preview_locked(
        self,
        session: _CalibrationSession,
    ) -> CalibrationSavePreview:
        proposed = CalibrationDocument(
            id=uuid4(),
            robot_variant=session.profile.variant,
            profile_fingerprint=session.profile.fingerprint,
            template=False,
            generated_at=self.clock.now(),
            notes=(
                "Created by protected read-only calibration workflow; "
                f"source={session.source.value}"
            ),
            joints=[session.confirmed[joint_id] for joint_id in session.profile.enabled_joints],
        )
        base = session.base_record
        return CalibrationSavePreview(
            session_id=session.session_id,
            base_revision=base.revision if base is not None else None,
            base_calibration_fingerprint=(
                base.calibration_fingerprint if base is not None else None
            ),
            source=session.source,
            proposed_calibration=proposed,
            proposed_calibration_fingerprint=calibration_document_fingerprint(proposed),
        )

    @staticmethod
    def _build_draft(
        profile: RobotProfile,
        created_at: datetime,
        *,
        base: CalibrationRevisionRecord | None,
        seed: CalibrationDocument | None,
    ) -> CalibrationDraft:
        seed_by_id = seed.joints_by_id if seed is not None else {}
        joints: list[CalibrationJointDraft] = []
        for joint_id in profile.enabled_joints:
            definition = profile.definitions_by_id[joint_id]
            servo_id = CalibrationWorkflowService._servo_id(definition)
            seed_joint = seed_by_id.get(joint_id)
            joints.append(
                CalibrationJointDraft(
                    joint_id=joint_id,
                    servo_id=servo_id,
                    present_raw=None,
                    logical_value=None,
                    direction=(
                        cast(Literal[-1, 1], seed_joint.direction)
                        if seed_joint is not None
                        else None
                    ),
                    phase=seed_joint.phase if seed_joint is not None else None,
                    raw_bounds=seed_joint.raw_bounds if seed_joint is not None else None,
                    operating_mode=(seed_joint.operating_mode if seed_joint is not None else None),
                )
            )
        return CalibrationDraft(
            robot_variant=profile.variant,
            profile_fingerprint=profile.fingerprint,
            enabled_joints=tuple(profile.enabled_joints),
            created_at=created_at,
            base_revision=base.revision if base is not None else None,
            base_calibration_fingerprint=(
                base.calibration_fingerprint if base is not None else None
            ),
            joints=tuple(joints),
        )

    @staticmethod
    def _replace_draft_joint(
        draft: CalibrationDraft,
        joint_id: str,
        **updates: object,
    ) -> CalibrationDraft:
        joints = tuple(
            joint.model_copy(update=updates) if joint.joint_id == joint_id else joint
            for joint in draft.joints
        )
        return CalibrationDraft.model_validate(
            draft.model_copy(update={"joints": joints}).model_dump()
        )


__all__ = [
    "CALIBRATION_JOINT_CONFIRMATION",
    "LEGACY_IMPORT_CONFIRMATION",
    "ROLLBACK_CONFIRMATION",
    "SAVE_CALIBRATION_CONFIRMATION",
    "CalibrationWorkflowRepository",
    "CalibrationWorkflowService",
]
