"""Capability-narrow commissioning routes; no route imports a Servo driver."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from momo.api.commissioning_schemas import (
    CommissioningMotionStatusResponse,
    CommissioningRelativeTestRequest,
)
from momo.api.dependencies import OperatorToken
from momo.api.security import authorize_control_request, authorize_priority_stop_request
from momo.application.services.commissioning_motion_test_service import (
    CommissioningMotionConflictError,
    CommissioningMotionStatus,
    CommissioningMotionTestService,
)
from momo.domain.commissioning import CommissioningTestEvidence

router = APIRouter(prefix="/device/commissioning", tags=["commissioning"])


def get_commissioning_service(request: Request) -> CommissioningMotionTestService:
    service = getattr(request.app.state, "commissioning_motion_test_service", None)
    if service is None:
        raise CommissioningMotionConflictError(
            "No field-verified commissioning motion adapter is configured",
            details={"reason": "COMMISSIONING_ADAPTER_UNAVAILABLE"},
        )
    return cast(CommissioningMotionTestService, service)


CommissioningServiceDependency = Annotated[
    CommissioningMotionTestService,
    Depends(get_commissioning_service),
]


def _status(value: CommissioningMotionStatus) -> CommissioningMotionStatusResponse:
    return CommissioningMotionStatusResponse(
        state=value.state,
        session_id=value.session_id,
        active_joint_id=value.active_joint_id,
        command_count=value.command_count,
        session_expires_at=value.session_expires_at,
        deadman_expires_at=value.deadman_expires_at,
        last_evidence_id=value.last_evidence_id,
        failure_reason=value.failure_reason,
        physical_stop_verification=value.physical_stop_verification,
    )


@router.get("/status", response_model=CommissioningMotionStatusResponse)
async def status(
    service: CommissioningServiceDependency,
) -> CommissioningMotionStatusResponse:
    return _status(await service.status())


@router.post(
    "/session",
    response_model=CommissioningMotionStatusResponse,
    dependencies=[Depends(authorize_control_request)],
)
async def start_session(
    service: CommissioningServiceDependency,
    token: OperatorToken,
) -> CommissioningMotionStatusResponse:
    return _status(await service.start_session(token))


@router.post(
    "/joints/{joint_id}/arm",
    response_model=CommissioningMotionStatusResponse,
    dependencies=[Depends(authorize_control_request)],
)
async def arm(
    joint_id: str,
    service: CommissioningServiceDependency,
    token: OperatorToken,
) -> CommissioningMotionStatusResponse:
    return _status(await service.arm(token, joint_id=joint_id))


@router.post(
    "/joints/{joint_id}/tests/start",
    response_model=CommissioningTestEvidence,
    dependencies=[Depends(authorize_control_request)],
)
async def run_test(
    joint_id: str,
    request_body: CommissioningRelativeTestRequest,
    http_request: Request,
    service: CommissioningServiceDependency,
    token: OperatorToken,
) -> CommissioningTestEvidence:
    evidence = await service.run_relative_test(
        token,
        joint_id=joint_id,
        signed_delta=request_body.signed_delta,
        requested_speed=request_body.requested_speed,
        requested_acceleration=request_body.requested_acceleration,
        command_duration_s=request_body.command_duration_s,
        request_id=request_body.request_id,
    )
    http_request.state.command_id = str(evidence.id)
    http_request.state.mode = "COMMISSIONING_MOTION_TEST"
    http_request.state.preflight = evidence.result.value
    http_request.state.audit_details = {
        "request_id": evidence.request_id,
        "session_id": str(evidence.session_id),
        "robot_unit_id": evidence.robot_unit_id,
        "joint_id": evidence.joint_id,
        "requested_delta": evidence.requested_delta,
        "requested_speed": evidence.requested_speed,
        "prepared_target_raw": evidence.prepared_target_raw,
        "before_raw": evidence.start_raw,
        "after_raw": evidence.final_raw,
        "before_logical": evidence.start_value,
        "after_logical": evidence.final_value,
        "result": evidence.result.value,
        "operator_id": evidence.operator_id,
        "software_commit": evidence.software_commit,
    }
    return evidence


@router.post(
    "/tests/heartbeat",
    response_model=CommissioningMotionStatusResponse,
    dependencies=[Depends(authorize_control_request)],
)
async def heartbeat(
    service: CommissioningServiceDependency,
    token: OperatorToken,
) -> CommissioningMotionStatusResponse:
    return _status(await service.heartbeat(token))


@router.post(
    "/tests/stop",
    response_model=CommissioningMotionStatusResponse,
    dependencies=[Depends(authorize_priority_stop_request)],
)
async def stop_test(
    service: CommissioningServiceDependency,
) -> CommissioningMotionStatusResponse:
    return _status(await service.priority_stop())


__all__ = ["router"]
