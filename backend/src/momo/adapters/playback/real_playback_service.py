"""REAL playback controller over the exact prepared-trajectory executor."""

from __future__ import annotations

import asyncio
from collections import deque
from uuid import UUID

from momo.adapters.hardware.real_robot_driver import AuthorizedServoBusBinding
from momo.adapters.motion.real_motion_executor import RealMotionExecutor
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.library_service import LibraryApplicationService
from momo.application.services.robot_service import RobotApplicationService
from momo.domain.errors import MotionConflictError, MotionPreflightError
from momo.domain.playback import (
    PlaybackEvent,
    PlaybackEventKind,
    PlaybackOperatorIntent,
    PlaybackState,
    PlaybackStatus,
)
from momo.domain.real_hardware import (
    RealHardwareAuthorizationPurpose,
    calibration_fingerprint,
)
from momo.domain.real_motion import (
    RealExecutionAuthorization,
    RealExecutionContext,
    RealMotionAuditEvent,
    RealMotionState,
    RealMotionStatus,
)
from momo.domain.robot import JointState
from momo.domain.trajectory import PreparedTrajectory
from momo.ports.clock import Clock
from momo.ports.playback import (
    PlaybackExecutionValidator,
    PlaybackObserver,
    PreparedTrajectoryView,
)

_ACTIVE = frozenset(
    {
        PlaybackState.PREFLIGHTING,
        PlaybackState.PLAYING,
        PlaybackState.STOPPING,
    }
)


class _PlaybackContext:
    def __init__(
        self,
        robot: RobotApplicationService,
        library: LibraryApplicationService,
        prepared: PreparedTrajectory,
        calibration_fingerprint_value: str,
        binding: AuthorizedServoBusBinding,
    ) -> None:
        self.robot = robot
        self.library = library
        self.prepared = prepared
        self.calibration_fingerprint = calibration_fingerprint_value
        self.binding = binding

    async def current_real_execution_context(self) -> RealExecutionContext:
        status, profile, state = await self.robot.get_motion_snapshot()
        plan = self.prepared.plan
        motion = await self.library.get_motion(plan.motion_id)
        return RealExecutionContext(
            robot_id=status.robot_id,
            variant=status.variant,
            connected=status.connected and self.binding.connected,
            state_fresh=not status.stale,
            stop_capable=self.binding.connected,
            state_sequence=status.state_sequence,
            joint_state=state,
            motion_id=motion.id,
            motion_revision=motion.revision,
            trajectory_digest=plan.digest.sha256,
            profile_fingerprint=profile.fingerprint,
            calibration_fingerprint=self.calibration_fingerprint,
            kinematics_fingerprint=plan.kinematics_fingerprint,
            observed_at=status.updated_at,
        )


