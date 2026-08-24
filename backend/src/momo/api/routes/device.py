"""Explicit Stage 8 device routes; none performs automatic discovery or connection."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, Request, Response

from momo.api.real_hardware_schemas import (
    DeviceDiagnosticsResponse,
    HardwareArtifactResponse,
    HardwareConfirmationResponse,
    HardwareDependencyResponse,
    OperatorSessionCreateRequest,
    OperatorSessionCreateResponse,
    OperatorSessionStatusResponse,
    RealHardwareCapabilityReadinessResponse,
    RealHardwareReadinessResponse,
    RealStopOutcomeResponse,
    ServoDiagnosticResponse,
)
from momo.api.security import authorize_control_request, authorize_priority_stop_request
from momo.application.services.device_diagnostics_service import DeviceDiagnosticsService
from momo.domain.real_hardware import (
    DeviceDiagnosticsSnapshot,
    HardwareConfirmationEvidence,
    RealHardwareReadinessReport,
    RealStopOutcome,
)

router = APIRouter(prefix="/device", tags=["device"])


def get_device_diagnostics_service(request: Request) -> DeviceDiagnosticsService:
    """Local dependency keeps this route independent of adapters and raw drivers."""

    return cast(DeviceDiagnosticsService, request.app.state.device_diagnostics_service)


DeviceServiceDependency = Annotated[
    DeviceDiagnosticsService,
    Depends(get_device_diagnostics_service),
]
OperatorToken = Annotated[
    str,
    Header(
        alias="X-MOMO-Operator-Session",
        min_length=20,
        max_length=200,
    ),
]


def _confirmation(value: HardwareConfirmationEvidence) -> HardwareConfirmationResponse:
    return HardwareConfirmationResponse(
        robot_id=value.robot_id,
        variant=value.variant,
        profile_fingerprint=value.profile_fingerprint,
        calibration_fingerprint=value.calibration_fingerprint,
        kinematics_fingerprint=value.kinematics_fingerprint,
        masked_serial_port=value.masked_serial_port,
        masked_servo_ids=list(value.masked_servo_ids),
        protocol=value.protocol,
        physical_estop_required=True,
        required_confirmation_text=value.required_confirmation_text,
    )


def _readiness(
    report: RealHardwareReadinessReport,
    *,
    connected: bool,
) -> RealHardwareReadinessResponse:
    session = report.session
    return RealHardwareReadinessResponse(
        state=report.state,
        ready=report.ready,
        session_authorizable=report.session_authorizable,
        blocking_reasons=[item.value for item in report.blocking_reasons],
        capabilities=RealHardwareCapabilityReadinessResponse.model_validate(
            report.capabilities.model_dump(mode="python")
        ),
        confirmation=_confirmation(report.confirmation),
        session=(
            OperatorSessionStatusResponse(
                active=session.active,
                session_id=session.session_id,
                expires_at=session.expires_at,
            )
            if session is not None
            else None
        ),
        connected=connected,
    )


def _diagnostics(value: DeviceDiagnosticsSnapshot) -> DeviceDiagnosticsResponse:
    return DeviceDiagnosticsResponse(
        connected=value.connected,
        captured_at=value.captured_at,
        dependency=HardwareDependencyResponse.model_validate(
            value.dependency.model_dump(mode="python")
        ),
        hardware_policy=value.hardware_policy,
        masked_serial_port=value.masked_serial_port,
        masked_servo_ids=list(value.masked_servo_ids),
        protocol=value.protocol,
        profile=HardwareArtifactResponse.model_validate(value.profile.model_dump(mode="python")),
        calibration=HardwareArtifactResponse.model_validate(
            value.calibration.model_dump(mode="python")
        ),
        kinematics=HardwareArtifactResponse.model_validate(
            value.kinematics.model_dump(mode="python")
        ),
        field_acceptance=value.field_acceptance,
        readiness=value.readiness,
        records=[
            ServoDiagnosticResponse(
                joint_id=item.joint_id,
                masked_servo_id=item.masked_servo_id,
                ping_responded=item.ping_responded,
                operating_mode=item.operating_mode,
                present_raw=item.present_raw,
                logical_value=item.logical_value,
                raw_bounds=item.raw_bounds,
                torque_enabled=item.torque_enabled,
            )
            for item in value.records
        ],
        last_error=value.last_error,
    )


def _stop(value: RealStopOutcome) -> RealStopOutcomeResponse:
    return RealStopOutcomeResponse(
        result=value.result,
        connected=value.connected,
        safety_state_known=value.safety_state_known,
        requested_count=len(value.requested_ids),
        affected_count=len(value.affected_ids),
        detail=value.detail,
    )


@router.get("/readiness", response_model=RealHardwareReadinessResponse)
async def readiness(service: DeviceServiceDependency) -> RealHardwareReadinessResponse:
    return _readiness(await service.readiness(), connected=service.connected)


@router.post("/operator-session", response_model=OperatorSessionCreateResponse)
async def create_operator_session(
    request: OperatorSessionCreateRequest,
    response: Response,
    service: DeviceServiceDependency,
) -> OperatorSessionCreateResponse:
    response.headers["Cache-Control"] = "no-store"
    issued = await service.issue_operator_session(
        confirmation_text=request.confirmation_text,
        physical_estop_confirmed=request.physical_estop_confirmed,
    )
    evidence = issued.evidence
    confirmation = service.authorization.confirmation_for(service.context)
    return OperatorSessionCreateResponse(
        session_token=issued.session_token.get_secret_value(),
        session_id=evidence.session_id,
        issued_at=evidence.issued_at,
        expires_at=evidence.expires_at,
        evidence=_confirmation(confirmation),
    )


@router.delete("/operator-session", response_model=RealHardwareReadinessResponse)
async def revoke_operator_session(
    service: DeviceServiceDependency,
    token: OperatorToken,
) -> RealHardwareReadinessResponse:
    await service.revoke_operator_session(token)
    return _readiness(await service.readiness(), connected=service.connected)


@router.post(
    "/connect",
    response_model=DeviceDiagnosticsResponse,
    dependencies=[Depends(authorize_control_request)],
)
async def connect(
    service: DeviceServiceDependency,
    token: OperatorToken,
) -> DeviceDiagnosticsResponse:
    return _diagnostics(await service.connect(token))


@router.post("/diagnostics", response_model=DeviceDiagnosticsResponse)
async def diagnostics(
    service: DeviceServiceDependency,
    token: OperatorToken,
) -> DeviceDiagnosticsResponse:
    return _diagnostics(await service.diagnostics(token))


@router.post(
    "/disconnect",
    response_model=DeviceDiagnosticsResponse,
    dependencies=[Depends(authorize_control_request)],
)
async def disconnect(
    service: DeviceServiceDependency,
    token: OperatorToken,
) -> DeviceDiagnosticsResponse:
    return _diagnostics(await service.disconnect(token))


@router.post(
    "/stop",
    response_model=RealStopOutcomeResponse,
    dependencies=[Depends(authorize_priority_stop_request)],
)
async def stop(service: DeviceServiceDependency) -> RealStopOutcomeResponse:
    return _stop(await service.stop())
