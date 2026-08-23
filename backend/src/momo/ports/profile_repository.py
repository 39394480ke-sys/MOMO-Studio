"""Storage boundary for reviewed robot profile documents."""

from typing import Protocol, runtime_checkable

from momo.domain.enums import RobotVariant
from momo.domain.robot import RobotProfile


@runtime_checkable
class ProfileRepository(Protocol):
    def get(self, variant: RobotVariant) -> RobotProfile: ...
