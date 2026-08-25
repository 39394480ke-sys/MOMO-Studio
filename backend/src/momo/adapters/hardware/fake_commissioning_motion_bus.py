"""Fail-closed in-memory adapter for commissioning-motion service tests only."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import timedelta
from math import isfinite
from typing import Literal
from uuid import UUID

from momo.domain.commissioning import PreparedCommissioningTestCommand
from momo.domain.real_hardware import (
    RealStopOutcome,
    RealStopResult,
    ServoWriteResult,
)
from momo.ports.clock import Clock
from momo.ports.servo_bus import CommissioningPositionReadback


class FakeCommissioningMotionBus:
    """One-servo fake with explicit fault injection and no physical claims.

    The adapter represents an already acquired bus.  It starts active for reads,
    but writes are disabled unless the test fixture opts in explicitly.  Delayed
    writes await the injected clock without shielding cancellation.  Stop or
    close advances a generation fence, so an older delayed write can never apply
    a target after either operation returns.
    """

    adapter_id = "fake-commissioning-motion-bus"
    is_physical_adapter: Literal[False] = False
    physical_stop_verified: Literal[False] = False

    def __init__(
        self,
        *,
        allowed_servo_ids: tuple[int, ...],
        session_id: UUID,
        present_positions: Mapping[int, int],
        clock: Clock,
        write_enabled: bool = False,
        stale_read_indexes: tuple[int, ...] = (),
        stale_read_age_s: float = 60.0,
        direction_inverted_ids: tuple[int, ...] = (),
        divergence_raw_by_servo_id: Mapping[int, int] | None = None,
        write_delay_s: float = 0.0,
        stop_result: RealStopResult = RealStopResult.SAFETY_STATE_UNCERTAIN,
    ) -> None:
        _validate_servo_ids(allowed_servo_ids, allow_empty=False)
        if not isinstance(session_id, UUID):
            raise TypeError("session_id must be a UUID")
        if not isinstance(write_enabled, bool):
            raise TypeError("write_enabled must be a bool")
        if set(present_positions) != set(allowed_servo_ids):
            raise ValueError("fake positions must exactly match the allowed servo IDs")
        if any(
            isinstance(raw, bool) or not isinstance(raw, int) for raw in present_positions.values()
        ):
            raise TypeError("fake raw positions must be integers")
        if len(stale_read_indexes) != len(set(stale_read_indexes)) or any(
            isinstance(index, bool) or not isinstance(index, int) or index < 1
            for index in stale_read_indexes
        ):
            raise ValueError("stale read indexes must be unique positive integers")
        if not isfinite(stale_read_age_s) or stale_read_age_s <= 0.0:
            raise ValueError("stale read age must be a positive finite duration")
        _validate_servo_ids(direction_inverted_ids, allow_empty=True)
        if not set(direction_inverted_ids) <= set(allowed_servo_ids):
            raise ValueError("direction inversion IDs must be allowed servo IDs")
        divergence = dict(divergence_raw_by_servo_id or {})
        if not set(divergence) <= set(allowed_servo_ids):
            raise ValueError("divergence IDs must be allowed servo IDs")
        if any(isinstance(raw, bool) or not isinstance(raw, int) for raw in divergence.values()):
            raise TypeError("configured raw divergence must use integers")
        if not isfinite(write_delay_s) or write_delay_s < 0.0:
            raise ValueError("write delay must be a non-negative finite duration")
        if stop_result is RealStopResult.STOPPED_AND_VERIFIED:
            raise ValueError("a fake adapter cannot claim physically verified stopping")
        if stop_result is RealStopResult.NOT_CONNECTED:
            raise ValueError("NOT_CONNECTED is derived from the fake close lifecycle")
        if stop_result not in {
            RealStopResult.HOLD_REQUESTED,
            RealStopResult.TORQUE_DISABLE_REQUESTED,
            RealStopResult.FAILED,
            RealStopResult.SAFETY_STATE_UNCERTAIN,
        }:
            raise ValueError("unsupported fake commissioning Stop outcome")

        self._allowed_servo_ids = frozenset(allowed_servo_ids)
        self._session_id = session_id
        self._positions = dict(present_positions)
        self._clock = clock
        self._write_enabled = write_enabled
        self._stale_read_indexes = frozenset(stale_read_indexes)
        self._stale_read_age_s = float(stale_read_age_s)
        self._direction_inverted_ids = frozenset(direction_inverted_ids)
        self._divergence = divergence
        self._write_delay_s = float(write_delay_s)
        self._stop_result = stop_result
        self._connected = True
        self._read_count = 0
        self._stop_generation = 0
        self._active_command_id: UUID | None = None
        self._events: list[tuple[str, object]] = []

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def positions(self) -> dict[int, int]:
        return dict(self._positions)

    @property
    def events(self) -> tuple[tuple[str, object], ...]:
        return tuple(self._events)

    @property
    def write_in_flight(self) -> bool:
        return self._active_command_id is not None

    async def read_present_position(self, servo_id: int) -> CommissioningPositionReadback:
        self._require_connected()
        self._require_allowed(servo_id)
        self._read_count += 1
        captured_at = self._clock.now()
        if self._read_count in self._stale_read_indexes:
            captured_at -= timedelta(seconds=self._stale_read_age_s)
        readback = CommissioningPositionReadback(
            servo_id=servo_id,
            raw_position=self._positions[servo_id],
            captured_at=captured_at,
        )
        self._events.append(("read_present_position", readback))
        return readback

    async def write_prepared_command(
        self,
        command: PreparedCommissioningTestCommand,
    ) -> ServoWriteResult:
        if not isinstance(command, PreparedCommissioningTestCommand):
            raise TypeError("only a prepared commissioning command may be written")
        self._require_connected()
        self._require_allowed(command.servo_id)
        if command.session_id != self._session_id:
            raise PermissionError("prepared command belongs to a different session")
        if not self._write_enabled:
            raise PermissionError("fake commissioning writes are disabled")
        if self._clock.now() >= command.readback_fresh_until:
            raise PermissionError("prepared command readback is no longer fresh")
        if self._positions[command.servo_id] != command.start_raw:
            raise RuntimeError("present position changed after command preparation")
        if self._active_command_id is not None:
            raise RuntimeError("only one commissioning write may be active")

        requested_ids = (command.servo_id,)
        start_generation = self._stop_generation
        self._active_command_id = command.command_id
        self._events.append(("write_started", command))
        try:
            if self._write_delay_s:
                try:
                    await self._clock.sleep(self._write_delay_s)
                except asyncio.CancelledError:
                    self._events.append(("write_cancelled", command.command_id))
                    raise

            if not self._connected:
                self._events.append(("write_fenced_by_close", command.command_id))
                return _failed_write(
                    command.servo_id,
                    connected=False,
                    detail="fake bus closed before the delayed write could apply",
                )
            if start_generation != self._stop_generation:
                self._events.append(("write_fenced_by_stop", command.command_id))
                return _failed_write(
                    command.servo_id,
                    connected=True,
                    detail="Stop/Hold fenced the delayed write before mutation",
                )

            raw_delta = command.target_raw - command.start_raw
            if command.servo_id in self._direction_inverted_ids:
                raw_delta = -raw_delta
            final_raw = command.start_raw + raw_delta + self._divergence.get(command.servo_id, 0)
            self._positions[command.servo_id] = final_raw
            self._events.append(
                (
                    "write_applied",
                    {
                        "command_id": command.command_id,
                        "servo_id": command.servo_id,
                        "raw_position": final_raw,
                    },
                )
            )
            return ServoWriteResult(
                requested_ids=requested_ids,
                written_ids=requested_ids,
                failed_ids=(),
                connected=True,
                complete=True,
                safety_state_known=True,
                detail="prepared command applied to in-memory fake state only",
            )
        finally:
            if self._active_command_id == command.command_id:
                self._active_command_id = None

    async def stop_or_hold(self, servo_id: int) -> RealStopOutcome:
        self._require_allowed(servo_id)
        self._stop_generation += 1
        self._events.append(("stop_or_hold", servo_id))
        requested_ids = (servo_id,)
        if not self._connected:
            return RealStopOutcome(
                result=RealStopResult.NOT_CONNECTED,
                requested_ids=requested_ids,
                affected_ids=(),
                connected=False,
                safety_state_known=False,
                detail="fake commissioning bus is closed",
            )
        affected_ids = (
            requested_ids
            if self._stop_result
            in {RealStopResult.HOLD_REQUESTED, RealStopResult.TORQUE_DISABLE_REQUESTED}
            else ()
        )
        return RealStopOutcome(
            result=self._stop_result,
            requested_ids=requested_ids,
            affected_ids=affected_ids,
            connected=True,
            safety_state_known=False,
            detail="fake software Stop/Hold path; physical behavior is never verified",
        )

    async def reset_for_session(self, session_id: UUID) -> None:
        """Fence the prior session before accepting another immutable command."""

        if not isinstance(session_id, UUID):
            raise TypeError("session_id must be a UUID")
        if self._active_command_id is not None:
            raise RuntimeError("cannot rebind while a commissioning write is active")
        self._require_connected()
        self._stop_generation += 1
        self._session_id = session_id
        self._events.append(("reset_for_session", session_id))

    async def close(self) -> None:
        self._stop_generation += 1
        self._write_enabled = False
        self._connected = False
        self._events.append(("close", None))

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("fake commissioning bus is closed")

    def _require_allowed(self, servo_id: int) -> None:
        _validate_servo_ids((servo_id,), allow_empty=False)
        if servo_id not in self._allowed_servo_ids:
            raise PermissionError("servo ID is outside the fake commissioning allowlist")


def _failed_write(servo_id: int, *, connected: bool, detail: str) -> ServoWriteResult:
    return ServoWriteResult(
        requested_ids=(servo_id,),
        written_ids=(),
        failed_ids=(servo_id,),
        connected=connected,
        complete=False,
        safety_state_known=False,
        detail=detail,
    )


def _validate_servo_ids(servo_ids: tuple[int, ...], *, allow_empty: bool) -> None:
    if not isinstance(servo_ids, tuple):
        raise TypeError("servo IDs must be an explicit tuple")
    if not allow_empty and not servo_ids:
        raise ValueError("at least one explicit servo ID is required")
    if len(servo_ids) != len(set(servo_ids)):
        raise ValueError("explicit servo IDs must be unique")
    if any(
        isinstance(servo_id, bool)
        or not isinstance(servo_id, int)
        or servo_id < 1
        or servo_id > 253
        for servo_id in servo_ids
    ):
        raise ValueError("explicit servo IDs must be integers from 1 through 253")


__all__ = ["FakeCommissioningMotionBus"]
