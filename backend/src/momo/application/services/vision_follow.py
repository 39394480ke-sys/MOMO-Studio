"""Lease-bound, Dry Run vision Follow controller."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.robot_service import RobotApplicationService
from momo.application.services.vision_command_coordinator import (
    VisionCommandCoordinator,
    VisionMotionGateway,
)
from momo.application.services.vision_follow_command_factory import (
    VisionFollowCommandFactory,
)
from momo.application.services.vision_follow_watchdog import VisionFollowWatchdog
from momo.domain.enums import (
    ControlMode,
    HardwareAccessPolicy,
    MotionCommandState,
    RobotConnectionState,
)
from momo.domain.errors import (
    MotionConflictError,
    MotionPreflightError,
    VisionFollowConflictError,
    VisionFollowLeaseNotFoundError,
)
from momo.domain.real_hardware import RealHardwareAuthorizationPurpose
from momo.domain.real_motion import RealExecutionAuthorization
from momo.domain.vision import TrackingResult, TrackingStatus
from momo.domain.vision_follow import (
    FollowController,
    FollowControllerState,
    FollowLease,
    FollowMetrics,
    FollowOperatorIntent,
    FollowState,
    FollowStatus,
    FollowStopReason,
)
from momo.ports.clock import Clock


@dataclass(slots=True)
class _FollowSession:
    follow_id: UUID
    intent: FollowOperatorIntent
    lease_id: UUID
    issued_at: datetime
    heartbeat_at: datetime
    expires_at: datetime
    expires_at_monotonic: float
    generation: int
    command_epoch: int
    authorization: RealExecutionAuthorization | None = None
    execution_purpose: RealHardwareAuthorizationPurpose | None = None
    state: FollowState = FollowState.ACTIVE
    stop_reason: FollowStopReason | None = None
    metrics: FollowMetrics | None = None
    controller_state: FollowControllerState = field(default_factory=FollowControllerState)
    last_frame_id: str | None = None
    last_captured_at: datetime | None = None
    last_frame_received_monotonic: float = 0.0
    lost_since_monotonic: float | None = None
    loss_reason: FollowStopReason | None = None
    active_command_id: UUID | None = None

    def next_deadline(self) -> float:
        configuration = self.intent.configuration
        deadlines = [
            self.expires_at_monotonic,
            self.last_frame_received_monotonic + configuration.frame_freshness_limit_s,
        ]
        if self.lost_since_monotonic is not None:
            deadlines.append(self.lost_since_monotonic + configuration.target_lost_limit_s)
        return min(deadlines)


class VisionFollowService:
    """Convert trustworthy target observations into bounded safety-gateway intents."""

    def __init__(
        self,
        robot: RobotApplicationService,
        kinematics: KinematicsService,
        motion: VisionMotionGateway,
        clock: Clock,
    ) -> None:
        self.robot = robot
        self.kinematics = kinematics
        self.commands = VisionCommandCoordinator(motion)
        self.command_factory = VisionFollowCommandFactory(kinematics)
        self.clock = clock
        self.watchdog = VisionFollowWatchdog(clock, self._watchdog_expired)
        self._guard = asyncio.Lock()
        self._generation = 0
        self._lifecycle_epoch = 0
        self._lifecycle_count = 0
        self._closed = False
        self._session: _FollowSession | None = None
        self._latest_status = FollowStatus(updated_at=self.clock.now())

    def get_status(self) -> FollowStatus:
        return self._latest_status

    @property
    def follow_active(self) -> bool:
        return self._latest_status.state is FollowState.ACTIVE

    async def start(
        self,
        intent: FollowOperatorIntent,
        *,
        authorization: RealExecutionAuthorization | None = None,
        execution_purpose: RealHardwareAuthorizationPurpose | None = None,
    ) -> FollowStatus:
        self._validate_execution_binding(authorization, execution_purpose)
        async with self._guard:
            if self._closed:
                raise VisionFollowConflictError(
                    "Vision Follow service is shut down",
                    details={"reason": "BACKEND_SHUTDOWN"},
                )
            if self._lifecycle_count:
                raise VisionFollowConflictError(
                    "Vision Follow cannot start during Global Stop",
                    details={"reason": "LIFECYCLE_STOP_ACTIVE"},
                )
            start_epoch = self._lifecycle_epoch
            if self._session is not None and self._session.state is FollowState.ACTIVE:
                raise VisionFollowConflictError("A Vision Follow lease is already active")
        status, profile, _ = await self.robot.get_motion_snapshot()
        reasons = _start_runtime_reasons(status)
        reasons.extend(self.command_factory.mapping_reasons(profile, intent.configuration))
        if reasons:
            raise VisionFollowConflictError(
                "Vision Follow start preflight failed",
                details={"reasons": reasons},
            )

        async with self._guard:
            if self._closed:
                raise VisionFollowConflictError(
                    "Vision Follow start was superseded by backend shutdown",
                    details={"reason": "BACKEND_SHUTDOWN"},
                )
            if self._lifecycle_count or start_epoch != self._lifecycle_epoch:
                raise VisionFollowConflictError(
                    "Vision Follow start was superseded by Global Stop",
                    details={"reason": "LIFECYCLE_EPOCH_CHANGED"},
                )
            if self._session is not None and self._session.state is FollowState.ACTIVE:
                raise VisionFollowConflictError("A Vision Follow lease is already active")
            command_epoch = await self.commands.begin_owner()
            self._generation += 1
            now = self.clock.now()
            now_monotonic = self.clock.monotonic()
            configuration = intent.configuration
            session = _FollowSession(
                follow_id=uuid4(),
                intent=intent,
                lease_id=uuid4(),
                issued_at=now,
                heartbeat_at=now,
                expires_at=now + timedelta(seconds=configuration.lease_ttl_s),
                expires_at_monotonic=now_monotonic + configuration.lease_ttl_s,
                generation=self._generation,
                command_epoch=command_epoch,
                authorization=authorization,
                execution_purpose=execution_purpose,
                last_frame_received_monotonic=now_monotonic,
            )
            self._session = session
            self._restart_watchdog_unlocked(session)
            return self._publish_unlocked(session)

    async def heartbeat(
        self,
        lease_id: UUID,
        *,
        authorization: RealExecutionAuthorization | None = None,
        execution_purpose: RealHardwareAuthorizationPurpose | None = None,
    ) -> FollowStatus:
        self._validate_execution_binding(authorization, execution_purpose)
        expired = False
        async with self._guard:
            session = self._require_session_unlocked(lease_id)
            if (
                session.authorization != authorization
                or session.execution_purpose is not execution_purpose
            ):
                raise VisionFollowConflictError(
                    "Vision Follow authority cannot be replaced in-place",
                    details={"reason": "AUTHORIZATION_SESSION_CHANGED"},
                )
            if session.state is not FollowState.ACTIVE:
                return self._latest_status
            now_monotonic = self.clock.monotonic()
            if now_monotonic >= session.expires_at_monotonic:
                expired = True
            else:
                now = self.clock.now()
                session.heartbeat_at = now
                session.expires_at = now + timedelta(
                    seconds=session.intent.configuration.lease_ttl_s
                )
                session.expires_at_monotonic = (
                    now_monotonic + session.intent.configuration.lease_ttl_s
                )
                self._restart_watchdog_unlocked(session)
                return self._publish_unlocked(session)
        if expired:
            return await self._stop_matching(
                lease_id,
                FollowStopReason.LEASE_EXPIRED,
            )
        raise AssertionError("unreachable")

    async def process_tracking(
        self,
        lease_id: UUID,
        result: TrackingResult,
    ) -> FollowStatus:
        """Process one latest-value observation and optionally dispatch one increment."""

        now = self.clock.now()
        now_monotonic = self.clock.monotonic()
        age_s = (now - result.metadata.captured_at).total_seconds()

        async with self._guard:
            session = self._require_session_unlocked(lease_id)
            if session.state is not FollowState.ACTIVE:
                return self._latest_status
            generation = session.generation
            configuration = session.intent.configuration
            if now_monotonic >= session.expires_at_monotonic:
                stop_reason = FollowStopReason.LEASE_EXPIRED
            elif (
                age_s > configuration.frame_freshness_limit_s
                or age_s < -configuration.frame_freshness_limit_s
                or (
                    session.last_captured_at is not None
                    and result.metadata.frame_id != session.last_frame_id
                    and result.metadata.captured_at <= session.last_captured_at
                )
                or result.status is TrackingStatus.STALE
            ):
                stop_reason = FollowStopReason.FRAME_STALE
            elif result.status is TrackingStatus.FAULTED:
                stop_reason = FollowStopReason.TRACKER_FAULT
            else:
                stop_reason = None
                duplicate_frame = result.metadata.frame_id == session.last_frame_id
                if (
                    duplicate_frame
                    and result.status is TrackingStatus.LOCKED
                    and result.confidence >= configuration.confidence_threshold
                ):
                    return self._latest_status
                if not duplicate_frame:
                    session.last_frame_id = result.metadata.frame_id
                    session.last_captured_at = result.metadata.captured_at
                    session.last_frame_received_monotonic = now_monotonic

        if stop_reason is not None:
            return await self._stop_matching(
                lease_id,
                stop_reason,
            )

        if (
            result.status is not TrackingStatus.LOCKED
            or result.bounding_box is None
            or result.confidence < configuration.confidence_threshold
        ):
            reason = (
                FollowStopReason.CONFIDENCE_LOW
                if result.status is TrackingStatus.LOCKED
                and result.confidence < configuration.confidence_threshold
                else FollowStopReason.TARGET_LOST
            )
            return await self._record_target_loss(lease_id, generation, reason)

        # Robot lifecycle evidence is refreshed for every trustworthy LOCKED
        # frame, including dead-zone frames and frames received while a prior
        # Vision command is active. Heartbeats/frames must never mask a robot
        # disconnect or fault behind an early controller return.
        try:
            robot_status, profile, current = await self.robot.get_motion_snapshot()
        except Exception:
            await self._stop_matching(
                lease_id,
                FollowStopReason.ROBOT_FAULTED,
            )
            raise
        robot_stop_reason = _robot_stop_reason(robot_status)
        if robot_stop_reason is not None:
            return await self._stop_matching(lease_id, robot_stop_reason)

        box = result.bounding_box
        async with self._guard:
            retained = self._active_generation_unlocked(lease_id, generation)
            if retained is None:
                return self._latest_status
            configuration = retained.intent.configuration
            decision = FollowController.update(
                configuration,
                retained.controller_state,
                frame_id=result.metadata.frame_id,
                source_id=result.metadata.source_id,
                captured_at=result.metadata.captured_at,
                frame_age_s=age_s,
                confidence=result.confidence,
                center_x=box.center_x,
                center_y=box.center_y,
                now_monotonic=now_monotonic,
            )
            retained.controller_state = decision.state
            retained.metrics = decision.metrics
            retained.lost_since_monotonic = None
            retained.loss_reason = None
            command_epoch = retained.command_epoch
            self._restart_watchdog_unlocked(retained)
            self._publish_unlocked(retained)

        try:
            ownership = await self.commands.inspect(command_epoch)
        except Exception:
            await self._stop_matching(lease_id, FollowStopReason.MOTION_REJECTED)
            raise
        async with self._guard:
            retained = self._active_generation_unlocked(lease_id, generation)
            if retained is None:
                return self._latest_status
            retained.active_command_id = ownership.active_command_id
            self._publish_unlocked(retained)
        if ownership.dispatch_busy:
            return self._latest_status
        if ownership.status is not None and ownership.status.state is MotionCommandState.FAULTED:
            return await self._stop_matching(
                lease_id,
                FollowStopReason.MOTION_REJECTED,
            )
        if ownership.active_command_id is not None:
            return self._latest_status

        pan_step = decision.metrics.pan_step
        tilt_step = decision.metrics.tilt_step
        if abs(pan_step) <= 1e-12 and abs(tilt_step) <= 1e-12:
            return self._latest_status

        try:
            built = self.command_factory.build(
                robot_status=robot_status,
                profile=profile,
                current=current,
                configuration=configuration,
                pan_step=pan_step,
                tilt_step=tilt_step,
            )
        except VisionFollowConflictError:
            await self._stop_matching(
                lease_id,
                FollowStopReason.MOTION_REJECTED,
            )
            raise
        except Exception:
            await self._stop_matching(
                lease_id,
                FollowStopReason.MOTION_REJECTED,
            )
            raise
        async with self._guard:
            retained = self._active_generation_unlocked(lease_id, generation)
            if retained is None:
                return self._latest_status
            if (
                retained.metrics is not None
                and retained.metrics.frame_id == result.metadata.frame_id
            ):
                retained.metrics = retained.metrics.model_copy(
                    update={
                        "pan_step": built.pan_step,
                        "tilt_step": built.tilt_step,
                    }
                )
                self._publish_unlocked(retained)
        command = built.command
        if command is None:
            return self._latest_status
        try:
            accepted_id = await self.commands.dispatch(
                command_epoch,
                command,
                authorization=retained.authorization,
                execution_purpose=retained.execution_purpose,
            )
        except MotionConflictError:
            return await self._stop_current(FollowStopReason.MOTION_CONFLICT)
        except MotionPreflightError:
            return await self._stop_current(FollowStopReason.MOTION_REJECTED)
        except Exception:
            await self._stop_current(FollowStopReason.MOTION_REJECTED)
            raise
        if accepted_id is None:
            return self._latest_status
        async with self._guard:
            retained = self._active_generation_unlocked(lease_id, generation)
            if retained is None:
                return self._latest_status
            retained.active_command_id = accepted_id
            retained.controller_state = FollowController.mark_dispatched(
                retained.controller_state,
                self.clock.monotonic(),
            )
            return self._publish_unlocked(retained)

    async def stop(
        self,
        lease_id: UUID,
        reason: FollowStopReason = FollowStopReason.OPERATOR_STOP,
    ) -> FollowStatus:
        return await self._stop_matching(
            lease_id,
            reason,
        )

    async def browser_disconnected(self, lease_id: UUID) -> FollowStatus:
        return await self.stop(lease_id, FollowStopReason.BROWSER_DISCONNECTED)

    async def stop_for_event(self, reason: FollowStopReason) -> FollowStatus:
        """Stop the current lease for a source, tracker, or robot lifecycle event."""

        if reason in {
            FollowStopReason.OPERATOR_STOP,
            FollowStopReason.GLOBAL_STOP,
        }:
            raise ValueError("use stop() or stop_all() for operator/global Stop")
        return await self._stop_current(reason)

    async def stop_all(self) -> None:
        """Global Stop hook: invalidate Follow without re-entering motion dispatch.

        MotionApplicationService invokes hooks while holding its dispatch/admission
        locks and has already cancelled the executor owner. A hook must therefore
        never synchronously call back into motion cancellation.
        """

        async with self._guard:
            self._lifecycle_count += 1
            self._lifecycle_epoch += 1
        try:
            await self._stop_current(FollowStopReason.GLOBAL_STOP, global_stop=True)
        finally:
            async with self._guard:
                self._lifecycle_epoch += 1
                self._lifecycle_count -= 1

    async def shutdown(self) -> None:
        # Fence start before checking the current session. A start may already be
        # awaiting its Robot snapshot while shutdown still observes no lease.
        # ``_closed`` is permanent: a disposed application service cannot acquire
        # a new Follow owner even after this barrier completes.
        async with self._guard:
            self._closed = True
            self._lifecycle_count += 1
            self._lifecycle_epoch += 1
        try:
            await self._stop_current(FollowStopReason.BACKEND_SHUTDOWN)
        finally:
            async with self._guard:
                self._lifecycle_epoch += 1
                self._lifecycle_count -= 1

    async def _record_target_loss(
        self,
        lease_id: UUID,
        generation: int,
        reason: FollowStopReason,
    ) -> FollowStatus:
        async with self._guard:
            session = self._active_generation_unlocked(lease_id, generation)
            if session is None:
                return self._latest_status
            now_monotonic = self.clock.monotonic()
            if session.lost_since_monotonic is None:
                session.lost_since_monotonic = now_monotonic
                session.loss_reason = reason
            elapsed = now_monotonic - session.lost_since_monotonic
            command_epoch = session.command_epoch
            session.active_command_id = None
            session.metrics = None
            target_lost_limit_s = session.intent.configuration.target_lost_limit_s
            resolved_reason = session.loss_reason or reason
            self._restart_watchdog_unlocked(session)
            self._publish_unlocked(session)

        await self.commands.suspend(command_epoch)
        if elapsed >= target_lost_limit_s:
            return await self._stop_matching(lease_id, resolved_reason)
        return self._latest_status

    async def _stop_matching(
        self,
        lease_id: UUID,
        reason: FollowStopReason,
    ) -> FollowStatus:
        async with self._guard:
            self._require_session_unlocked(lease_id)
        return await self._stop_current(
            reason,
            expected_lease_id=lease_id,
        )

    async def _stop_current(
        self,
        reason: FollowStopReason,
        *,
        expected_lease_id: UUID | None = None,
        global_stop: bool = False,
    ) -> FollowStatus:
        async with self._guard:
            session = self._session
            if session is None:
                return self._latest_status
            if expected_lease_id is not None and session.lease_id != expected_lease_id:
                raise VisionFollowLeaseNotFoundError(f"Unknown Follow lease: {expected_lease_id}")
            if session.state is FollowState.STOPPED:
                return self._latest_status
            self._generation += 1
            session.state = FollowState.STOPPED
            session.stop_reason = reason
            session.generation = self._generation
            command_epoch = session.command_epoch
            session.active_command_id = None
            self.watchdog.cancel()
            status = self._publish_unlocked(session)
        await self.commands.stop(command_epoch, global_stop=global_stop)
        return status

    async def _watchdog_expired(self, lease_id: UUID, generation: int) -> None:
        async with self._guard:
            session = self._active_generation_unlocked(lease_id, generation)
            if session is None:
                return
            now = self.clock.monotonic()
            if now >= session.expires_at_monotonic:
                reason = FollowStopReason.LEASE_EXPIRED
            elif session.lost_since_monotonic is not None and now >= (
                session.lost_since_monotonic + session.intent.configuration.target_lost_limit_s
            ):
                reason = session.loss_reason or FollowStopReason.TARGET_LOST
            elif now >= (
                session.last_frame_received_monotonic
                + session.intent.configuration.frame_freshness_limit_s
            ):
                reason = FollowStopReason.FRAME_STALE
            else:
                self._restart_watchdog_unlocked(session)
                return
        await self._stop_matching(lease_id, reason)

    def _restart_watchdog_unlocked(self, session: _FollowSession) -> None:
        self.watchdog.restart(
            session.lease_id,
            session.generation,
            session.next_deadline(),
        )

    def _active_generation_unlocked(
        self,
        lease_id: UUID,
        generation: int,
    ) -> _FollowSession | None:
        session = self._session
        if (
            session is None
            or session.lease_id != lease_id
            or session.generation != generation
            or session.state is not FollowState.ACTIVE
        ):
            return None
        return session

    def _require_session_unlocked(self, lease_id: UUID) -> _FollowSession:
        session = self._session
        if session is None or session.lease_id != lease_id:
            raise VisionFollowLeaseNotFoundError(f"Unknown Follow lease: {lease_id}")
        return session

    @staticmethod
    def _validate_execution_binding(
        authorization: RealExecutionAuthorization | None,
        execution_purpose: RealHardwareAuthorizationPurpose | None,
    ) -> None:
        if (authorization is None) is not (execution_purpose is None):
            raise VisionFollowConflictError(
                "Vision Follow requires a complete execution authorization binding",
                details={"reason": "AUTHORIZATION_BINDING_INCOMPLETE"},
            )
        if authorization is None:
            return
        if (
            execution_purpose is not RealHardwareAuthorizationPurpose.REAL_VISION_FOLLOW
            or authorization.purpose is not execution_purpose
        ):
            raise VisionFollowConflictError(
                "Vision Follow requires its dedicated execution capability",
                details={"reason": "AUTHORIZATION_PURPOSE_MISMATCH"},
            )

    def _publish_unlocked(self, session: _FollowSession) -> FollowStatus:
        lease = FollowLease(
            lease_id=session.lease_id,
            issued_at=session.issued_at,
            heartbeat_at=session.heartbeat_at,
            expires_at=session.expires_at,
        )
        self._latest_status = FollowStatus(
            follow_id=session.follow_id,
            operator_intent_id=session.intent.intent_id,
            state=session.state,
            configuration=session.intent.configuration,
            lease=lease,
            metrics=session.metrics,
            active_command_id=session.active_command_id,
            stop_reason=session.stop_reason,
            updated_at=self.clock.now(),
        )
        return self._latest_status


def _start_runtime_reasons(status: object) -> list[str]:
    reasons: list[str] = []
    if not getattr(status, "connected", False):
        reasons.append("ROBOT_DISCONNECTED")
    if getattr(status, "connection_state", None) is RobotConnectionState.FAULTED:
        reasons.append("ROBOT_FAULTED")
    if getattr(status, "stale", True):
        reasons.append("ROBOT_STATE_STALE")
    if getattr(status, "control_mode", None) is not ControlMode.DRY_RUN:
        reasons.append("DRY_RUN_REQUIRED")
    if getattr(status, "hardware_access_policy", None) is not HardwareAccessPolicy.DISABLED:
        reasons.append("HARDWARE_ACCESS_MUST_REMAIN_DISABLED")
    return reasons


def _robot_stop_reason(status: object) -> FollowStopReason | None:
    connection_state = getattr(status, "connection_state", None)
    if connection_state is RobotConnectionState.FAULTED:
        return FollowStopReason.ROBOT_FAULTED
    if not getattr(status, "connected", False):
        return FollowStopReason.ROBOT_DISCONNECTED
    if getattr(status, "stale", True):
        return FollowStopReason.ROBOT_STATE_STALE
    if getattr(status, "control_mode", None) is not ControlMode.DRY_RUN:
        return FollowStopReason.MOTION_REJECTED
    if getattr(status, "hardware_access_policy", None) is not HardwareAccessPolicy.DISABLED:
        return FollowStopReason.MOTION_REJECTED
    return None
