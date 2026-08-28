"""Bounded response DTOs for Pose and Motion library collections."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from momo.domain.enums import MotionMode, RobotVariant
from momo.domain.pose import TcpPose
from momo.domain.robot import JointState


class PoseSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    name: str
    description: str
    tags: list[str]
    robot_variant: RobotVariant
    joint_state: JointState
    tcp_pose: TcpPose
    profile_fingerprint: str
    kinematics_fingerprint: str
    state_sequence: int | None
    created_at: datetime
    updated_at: datetime
    revision: int


class MotionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    name: str
    description: str
    robot_variant: RobotVariant
    keyframe_count: int
    total_duration_s: float
    motion_types: list[MotionMode]
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    revision: int


class PoseListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[PoseSummary]
    page: int
    page_size: int
    total: int


class MotionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[MotionSummary]
    page: int
    page_size: int
    total: int


LibrarySort = Literal["created_at", "updated_at", "name"]
SortOrder = Literal["asc", "desc"]
