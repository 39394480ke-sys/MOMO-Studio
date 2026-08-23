"""Compile/cache/preview/playback orchestration for stored Motion entities."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.library_service import LibraryApplicationService
from momo.application.services.motion_safety_gateway import (
    MotionAdmissionCoordinator,
    MotionSafetyGateway,
)
from momo.application.services.playback_service import PlaybackService
from momo.application.services.robot_service import RobotApplicationService
from momo.application.services.trajectory_compiler import TrajectoryCompiler
from momo.domain.enums import MotionCommandSource, RealReadiness
from momo.domain.errors import (
    EntityNotFoundError,
    MotionConflictError,
    MotionPreflightError,
    PreparedTrajectoryNotFoundError,
    RevisionConflictError,
)
from momo.domain.motion import Motion
from momo.domain.playback import (
    MAX_PLAYBACK_LOOPS,
    PlaybackExecutionSnapshot,
    PlaybackOperatorIntent,
    PlaybackState,
    PlaybackStatus,
)
from momo.domain.trajectory import (
    PreparedTrajectory,
    TrajectoryCompileOutcome,
)
from momo.ports.playback import PreparedTrajectoryView

PREPARED_TRAJECTORY_CACHE_LIMIT = 16
PREVIEW_POINT_LIMIT = 1000
_PLAYBACK_ACTIVE_STATES = frozenset(
    {
        PlaybackState.PREFLIGHTING,
        PlaybackState.PLAYING,
        PlaybackState.PAUSED,
        PlaybackState.STOPPING,
    }
)


@dataclass(frozen=True, slots=True)
class PreparedTrajectoryPreview:
    """Bounded read model source; the API owns its transport-only formatting."""

    prepared: PreparedTrajectory
    motion: Motion
    sample_indices: tuple[int, ...]


class PlaybackSafetyValidator:
    """Resolve fresh repository/runtime evidence through the one safety gateway."""

    def __init__(
        self,
        library: LibraryApplicationService,
        gateway: MotionSafetyGateway,
    ) -> None:
        self.library = library
        self.gateway = gateway

    @asynccontextmanager
    async def validate_playback_execution(
        self,
        prepared: PreparedTrajectoryView,
        intent: PlaybackOperatorIntent,
    ) -> AsyncIterator[PlaybackExecutionSnapshot]:
        if not isinstance(prepared, PreparedTrajectory):
            raise TypeError("Playback composition requires a PreparedTrajectory")
        try:
            async with self.library.motion_revision_lease(
                prepared.plan.motion_id,
                prepared.plan.motion_revision,
            ) as motion:
                yield await self.gateway.validate_prepared_trajectory(
                    prepared,
                    intent,
                    motion_revision=motion.revision,
                )
        except (RevisionConflictError, EntityNotFoundError) as error:
            raise MotionPreflightError(
                "Motion changed after trajectory preflight",
                details={"reason": "MOTION_REVISION_CHANGED"},
            ) from error


class TrajectoryApplicationService:
    """Own a bounded prepared-plan cache; routes never accept executable samples."""

    def __init__(
        self,
        library: LibraryApplicationService,
        robot: RobotApplicationService,
        kinematics: KinematicsService,
        compiler: TrajectoryCompiler,
        playback: PlaybackService,
        motion_admission: MotionAdmissionCoordinator,
        *,
        cache_limit: int = PREPARED_TRAJECTORY_CACHE_LIMIT,
    ) -> None:
        self.library = library
        self.robot = robot
        self.kinematics = kinematics
        self.compiler = compiler
        self.playback = playback
        self.motion_admission = motion_admission
        self.cache_limit = max(1, min(PREPARED_TRAJECTORY_CACHE_LIMIT, int(cache_limit)))
        self._prepared: OrderedDict[str, tuple[PreparedTrajectory, Motion]] = OrderedDict()
        self._preflight_lock = asyncio.Lock()
        self._preflight_generation = 0
        self._preflight_cancel: asyncio.Event | None = None

    async def preflight(
        self,
        motion_id: UUID,
        *,
        expected_revision: int,
        sample_rate_hz: float,
    ) -> TrajectoryCompileOutcome:
        lifecycle_epoch = self.motion_admission.capture_lifecycle_epoch()
        # Claim before waiting for the owner lock.  A newer request cancels the
        # current owner immediately but cannot begin its expensive compile until
        # that owner has observed cancellation and released the lock.
        self._preflight_generation += 1
        generation = self._preflight_generation
        active_cancellation = self._preflight_cancel
        if active_cancellation is not None:
            active_cancellation.set()
        async with self._preflight_lock:
            self.motion_admission.require_lifecycle_epoch(lifecycle_epoch)
            self._require_preflight_generation(generation)
            return await self._preflight_owned(
                motion_id,
                expected_revision=expected_revision,
                sample_rate_hz=sample_rate_hz,
                generation=generation,
                lifecycle_epoch=lifecycle_epoch,
            )

    async def _preflight_owned(
        self,
        motion_id: UUID,
        *,
        expected_revision: int,
        sample_rate_hz: float,
        generation: int,
        lifecycle_epoch: int,
    ) -> TrajectoryCompileOutcome:
        self.motion_admission.require_lifecycle_epoch(lifecycle_epoch)
        self._reject_if_playing()
        motion = await self.library.get_motion(motion_id)
        self.motion_admission.require_lifecycle_epoch(lifecycle_epoch)
        self._require_preflight_generation(generation)
        self._require_revision(motion, expected_revision)
        self._discard_motion(motion_id)
        cancellation = asyncio.Event()
        self._preflight_cancel = cancellation

        try:
            # begin_preflight already clears any older READY value atomically.
            # Keeping this as the first playback transition avoids an observable
            # IDLE gap in which lifecycle Stop could miss the pending owner.
            async with self.motion_admission.admit():
                self.motion_admission.require_lifecycle_epoch(lifecycle_epoch)
                self._require_preflight_generation(generation)
                if not self.motion_admission.motion_slot_is_free():
                    raise MotionConflictError(
                        "Another motion owns the shared motion slot",
                        details={"reason": "MOTION_SLOT_OCCUPIED"},
                    )
                await self.playback.begin_preflight(motion_id, expected_revision)
                try:
                    self._require_preflight_generation(generation)
                    await self._require_lifecycle_after_claim(lifecycle_epoch)
                except MotionConflictError:
                    await self.playback.stop()
                    raise
            self._require_preflight_generation(generation)
            await self._require_lifecycle_after_claim(lifecycle_epoch)
            status, profile, start_state = await self.robot.get_motion_snapshot()
            await self._require_lifecycle_after_claim(lifecycle_epoch)
            model = self.kinematics.model_for(profile)
            calibration = self.robot.calibration_service.get_for_variant(profile.variant)
            outcome = await self.compiler.compile(
                motion=motion,
                profile=profile,
                start_state=start_state,
                start_state_sequence=status.state_sequence,
                expected_motion_revision=expected_revision,
                expected_robot_variant=status.variant,
                expected_profile_fingerprint=status.profile_fingerprint,
                expected_kinematics_fingerprint=model.fingerprint,
                expected_state_sequence=status.state_sequence,
                connected=status.connected,
                state_fresh=not status.stale,
                hardware_access_policy=status.hardware_access_policy,
                sample_rate_hz=sample_rate_hz,
                calibration=calibration,
                control_mode=status.control_mode,
                stop_capable=True,
                source=MotionCommandSource.LIBRARY,
                real_readiness=RealReadiness.BLOCKED_BY_STAGE_POLICY,
                field_acceptance_complete=False,
                cancellation_requested=cancellation.is_set,
            )
        except asyncio.CancelledError:
            cancellation.set()
            await self._fail_preflight_if_owned("Trajectory preflight cancelled")
            raise
        except Exception:
            await self._fail_preflight_if_owned("Trajectory preflight failed")
            raise
        finally:
            if self._preflight_cancel is cancellation:
                self._preflight_cancel = None
        if generation != self._preflight_generation or cancellation.is_set():
            await self._fail_preflight_if_owned("Trajectory preflight cancelled")
            raise MotionConflictError(
                "Trajectory preflight was cancelled by a lifecycle Stop",
                details={"reason": "TRAJECTORY_COMPILATION_CANCELLED"},
            )
        await self._require_lifecycle_after_claim(lifecycle_epoch)
        if outcome.prepared is not None:
            digest = outcome.prepared.plan.digest.sha256
            await self.playback.set_ready(outcome.prepared)
            if (
                generation != self._preflight_generation
                or cancellation.is_set()
                or self.motion_admission.lifecycle_count
                or lifecycle_epoch != self.motion_admission.lifecycle_epoch
            ):
                await self.playback.stop()
                raise MotionConflictError(
                    "Trajectory preflight was cancelled before publication",
                    details={"reason": "TRAJECTORY_COMPILATION_CANCELLED"},
                )
            self._prepared[digest] = (outcome.prepared, motion)
            self._prepared.move_to_end(digest)
            while len(self._prepared) > self.cache_limit:
                self._prepared.popitem(last=False)
        else:
            reason = (
                outcome.report.violations[0].message
                if outcome.report.violations
                else "Trajectory preflight rejected"
            )
            await self.playback.preflight_failed(reason)
        return outcome

    def _require_preflight_generation(self, generation: int) -> None:
        if generation != self._preflight_generation:
            raise MotionConflictError(
                "Trajectory preflight was superseded or cancelled",
                details={"reason": "TRAJECTORY_PREFLIGHT_SUPERSEDED"},
            )

    async def cancel_for_lifecycle(self) -> None:
        """Cancel compilation or execution before the robot lifecycle Stop proceeds."""

        self._preflight_generation += 1
        cancellation = self._preflight_cancel
        if cancellation is not None:
            cancellation.set()
        # PlaybackService.stop resolves PREFLIGHTING vs READY while holding its
        # own guard.  A status read followed by cancel_preflight would race a
        # concurrent set_ready transition and could leave a late READY plan.
        await self.playback.stop()

    async def shutdown(self) -> None:
        await self.cancel_for_lifecycle()

    async def play(
        self,
        motion_id: UUID,
        *,
        expected_revision: int,
        trajectory_digest: str,
        loop: bool,
        rate: float,
    ) -> PlaybackStatus:
        lifecycle_epoch = self.motion_admission.capture_lifecycle_epoch()
        prepared, _ = self._prepared_for(trajectory_digest)
        generation = self._preflight_generation
        if prepared.plan.motion_id != motion_id:
            raise PreparedTrajectoryNotFoundError(
                "Prepared trajectory does not belong to this Motion"
            )
        motion = await self.library.get_motion(motion_id)
        self.motion_admission.require_lifecycle_epoch(lifecycle_epoch)
        self._require_play_binding(trajectory_digest, prepared, generation)
        self._require_revision(motion, expected_revision)
        intent = PlaybackOperatorIntent(
            motion_id=motion_id,
            motion_revision=expected_revision,
            trajectory_digest=trajectory_digest,
            confirmed=True,
        )
        async with self.motion_admission.admit():
            self.motion_admission.require_lifecycle_epoch(lifecycle_epoch)
            # Lock acquisition is itself an await: re-resolve both cache identity
            # and generation before claiming the reciprocal motion owner.
            self._require_play_binding(trajectory_digest, prepared, generation)
            if not self.motion_admission.motion_slot_is_free():
                raise MotionConflictError(
                    "Another motion owns the shared motion slot",
                    details={"reason": "MOTION_SLOT_OCCUPIED"},
                )
            status = await self.playback.play(
                prepared,
                intent,
                rate=rate,
                loop=loop,
                loop_count=MAX_PLAYBACK_LOOPS if loop else 1,
            )
            try:
                # PlaybackService.play can await its own guard.  A concurrent
                # preflight/Stop may invalidate the cache while that happens.
                self._require_play_binding(trajectory_digest, prepared, generation)
                self.motion_admission.require_lifecycle_epoch(lifecycle_epoch)
            except PreparedTrajectoryNotFoundError:
                await self.playback.stop()
                raise
            except MotionConflictError:
                await self.playback.stop()
                raise
            return status

    async def pause(self) -> PlaybackStatus:
        return await self.playback.pause()

    async def resume(self) -> PlaybackStatus:
        return await self.playback.resume()

    async def stop(self) -> PlaybackStatus:
        await self.cancel_for_lifecycle()
        return self.playback.get_status()

    async def set_rate(self, rate: float) -> PlaybackStatus:
        return await self.playback.set_rate(rate)

    async def set_loop(self, enabled: bool) -> PlaybackStatus:
        return await self.playback.set_loop(
            enabled,
            loop_count=MAX_PLAYBACK_LOOPS if enabled else 1,
        )

    def get_status(self) -> PlaybackStatus:
        return self.playback.get_status()

    def preview(self, digest: str) -> PreparedTrajectoryPreview:
        prepared, motion = self._prepared_for(digest)
        return PreparedTrajectoryPreview(
            prepared=prepared,
            motion=motion,
            sample_indices=self._preview_indices(len(prepared.plan.samples)),
        )

    def _prepared_for(self, digest: str) -> tuple[PreparedTrajectory, Motion]:
        value = self._prepared.get(digest)
        if value is None:
            raise PreparedTrajectoryNotFoundError(
                "Prepared trajectory is unavailable; run preflight again"
            )
        self._prepared.move_to_end(digest)
        return value

    def _require_play_binding(
        self,
        digest: str,
        prepared: PreparedTrajectory,
        generation: int,
    ) -> None:
        current = self._prepared.get(digest)
        if (
            generation != self._preflight_generation
            or current is None
            or current[0] is not prepared
        ):
            raise PreparedTrajectoryNotFoundError(
                "Prepared trajectory changed while Play was being admitted; run preflight again"
            )

    def _discard_motion(self, motion_id: UUID) -> None:
        for digest, (prepared, _) in tuple(self._prepared.items()):
            if prepared.plan.motion_id == motion_id:
                del self._prepared[digest]

    def _reject_if_playing(self) -> None:
        status = self.playback.get_status()
        if status.state in _PLAYBACK_ACTIVE_STATES:
            raise MotionConflictError(
                "Cannot preflight while playback owns the motion slot",
                details={"state": status.state.value},
            )

    async def _fail_preflight_if_owned(self, reason: str) -> None:
        status = self.playback.get_status()
        if status.state is PlaybackState.PREFLIGHTING and status.session_id is None:
            await self.playback.preflight_failed(reason)

    async def _require_lifecycle_after_claim(self, lifecycle_epoch: int) -> None:
        """Cancel claimed preflight state before propagating a lifecycle fence."""

        try:
            self.motion_admission.require_lifecycle_epoch(lifecycle_epoch)
        except MotionConflictError:
            await self.playback.stop()
            raise

    @staticmethod
    def _require_revision(motion: Motion, expected_revision: int) -> None:
        if motion.revision != expected_revision:
            raise RevisionConflictError(
                "Motion revision changed",
                details={
                    "expected_revision": expected_revision,
                    "actual_revision": motion.revision,
                },
            )

    @staticmethod
    def _preview_indices(sample_count: int) -> tuple[int, ...]:
        if sample_count <= PREVIEW_POINT_LIMIT:
            return tuple(range(sample_count))
        last = sample_count - 1
        return tuple(
            sorted(
                {
                    round(index * last / (PREVIEW_POINT_LIMIT - 1))
                    for index in range(PREVIEW_POINT_LIMIT)
                }
            )
        )
