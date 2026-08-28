"""HTTP request/response models for raw, path-free backup transfer."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from momo.domain.backup import BackupImportPreview, BackupRestoreResult

BACKUP_MEDIA_TYPE = "application/vnd.momo.backup+json"


class BackupExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_calibration: bool = False


class BackupRestoreConfirmation(BaseModel):
    """Documentation-only shape for clients using the required restore headers."""

    model_config = ConfigDict(extra="forbid")

    bundle_sha256: str
    confirmation: Literal["RESTORE"]


BackupImportPreviewResponse = BackupImportPreview
BackupRestoreResponse = BackupRestoreResult
