"""Backend-owned lease/deadman lifecycle for continuous jog."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

from momo.application.services.motion_service import MotionApplicationService
from momo.domain.enums import MotionCommandState, MotionCommandType
from momo.domain.errors import (
    JogLeaseExpiredError,
    JogSessionNotFoundError,
    MotionCommandNotFoundError,
    MotionConflictError,
)
from momo.domain.jog import JogLeaseResponse, JogStopResponse
from momo.domain.motion_command import CartesianJogPayload, MotionCommand
from momo.domain.real_hardware import RealHardwareAuthorizationPurpose
from momo.domain.real_motion import RealExecutionAuthorization
from momo.ports.clock import Clock


@dataclass(slots=True)
class _JogSession:
    session_id: UUID
    command_id: UUID
    idempotency_key: str
    expires_at: float
    last_state: MotionCommandState
    stopped: bool = False
    watchdog: asyncio.Task[None] | None = None


class JogLeaseService:
    def __init__(
        self,
        motion_service: MotionApplicationService,
        clock: Clock,
        *,
        lease_ttl_ms: int = 400,
        session_limit: int = 256,
    ) -> None:
        if not 250 <= lease_ttl_ms <= 500:
            raise ValueError("continuous jog lease TTL must be between 250 and 500 ms")
        self.motion_service = motion_service
        self.clock = clock
        self.lease_ttl_ms = int(lease_ttl_ms)
        self.session_limit = max(8, int(session_limit))
        self._sessions: dict[UUID, _JogSession] = {}
        self._by_command: dict[UUID, UUID] = {}
        self._by_idempotency_key: dict[str, UUID] = {}
        self._pending_reservations = 0
        self._guard = asyncio.Lock()

    async def start(
        self,
        command: MotionCommand,
        *,
        authorization: RealExecutionAuthorization | None = None,
        execution_purpose: RealHardwareAuthorizationPurpose | None = None,
    ) -> JogLeaseResponse:
        lease_controlled_cartesian = (
            command.command_type is MotionCommandType.CARTESIAN_JOG
            and isinstance(command.payload, CartesianJogPayload)
            and command.payload.lease_controlled
        )
        if (
            command.command_type is not MotionCommandType.CONTINUOUS_JOG
            and not lease_controlled_cartesian
        ):
            raise ValueError(
                "JogLeaseService requires a continuous joint or lease-controlled Cartesian jog"
            )
        reserved = False
        async with self._guard:
            self._prune_terminal_sessions()
            existing_by_key = self._by_idempotency_key.get(command.idempotency_key)
            if existing_by_key is None:
                if len(self._sessions) + self._pending_reservations >= self.session_limit:
                    raise MotionConflictError(
                        "Continuous jog session capacity is exhausted",
                        details={"session_limit": self.session_limit},
                    )
                self._pending_reservations += 1
                reserved = True
        accepted_command_id: UUID | None = None
        lease_secured = False
        try:
            if authorization is None and execution_purpose is None:
                accepted = await self.motion_service.submit(command)
            else:
                accepted = await self.motion_service.submit(
                    command,
                    authorization=authorization,
                    execution_purpose=execution_purpose,
                )
            accepted_command_id = accepted.command_id
            response = await self._register(command, accepted.command_id)
            lease_secured = True
            return response
        finally:
            cleanup_command_id = (
                accepted_command_id
                if accepted_command_id is not None
                else command.command_id
                if reserved
                else None
            )
            cleanup = asyncio.create_task(
                self._finish_start_attempt(
                    reserved=reserved,
                    cancel_command_id=(None if lease_secured else cleanup_command_id),
                )
            )
            await asyncio.shield(cleanup)

    async def _register(
        self,
        command: MotionCommand,
        command_id: UUID,
    ) -> JogLeaseResponse:
        """Install the lease after submit; kept separate for cancellation testing."""

        async with self._guard:
            existing_id = self._by_command.get(command_id)
            if existing_id is not None:
                return self._response(self._sessions[existing_id])
            accepted_status = self.motion_service.get_status(command_id)
            if accepted_status.state in _TERMINAL_STATES:
                raise MotionConflictError(
                    "Continuous jog command is already terminal",
                    details={"command_id": str(command_id)},
                )
            if len(self._sessions) >= self.session_limit:
                raise MotionConflictError(
                    "Continuous jog session capacity is exhausted",
                    details={"session_limit": self.session_limit},
                )
            session = _JogSession(
                session_id=uuid4(),
                command_id=command_id,
                idempotency_key=command.idempotency_key,
                expires_at=self.clock.monotonic() + self.lease_ttl_ms / 1000.0,
                last_state=accepted_status.state,
            )
            self._sessions[session.session_id] = session
            self._by_command[session.command_id] = session.session_id
            self._by_idempotency_key[session.idempotency_key] = session.session_id
            session.watchdog = asyncio.create_task(
                self._watchdog(session.session_id),
                name=f"jog-lease-{session.session_id}",
            )
            return self._response(session)

    async def _finish_start_attempt(
        self,
        *,
        reserved: bool,
        cancel_command_id: UUID | None,
    ) -> None:
        if reserved:
            async with self._guard:
                self._pending_reservations -= 1
        if cancel_command_id is not None:
            await self.motion_service.cancel_command(cancel_command_id)

    async def heartbeat(self, session_id: UUID) -> JogLeaseResponse:
        async with self._guard:
            session = self._sessions.get(session_id)
            if session is None:
                raise JogSessionNotFoundError(f"Unknown jog session: {session_id}")
            try:
                status = self.motion_service.get_status(session.command_id)
                session.last_state = status.state
            except MotionCommandNotFoundError:
                if session.last_state not in _TERMINAL_STATES:
                    self._evict_session(session_id, session)
                    raise JogSessionNotFoundError(
                        f"Jog command history expired: {session.command_id}"
                    ) from None
            if (
                session.stopped
                or session.last_state in _TERMINAL_STATES
                or self.clock.monotonic() >= session.expires_at
            ):
                session.stopped = True
                expired_command = session.command_id
            else:
                session.expires_at = self.clock.monotonic() + self.lease_ttl_ms / 1000.0
                return self._response(session)
        cancelled = await self.motion_service.cancel_command(expired_command)
        if cancelled is not None:
            async with self._guard:
                retained = self._sessions.get(session_id)
                if retained is not None:
                    retained.last_state = cancelled.state
        raise JogLeaseExpiredError("Continuous jog lease has expired")

    async def stop(self, session_id: UUID) -> JogStopResponse:
        async with self._guard:
            session = self._sessions.get(session_id)
            if session is None:
                raise JogSessionNotFoundError(f"Unknown jog session: {session_id}")
            already_stopped = session.stopped
            retained_state = session.last_state
            session.stopped = True
            watchdog = session.watchdog
            if watchdog is not None and watchdog is not asyncio.current_task():
                watchdog.cancel()
        status = await self.motion_service.cancel_command(session.command_id)
        if status is not None:
            state = status.state
            async with self._guard:
                retained = self._sessions.get(session_id)
                if retained is not None:
                    retained.last_state = state
        elif retained_state in _TERMINAL_STATES:
            state = retained_state
        else:
            async with self._guard:
                retained = self._sessions.get(session_id)
                if retained is not None:
                    self._evict_session(session_id, retained)
            raise JogSessionNotFoundError(f"Jog command history expired: {session.command_id}")
        return JogStopResponse(
            jog_session_id=session_id,
            stopped=not already_stopped or state in _TERMINAL_STATES,
            status=state,
        )

    async def stop_all(self) -> None:
        async with self._guard:
            session_ids = [
                session_id for session_id, session in self._sessions.items() if not session.stopped
            ]
        for session_id in session_ids:
            try:
                await self.stop(session_id)
            except JogSessionNotFoundError:
                # Executor history and retained lease history have independent
                # bounded lifetimes.  A stale lease must never abort Global Stop
                # or prevent later sessions from being cancelled.
                continue

    async def shutdown(self) -> None:
        await self.stop_all()

    async def _watchdog(self, session_id: UUID) -> None:
        try:
            while True:
                async with self._guard:
                    session = self._sessions.get(session_id)
                    if session is None or session.stopped:
                        return
                    remaining = session.expires_at - self.clock.monotonic()
                    if remaining <= 0:
                        session.stopped = True
                        command_id = session.command_id
                        break
                await self.clock.sleep(remaining)
            status = await self.motion_service.cancel_command(command_id)
            if status is not None:
                async with self._guard:
                    retained = self._sessions.get(session_id)
                    if retained is not None:
                        retained.last_state = status.state
        except asyncio.CancelledError:
            return

    def _response(self, session: _JogSession) -> JogLeaseResponse:
        remaining_ms = max(
            0,
            round((session.expires_at - self.clock.monotonic()) * 1000.0),
        )
        return JogLeaseResponse(
            jog_session_id=session.session_id,
            command_id=session.command_id,
            lease_expires_in_ms=remaining_ms,
            status=session.last_state,
        )

    def _prune_terminal_sessions(self) -> None:
        for session_id, session in list(self._sessions.items()):
            try:
                status = self.motion_service.get_status(session.command_id)
                session.last_state = status.state
            except MotionCommandNotFoundError:
                if session.last_state in _TERMINAL_STATES:
                    session.stopped = True
                    continue
                self._evict_session(session_id, session)
                continue
            if session.last_state not in _TERMINAL_STATES:
                continue
            session.stopped = True
            if session.watchdog is not None:
                session.watchdog.cancel()
        for session_id, session in list(self._sessions.items()):
            if not session.stopped:
                continue
            if len(self._sessions) + self._pending_reservations < self.session_limit:
                return
            self._evict_session(session_id, session)
            if len(self._sessions) + self._pending_reservations < self.session_limit:
                return

    def _evict_session(self, session_id: UUID, session: _JogSession) -> None:
        if session.watchdog is not None:
            session.watchdog.cancel()
        self._sessions.pop(session_id, None)
        self._by_command.pop(session.command_id, None)
        self._by_idempotency_key.pop(session.idempotency_key, None)


_TERMINAL_STATES = {
    MotionCommandState.CANCELLED,
    MotionCommandState.COMPLETED,
    MotionCommandState.FAULTED,
}