class RealPlaybackService:
    """One non-looping immutable REAL playback session with priority Stop."""

    def __init__(
        self,
        clock: Clock,
        robot: RobotApplicationService,
        library: LibraryApplicationService,
        kinematics: KinematicsService,
        validator: PlaybackExecutionValidator,
        observer: PlaybackObserver,
        binding: AuthorizedServoBusBinding,
    ) -> None:
        self.clock = clock
        self.robot = robot
        self.library = library
        self.kinematics = kinematics
        self.validator = validator
        self.observer = observer
        self.binding = binding
        self._status = PlaybackStatus(updated_at=clock.now())
        self._ready: PreparedTrajectory | None = None
        self._inner: RealMotionExecutor | None = None
        self._task: asyncio.Task[None] | None = None
        self._guard = asyncio.Lock()
        self._event_sequence = 0
        self._audit: deque[RealMotionAuditEvent] = deque(maxlen=512)

    @property
    def motion_active(self) -> bool:
        return self._status.state in _ACTIVE

    def get_status(self) -> PlaybackStatus:
        inner = self._inner
        if inner is not None:
            status = inner.latest_status()
            if status is not None and self._status.state in _ACTIVE:
                self._status = self._mapped_status(status)
        return self._status

    async def begin_preflight(self, motion_id: UUID, motion_revision: int) -> PlaybackStatus:
        async with self._guard:
            self._require_idle()
            self._ready = None
            self._status = PlaybackStatus(
                state=PlaybackState.PREFLIGHTING,
                motion_id=motion_id,
                motion_revision=motion_revision,
                updated_at=self.clock.now(),
            )
            self._publish(PlaybackEventKind.STATE)
            return self._status

    async def preflight_failed(self, reason: str = "") -> PlaybackStatus:
        async with self._guard:
            now = self.clock.now()
            self._ready = None
            self._status = self._status.model_copy(
                update={
                    "state": PlaybackState.FAULTED,
                    "error": (reason.strip()[:240] or "Trajectory preflight rejected"),
                    "updated_at": now,
                    "finished_at": now,
                }
            )
            self._publish(PlaybackEventKind.STATE)
            return self._status

    async def clear_ready(self) -> PlaybackStatus:
        async with self._guard:
            self._require_idle()
            self._ready = None
            self._status = PlaybackStatus(updated_at=self.clock.now())
            self._publish(PlaybackEventKind.STATE)
            return self._status

    async def set_ready(self, prepared: PreparedTrajectoryView) -> PlaybackStatus:
        if not isinstance(prepared, PreparedTrajectory):
            raise TypeError("REAL playback requires a PreparedTrajectory")
        async with self._guard:
            if self._task is not None and not self._task.done():
                raise MotionConflictError("REAL playback is already active")
            self._ready = prepared
            self._status = PlaybackStatus(
                state=PlaybackState.READY,
                motion_id=prepared.plan.motion_id,
                motion_revision=prepared.plan.motion_revision,
                trajectory_digest=prepared.plan.digest.sha256,
                duration_s=prepared.plan.duration_s,
                updated_at=self.clock.now(),
            )
            self._publish(PlaybackEventKind.STATE)
            return self._status

    async def play(
        self,
        prepared: PreparedTrajectoryView,
        intent: PlaybackOperatorIntent,
        *,
        rate: float = 1.0,
        loop: bool = False,
        loop_count: int = 2,
        authorization: RealExecutionAuthorization | None = None,
    ) -> PlaybackStatus:
        del loop_count
        if not isinstance(prepared, PreparedTrajectory):
            raise TypeError("REAL playback requires a PreparedTrajectory")
        if authorization is None:
            raise PermissionError("REAL playback requires an execution authorization")
        if authorization.purpose is not RealHardwareAuthorizationPurpose.REAL_PLAYBACK:
            raise PermissionError("REAL playback authorization purpose does not match")
        if rate != 1.0 or loop:
            raise MotionPreflightError(
                "REAL playback currently requires rate 1.0 and loop disabled",
                details={"reason": "REAL_PLAYBACK_CONTROLS_UNSUPPORTED"},
            )
        async with self._guard:
            self._require_idle()
            if self._ready is not prepared:
                raise MotionConflictError("REAL playback must use the exact READY plan")
            now = self.clock.now()
            self._status = PlaybackStatus(
                state=PlaybackState.PREFLIGHTING,
                motion_id=prepared.plan.motion_id,
                motion_revision=prepared.plan.motion_revision,
                trajectory_digest=prepared.plan.digest.sha256,
                duration_s=prepared.plan.duration_s,
                operator_intent_id=intent.intent_id,
                updated_at=now,
            )
            self._publish(PlaybackEventKind.STATE)
            self._task = asyncio.create_task(
                self._run(prepared, intent, authorization),
                name=f"real-playback-{intent.intent_id}",
            )
            return self._status

    async def _run(
        self,
        prepared: PreparedTrajectory,
        intent: PlaybackOperatorIntent,
        authorization: RealExecutionAuthorization,
    ) -> None:
        try:
            async with self.validator.validate_playback_execution(prepared, intent) as evidence:
                if (
                    evidence.control_mode.value != "REAL"
                    or evidence.hardware_access_policy.value != "FULL"
                    or not evidence.connected
                    or evidence.stale
                    or not evidence.stop_capable
                ):
                    raise MotionPreflightError(
                        "REAL playback safety context changed",
                        details={"reason": "UNSAFE_EXECUTION_CONTEXT"},
                    )
                status, profile, _ = await self.robot.get_motion_snapshot()
                calibration = self.robot.calibration_service.get_for_variant(profile.variant)
                if calibration is None:
                    raise MotionPreflightError("REAL playback Calibration is unavailable")
                fingerprint = calibration_fingerprint(calibration)
                context = _PlaybackContext(
                    self.robot,
                    self.library,
                    prepared,
                    fingerprint,
                    self.binding,
                )
                inner = RealMotionExecutor(
                    self.binding.require_bus(),
                    self.clock,
                    robot_id=status.robot_id,
                    profile=profile,
                    calibration=calibration,
                    kinematics_fingerprint=self.kinematics.model_for(profile).fingerprint,
                    context_provider=context,
                    observer=self,
                    divergence_tolerance_raw=32,
                )
                self._inner = inner
                accepted = await inner.submit(
                    prepared,
                    expected_digest=prepared.plan.digest.sha256,
                    authorization=authorization,
                    execution_purpose=RealHardwareAuthorizationPurpose.REAL_PLAYBACK,
                )
                self._status = self._mapped_status(accepted)
                self._publish(PlaybackEventKind.STATE)
                terminal = await inner.wait(accepted.execution_id)
                self._status = self._mapped_status(terminal)
                self._publish(PlaybackEventKind.STATE)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            now = self.clock.now()
            latest_inner_status = self._inner.latest_status() if self._inner is not None else None
            self._status = self._status.model_copy(
                update={
                    "state": PlaybackState.FAULTED,
                    "error": type(error).__name__[:240],
                    "hardware_accessed": bool(
                        latest_inner_status is not None and latest_inner_status.hardware_accessed
                    ),
                    "updated_at": now,
                    "finished_at": now,
                }
            )
            self._publish(PlaybackEventKind.STATE)

    async def pause(self) -> PlaybackStatus:
        raise MotionConflictError("Pause is unavailable during REAL playback")

    async def resume(self) -> PlaybackStatus:
        raise MotionConflictError("Resume is unavailable during REAL playback")

    async def set_rate(self, rate: float) -> PlaybackStatus:
        if rate != 1.0:
            raise MotionConflictError("REAL playback rate is fixed at 1.0")
        return self._status

    async def set_loop(self, enabled: bool, *, loop_count: int = 2) -> PlaybackStatus:
        del loop_count
        if enabled:
            raise MotionConflictError("Loop is unavailable during REAL playback")
        return self._status

    async def stop(self) -> PlaybackStatus:
        inner = self._inner
        if inner is None:
            if self._status.state in {PlaybackState.PREFLIGHTING, PlaybackState.READY}:
                now = self.clock.now()
                self._ready = None
                self._status = self._status.model_copy(
                    update={
                        "state": PlaybackState.STOPPED,
                        "updated_at": now,
                        "finished_at": now,
                    }
                )
            return self._status
        self._status = self._status.model_copy(
            update={"state": PlaybackState.STOPPING, "updated_at": self.clock.now()}
        )
        self._publish(PlaybackEventKind.STATE)
        terminal = await inner.cancel_active()
        if terminal is not None:
            self._status = self._mapped_status(terminal)
        task = self._task
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        self._publish(PlaybackEventKind.STATE)
        return self._status

    async def shutdown(self) -> None:
        await self.stop()
        if self._inner is not None:
            await self._inner.shutdown()

    async def apply_real_readback(self, execution_id: UUID, state: JointState) -> int:
        return await self.robot.apply_real_readback(execution_id, state)

    async def record_real_motion_audit(self, event: RealMotionAuditEvent) -> None:
        self._audit.append(event)

    def audit_events(self) -> tuple[RealMotionAuditEvent, ...]:
        return tuple(self._audit)

    def _mapped_status(self, status: RealMotionStatus) -> PlaybackStatus:
        prepared = self._ready
        if prepared is None:
            raise RuntimeError("REAL playback plan history is unavailable")
        state = {
            RealMotionState.ACCEPTED: PlaybackState.PREFLIGHTING,
            RealMotionState.RUNNING: PlaybackState.PLAYING,
            RealMotionState.COMPLETED: PlaybackState.COMPLETED,
            RealMotionState.CANCELLED: PlaybackState.STOPPED,
            RealMotionState.FAULTED: PlaybackState.FAULTED,
        }[status.state]
        sample = (
            prepared.plan.samples[status.sample_index] if status.sample_index is not None else None
        )
        return PlaybackStatus(
            session_id=status.execution_id,
            state=state,
            motion_id=prepared.plan.motion_id,
            motion_revision=prepared.plan.motion_revision,
            trajectory_digest=prepared.plan.digest.sha256,
            progress=status.progress,
            elapsed_s=prepared.plan.duration_s * status.progress,
            duration_s=prepared.plan.duration_s,
            current_keyframe_id=(sample.keyframe_id if sample is not None else None),
            current_segment_index=(sample.segment_index if sample is not None else None),
            current_sample_index=status.sample_index,
            loop=False,
            loop_count=1,
            completed_loops=1 if state is PlaybackState.COMPLETED else 0,
            rate=1.0,
            error=(status.fault_code.value if status.fault_code is not None else None),
            operator_intent_id=self._status.operator_intent_id,
            started_at=status.started_at,
            updated_at=status.updated_at,
            finished_at=status.finished_at,
            hardware_accessed=status.hardware_accessed,
        )

    def _require_idle(self) -> None:
        if self._task is not None and not self._task.done():
            raise MotionConflictError("REAL playback is already active")

    def _publish(self, kind: PlaybackEventKind) -> None:
        self._event_sequence += 1
        self.observer.publish_playback_event(
            PlaybackEvent(
                sequence=self._event_sequence,
                kind=kind,
                status=self._status,
                emitted_at=self.clock.now(),
            )
        )


__all__ = ["RealPlaybackService"]
