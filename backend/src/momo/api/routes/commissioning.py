"""Capability-narrow commissioning routes; no route imports a Servo driver."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from momo.api.commissioning_schemas import (
    CommissioningDirectControlResponse,
    CommissioningDirectJogStartRequest,
    CommissioningDirectJointStateResponse,
    CommissioningDirectStepRequest,
    CommissioningMotionStatusResponse,
    CommissioningRelativeTestRequest,
    RawDirectionAlignmentRequest,
    RawDirectionDraftConfirmationRequest,
    RawDirectionStatusResponse,
    RawDirectionStepRequest,
)
from momo.api.dependencies import OperatorToken
from momo.api.security import (
    authorize_control_keepalive_request,
    authorize_control_request,
    authorize_priority_stop_request,
)
from momo.application.services.commissioning_motion_test_service import (
    CommissioningDirectControlResult,
    CommissioningDirectJointStateResult,
    CommissioningMotionConflictError,
    CommissioningMotionStatus,
    CommissioningMotionTestService,
)
from momo.application.services.raw_direction_test_service import (
    RawDirectionConflictError,
    RawDirectionStatus,
    RawDirectionTestService,
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


def get_raw_direction_service(request: Request) -> RawDirectionTestService:
    service = getattr(request.app.state, "raw_direction_test_service", None)
    if service is None:
        raise RawDirectionConflictError(
            "Raw direction software chain is installed but physical execution is disabled",
            details={"reason": "RAW_DIRECTION_ADAPTER_UNAVAILABLE"},
        )
    return cast(RawDirectionTestService, service)


RawDirectionServiceDependency = Annotated[
    RawDirectionTestService,
    Depends(get_raw_direction_service),
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


def _direct(value: CommissioningDirectControlResult) -> CommissioningDirectControlResponse:
    return CommissioningDirectControlResponse(**asdict(value))


def _direct_state(
    value: CommissioningDirectJointStateResult,
) -> CommissioningDirectJointStateResponse:
    return CommissioningDirectJointStateResponse(**asdict(value))


def _raw_status(value: RawDirectionStatus) -> RawDirectionStatusResponse:
    return RawDirectionStatusResponse.model_validate(asdict(value))


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
    "/joints/{joint_id}/direct/step",
    response_model=CommissioningDirectControlResponse,
    dependencies=[Depends(authorize_control_request)],
)
async def direct_step(
    joint_id: str,
    request_body: CommissioningDirectStepRequest,
    service: CommissioningServiceDependency,
    token: OperatorToken,
) -> CommissioningDirectControlResponse:
    return _direct(
        await service.direct_step(
            token,
            joint_id=joint_id,
            signed_delta=request_body.signed_delta,
            requested_speed=request_body.requested_speed,
        )
    )


@router.get(
    "/direct/jog/status",
    response_model=CommissioningDirectControlResponse,
)
async def direct_jog_status(
    service: CommissioningServiceDependency,
) -> CommissioningDirectControlResponse:
    return _direct(await service.direct_jog_status())


@router.get(
    "/direct/joints/state",
    response_model=CommissioningDirectJointStateResponse,
)
async def direct_joint_state(
    service: CommissioningServiceDependency,
    token: OperatorToken,
) -> CommissioningDirectJointStateResponse:
    return _direct_state(await service.read_direct_joint_state(token))


@router.post(
    "/joints/{joint_id}/direct/jog/start",
    response_model=CommissioningDirectControlResponse,
    dependencies=[Depends(authorize_control_request)],
)
async def start_direct_jog(
    joint_id: str,
    request_body: CommissioningDirectJogStartRequest,
    service: CommissioningServiceDependency,
    token: OperatorToken,
) -> CommissioningDirectControlResponse:
    return _direct(
        await service.start_direct_jog(
            token,
            joint_id=joint_id,
            direction=request_body.direction,
            requested_speed=request_body.requested_speed,
        )
    )


@router.post(
    "/direct/jog/heartbeat",
    response_model=CommissioningDirectControlResponse,
    dependencies=[Depends(authorize_control_keepalive_request)],
)
async def heartbeat_direct_jog(
    service: CommissioningServiceDependency,
    token: OperatorToken,
) -> CommissioningDirectControlResponse:
    return _direct(await service.heartbeat_direct_jog(token))


@router.post(
    "/direct/jog/stop",
    response_model=CommissioningDirectControlResponse,
    dependencies=[Depends(authorize_priority_stop_request)],
)
async def stop_direct_jog(
    service: CommissioningServiceDependency,
) -> CommissioningDirectControlResponse:
    return _direct(await service.stop_direct_jog())


@router.post(
    "/direct/jog/release",
    response_model=CommissioningDirectControlResponse,
    dependencies=[Depends(authorize_control_request)],
)
async def release_direct_jog(
    service: CommissioningServiceDependency,
    token: OperatorToken,
) -> CommissioningDirectControlResponse:
    return _direct(await service.release_direct_jog(token))


@router.post(
    "/tests/heartbeat",
    response_model=CommissioningMotionStatusResponse,
    dependencies=[Depends(authorize_control_keepalive_request)],
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


@router.get("/raw-direction/status", response_model=RawDirectionStatusResponse)
async def raw_direction_status(
    service: RawDirectionServiceDependency,
) -> RawDirectionStatusResponse:
    return _raw_status(await service.status())


@router.post(
    "/raw-direction/session",
    response_model=RawDirectionStatusResponse,
    dependencies=[Depends(authorize_control_request)],
)
async def start_raw_direction_session(
    service: RawDirectionServiceDependency,
    token: OperatorToken,
) -> RawDirectionStatusResponse:
    return _raw_status(await service.start_session(token))


@router.post(
    "/raw-direction/joints/{joint_id}/arm",
    response_model=RawDirectionStatusResponse,
    dependencies=[Depends(authorize_control_request)],
)
async def arm_raw_direction(
    joint_id: str,
    service: RawDirectionServiceDependency,
    token: OperatorToken,
) -> RawDirectionStatusResponse:
    return _raw_status(await service.arm(token, joint_id))


@router.post(
    "/raw-direction/joints/{joint_id}/step",
    response_model=RawDirectionStatusResponse,
    dependencies=[Depends(authorize_control_request)],
)
async def step_raw_direction(
    joint_id: str,
    body: RawDirectionStepRequest,
    service: RawDirectionServiceDependency,
    token: OperatorToken,
) -> RawDirectionStatusResponse:
    return _raw_status(await service.step(token, joint_id=joint_id, direction=body.direction))


@router.post(
    "/raw-direction/heartbeat",
    response_model=RawDirectionStatusResponse,
    dependencies=[Depends(authorize_control_keepalive_request)],
)
async def heartbeat_raw_direction(
    service: RawDirectionServiceDependency,
    token: OperatorToken,
) -> RawDirectionStatusResponse:
    return _raw_status(await service.heartbeat(token))


@router.post(
    "/raw-direction/joints/{joint_id}/alignment",
    response_model=RawDirectionStatusResponse,
    dependencies=[Depends(authorize_control_request)],
)
async def record_raw_direction_alignment(
    joint_id: str,
    body: RawDirectionAlignmentRequest,
    service: RawDirectionServiceDependency,
    token: OperatorToken,
) -> RawDirectionStatusResponse:
    return _raw_status(
        await service.record_urdf_alignment(
            token,
            joint_id=joint_id,
            matches_urdf=body.matches_urdf,
        )
    )


@router.post(
    "/raw-direction/draft/confirm",
    response_model=RawDirectionStatusResponse,
    dependencies=[Depends(authorize_control_request)],
)
async def confirm_raw_direction_draft(
    body: RawDirectionDraftConfirmationRequest,
    service: RawDirectionServiceDependency,
    token: OperatorToken,
) -> RawDirectionStatusResponse:
    return _raw_status(
        await service.confirm_calibration_draft(
            token,
            confirmation_text=body.confirmation_text,
        )
    )


@router.post(
    "/raw-direction/stop",
    response_model=RawDirectionStatusResponse,
    dependencies=[Depends(authorize_priority_stop_request)],
)
async def stop_raw_direction(
    service: RawDirectionServiceDependency,
) -> RawDirectionStatusResponse:
    return _raw_status(await service.priority_stop())


__all__ = ["router"]
