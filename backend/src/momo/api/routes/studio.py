"""Recoverable Studio drafts and compiler-backed conversion; no executable input exists."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from momo.api.dependencies import get_studio_service
from momo.api.studio_schemas import (
    MotionDraftCompileResponse,
    MotionDraftListResponse,
    MotionDraftSaveResponse,
    MotionDraftSummary,
    MotionDraftValidationIssue,
    MotionDraftValidationResponse,
    StudioCaptureRequest,
)
from momo.api.trajectory_presenters import preflight_response, preview_response
from momo.application.services.studio_service import StudioApplicationService
from momo.application.studio_commands import (
    MotionDraftAbandonSaveIntentCommand,
    MotionDraftAutosaveCommand,
    MotionDraftCompileCommand,
    MotionDraftCreateCommand,
    MotionDraftGotoCommand,
    MotionDraftRevisionCommand,
    MotionDraftSaveAsCommand,
    MotionDraftSaveCommand,
)
from momo.domain.motion_draft import MotionDraft
from momo.domain.motion_preflight import MotionAccepted
from momo.domain.pose import PoseSnapshot

router = APIRouter(prefix="/studio", tags=["studio"])
StudioService = Annotated[StudioApplicationService, Depends(get_studio_service)]
Page = Annotated[int, Query(ge=1, le=100000)]
PageSize = Annotated[int, Query(ge=1, le=50)]
ExpectedRevisionQuery = Annotated[int, Query(ge=1)]


@router.get("/drafts", response_model=MotionDraftListResponse)
async def list_drafts(
    service: StudioService,
    page: Page = 1,
    page_size: PageSize = 24,
) -> MotionDraftListResponse:
    items, total = await service.list_drafts(page=page, page_size=page_size)
    return MotionDraftListResponse(
        items=[
            MotionDraftSummary(
                id=item.id,
                source_motion_id=item.source_motion_id,
                source_motion_revision=item.source_motion_revision,
                name=item.name,
                robot_variant=item.robot_variant,
                keyframe_count=len(item.keyframes),
                created_at=item.created_at,
                updated_at=item.updated_at,
                revision=item.revision,
            )
            for item in items
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/drafts", response_model=MotionDraft, status_code=status.HTTP_201_CREATED)
async def create_draft(
    request: MotionDraftCreateCommand,
    service: StudioService,
) -> MotionDraft:
    return await service.create_draft(request)


@router.post(
    "/drafts/from-motion/{motion_id}",
    response_model=MotionDraft,
    status_code=status.HTTP_201_CREATED,
)
async def open_motion_as_draft(
    motion_id: UUID,
    request: MotionDraftRevisionCommand,
    service: StudioService,
) -> MotionDraft:
    return await service.open_motion(motion_id, expected_revision=request.expected_revision)


@router.get("/drafts/{draft_id}", response_model=MotionDraft)
async def get_draft(draft_id: UUID, service: StudioService) -> MotionDraft:
    return await service.get_draft(draft_id)


@router.put("/drafts/{draft_id}", response_model=MotionDraft)
async def autosave_draft(
    draft_id: UUID,
    request: MotionDraftAutosaveCommand,
    service: StudioService,
) -> MotionDraft:
    return await service.autosave_draft(draft_id, request)


@router.post(
    "/drafts/{draft_id}/fork",
    response_model=MotionDraft,
    status_code=status.HTTP_201_CREATED,
)
async def fork_draft(
    draft_id: UUID,
    request: MotionDraftRevisionCommand,
    service: StudioService,
) -> MotionDraft:
    return await service.fork_draft(draft_id, request)


@router.delete("/drafts/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft(
    draft_id: UUID,
    service: StudioService,
    expected_revision: ExpectedRevisionQuery,
) -> Response:
    await service.delete_draft(draft_id, expected_revision=expected_revision)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/drafts/{draft_id}/save-intent/abandon", response_model=MotionDraft)
async def abandon_draft_save_intent(
    draft_id: UUID,
    request: MotionDraftAbandonSaveIntentCommand,
    service: StudioService,
) -> MotionDraft:
    return await service.abandon_save_intent(draft_id, request)


@router.post(
    "/drafts/{draft_id}/keyframes/{keyframe_id}/goto",
    response_model=MotionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def goto_draft_keyframe(
    draft_id: UUID,
    keyframe_id: UUID,
    request: MotionDraftGotoCommand,
    service: StudioService,
) -> MotionAccepted:
    return await service.goto_keyframe(draft_id, keyframe_id, request)


@router.post("/drafts/{draft_id}/validate", response_model=MotionDraftValidationResponse)
async def validate_draft(
    draft_id: UUID,
    request: MotionDraftRevisionCommand,
    service: StudioService,
) -> MotionDraftValidationResponse:
    result = await service.validate_draft(
        draft_id,
        expected_revision=request.expected_revision,
    )
    return MotionDraftValidationResponse(
        draft_id=result.draft.id,
        draft_revision=result.draft.revision,
        valid=result.valid,
        issues=[
            MotionDraftValidationIssue(code=item.code, message=item.message)
            for item in result.issues
        ],
    )


@router.post("/drafts/{draft_id}/compile", response_model=MotionDraftCompileResponse)
async def compile_draft(
    draft_id: UUID,
    request: MotionDraftCompileCommand,
    service: StudioService,
) -> MotionDraftCompileResponse:
    result = await service.compile_draft(draft_id, request)
    prepared = result.outcome.prepared
    return MotionDraftCompileResponse(
        draft_id=result.draft.id,
        draft_revision=result.draft.revision,
        preflight=preflight_response(result.outcome),
        preview=(preview_response(prepared, result.candidate) if prepared is not None else None),
        executable=False,
    )


@router.post("/drafts/{draft_id}/save", response_model=MotionDraftSaveResponse)
async def save_draft(
    draft_id: UUID,
    request: MotionDraftSaveCommand,
    service: StudioService,
) -> MotionDraftSaveResponse:
    result = await service.save_draft(draft_id, request)
    return MotionDraftSaveResponse(
        draft=result.draft,
        motion=result.motion,
        preflight=preflight_response(result.outcome),
    )


@router.post(
    "/drafts/{draft_id}/save-as",
    response_model=MotionDraftSaveResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_draft_as(
    draft_id: UUID,
    request: MotionDraftSaveAsCommand,
    service: StudioService,
) -> MotionDraftSaveResponse:
    result = await service.save_draft_as(draft_id, request)
    return MotionDraftSaveResponse(
        draft=result.draft,
        motion=result.motion,
        preflight=preflight_response(result.outcome),
    )


@router.post("/capture", response_model=PoseSnapshot)
async def capture_snapshot(
    request: StudioCaptureRequest,
    service: StudioService,
) -> PoseSnapshot:
    del request
    return await service.capture_snapshot()
