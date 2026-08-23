"""Repository boundary for reviewed, fixed-name kinematics models."""

from typing import Protocol, runtime_checkable

from momo.domain.enums import RobotVariant
from momo.domain.kinematics.model import KinematicsModel


@runtime_checkable
class KinematicsModelRepository(Protocol):
    def get(self, variant: RobotVariant) -> KinematicsModel: ...
