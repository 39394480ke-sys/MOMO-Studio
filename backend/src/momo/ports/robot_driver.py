"""Hardware-facing robot driver boundary; no implementation exists in Stage 1."""

from typing import Protocol, runtime_checkable

from momo.domain.enums import RobotVariant
from momo.domain.robot import JointState, RobotId, RobotProfile


@runtime_checkable
class RobotDriver(Protocol):
    """Minimal driver contract owned by adapters, never by API routes."""

    @property
    def robot_id(self) -> RobotId: ...

    @property
    def variant(self) -> RobotVariant: ...

    @property
    def profile(self) -> RobotProfile: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def is_connected(self) -> bool: ...

    async def read_joint_state(self) -> JointState: ...

    async def stop(self) -> None: ...
