"""Completely in-memory robot driver with no serial or SDK imports."""

from __future__ import annotations

from collections.abc import Mapping

from momo.domain.enums import RobotConnectionState, RobotVariant
from momo.domain.robot import JointState, RobotId, RobotProfile
from momo.domain.runtime import RuntimeState
from momo.ports.runtime_state_repository import RuntimeStateRepository


class DryRunRobotDriver:
    """Read-only Stage 2 driver whose only state is a validated joint mapping."""

    def __init__(
        self,
        robot_id: RobotId | str,
        profile: RobotProfile,
        initial_positions: Mapping[str, float] | None = None,
        runtime_repository: RuntimeStateRepository | None = None,
    ) -> None:
        self._robot_id = robot_id if isinstance(robot_id, RobotId) else RobotId(robot_id)
        self._profile = profile
        self._runtime_repository = runtime_repository
        homes = {definition.joint_id: definition.home for definition in profile.joint_definitions}
        self._positions = dict(initial_positions) if initial_positions is not None else homes
        JointState(positions=self._positions).validate_against(profile)
        self._connected = False
        self._state_sequence = 0
        self._connection_state = RobotConnectionState.DISCONNECTED
        self._persist()

    @property
    def robot_id(self) -> RobotId:
        return self._robot_id

    @property
    def variant(self) -> RobotVariant:
        return self._profile.variant

    @property
    def profile(self) -> RobotProfile:
        return self._profile

    @property
    def connection_state(self) -> RobotConnectionState:
        return self._connection_state

    @property
    def positions(self) -> dict[str, float]:
        return dict(self._positions)

    @property
    def hardware_accessed(self) -> bool:
        return False

    async def connect(self) -> None:
        self._connected = True
        self._connection_state = RobotConnectionState.CONNECTED
        self._state_sequence += 1
        self._persist()

    async def disconnect(self) -> None:
        self._connected = False
        self._connection_state = RobotConnectionState.DISCONNECTED
        self._state_sequence += 1
        self._persist()

    async def is_connected(self) -> bool:
        return self._connected

    async def read_joint_state(self) -> JointState:
        return JointState(
            positions=dict(self._positions),
            units={
                definition.joint_id: definition.domain_unit
                for definition in self._profile.joint_definitions
            },
        ).validate_against(self._profile)

    async def stop(self) -> None:
        # A Dry Run stop is deliberately idempotent and does not synthesize motion.
        self._state_sequence += 1
        self._persist()

    def _persist(self) -> None:
        if self._runtime_repository is None:
            return
        self._runtime_repository.save(
            RuntimeState(
                robot_id=self._robot_id.root,
                variant=self._profile.variant,
                profile_fingerprint=self._profile.fingerprint,
                positions=dict(self._positions),
                units={
                    definition.joint_id: definition.domain_unit.value
                    for definition in self._profile.joint_definitions
                },
                connection_state=self._connection_state,
                state_sequence=self._state_sequence,
            )
        )
