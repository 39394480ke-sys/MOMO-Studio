"""HTTP response contracts. Domain models remain independent from FastAPI."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from momo.domain.enums import ControlMode, RobotVariant


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    product: str
    version: str
    control_mode: ControlMode
    real_motion_enabled: Literal[False] = False


class MetaResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: str
    version: str
    api_version: Literal["v1"] = "v1"
    stage: Literal[1] = 1
    active_robot_variant: RobotVariant
    supported_robot_variants: list[RobotVariant] = Field(
        default_factory=lambda: [RobotVariant.V1, RobotVariant.V2]
    )
    supported_control_modes: list[ControlMode] = Field(
        default_factory=lambda: [ControlMode.DRY_RUN, ControlMode.REAL]
    )
    real_motion_enabled: Literal[False] = False


class ProductScopeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: str
    release: Literal["first_version"] = "first_version"
    stage: Literal[1] = 1
    stage_1_available: list[str]
    included_in_first_version: list[str]
    excluded_from_first_version: list[str]
