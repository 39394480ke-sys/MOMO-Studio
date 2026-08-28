"""In-memory Raw +/- bus used only by automated software acceptance."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal
from uuid import UUID

from momo.domain.raw_direction import PreparedRawDirectionCommand
from momo.domain.real_hardware import RealStopOutcome, RealStopResult, ServoWriteResult
from momo.ports.clock import Clock
from momo.ports.servo_bus import CommissioningPositionReadback


class FakeRawDirectionBus:
    adapter_id = "fake-raw-direction-bus"
    is_physical_adapter: Literal[False] = False

    def __init__(
        self,
        *,
        allowed_servo_ids: tuple[int, ...],
        session_id: UUID,
        present_positions: Mapping[int, int],
        clock: Clock,
        write_enabled: bool = False,
    ) -> None:
        if not allowed_servo_ids or len(allowed_servo_ids) != len(set(allowed_servo_ids)):
            raise ValueError("fake Raw bus requires unique explicit Servo IDs")
        if set(present_positions) != set(allowed_servo_ids):
            raise ValueError("fake Raw positions must exactly match the allowlist")
        if any(
            isinstance(raw, bool) or not isinstance(raw, int) for raw in present_positions.values()
        ):
            raise TypeError("fake Raw positions must be integers")
        self._allowed = frozenset(allowed_servo_ids)
        self._session_id = session_id
        self._positions = dict(present_positions)
        self._clock = clock
        self._write_enabled = write_enabled
        self._connected = True
        self._events: list[tuple[str, object]] = []

    @property
    def positions(self) -> dict[int, int]:
        return dict(self._positions)

    @property
    def events(self) -> tuple[tuple[str, object], ...]:
        return tuple(self._events)

    async def read_present_position(self, servo_id: int) -> CommissioningPositionReadback:
        self._require(servo_id)
        readback = CommissioningPositionReadback(
            servo_id=servo_id,
            raw_position=self._positions[servo_id],
            captured_at=self._clock.now(),
        )
        self._events.append(("read", readback))
        return readback

    async def write_prepared_raw_direction_command(
        self,
        command: PreparedRawDirectionCommand,
    ) -> ServoWriteResult:
        self._require(command.servo_id)
        if not self._write_enabled:
            raise PermissionError("fake Raw writes require explicit test-fixture opt-in")
        if command.session_id != self._session_id:
            raise PermissionError("prepared Raw command belongs to a different session")
        if self._clock.now() >= command.readback_fresh_until:
            raise PermissionError("prepared Raw command readback expired")
        if self._positions[command.servo_id] != command.start_raw:
            raise RuntimeError("Raw position changed after command preparation")
        self._positions[command.servo_id] = command.target_raw
        self._events.append(("write", command))
        return ServoWriteResult(
            requested_ids=(command.servo_id,),
            written_ids=(command.servo_id,),
            failed_ids=(),
            connected=True,
            complete=True,
            safety_state_known=True,
            detail="prepared Raw command applied to in-memory fake state only",
        )

    async def stop_or_hold(self, servo_id: int) -> RealStopOutcome:
        self._require(servo_id)
        self._events.append(("stop", servo_id))
        return RealStopOutcome(
            result=RealStopResult.HOLD_REQUESTED,
            requested_ids=(servo_id,),
            affected_ids=(servo_id,),
            connected=True,
            safety_state_known=False,
            detail="fake Raw Hold path; no physical behavior is claimed",
        )

    async def reset_for_session(self, session_id: UUID) -> None:
        if not isinstance(session_id, UUID):
            raise TypeError("session_id must be a UUID")
        self._session_id = session_id
        self._events.append(("reset", session_id))

    async def close(self) -> None:
        self._connected = False
        self._write_enabled = False
        self._events.append(("close", None))

    def _require(self, servo_id: int) -> None:
        if not self._connected:
            raise RuntimeError("fake Raw bus is closed")
        if servo_id not in self._allowed:
            raise PermissionError("Servo ID is outside the fake Raw allowlist")


__all__ = ["FakeRawDirectionBus"]
