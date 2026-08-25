"""Server-owned joint-state snapshot boundary for field Kinematics verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from momo.domain.robot import JointState


@dataclass(frozen=True, slots=True)
class KinematicsJointStateSnapshot:
    """One fresh, device-bound state captured outside the client request body."""

    robot_unit_id: str
    profile_fingerprint: str
    calibration_fingerprint: str
    device_fingerprint: str
    operator_session_id: UUID
    joint_state: JointState
    state_sequence: int
    captured_at: datetime

    def __post_init__(self) -> None:
        if not self.robot_unit_id.strip():
            raise ValueError("snapshot robot_unit_id is required")
        for name, value in (
            ("profile_fingerprint", self.profile_fingerprint),
            ("calibration_fingerprint", self.calibration_fingerprint),
            ("device_fingerprint", self.device_fingerprint),
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"snapshot {name} must be a SHA-256 fingerprint")
        if (
            isinstance(self.state_sequence, bool)
            or not isinstance(self.state_sequence, int)
            or self.state_sequence < 0
        ):
            raise ValueError("snapshot state_sequence must be a non-negative integer")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("snapshot captured_at must include a timezone offset")


@runtime_checkable
class KinematicsJointStateSnapshotProvider(Protocol):
    """Capture a state from the current field-controlled device/session boundary."""

    async def capture(self) -> KinematicsJointStateSnapshot: ...


__all__ = [
    "KinematicsJointStateSnapshot",
    "KinematicsJointStateSnapshotProvider",
]
