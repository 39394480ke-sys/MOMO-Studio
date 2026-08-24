"""Protected selected-joint calibration routes; no endpoint can move a servo."""

from __future__ import annotations

from http import HTTPStatus
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from momo.api.calibration_workflow_schemas import (
    CalibrationCompleteRequest,
    CalibrationJointConfirmRequest,
    CalibrationJointPreviewRequest,
    CalibrationJointReadRequest,
    CalibrationRevisionSummaryResponse,
    CalibrationRollbackRequest,
    CalibrationSessionStartRequest,
)
from momo.api.security import authorize_control_request
from momo.application.services.calibration_workflow_coordinator import (
    CalibrationWorkflowCoordinator,
)
from momo.domain.calibration_workflow import (
    CalibrationJointPreview,
    CalibrationRevisionRecord,
    CalibrationWorkflowError,
    CalibrationWorkflowStatus,
)

router = APIRouter(
    prefix="/device/calibration",
    tags=["device-calibration"],
    dependencies=[Depends(authorize_control_request)],
)


def get_calibration_coordinator(request: Request) -> CalibrationWorkflowCoordinator:
    return cast(
        CalibrationWorkflowCoordinator,
        request.app.state.calibration_workflow_coordinator,
    )


Coordinator = Annotated[
    CalibrationWorkflowCoordinator,
    Depends(get_calibration_coordinator),
]
OperatorToken = Annotated[
    str,
    Header(alias="X-MOMO-Operator-Session", min_length=20, max_length=200),
]


def _error(error: CalibrationWorkflowError) -> HTTPException:
    if error.code == "CALIBRATION_SESSION_NOT_FOUND":
        status = HTTPStatus.NOT_FOUND
    elif "EXPIRED" in error.code or "AUTHORIZATION" in error.code:
        status = HTTPStatus.UNAUTHORIZED
    elif "CONFLICT" in error.code or "CHANGED" in error.code:
        status = HTTPStatus.CONFLICT
    elif "FAILED" in error.code or "STORAGE" in error.code:
        status = HTTPStatus.SERVICE_UNAVAILABLE
    else:
        status = HTTPStatus.UNPROCESSABLE_ENTITY
    return HTTPException(
        status_code=int(status),
        detail={"code": error.code, "message": str(error), "details": error.details},
    )


def _revision(record: CalibrationRevisionRecord) -> CalibrationRevisionSummaryResponse:
    return CalibrationRevisionSummaryResponse(
        revision=record.revision,
        calibration_fingerprint=record.calibration_fingerprint,
        previous_calibration_fingerprint=record.previous_calibration_fingerprint,
        variant=record.calibration.robot_variant,
        created_at=record.created_at.isoformat(),
    )


@router.post("/sessions", response_model=CalibrationWorkflowStatus)
async def start_session(
    body: CalibrationSessionStartRequest,
    service: Coordinator,
    token: OperatorToken,
) -> CalibrationWorkflowStatus:
    try:
        return await service.start(
            token,
            source=body.source,
            explicit_legacy_calibration=body.explicit_legacy_calibration,
            legacy_confirmation=body.legacy_confirmation,
        )
    except CalibrationWorkflowError as error:
        raise _error(error) from error


@router.get("/sessions/{session_id}", response_model=CalibrationWorkflowStatus)
async def session_status(
    session_id: UUID,
    service: Coordinator,
    token: OperatorToken,
) -> CalibrationWorkflowStatus:
    try:
        return await service.status(token, session_id)
    except CalibrationWorkflowError as error:
        raise _error(error) from error


@router.post("/sessions/{session_id}/read", response_model=CalibrationWorkflowStatus)
async def read_joint(
    session_id: UUID,
    body: CalibrationJointReadRequest,
    service: Coordinator,
    token: OperatorToken,
) -> CalibrationWorkflowStatus:
    try:
        return await service.read_selected_joint(token, session_id, body.joint_id)
    except CalibrationWorkflowError as error:
        raise _error(error) from error


@router.post("/sessions/{session_id}/preview", response_model=CalibrationJointPreview)
async def preview_joint(
    session_id: UUID,
    body: CalibrationJointPreviewRequest,
    service: Coordinator,
    token: OperatorToken,
) -> CalibrationJointPreview:
    try:
        return await service.preview_joint(
            token,
            session_id,
            body.joint_id,
            logical_value=body.logical_value,
            direction=body.direction,
            phase=body.phase,
            raw_bounds=body.raw_bounds,
        )
    except CalibrationWorkflowError as error:
        raise _error(error) from error


@router.post("/sessions/{session_id}/confirm", response_model=CalibrationWorkflowStatus)
async def confirm_joint(
    session_id: UUID,
    body: CalibrationJointConfirmRequest,
    service: Coordinator,
    token: OperatorToken,
) -> CalibrationWorkflowStatus:
    try:
        return await service.confirm_joint(
            token,
            session_id,
            body.joint_id,
            preview_fingerprint=body.preview_fingerprint,
            confirmation=body.confirmation,
        )
    except CalibrationWorkflowError as error:
        raise _error(error) from error


@router.post(
    "/sessions/{session_id}/complete",
    response_model=CalibrationRevisionSummaryResponse,
)
async def complete_session(
    session_id: UUID,
    body: CalibrationCompleteRequest,
    service: Coordinator,
    token: OperatorToken,
) -> CalibrationRevisionSummaryResponse:
    try:
        return _revision(
            await service.complete(
                token,
                session_id,
                proposed_calibration_fingerprint=(body.proposed_calibration_fingerprint),
                confirmation=body.confirmation,
            )
        )
    except CalibrationWorkflowError as error:
        raise _error(error) from error


@router.delete("/sessions/{session_id}", response_model=CalibrationWorkflowStatus)
async def cancel_session(
    session_id: UUID,
    service: Coordinator,
    token: OperatorToken,
) -> CalibrationWorkflowStatus:
    try:
        return await service.cancel(token, session_id)
    except CalibrationWorkflowError as error:
        raise _error(error) from error


@router.post("/rollback", response_model=CalibrationRevisionSummaryResponse)
async def rollback_calibration(
    body: CalibrationRollbackRequest,
    service: Coordinator,
    token: OperatorToken,
) -> CalibrationRevisionSummaryResponse:
    try:
        return _revision(
            await service.rollback(
                token,
                target_revision=body.target_revision,
                confirmation=body.confirmation,
            )
        )
    except CalibrationWorkflowError as error:
        raise _error(error) from error


__all__ = ["router"]
