"""Explicit-authorized read-only ServoBus connection and diagnostics workflow."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import TypeVar
from uuid import UUID

from momo.application.services.operator_session_service import OperatorSessionService
from momo.application.services.real_hardware_authorization import RealHardwareAuthorization
from momo.domain.calibration import CalibrationDocument
from momo.domain.commissioning import (
    FieldAcceptanceCapability,
    FieldAcceptanceEvidence,
    KinematicsEvidenceState,
    KinematicsVerificationEvidence,
    ValidatedFieldAcceptanceBundle,
)
from momo.domain.enums import (
    HardwareAccessPolicy,
    KinematicsVerificationStatus,
    ProfileVerificationStatus,
)
from momo.domain.errors import HardwareMappingError, RobotApplicationError
from momo.domain.hardware_mapping import effective_raw_bounds, goal_raw_to_logical
from momo.domain.real_hardware import (
    DeviceDiagnosticsSnapshot,
    HardwareArtifactStatus,
    HardwareDependencyState,
    HardwareDependencyStatus,
    IssuedOperatorSession,
    OperatorSessionEvidence,
    OperatorSessionPurpose,
    RealHardwareAuthorizationPurpose,
    RealHardwareBlocker,
    RealHardwareCapabilityReadiness,
    RealHardwareContext,
    RealHardwareGateInput,
    RealHardwareReadinessReport,
    RealHardwareReadinessState,
    RealStopOutcome,
    RealStopResult,
    ServoDiagnosticRecord,
    ServoPingResult,
    calibration_fingerprint,
    effective_field_acceptance_status,
    field_acceptance_evidence_state,
    kinematics_verification_evidence_state,
)
from momo.ports.clock import Clock
from momo.ports.servo_bus import (
    ReadOnlyServoBus,
    ReadOnlyServoBusFacade,
    ServoBus,
    ServoBusFactory,
)

_T = TypeVar("_T")


async def _wait_task_terminal(task: asyncio.Task[_T]) -> asyncio.CancelledError | None:
    """Observe a safety child through repeated cancellation of its caller."""

    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            if cancellation is None:
                cancellation = error
        except Exception:
            pass
    return cancellation


class DeviceConnectionError(RobotApplicationError):
    code = "REAL_DEVICE_CONNECTION_FAILED"
    status_code = 503


class DeviceAlreadyConnectedError(RobotApplicationError):
    code = "REAL_DEVICE_ALREADY_CONNECTED"
    status_code = 409


class DeviceNotConnectedError(RobotApplicationError):
    code = "REAL_DEVICE_NOT_CONNECTED"
    status_code = 409


class DeviceDiagnosticsService:
    """Own one explicit bus without ever scanning, homing, moving, or enabling torque."""

    def __init__(
        self,
        *,
        context: RealHardwareContext,
        authorization: RealHardwareAuthorization,
        sessions: OperatorSessionService,
        bus_factory: ServoBusFactory | None,
        clock: Clock,
    ) -> None:
        dependency = bus_factory.dependency if bus_factory is not None else None
        self.context = context.model_copy(
            update={
                "dependency_state": (
                    dependency.state
                    if dependency is not None
                    else HardwareDependencyState.UNAVAILABLE
                ),
                "dependency_adapter_id": (
                    dependency.adapter_id if dependency is not None else "no-servo-bus"
                ),
            }
        )
        self.authorization = authorization
        self.sessions = sessions
        self.bus_factory = bus_factory
        self.clock = clock
        self._guard = asyncio.Lock()
        self._bus: ServoBus | None = None
        self._read_only_bus: ReadOnlyServoBus | None = None
        # Candidate exists after the inert factory returns and before validation
        # commits Connected state. Priority Stop must still be able to reach it.
        self._candidate_bus: ServoBus | None = None
        # A close attempt may fail or still be running after cancellation. Keep
        # that handle reachable by priority Stop until close is known to finish.
        self._uncertain_bus: ServoBus | None = None
        self._connected_session_id: UUID | None = None
        self._expiry_watchdog: asyncio.Task[None] | None = None
        self._records: tuple[ServoDiagnosticRecord, ...] = ()
        self._last_error = ""

    @property
    def connected(self) -> bool:
        return self._bus is not None

    async def readiness(self) -> RealHardwareReadinessReport:
        evidence = await self.sessions.current_evidence(self.context)
        report = self.authorization.evaluate(
            RealHardwareGateInput(
                context=self.context,
                evaluated_at=self.clock.now(),
                operator_session=evidence,
            )
        )
        if self._candidate_bus is None and self._uncertain_bus is None:
            return report
        return RealHardwareReadinessReport(
            state=RealHardwareReadinessState.BLOCKED_BY_DEVICE,
            ready=False,
            session_authorizable=False,
            blocking_reasons=tuple(
                dict.fromkeys(
                    (
                        RealHardwareBlocker.DEVICE_SAFETY_STATE_UNCERTAIN,
                        *report.blocking_reasons,
                    )
                )
            ),
            capabilities=RealHardwareCapabilityReadiness(),
            confirmation=report.confirmation,
            session=report.session,
        )

    async def issue_operator_session(
        self,
        *,
        purpose: OperatorSessionPurpose | None = None,
        confirmation_text: str,
        physical_estop_confirmed: bool,
        workspace_clear_confirmed: bool = False,
        operator_id: str = "operator",
    ) -> IssuedOperatorSession:
        async with self._guard:
            if self._has_bus_reference:
                raise DeviceAlreadyConnectedError(
                    "Close the current or uncertain ServoBus before replacing its session"
                )
            return await self.sessions.issue(
                self.context,
                purpose=purpose,
                confirmation_text=confirmation_text,
                physical_estop_confirmed=physical_estop_confirmed,
                workspace_clear_confirmed=workspace_clear_confirmed,
                operator_id=operator_id,
            )

    async def authorize_operator_purpose(
        self,
        token: str,
        *,
        purpose: RealHardwareAuthorizationPurpose,
    ) -> OperatorSessionEvidence:
        """Authorize an API capability without exposing the session store."""

        return await self.sessions.authorize(token, self.context, purpose=purpose)

    async def revoke_operator_session(self, token: str) -> None:
        async with self._guard:
            await self.sessions.revoke(token)
            try:
                await self._close_connected_bus_unlocked()
            finally:
                await self.sessions.invalidate()

    async def connect(self, token: str) -> DeviceDiagnosticsSnapshot:
        await self.sessions.authorize(
            token,
            self.context,
            purpose=RealHardwareAuthorizationPurpose.DIAGNOSTICS,
        )
        async with self._guard:
            if self._has_bus_reference:
                raise DeviceAlreadyConnectedError(
                    "An explicit or uncertain ServoBus already owns the device"
                )
            # Authorization is checked again after waiting for connection ownership,
            # immediately before the gate -> factory -> open sequence.
            evidence = await self.sessions.authorize(
                token,
                self.context,
                purpose=RealHardwareAuthorizationPurpose.DIAGNOSTICS,
            )
            grant = self.authorization.require_authorized(
                RealHardwareGateInput(
                    context=self.context,
                    evaluated_at=self.clock.now(),
                    operator_session=evidence,
                ),
                purpose=RealHardwareAuthorizationPurpose.DIAGNOSTICS,
            )
            factory = self.bus_factory
            device = self.context.device
            if factory is None or device is None:
                await self.sessions.invalidate()
                raise DeviceConnectionError(
                    "No authorized ServoBus factory is configured",
                    details={"reason": "DEPENDENCY_UNAVAILABLE"},
                )
            bus: ServoBus | None = None
            read_only_bus: ReadOnlyServoBus | None = None
            try:
                # Gate -> factory -> open -> explicit ping -> modes -> positions ->
                # validation. No torque write/read, move, scan, or Home occurs here.
                create_task = asyncio.create_task(
                    asyncio.to_thread(factory.create, grant),
                    name="explicit-servo-bus-create",
                )
                create_cancellation = await _wait_task_terminal(create_task)
                try:
                    bus = create_task.result()
                except BaseException as error:
                    if create_cancellation is not None and error is not create_cancellation:
                        raise create_cancellation from error
                    raise
                if create_cancellation is not None:
                    raise create_cancellation
                self._candidate_bus = bus
                read_only_bus = ReadOnlyServoBusFacade(bus)
                await read_only_bus.open(device.serial_port, device.protocol)
                ping = await read_only_bus.ping_explicit_ids(device.servo_ids)
                self._validate_ping(device.servo_ids, ping)
                modes = await read_only_bus.read_operating_modes(device.servo_ids)
                self._validate_exact_mapping(device.servo_ids, modes, "operating modes")
                positions = await read_only_bus.read_present_positions(device.servo_ids)
                self._validate_exact_mapping(device.servo_ids, positions, "present positions")
                records = self._validated_records(ping, modes, positions, torque=None)
                # A short session can expire or be replaced while read-only I/O is
                # pending. Re-authorize before publishing Connected state.
                current = await self.sessions.authorize(
                    token,
                    self.context,
                    purpose=RealHardwareAuthorizationPurpose.DIAGNOSTICS,
                )
                if current.session_id != evidence.session_id:
                    raise DeviceConnectionError(
                        "Operator session changed during explicit connection"
                    )
                # Build the response before publishing ownership. Cancellation or
                # clock/session failure here therefore still follows partial-bus
                # cleanup and cannot leave an unacknowledged live connection.
                snapshot = await self._snapshot(
                    records,
                    connected=True,
                    include_transitional_blocker=False,
                )
            except BaseException as error:
                try:
                    await self._cleanup_partial_bus(bus)
                finally:
                    await self.sessions.invalidate()
                    self._records = ()
                if self._uncertain_bus is None:
                    self._last_error = f"{type(error).__name__} during explicit connection"
                if isinstance(error, asyncio.CancelledError):
                    raise
                if isinstance(error, RobotApplicationError):
                    raise
                raise DeviceConnectionError(
                    "Explicit read-only device connection failed",
                    details={"reason": type(error).__name__},
                ) from error
            self._bus = bus
            self._read_only_bus = read_only_bus
            self._candidate_bus = None
            self._connected_session_id = evidence.session_id
            self._records = records
            self._last_error = ""
            self._start_expiry_watchdog_unlocked(
                evidence.session_id,
                evidence.expires_at,
            )
        return snapshot

    async def diagnostics(
        self,
        token: str,
        *,
        include_torque: bool = True,
    ) -> DeviceDiagnosticsSnapshot:
        await self.sessions.authorize(
            token,
            self.context,
            purpose=RealHardwareAuthorizationPurpose.DIAGNOSTICS,
        )
        async with self._guard:
            evidence = await self.sessions.authorize(
                token,
                self.context,
                purpose=RealHardwareAuthorizationPurpose.DIAGNOSTICS,
            )
            bus = self._read_only_bus
            device = self.context.device
            if bus is None or device is None:
                raise DeviceNotConnectedError("The explicit ServoBus is not connected")
            if self._connected_session_id != evidence.session_id:
                raise DeviceNotConnectedError(
                    "The connected ServoBus belongs to a different operator session"
                )
            try:
                ping = await bus.ping_explicit_ids(device.servo_ids)
                self._validate_ping(device.servo_ids, ping)
                modes = await bus.read_operating_modes(device.servo_ids)
                self._validate_exact_mapping(device.servo_ids, modes, "operating modes")
                positions = await bus.read_present_positions(device.servo_ids)
                self._validate_exact_mapping(device.servo_ids, positions, "present positions")
                torque: Mapping[int, bool] | None = None
                if include_torque:
                    torque = await bus.read_torque_states(device.servo_ids)
                    self._validate_exact_mapping(device.servo_ids, torque, "torque states")
                    if any(not isinstance(value, bool) for value in torque.values()):
                        raise ValueError("torque states must be booleans")
                self._records = self._validated_records(ping, modes, positions, torque)
                self._last_error = ""
            except Exception as error:
                self._last_error = f"{type(error).__name__} during explicit diagnostics"
                raise DeviceConnectionError(
                    "Explicit read-only diagnostics failed",
                    details={"reason": type(error).__name__},
                ) from error
            current = await self.sessions.authorize(
                token,
                self.context,
                purpose=RealHardwareAuthorizationPurpose.DIAGNOSTICS,
            )
            if current.session_id != evidence.session_id:
                raise DeviceNotConnectedError(
                    "Operator session changed during explicit diagnostics"
                )
            records = self._records
            snapshot = await self._snapshot(records)
        return snapshot

    async def require_authorized_connected_bus(
        self,
        token: str,
        *,
        purpose: RealHardwareAuthorizationPurpose = RealHardwareAuthorizationPurpose.DIAGNOSTICS,
    ) -> tuple[ReadOnlyServoBus, OperatorSessionEvidence]:
        """Return the existing read-only-grant bus for a same-session coordinator.

        This never creates or opens a bus. The caller must hold the application-level
        exclusive hardware lease while using the returned reference; disconnect or
        priority Stop may still make an in-flight read fail closed.
        """

        if purpose not in {
            RealHardwareAuthorizationPurpose.DIAGNOSTICS,
            RealHardwareAuthorizationPurpose.CALIBRATION_CAPTURE,
        }:
            raise ValueError("the connected read-only bus supports commissioning purposes only")
        await self.sessions.authorize(
            token,
            self.context,
            purpose=purpose,
        )
        async with self._guard:
            evidence = await self.sessions.authorize(
                token,
                self.context,
                purpose=purpose,
            )
            bus = self._read_only_bus
            if bus is None:
                raise DeviceNotConnectedError("The explicit ServoBus is not connected")
            if self._connected_session_id != evidence.session_id:
                raise DeviceNotConnectedError(
                    "The connected ServoBus belongs to a different operator session"
                )
            return bus, evidence

    async def invalidate_calibration_authorization(
        self,
        persisted_calibration: CalibrationDocument | None = None,
    ) -> None:
        """Revoke stale authority and optionally publish an exact persisted revision.

        Successful workflow persistence supplies the returned, fully validated
        document. It is installed only after the old session is revoked and its
        read-only bus is closed, so the commissioning token can never be upgraded.
        An uncertain persistence outcome supplies ``None`` and clears the loaded
        calibration fail-closed until composition reloads durable state.
        """

        prospective = self.context.model_copy(update={"calibration": persisted_calibration})
        calibration_blockers = (
            self.authorization.calibration_blockers(prospective)
            if persisted_calibration is not None
            else ()
        )

        async with self._guard:
            await self.sessions.invalidate()
            try:
                await self._close_connected_bus_unlocked()
            finally:
                self.context = self.context.model_copy(
                    update={
                        "calibration": (persisted_calibration if not calibration_blockers else None)
                    }
                )
                self._records = ()
                await self.sessions.invalidate()
        if calibration_blockers:
            raise ValueError(
                "persisted calibration does not match the current hardware context: "
                + ", ".join(item.value for item in calibration_blockers)
            )

    async def invalidate_profile_authorization(self) -> None:
        """Revoke old hardware identity before the active robot Profile can change.

        Profile/variant switching is a cross-service operation. Clearing every
        profile-derived hardware input before the Robot service mutates prevents an
        old Motion token from authorizing a request against the new active robot.
        Existing acceptance evidence is retained only so it is visibly STALE; with
        Profile, Calibration, Kinematics, and Device absent it cannot grant access.
        """

        async with self._guard:
            await self.sessions.invalidate()
            try:
                await self._close_connected_bus_unlocked()
            finally:
                self.context = self.context.model_copy(
                    update={
                        "profile": None,
                        "calibration": None,
                        "kinematics": None,
                        "expected_kinematics_fingerprint": None,
                        "device": None,
                    }
                )
                self._records = ()
                await self.sessions.invalidate()

    async def apply_field_acceptance_evidence(
        self,
        evidence: FieldAcceptanceEvidence,
        *,
        validated_bundle: ValidatedFieldAcceptanceBundle,
        token: str,
        expected_session_id: UUID,
        persist: Callable[[], Awaitable[None]],
    ) -> None:
        """Linearize authorization, durable persistence, and live publication.

        Acceptance changes authorization context. Any existing read-only session is
        ended and its bus is closed; a later motion session must be newly confirmed.
        Holding the device guard across persistence makes the accepted command
        discrete: either a concurrent revoke wins before authorization and no record
        is saved, or acceptance wins and its durable record is legitimately committed
        before that revoke can proceed.
        """

        if evidence.capability is FieldAcceptanceCapability.PRE_MOTION_CHECKS:
            purpose = RealHardwareAuthorizationPurpose.DIAGNOSTICS
        elif evidence.capability is FieldAcceptanceCapability.JOINT_MOTION:
            purpose = RealHardwareAuthorizationPurpose.COMMISSIONING_SINGLE_JOINT_TEST
        else:
            raise ValueError("this field acceptance capability has no publication workflow")

        async with self._guard:
            current = await self.sessions.authorize(
                token,
                self.context,
                purpose=purpose,
            )
            if current.session_id != expected_session_id:
                raise ValueError("field acceptance session changed before publication")
            if current.operator_id != evidence.accepted_by:
                raise ValueError("field acceptance operator changed before publication")
            if evidence.evidence_id not in {item.evidence_id for item in validated_bundle.records}:
                raise ValueError("applied field acceptance is absent from the resolved bundle")
            prospective = self.context.model_copy(
                update={
                    "field_acceptance_evidence": evidence,
                    "field_acceptance_bundle": validated_bundle,
                }
            )
            _, stale_fields = field_acceptance_evidence_state(prospective)
            if stale_fields:
                raise ValueError(
                    "field acceptance evidence does not match the current context: "
                    + ", ".join(stale_fields)
                )
            if evidence.capability not in validated_bundle.valid_capabilities(prospective):
                raise ValueError("field acceptance evidence chain is not authoritative")

            async def commit() -> None:
                await persist()
                await self.sessions.invalidate()
                try:
                    await self._close_connected_bus_unlocked()
                finally:
                    self.context = prospective
                    self._records = ()
                    await self.sessions.invalidate()

            transaction = asyncio.create_task(
                commit(),
                name=f"publish-field-acceptance-{evidence.evidence_id}",
            )
            cancellation = await _wait_task_terminal(transaction)
            try:
                transaction.result()
            except BaseException as error:
                if cancellation is not None:
                    raise cancellation from error
                raise
            if cancellation is not None:
                raise cancellation

    async def apply_kinematics_verification_evidence(
        self,
        evidence: KinematicsVerificationEvidence,
        *,
        token: str,
        expected_session_id: UUID,
    ) -> None:
        """Atomically publish only for the still-current Real Motion session."""

        async with self._guard:
            current = await self.sessions.authorize(
                token,
                self.context,
                purpose=RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION,
            )
            if current.session_id != expected_session_id:
                raise ValueError("kinematics verification session changed before publication")
            prospective = self.context.model_copy(
                update={"kinematics_verification_evidence": evidence}
            )
            state, stale_fields = kinematics_verification_evidence_state(prospective)
            if state is not KinematicsEvidenceState.VALID:
                raise ValueError(
                    "kinematics verification evidence does not match current context: "
                    + ", ".join(stale_fields)
                )
            await self.sessions.invalidate()
            try:
                await self._close_connected_bus_unlocked()
            finally:
                self.context = prospective
                self._records = ()
                await self.sessions.invalidate()

    async def disconnect(self, token: str) -> DeviceDiagnosticsSnapshot:
        async with self._guard:
            await self.sessions.revoke(token)
            try:
                await self._close_connected_bus_unlocked()
            finally:
                await self.sessions.invalidate()
            snapshot = await self._snapshot(())
        return snapshot

    async def stop(self) -> RealStopOutcome:
        """Priority safety action: deliberately does not require a session token."""

        device = self.context.device
        requested = device.servo_ids if device is not None else ()
        # Do not queue behind a slow diagnostics read. The published bus reference
        # may race a disconnect; that race is reported as uncertain, never success.
        bus = self._bus or self._candidate_bus or self._uncertain_bus
        if bus is None:
            return RealStopOutcome(
                result=RealStopResult.NOT_CONNECTED,
                requested_ids=requested,
                affected_ids=(),
                connected=False,
                safety_state_known=False,
                detail="No explicit ServoBus is connected",
            )
        if self.context.hardware_access_policy is HardwareAccessPolicy.READ_ONLY:
            return RealStopOutcome(
                result=RealStopResult.SAFETY_STATE_UNCERTAIN,
                requested_ids=requested,
                affected_ids=(),
                connected=True,
                safety_state_known=False,
                detail=(
                    "READ_ONLY commissioning forbids software Stop/Hold writes; "
                    "use the physical E-stop"
                ),
            )
        try:
            outcome = await bus.stop_or_hold(requested)
            # NOT_CONNECTED from a handle whose close has not completed is not
            # enough evidence to claim that the physical device is safe.
            if outcome.result is RealStopResult.NOT_CONNECTED and (
                self._candidate_bus is bus or self._uncertain_bus is bus
            ):
                return RealStopOutcome(
                    result=RealStopResult.SAFETY_STATE_UNCERTAIN,
                    requested_ids=requested,
                    affected_ids=(),
                    connected=True,
                    safety_state_known=False,
                    detail="Device close is unverified; use the physical E-stop",
                )
            return outcome
        except Exception:
            return RealStopOutcome(
                result=RealStopResult.SAFETY_STATE_UNCERTAIN,
                requested_ids=requested,
                affected_ids=(),
                connected=True,
                safety_state_known=False,
                detail="Software Stop failed; use the physical E-stop",
            )

    async def shutdown(self) -> None:
        async with self._guard:
            try:
                await self._close_connected_bus_unlocked()
            finally:
                await self.sessions.invalidate()

    async def _close_connected_bus_unlocked(self) -> None:
        await self._cancel_expiry_watchdog_unlocked()
        bus = self._bus or self._candidate_bus or self._uncertain_bus
        self._bus = None
        self._read_only_bus = None
        self._candidate_bus = None
        self._connected_session_id = None
        self._records = ()
        if bus is None:
            return
        error = await self._attempt_bus_close_unlocked(
            bus,
            task_name="explicit-servo-bus-close",
        )
        if error is not None:
            raise DeviceConnectionError(
                "Explicit ServoBus close failed; hardware state is uncertain",
                details={"reason": type(error).__name__},
            ) from error

    async def _cleanup_partial_bus(self, bus: ServoBus | None) -> None:
        if bus is None:
            return
        await self._attempt_bus_close_unlocked(
            bus,
            task_name="partial-servo-bus-close",
        )

    async def _attempt_bus_close_unlocked(
        self,
        bus: ServoBus,
        *,
        task_name: str,
    ) -> Exception | None:
        existing = self._uncertain_bus
        if existing is not None and existing is not bus:
            raise RuntimeError("another uncertain ServoBus already owns the device")
        if self._candidate_bus is bus:
            self._candidate_bus = None
        self._uncertain_bus = bus
        cleanup = asyncio.create_task(bus.close(), name=task_name)
        cancellation = await _wait_task_terminal(cleanup)
        try:
            cleanup.result()
        except BaseException as error:
            self._last_error = (
                f"{type(error).__name__} while closing explicit ServoBus; safety state uncertain"
            )
            if cancellation is not None and error is not cancellation:
                raise cancellation from error
            if isinstance(error, asyncio.CancelledError):
                raise
            if not isinstance(error, Exception):
                raise
            return error
        self._clear_uncertain_bus(bus)
        if cancellation is not None:
            raise cancellation
        return None

    def _clear_uncertain_bus(self, bus: ServoBus) -> None:
        if self._uncertain_bus is bus:
            self._uncertain_bus = None
        self._last_error = ""

    def _start_expiry_watchdog_unlocked(
        self,
        session_id: UUID,
        expires_at: datetime,
    ) -> None:
        if self._expiry_watchdog is not None:
            raise RuntimeError("an explicit device expiry watchdog is already active")
        self._expiry_watchdog = asyncio.create_task(
            self._watch_connected_session_expiry(session_id, expires_at),
            name=f"explicit-device-session-expiry-{session_id}",
        )

    async def _cancel_expiry_watchdog_unlocked(self) -> None:
        task = self._expiry_watchdog
        self._expiry_watchdog = None
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _watch_connected_session_expiry(
        self,
        session_id: UUID,
        expires_at: datetime,
    ) -> None:
        try:
            while True:
                remaining = (expires_at - self.clock.now()).total_seconds()
                if remaining > 0:
                    await self.clock.sleep(remaining)
                    continue
                async with self._guard:
                    if self._connected_session_id != session_id:
                        return
                    if self.clock.now() < expires_at:
                        continue
                    await self.sessions.invalidate()
                    try:
                        await self._close_connected_bus_unlocked()
                    except Exception:
                        # Close records and retains an uncertain bus reference so
                        # unauthenticated priority Stop can still reach it.
                        pass
                    finally:
                        await self.sessions.invalidate()
                    return
        except asyncio.CancelledError:
            return

    @property
    def _has_bus_reference(self) -> bool:
        return (
            self._bus is not None
            or self._candidate_bus is not None
            or self._uncertain_bus is not None
        )

    def _validated_records(
        self,
        ping: Mapping[int, ServoPingResult],
        modes: Mapping[int, object],
        positions: Mapping[int, object],
        torque: Mapping[int, bool] | None,
    ) -> tuple[ServoDiagnosticRecord, ...]:
        profile = self.context.profile
        calibration = self.context.calibration
        device = self.context.device
        if profile is None or device is None:
            raise ValueError("device validation artifacts are incomplete")
        calibration_by_servo = (
            {joint.servo_id: joint for joint in calibration.joints}
            if calibration is not None
            and calibration.robot_variant is profile.variant
            and calibration.profile_fingerprint == profile.fingerprint
            and tuple(joint.joint_id for joint in calibration.joints)
            == tuple(profile.enabled_joints)
            else {}
        )
        definition_by_servo = {
            definition.servo_id: definition
            for definition in profile.joint_definitions
            if definition.servo_id is not None
        }
        records: list[ServoDiagnosticRecord] = []
        for index, servo_id in enumerate(device.servo_ids):
            definition = definition_by_servo.get(servo_id)
            calibration_joint = calibration_by_servo.get(servo_id)
            if definition is None:
                raise ValueError("explicit servo ID has no matching Profile joint")
            mode = modes[servo_id]
            if not isinstance(mode, str) or mode != definition.operating_mode.value:
                raise ValueError("operating mode does not match the reviewed Profile")
            raw = positions[servo_id]
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise ValueError("present raw position must be an integer")
            logical: float | None = None
            raw_bounds: tuple[int, int] | None = None
            if (
                calibration_joint is not None
                and calibration_joint.joint_id == definition.joint_id
                and calibration_joint.operating_mode is definition.operating_mode
            ):
                lower, upper = effective_raw_bounds(definition, calibration_joint)
                if not lower <= raw <= upper:
                    raise HardwareMappingError("present raw position is outside reviewed bounds")
                logical = goal_raw_to_logical(
                    definition.joint_id,
                    raw,
                    profile,
                    calibration_joint,
                )
                if not definition.minimum <= logical <= definition.maximum:
                    raise HardwareMappingError(
                        "present raw position maps outside reviewed logical limits"
                    )
                raw_bounds = (lower, upper)
            records.append(
                ServoDiagnosticRecord(
                    joint_id=definition.joint_id,
                    servo_id=servo_id,
                    masked_servo_id=device.masked_servo_ids[index],
                    ping_responded=ping[servo_id].responded,
                    operating_mode=mode,
                    present_raw=raw,
                    logical_value=logical,
                    raw_bounds=raw_bounds,
                    torque_enabled=torque[servo_id] if torque is not None else None,
                )
            )
        return tuple(records)

    async def _snapshot(
        self,
        records: tuple[ServoDiagnosticRecord, ...],
        *,
        connected: bool | None = None,
        include_transitional_blocker: bool = True,
    ) -> DeviceDiagnosticsSnapshot:
        if include_transitional_blocker:
            report = await self.readiness()
        else:
            evidence = await self.sessions.current_evidence(self.context)
            report = self.authorization.evaluate(
                RealHardwareGateInput(
                    context=self.context,
                    evaluated_at=self.clock.now(),
                    operator_session=evidence,
                )
            )
        profile = self.context.profile
        calibration = self.context.calibration
        kinematics = self.context.kinematics
        device = self.context.device
        calibration_ready = (
            not any(item.name.startswith("CALIBRATION_") for item in report.blocking_reasons)
            and profile is not None
            and calibration is not None
        )
        kinematics_ready = bool(
            profile is not None
            and kinematics is not None
            and kinematics.verification_status is KinematicsVerificationStatus.VERIFIED_FOR_REAL
            and self.context.expected_kinematics_fingerprint is not None
            and kinematics.fingerprint == self.context.expected_kinematics_fingerprint
        )
        if kinematics_ready:
            assert profile is not None and kinematics is not None
            try:
                kinematics.validate_against_profile(profile)
            except ValueError:
                kinematics_ready = False
        return DeviceDiagnosticsSnapshot(
            connected=self.connected if connected is None else connected,
            captured_at=self.clock.now(),
            dependency=self._dependency(),
            hardware_policy=self.context.hardware_access_policy,
            masked_serial_port=device.masked_serial_port if device is not None else None,
            masked_servo_ids=device.masked_servo_ids if device is not None else (),
            protocol=device.protocol if device is not None else None,
            profile=HardwareArtifactStatus(
                configured=profile is not None,
                fingerprint=profile.fingerprint if profile is not None else None,
                verification_status=(
                    profile.verification_status.value if profile is not None else None
                ),
                template=profile.template if profile is not None else None,
                ready_for_real=(
                    profile is not None
                    and not profile.template
                    and profile.verification_status is ProfileVerificationStatus.VERIFIED_FOR_REAL
                ),
            ),
            calibration=HardwareArtifactStatus(
                configured=calibration is not None,
                fingerprint=(
                    calibration_fingerprint(calibration) if calibration is not None else None
                ),
                verification_status=("COMPLETE_MATCHED" if calibration_ready else "BLOCKED"),
                template=calibration.template if calibration is not None else None,
                ready_for_real=calibration_ready,
            ),
            kinematics=HardwareArtifactStatus(
                configured=kinematics is not None,
                fingerprint=kinematics.fingerprint if kinematics is not None else None,
                verification_status=(
                    kinematics.verification_status.value if kinematics is not None else None
                ),
                template=None,
                ready_for_real=kinematics_ready,
            ),
            field_acceptance=effective_field_acceptance_status(self.context),
            readiness=report.state,
            records=records,
            last_error=self._last_error,
        )

    def _dependency(self) -> HardwareDependencyStatus:
        factory = self.bus_factory
        if factory is not None:
            return factory.dependency
        return HardwareDependencyStatus(
            adapter_id="no-servo-bus",
            state=HardwareDependencyState.UNAVAILABLE,
            package_name=None,
            license_status="NOT_APPLICABLE",
            notice="No ServoBus factory is configured; hardware access remains disabled.",
        )

    @staticmethod
    def _validate_ping(
        requested: tuple[int, ...],
        results: Mapping[int, ServoPingResult],
    ) -> None:
        DeviceDiagnosticsService._validate_exact_mapping(requested, results, "ping")
        for servo_id in requested:
            result = results[servo_id]
            if result.servo_id != servo_id or not result.responded:
                raise ValueError("not every explicitly configured servo responded")

    @staticmethod
    def _validate_exact_mapping(
        requested: tuple[int, ...],
        values: Mapping[int, object],
        label: str,
    ) -> None:
        if set(values) != set(requested) or len(values) != len(requested):
            raise ValueError(f"{label} did not exactly match explicit servo IDs")
