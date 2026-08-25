"""HTTP contracts for measured-TCP Kinematics field verification."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from momo.domain.commissioning import KinematicsVerificationThresholds
from momo.domain.pose import TcpPose


class KinematicsVerificationDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thresholds: KinematicsVerificationThresholds | None = None


class KinematicsVerificationMeasurementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
    ]
    measured_tcp: TcpPose


__all__ = [
    "KinematicsVerificationDraftRequest",
    "KinematicsVerificationMeasurementRequest",
]
