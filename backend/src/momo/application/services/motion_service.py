"""Submission, idempotency, status, and high-priority Stop orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from momo.application.services.motion_safety_gateway import MotionSafetyGateway
from momo.application.services.robot_service import RobotApplicationService
from momo.domain.errors import (
    IdempotencyConflictError,
    MotionCommandNotFoundError,
    MotionConflictError,
)
from momo.domain.motion_command import MotionCommand
from momo.domain.motion_preflight import (
    MotionAccepted,
    MotionCommandStatus,
    PreparedContinuousJog,
)
from momo.domain.runtime import RobotStatus, StopResponse
from momo.ports.motion_executor import MotionExecutor


@dataclass(frozen=True, slots=True)
class _IdempotencyRecord:
    command_id: UUID
    digest: str


class MotionApplicationService:
    def __init__(
        self,
        robot_service: RobotApplicationService,
        gateway: MotionSafetyGateway,
        executor: MotionExecutor,
        *,
        idempotency_limit: int = 512,
    ) -> None:
        self.robot_service = robot_service
        self.gateway = gateway
        self.executor = executor
        self._dispatch_lock = asyncio.Lock()
        self._idempotency_limit = max(16, int(idempotency_limit))
        self._idempotency: OrderedDict[str, _IdempotencyRecord] = OrderedDict()
        self._stop_hooks: list[Callable[[], Awaitable[None]]] = []
        self._last_stop_hook_errors: tuple[str, ...] = ()
        self._lifecycle_epoch = 0
        self._lifecycle_count = 0

    def register_stop_hook(self, hook: Callable[[], Awaitable[None]]) -> None:
        self._stop_hooks.append(hook)

    async def submit(self, command: MotionCommand) -> MotionAccepted:
        submission_epoch = self._lifecycle_epoch
        digest = self._command_digest(command)
        async with self._dispatch_lock:
            self._ensure_dispatch_allowed(submission_epoch)
            existing = self._idempotent_result(command.idempotency_key, digest)
            if existing is not None:
                return existing

        # FK/IK and sampled-path validation can be expensive. It must never hold
        # the short dispatch lock that gives lifecycle Stop priority.
        prepared = await self.gateway.prepare(command)

        async with self._dispatch_lock:
            self._ensure_dispatch_allowed(submission_epoch)
            existing = self._idempotent_result(command.idempotency_key, digest)
            if existing is not None:
                return existing
            status_snapshot, profile, _ = await self.robot_service.get_motion_snapshot()
            self._ensure_dispatch_allowed(submission_epoch)
            current_kinematics_fingerprint = self.gateway.kinematics_service.model_for(
                profile
            ).fingerprint
            if (
                not status_snapshot.connected
                or status_snapshot.stale
                or status_snapshot.robot_id != command.robot_id
                or status_snapshot.state_sequence != command.expected_state_sequence
                or profile.fingerprint != command.expected_profile_fingerprint
                or current_kinematics_fingerprint != command.expected_kinematics_fingerprint
                or self.executor.active_command_id is not None
            ):
                raise MotionConflictError(
                    "Prepared motion became stale before dispatch",
                    details={"reason": "PREPARED_STATE_CHANGED"},
                )
            if isinstance(prepared, PreparedContinuousJog):
                status = await self.executor.submit_continuous_jog(prepared)
            else:
                status = await self.executor.submit(prepared)
            self._idempotency[command.idempotency_key] = _IdempotencyRecord(
                command_id=command.command_id,
                digest=digest,
            )
            self._idempotency.move_to_end(command.idempotency_key)
            while len(self._idempotency) > self._idempotency_limit:
                self._idempotency.popitem(last=False)
            return MotionAccepted(
                command_id=status.command_id,
                status=status.state,
                preflight=status.preflight,
            )

    def _idempotent_result(self, key: str, digest: str) -> MotionAccepted | None:
        prior = self._idempotency.get(key)
        if prior is None:
            return None
        if prior.digest != digest:
            raise IdempotencyConflictError(
                "Idempotency key was already used for different motion intent"
            )
        status = self.executor.get_status(prior.command_id)
        if status is None:
            raise MotionCommandNotFoundError("Idempotent command history expired")
        return MotionAccepted(
            command_id=status.command_id,
            status=status.state,
            preflight=status.preflight,
        )

    def _ensure_dispatch_allowed(self, submission_epoch: int) -> None:
        if self._lifecycle_count or submission_epoch != self._lifecycle_epoch:
            raise MotionConflictError(
                "Motion intent was superseded by a lifecycle Stop",
                details={"reason": "LIFECYCLE_EPOCH_CHANGED"},
            )

    def _begin_lifecycle(self) -> None:
        self._lifecycle_count += 1
        self._lifecycle_epoch += 1

    def _end_lifecycle(self) -> None:
        self._lifecycle_epoch += 1
        self._lifecycle_count -= 1

    def get_status(self, command_id: UUID) -> MotionCommandStatus:
        status = self.executor.get_status(command_id)
        if status is None:
            raise MotionCommandNotFoundError(f"Unknown motion command: {command_id}")
        return status

    def active_status(self) -> MotionCommandStatus | None:
        return self.executor.active_status()

    def latest_status(self) -> MotionCommandStatus | None:
        return self.executor.latest_status()

    async def cancel_active(self) -> MotionCommandStatus | None:
        return await self.executor.cancel_active()

    async def cancel_command(self, command_id: UUID) -> MotionCommandStatus | None:
        """Cancel one prepared command without exposing the executor to callers."""

        return await self.executor.cancel(command_id)

    async def stop(self) -> StopResponse:
        self._begin_lifecycle()
        try:
            async with self._dispatch_lock:
                await self._cancel_for_lifecycle_unlocked()
                return await self.robot_service.stop()
        finally:
            self._end_lifecycle()

    async def disconnect(self) -> RobotStatus:
        self._begin_lifecycle()
        try:
            async with self._dispatch_lock:
                await self._cancel_for_lifecycle_unlocked()
                return await self.robot_service.disconnect()
        finally:
            self._end_lifecycle()

    async def cancel_for_lifecycle(self) -> MotionCommandStatus | None:
        self._begin_lifecycle()
        try:
            async with self._dispatch_lock:
                return await self._cancel_for_lifecycle_unlocked()
        finally:
            self._end_lifecycle()

    async def _cancel_for_lifecycle_unlocked(self) -> MotionCommandStatus | None:
        # Cancel the executor first so no stale lease bookkeeping failure can
        # delay or prevent the highest-priority motion cancellation path.
        cancelled = await self.executor.cancel_active()
        hook_errors: list[str] = []
        for hook in self._stop_hooks:
            try:
                await hook()
            except Exception as error:
                hook_errors.append(type(error).__name__)
        self._last_stop_hook_errors = tuple(hook_errors)
        return cancelled

    async def shutdown(self) -> None:
        self._begin_lifecycle()
        try:
            async with self._dispatch_lock:
                await self._cancel_for_lifecycle_unlocked()
                await self.executor.shutdown()
                await self.robot_service.drain_runtime_persistence()
        finally:
            self._end_lifecycle()

    @staticmethod
    def _command_digest(command: MotionCommand) -> str:
        payload = command.model_dump(
            mode="json",
            exclude={"command_id", "issued_at"},
        )
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()
