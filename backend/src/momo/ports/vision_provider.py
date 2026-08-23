"""Future vision-frame provider boundary; no camera access occurs in Stage 1."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from momo.domain.robot import RobotId


@dataclass(frozen=True, slots=True)
class VisionFrame:
    content: bytes
    media_type: str
    captured_at: datetime


@runtime_checkable
class VisionProvider(Protocol):
    async def latest_frame(self, robot_id: RobotId) -> VisionFrame | None: ...
