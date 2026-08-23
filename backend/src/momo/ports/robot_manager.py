"""Single-active-robot manager boundary without a process-global robot."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from momo.domain.robot import RobotId
from momo.ports.robot_driver import RobotDriver


@runtime_checkable
class RobotManager(Protocol):
    """Registry abstraction extensible to multiple known robots, not Fleet features."""

    async def list_robot_ids(self) -> Sequence[RobotId]: ...

    async def get(self, robot_id: RobotId) -> RobotDriver | None: ...

    async def get_active(self) -> RobotDriver | None: ...

    async def set_active(self, robot_id: RobotId) -> None: ...
