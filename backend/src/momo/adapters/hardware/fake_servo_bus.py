"""Deterministic explicit-ID ServoBus used exclusively by tests and Dry fixtures."""

from __future__ import annotations

from collections.abc import Mapping

from momo.domain.real_hardware import (
    ExplicitServoDevice,
    HardwareDependencyState,
    HardwareDependencyStatus,
    RealHardwareAccessGrant,
    RealHardwareAuthorizationPurpose,
    RealStopOutcome,
    RealStopResult,
    ServoPingResult,
    ServoWriteResult,
    explicit_device_fingerprint,
)


class FakeServoBus:
    """In-memory bus with bounded fault injection and an auditable call trace."""

    def __init__(
        self,
        *,
        present_positions: Mapping[int, int],
        operating_modes: Mapping[int, str],
        torque_states: Mapping[int, bool],
        missing_ping_ids: tuple[int, ...] = (),
        failed_write_ids: tuple[int, ...] = (),
        fail_open: bool = False,
        fail_read_kind: str | None = None,
        stop_result: RealStopResult = RealStopResult.STOPPED_AND_VERIFIED,
    ) -> None:
        known = tuple(present_positions)
        _validate_ids(known, allow_empty=False)
        if set(known) != set(operating_modes) or set(known) != set(torque_states):
            raise ValueError("fake bus position, mode, and torque IDs must match exactly")
        _validate_ids(missing_ping_ids, allow_empty=True)
        _validate_ids(failed_write_ids, allow_empty=True)
        if not set(missing_ping_ids) <= set(known):
            raise ValueError("missing ping IDs must be configured fake IDs")
        if not set(failed_write_ids) <= set(known):
            raise ValueError("failed write IDs must be configured fake IDs")
        if fail_read_kind not in {None, "positions", "modes", "torque"}:
            raise ValueError("unsupported fake read failure kind")
        self._positions = dict(present_positions)
        self._modes = dict(operating_modes)
        self._torque = dict(torque_states)
        self._known_ids = known
        self._missing_ping_ids = frozenset(missing_ping_ids)
        self._failed_write_ids = frozenset(failed_write_ids)
        self._fail_open = fail_open
        self._fail_read_kind = fail_read_kind
        self._stop_result = stop_result
        self._connected = False
        self._authorization: RealHardwareAccessGrant | None = None
        self._events: list[tuple[str, object]] = []

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def events(self) -> tuple[tuple[str, object], ...]:
        return tuple(self._events)

    @property
    def positions(self) -> dict[int, int]:
        return dict(self._positions)

    def bind_authorization(self, authorization: RealHardwareAccessGrant) -> None:
        """Bind the factory grant before open; a connected bus cannot be rebound."""

        if self._connected:
            raise RuntimeError("cannot replace fake bus authorization while connected")
        self._authorization = authorization

    async def open(self, device: str, protocol: str) -> None:
        if not isinstance(device, str) or not device.strip():
            raise ValueError("fake bus requires an explicit device")
        if not isinstance(protocol, str) or not protocol.strip():
            raise ValueError("fake bus requires an explicit protocol")
        authorization = self._authorization
        if authorization is not None:
            candidate = ExplicitServoDevice(
                serial_port=device,
                protocol=protocol,
                servo_ids=authorization.session.allowed_servo_ids,
            )
            if explicit_device_fingerprint(candidate) != authorization.device_fingerprint:
                raise PermissionError("device and protocol must match the authorized grant")
        self._events.append(("open", (device, protocol)))
        if self._fail_open:
            raise RuntimeError("configured fake open failure")
        self._connected = True

    async def close(self) -> None:
        self._events.append(("close", None))
        self._connected = False

    async def ping_explicit_ids(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, ServoPingResult]:
        self._require_connected()
        _validate_ids(servo_ids, allow_empty=False)
        self._require_granted_read_ids(servo_ids)
        self._events.append(("ping_explicit_ids", servo_ids))
        return {
            servo_id: ServoPingResult(
                servo_id=servo_id,
                responded=(servo_id in self._positions and servo_id not in self._missing_ping_ids),
                detail=(
                    "explicit fake servo responded"
                    if servo_id in self._positions and servo_id not in self._missing_ping_ids
                    else "explicit fake servo did not respond"
                ),
            )
            for servo_id in servo_ids
        }

    async def read_present_positions(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, int]:
        self._events.append(("read_present_positions", servo_ids))
        self._require_read(servo_ids, "positions")
        return {servo_id: self._positions[servo_id] for servo_id in servo_ids}

    async def read_operating_modes(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, str]:
        self._events.append(("read_operating_modes", servo_ids))
        self._require_read(servo_ids, "modes")
        return {servo_id: self._modes[servo_id] for servo_id in servo_ids}

    async def read_torque_states(
        self,
        servo_ids: tuple[int, ...],
    ) -> Mapping[int, bool]:
        self._events.append(("read_torque_states", servo_ids))
        self._require_read(servo_ids, "torque")
        return {servo_id: self._torque[servo_id] for servo_id in servo_ids}

    async def write_goal_positions(
        self,
        goal_positions: Mapping[int, int],
    ) -> ServoWriteResult:
        requested = tuple(goal_positions)
        _validate_ids(requested, allow_empty=False)
        self._require_full_granted_ids(requested)
        self._require_goal_write_authorization()
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in goal_positions.values()
        ):
            raise TypeError("fake goal positions must be integer raw values")
        self._events.append(("write_goal_positions", dict(goal_positions)))
        if not self._connected:
            return ServoWriteResult(
                requested_ids=requested,
                written_ids=(),
                failed_ids=requested,
                connected=False,
                complete=False,
                safety_state_known=False,
                detail="fake bus is not connected",
            )
        unknown = set(requested) - set(self._known_ids)
        failed = tuple(
            servo_id
            for servo_id in requested
            if servo_id in unknown or servo_id in self._failed_write_ids
        )
        written = tuple(servo_id for servo_id in requested if servo_id not in set(failed))
        for servo_id in written:
            self._positions[servo_id] = goal_positions[servo_id]
        complete = not failed
        return ServoWriteResult(
            requested_ids=requested,
            written_ids=written,
            failed_ids=failed,
            connected=True,
            complete=complete,
            safety_state_known=complete,
            detail=("all fake goals written" if complete else "configured fake partial write"),
        )

    async def stop_or_hold(self, servo_ids: tuple[int, ...]) -> RealStopOutcome:
        _validate_ids(servo_ids, allow_empty=False)
        self._require_full_granted_ids(servo_ids)
        self._events.append(("stop_or_hold", servo_ids))
        if not self._connected:
            return RealStopOutcome(
                result=RealStopResult.NOT_CONNECTED,
                requested_ids=servo_ids,
                affected_ids=(),
                connected=False,
                safety_state_known=False,
                detail="fake bus is not connected",
            )
        if not set(servo_ids) <= set(self._known_ids):
            return RealStopOutcome(
                result=RealStopResult.FAILED,
                requested_ids=servo_ids,
                affected_ids=(),
                connected=True,
                safety_state_known=False,
                detail="Stop requested an ID outside the explicit fake allowlist",
            )
        if self._stop_result is RealStopResult.STOPPED_AND_VERIFIED:
            return RealStopOutcome(
                result=self._stop_result,
                requested_ids=servo_ids,
                affected_ids=servo_ids,
                connected=True,
                safety_state_known=True,
                detail="fake Stop was applied and verified",
            )
        affected = (
            servo_ids
            if self._stop_result
            in {RealStopResult.HOLD_REQUESTED, RealStopResult.TORQUE_DISABLE_REQUESTED}
            else ()
        )
        return RealStopOutcome(
            result=self._stop_result,
            requested_ids=servo_ids,
            affected_ids=affected,
            connected=True,
            safety_state_known=False,
            detail="fake Stop outcome intentionally does not claim physical verification",
        )

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("fake ServoBus is not connected")

    def _require_read(self, servo_ids: tuple[int, ...], kind: str) -> None:
        self._require_connected()
        _validate_ids(servo_ids, allow_empty=False)
        self._require_granted_read_ids(servo_ids)
        if not set(servo_ids) <= set(self._known_ids):
            raise RuntimeError("read requested an ID outside the explicit fake allowlist")
        if self._fail_read_kind == kind:
            raise RuntimeError(f"configured fake {kind} read failure")

    def _require_granted_read_ids(self, servo_ids: tuple[int, ...]) -> None:
        authorization = self._authorization
        if authorization is None:
            return
        if not set(servo_ids) <= set(authorization.session.allowed_servo_ids):
            raise PermissionError("read IDs must be a subset of the authorized allowlist")

    def _require_full_granted_ids(self, servo_ids: tuple[int, ...]) -> None:
        authorization = self._authorization
        if authorization is None:
            return
        if servo_ids != authorization.session.allowed_servo_ids:
            raise PermissionError("write/Stop IDs must exactly match the authorized allowlist")

    def _require_goal_write_authorization(self) -> None:
        authorization = self._authorization
        if authorization is None:
            return
        if authorization.purpose is RealHardwareAuthorizationPurpose.DIAGNOSTICS:
            raise PermissionError("a read-only diagnostics grant cannot write goal positions")


class FakeServoBusFactory:
    def __init__(self, bus: FakeServoBus) -> None:
        self.bus = bus
        self.grants: list[RealHardwareAccessGrant] = []

    @property
    def dependency(self) -> HardwareDependencyStatus:
        return HardwareDependencyStatus(
            adapter_id="fake-servo-bus",
            state=HardwareDependencyState.AVAILABLE,
            package_name=None,
            license_status="MOMO_TEST_FIXTURE",
            notice="In-memory test adapter; no hardware or third-party SDK is used.",
        )

    def create(self, authorization: RealHardwareAccessGrant) -> FakeServoBus:
        dependency = self.dependency
        if (
            dependency.state is not HardwareDependencyState.AVAILABLE
            or authorization.adapter_id != dependency.adapter_id
        ):
            raise PermissionError("access grant does not match the fake ServoBus adapter")
        self.grants.append(authorization)
        self.bus.bind_authorization(authorization)
        return self.bus


def _validate_ids(servo_ids: tuple[int, ...], *, allow_empty: bool) -> None:
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
