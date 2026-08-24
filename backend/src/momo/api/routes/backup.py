"""Configuration-free backup download, dry-run preview, and confirmed restore."""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

from momo.api.backup_schemas import (
    BACKUP_MEDIA_TYPE,
    BackupExportRequest,
    BackupImportPreviewResponse,
    BackupRestoreResponse,
)
from momo.api.security import (
    authorize_control_request,
    authorize_rest_request,
    read_bounded_body,
)
from momo.application.services.backup_service import BackupApplicationService
from momo.domain.backup import (
    MAX_BACKUP_UPLOAD_BYTES,
    BackupCollisionPolicy,
)
from momo.domain.security import AuthorizedPrincipal

router = APIRouter(prefix="/backup", tags=["backup"])
BackupDigest = Annotated[
    str,
    Header(alias="X-MOMO-Backup-SHA256", pattern=r"^[0-9a-f]{64}$"),
]
RestoreConfirmation = Annotated[
    Literal["RESTORE"],
    Header(alias="X-MOMO-Restore-Confirmation"),
]
CollisionPolicyQuery = Annotated[BackupCollisionPolicy, Query()]
AllowCalibrationQuery = Annotated[bool, Query()]
AuthorizedRest = Annotated[AuthorizedPrincipal, Depends(authorize_rest_request)]
AuthorizedControl = Annotated[AuthorizedPrincipal, Depends(authorize_control_request)]

_RAW_BODY_OPENAPI = {
    "requestBody": {
        "required": True,
        "content": {BACKUP_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
    }
}


def get_backup_service(request: Request) -> BackupApplicationService:
    return cast(BackupApplicationService, request.app.state.backup_service)


BackupServiceDependency = Annotated[BackupApplicationService, Depends(get_backup_service)]


@router.post("/export", response_class=Response)
async def export_backup(
    command: BackupExportRequest,
    service: BackupServiceDependency,
    _principal: AuthorizedRest,
) -> Response:
    envelope = await service.export_bundle(include_calibration=command.include_calibration)
    content = envelope.to_bytes()
    return Response(
        content=content,
        media_type=BACKUP_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Content-Disposition": 'attachment; filename="momo-studio-backup.json"',
            "X-MOMO-Backup-SHA256": envelope.sha256,
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/import/preview",
    response_model=BackupImportPreviewResponse,
    openapi_extra=_RAW_BODY_OPENAPI,
)
async def preview_backup_import(
    request: Request,
    service: BackupServiceDependency,
    _principal: AuthorizedRest,
    collision_policy: CollisionPolicyQuery = BackupCollisionPolicy.REJECT,
    allow_calibration: AllowCalibrationQuery = False,
) -> BackupImportPreviewResponse:
    _require_backup_content_type(request)
    content = await read_bounded_body(request, maximum_bytes=MAX_BACKUP_UPLOAD_BYTES)
    return await service.preview_import(
        content,
        collision_policy=collision_policy,
        allow_calibration=allow_calibration,
    )


@router.post(
    "/import/restore",
    response_model=BackupRestoreResponse,
    openapi_extra=_RAW_BODY_OPENAPI,
)
async def restore_backup(
    request: Request,
    service: BackupServiceDependency,
    _principal: AuthorizedControl,
    expected_bundle_sha256: BackupDigest,
    confirmation: RestoreConfirmation,
    collision_policy: CollisionPolicyQuery = BackupCollisionPolicy.REJECT,
    allow_calibration: AllowCalibrationQuery = False,
) -> BackupRestoreResponse:
    _require_backup_content_type(request)
    content = await read_bounded_body(request, maximum_bytes=MAX_BACKUP_UPLOAD_BYTES)
    return await service.restore_bundle(
        content,
        expected_bundle_sha256=expected_bundle_sha256,
        confirmation=confirmation,
        collision_policy=collision_policy,
        allow_calibration=allow_calibration,
    )


def _require_backup_content_type(request: Request) -> None:
    media_type = request.headers.get("content-type", "").partition(";")[0].strip().casefold()
    if media_type != BACKUP_MEDIA_TYPE:
        raise HTTPException(
            status_code=415,
            detail={
                "code": "BACKUP_MEDIA_TYPE_REQUIRED",
                "message": f"Content-Type must be {BACKUP_MEDIA_TYPE}",
            },
        )
