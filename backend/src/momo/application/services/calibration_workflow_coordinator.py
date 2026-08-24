"""Bind protected calibration workflows to one current explicit device session."""

from __future__ import annotations

import asyncio
from uuid import UUID

from momo.application.services.calibration_workflow_service import (
    CalibrationWorkflowRepository,
    CalibrationWorkflowService,
)
from momo.application.services.device_diagnostics_service import DeviceDiagnosticsService
from momo.domain.calibration import CalibrationDocument
from momo.domain.calibration_workflow import (
    CalibrationAuthorization,
    CalibrationJointPreview,
    CalibrationRevisionRecord,
    CalibrationWorkflowError,
    CalibrationWorkflowSource,
    CalibrationWorkflowStatus,
    calibration_document_fingerprint,
)
from momo.domain.enums import HardwareAccessPolicy
from momo.domain.real_hardware import (
    OperatorSessionEvidence,
    RealHardwareAuthorizationPurpose,
    RealHardwareGateInput,
)
from momo.domain.robot import RobotProfile
from momo.ports.clock import Clock
from momo.ports.servo_bus import ReadOnlyServoBus


class CalibrationWorkflowCoordinator:
    """Keep one workflow pinned to an already-open, same-session read-only bus.

    The coordinator never opens a port and never creates a bus. Every request
    re-authorizes the short operator token through ``DeviceDiagnosticsService`` and
    verifies that the published bus and operator session have not changed.
    """

    def __init__(
        self,
        *,
        device: DeviceDiagnosticsService,
        repository: CalibrationWorkflowRepository,
        clock: Clock,
    ) -> None:
        self.device = device
        self.repository = repository
        self.clock = clock
        self._guard = asyncio.Lock()
        self._workflow: CalibrationWorkflowService | None = None
        self._bus: ReadOnlyServoBus | None = None
        self._authorization_session_id: UUID | None = None

    async def start(
        self,
        token: str,
        *,
        source: CalibrationWorkflowSource,
        explicit_legacy_calibration: CalibrationDocument | None = None,
        legacy_confirmation: str | None = None,
    ) -> CalibrationWorkflowStatus:
        async with self._guard:
            bus, evidence, authorization, profile = await self._current_access(token)
            existing = self._workflow
            if existing is not None:
                if self._authorization_session_id == evidence.session_id:
                    raise CalibrationWorkflowError(
                        "CALIBRATION_WORKFLOW_CONFLICT",
                        "Another calibration workflow is active",
                    )
                # Device expiry invalidates and closes its session independently.
                # A workflow bound to that old identity cannot permanently block a
                # newly confirmed, explicitly connected operator session.
                await existing.shutdown()
                self._clear()
            workflow = CalibrationWorkflowService(
                self.repository,
                bus,
                self.clock,
            )
            status = await workflow.start(
                authorization,
                profile,
                source=source,
                explicit_legacy_calibration=explicit_legacy_calibration,
                legacy_confirmation=legacy_confirmation,
            )
            self._workflow = workflow
            self._bus = bus
            self._authorization_session_id = evidence.session_id
            return status

    async def status(
        self,
        token: str,
        session_id: UUID,
    ) -> CalibrationWorkflowStatus:
        async with self._guard:
            workflow, authorization = await self._active(token)
            return await workflow.status(session_id, authorization)

    async def read_selected_joint(
        self,
        token: str,
        session_id: UUID,
        joint_id: str,
    ) -> CalibrationWorkflowStatus:
        async with self._guard:
            workflow, authorization = await self._active(token)
            return await workflow.read_selected_joint(session_id, authorization, joint_id)

    async def preview_joint(
        self,
        token: str,
        session_id: UUID,
        joint_id: str,
        *,
        logical_value: float,
        direction: int | None,
        phase: int | None,
        raw_bounds: tuple[int, int] | None,
    ) -> CalibrationJointPreview:
        async with self._guard:
            workflow, authorization = await self._active(token)
            return await workflow.preview_joint(
                session_id,
                authorization,
                joint_id,
                logical_value=logical_value,
                direction=direction,
                phase=phase,
                raw_bounds=raw_bounds,
            )

    async def confirm_joint(
        self,
        token: str,
        session_id: UUID,
        joint_id: str,
        *,
        preview_fingerprint: str,
        confirmation: str,
    ) -> CalibrationWorkflowStatus:
        async with self._guard:
            workflow, authorization = await self._active(token)
            return await workflow.confirm_joint(
                session_id,
                authorization,
                joint_id,
                preview_fingerprint=preview_fingerprint,
                confirmation=confirmation,
            )

    async def complete(
        self,
        token: str,
        session_id: UUID,
        *,
        proposed_calibration_fingerprint: str,
        confirmation: str,
    ) -> CalibrationRevisionRecord:
        async with self._guard:
            workflow, authorization = await self._active(token)
            persistence_started = False
            persisted_calibration: CalibrationDocument | None = None

            def mark_persistence_started() -> None:
                nonlocal persistence_started
                persistence_started = True

            try:
                record = await workflow.complete(
                    session_id,
                    authorization,
                    proposed_calibration_fingerprint=proposed_calibration_fingerprint,
                    confirmation=confirmation,
                    before_persist=mark_persistence_started,
                )
                persisted_calibration = record.calibration
            finally:
                if persistence_started:
                    try:
                        await workflow.shutdown()
                    finally:
                        self._clear()
                        # Persistence may have changed the calibration identity,
                        # including replace-then-fsync failure. Cleanup is
                        # completion-observed even when the request is cancelled.
                        await self._invalidate_device_after_persistence(persisted_calibration)
        return record

    async def cancel(
        self,
        token: str,
        session_id: UUID,
    ) -> CalibrationWorkflowStatus:
        async with self._guard:
            workflow, authorization = await self._active(token)
            status = await workflow.cancel(session_id, authorization)
            await workflow.shutdown()
            self._clear()
            return status

    async def rollback(
        self,
        token: str,
        *,
        target_revision: int,
        confirmation: str,
    ) -> CalibrationRevisionRecord:
        async with self._guard:
            if self._workflow is not None:
                raise CalibrationWorkflowError(
                    "CALIBRATION_WORKFLOW_CONFLICT",
                    "Cannot roll back while a calibration workflow is active",
                )
            bus, _evidence, authorization, profile = await self._current_access(token)
            workflow = CalibrationWorkflowService(
                self.repository,
                bus,
                self.clock,
            )
            persistence_started = False
            persisted_calibration: CalibrationDocument | None = None

            def mark_persistence_started() -> None:
                nonlocal persistence_started
                persistence_started = True

            try:
                record = await workflow.rollback(
                    authorization,
                    profile,
                    target_revision=target_revision,
                    confirmation=confirmation,
                    before_persist=mark_persistence_started,
                )
                persisted_calibration = record.calibration
            finally:
                try:
                    await workflow.shutdown()
                finally:
                    if persistence_started:
                        await self._invalidate_device_after_persistence(persisted_calibration)
        return record

    async def _invalidate_device_after_persistence(
        self,
        persisted_calibration: CalibrationDocument | None,
    ) -> None:
        cleanup = asyncio.create_task(
            self.device.invalidate_calibration_authorization(persisted_calibration),
            name="invalidate-stale-calibration-authorization",
        )
        cancellation: asyncio.CancelledError | None = None
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError as error:
                # Repeated request cancellation must not detach safety cleanup.
                if cancellation is None:
                    cancellation = error
        try:
            cleanup.result()
        except BaseException as error:
            if cancellation is not None:
                raise cancellation from error
            raise
        if cancellation is not None:
            raise cancellation

    async def shutdown(self) -> None:
        async with self._guard:
            workflow = self._workflow
            self._clear()
            if workflow is not None:
                await workflow.shutdown()

    async def _active(
        self,
        token: str,
    ) -> tuple[CalibrationWorkflowService, CalibrationAuthorization]:
        workflow = self._workflow
        if workflow is None:
            raise CalibrationWorkflowError(
                "CALIBRATION_SESSION_NOT_FOUND",
                "Calibration workflow session was not found",
            )
        try:
            bus, evidence, authorization, _profile = await self._current_access(token)
        except Exception:
            await workflow.shutdown()
            self._clear()
            raise
        if bus is not self._bus or evidence.session_id != self._authorization_session_id:
            await workflow.shutdown()
            self._clear()
            raise CalibrationWorkflowError(
                "CALIBRATION_AUTHORIZATION_MISMATCH",
                "The explicit device or operator session changed",
            )
        return workflow, authorization

    async def _current_access(
        self,
        token: str,
    ) -> tuple[
        ReadOnlyServoBus,
        OperatorSessionEvidence,
        CalibrationAuthorization,
        RobotProfile,
    ]:
        bus, evidence = await self.device.require_authorized_connected_bus(
            token,
            purpose=RealHardwareAuthorizationPurpose.CALIBRATION_CAPTURE,
        )
        context = self.device.context
        profile = context.profile
        if profile is None:
            raise CalibrationWorkflowError(
                "PROFILE_NOT_CONFIGURED",
                "A reviewed Real profile is required for calibration",
            )
        if evidence.hardware_access_policy is not HardwareAccessPolicy.READ_ONLY:
            raise CalibrationWorkflowError(
                "CALIBRATION_AUTHORIZATION_MISMATCH",
                "Calibration capture requires a READ_ONLY commissioning session",
            )
        grant = self.device.authorization.require_authorized(
            RealHardwareGateInput(
                context=context,
                evaluated_at=self.clock.now(),
                operator_session=evidence,
            ),
            purpose=RealHardwareAuthorizationPurpose.CALIBRATION_CAPTURE,
        )
        authorization = CalibrationAuthorization(
            session_id=evidence.session_id,
            robot_id=evidence.robot_id,
            variant=evidence.variant,
            profile_fingerprint=evidence.profile_fingerprint,
            calibration_fingerprint=(
                calibration_document_fingerprint(context.calibration)
                if context.calibration is not None
                else None
            ),
            allowed_servo_ids=evidence.allowed_servo_ids,
            issued_at=evidence.issued_at,
            expires_at=evidence.expires_at,
            confirmed=True,
            physical_estop_confirmed=evidence.physical_estop_confirmed,
            control_mode=evidence.control_mode,
            hardware_policy=HardwareAccessPolicy.READ_ONLY,
            purpose=RealHardwareAuthorizationPurpose.CALIBRATION_CAPTURE,
            capabilities=grant.capabilities,
        )
        return bus, evidence, authorization, profile

    def _clear(self) -> None:
        self._workflow = None
        self._bus = None
        self._authorization_session_id = None


__all__ = ["CalibrationWorkflowCoordinator"]
