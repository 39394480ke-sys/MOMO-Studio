"""Immutable preflight evidence and prepared Dry Run motion values."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from momo.domain.enums import DomainUnit, MotionCommandState
from momo.domain.immutable import freeze_sequence
from momo.domain.motion_command import MAX_EFFECTIVE_MOTION_DURATION_S, MIN_MOTION_DURATION_S
from momo.domain.pose import TcpPose, utc_now
from momo.domain.robot import JointState
from momo.domain.trajectory import PreparedTrajectory, TrajectoryPreflightReport


class PreflightCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    passed: bool
    detail: str


class MotionPreflight(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    accepted: bool
    command_id: UUID
    checks: list[PreflightCheck]
    warnings: list[str]
    profile_fingerprint: str
    kinematics_fingerprint: str

    @field_validator("checks", "warnings")
    @classmethod
    def freeze_lists(cls, value: list[object]) -> list[object]:
        return freeze_sequence(value)


class PreparedMotionSample(BaseModel):
    """One immutable, gateway-reviewed joint sample for a non-joint path."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    time_s: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    joint_state: JointState
    tcp_pose: TcpPose | None = None


class PreparedMotion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_id: UUID
    start_state: JointState
    target_state: JointState
    duration_s: Annotated[
        float,
        Field(
            ge=MIN_MOTION_DURATION_S,
            le=MAX_EFFECTIVE_MOTION_DURATION_S,
            allow_inf_nan=False,
        ),
    ]
    trajectory_samples: list[PreparedMotionSample] | None = None
    preflight: MotionPreflight
    executable_trajectory: PreparedTrajectory | None = None

    @field_validator("trajectory_samples")
    @classmethod
    def freeze_trajectory_samples(
        cls,
        value: list[PreparedMotionSample] | None,
    ) -> list[PreparedMotionSample] | None:
        return None if value is None else freeze_sequence(value)

    @model_validator(mode="after")
    def exact_trajectory_matches_command(self) -> Self:
        executable = self.executable_trajectory
        if executable is None:
            return self
        plan = executable.plan
        if plan.motion_id != self.command_id or abs(plan.duration_s - self.duration_s) > 1e-9:
            raise ValueError("exact executable trajectory does not match prepared motion")
        first = plan.samples[0]
        last = plan.samples[-1]
        if (
            dict(first.positions) != dict(self.start_state.positions)
            or dict(first.units) != dict(self.start_state.units or {})
            or dict(last.positions) != dict(self.target_state.positions)
            or dict(last.units) != dict(self.target_state.units or {})
        ):
            raise ValueError("exact executable trajectory endpoints do not match prepared motion")
        return self


class PreparedContinuousJog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_id: UUID
    start_state: JointState
    joint_id: str
    direction: Literal[-1, 1]
    speed_units_s: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    acceleration_units_s2: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    unit: DomainUnit
    minimum: Annotated[float, Field(allow_inf_nan=False)]
    maximum: Annotated[float, Field(allow_inf_nan=False)]
    preflight: MotionPreflight
    executable_trajectory: PreparedTrajectory | None = None

    @model_validator(mode="after")
    def exact_trajectory_matches_envelope(self) -> Self:
        executable = self.executable_trajectory
        if executable is None:
            return self
        plan = executable.plan
        if plan.motion_id != self.command_id:
            raise ValueError("exact executable trajectory does not match prepared jog")
        first = plan.samples[0]
        if dict(first.positions) != dict(self.start_state.positions) or dict(first.units) != dict(
            self.start_state.units or {}
        ):
            raise ValueError("exact executable jog must begin at its reviewed start state")
        if any(
            not self.minimum <= sample.positions[self.joint_id] <= self.maximum
            for sample in plan.samples
        ):
            raise ValueError("exact executable jog escaped its reviewed envelope")
        return self


class MotionCommandStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    command_id: UUID
    state: MotionCommandState
    progress: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    preflight: MotionPreflight
    trajectory_preflight: TrajectoryPreflightReport | None = None
    error: str | None = None
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    hardware_accessed: bool = False


class MotionAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_id: UUID
    status: MotionCommandState
    preflight: MotionPreflight
    trajectory_preflight: TrajectoryPreflightReport | None = None
