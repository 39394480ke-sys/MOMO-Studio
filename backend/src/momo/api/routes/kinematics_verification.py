"""Measured-TCP Kinematics evidence routes."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from momo.api.dependencies import OperatorToken
from momo.api.kinematics_verification_schemas import (
    KinematicsVerificationDraftRequest,
    KinematicsVerificationMeasurementRequest,
)
from momo.api.security import authorize_control_request
from momo.application.services.kinematics_verification_service import (
    KinematicsVerificationDraft,
    KinematicsVerificationService,
    KinematicsVerificationStatus,
)
from momo.domain.commissioning import KinematicsVerificationEvidence

router = APIRouter(prefix="/kinematics-verification", tags=["kinematics-verification"])


def get_service(request: Request) -> KinematicsVerificationService:
    return cast(
        KinematicsVerificationService,
        request.app.state.kinematics_verification_service,
    )


ServiceDependency = Annotated[KinematicsVerificationService, Depends(get_service)]


@router.get("", response_model=KinematicsVerificationStatus)
async def status(service: ServiceDependency) -> KinematicsVerificationStatus:
    return service.status()


@router.post(
    "/draft",
    response_model=KinematicsVerificationDraft,
    dependencies=[Depends(authorize_control_request)],
)
async def start_draft(
    request: KinematicsVerificationDraftRequest,
    service: ServiceDependency,
    token: OperatorToken,
) -> KinematicsVerificationDraft:
    return await service.start_draft(token, thresholds=request.thresholds)


@router.post(
    "/draft/{draft_id}/measurement",
    response_model=KinematicsVerificationDraft,
    dependencies=[Depends(authorize_control_request)],
)
async def add_measurement(
    draft_id: UUID,
    request: KinematicsVerificationMeasurementRequest,
    service: ServiceDependency,
    token: OperatorToken,
) -> KinematicsVerificationDraft:
    return await service.add_measurement(
        token,
        draft_id,
        label=request.label,
        measured_tcp=request.measured_tcp,
    )


@router.post(
    "/draft/{draft_id}/commit",
    response_model=KinematicsVerificationEvidence,
    dependencies=[Depends(authorize_control_request)],
)
async def commit(
    draft_id: UUID,
    service: ServiceDependency,
    token: OperatorToken,
) -> KinematicsVerificationEvidence:
    return await service.commit(token, draft_id)


__all__ = ["router"]
