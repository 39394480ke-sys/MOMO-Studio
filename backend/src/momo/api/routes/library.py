"""Bounded Pose and Motion library API; no client filesystem paths are accepted."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from momo.api.dependencies import get_library_service
from momo.api.library_schemas import (
    LibrarySort,
    MotionListResponse,
    MotionSummary,
    PoseListResponse,
    PoseSummary,
    SortOrder,
)
from momo.api.security import authorize_control_request
from momo.application.library_commands import (
    DuplicateEntityCommand,
    GotoPoseCommand,
    MotionCreateCommand,
    MotionPatchCommand,
    PoseCaptureCommand,
    PoseCreateCommand,
    PosePatchCommand,
    Tag,
)
from momo.application.services.library_service import LibraryApplicationService
from momo.domain.motion import Motion
from momo.domain.motion_preflight import MotionAccepted
from momo.domain.pose import Pose

router = APIRouter(tags=["library"])
LibraryService = Annotated[LibraryApplicationService, Depends(get_library_service)]
Page = Annotated[int, Query(ge=1, le=100000)]
PageSize = Annotated[int, Query(ge=1, le=50)]
ExpectedRevisionQuery = Annotated[int, Query(ge=1)]


@router.get("/poses", response_model=PoseListResponse)
async def list_poses(
    service: LibraryService,
    page: Page = 1,
    page_size: PageSize = 24,
    search: Annotated[str | None, Query(max_length=200)] = None,
    tag: Annotated[list[Tag] | None, Query(max_length=32)] = None,
    sort: LibrarySort = "created_at",
    order: SortOrder = "desc",
) -> PoseListResponse:
    items, total = await service.list_poses(
        page=page,
        page_size=page_size,
        search=search,
        tags=tag or (),
        sort=sort,
        order=order,
    )
    summaries = [
        PoseSummary(
            id=item.id,
            name=item.name,
            description=item.description,
            tags=list(item.tags),
            robot_variant=item.snapshot.robot_variant,
            joint_state=item.snapshot.joint_state,
            tcp_pose=item.snapshot.tcp_pose,
            profile_fingerprint=item.snapshot.profile_fingerprint,
            kinematics_fingerprint=item.snapshot.kinematics_fingerprint,
            state_sequence=item.snapshot.state_sequence,
            created_at=item.created_at,
            updated_at=item.updated_at,
            revision=item.revision,
        )
        for item in items
    ]
    return PoseListResponse(items=summaries, page=page, page_size=page_size, total=total)


@router.post("/poses", response_model=Pose, status_code=status.HTTP_201_CREATED)
async def create_pose(request: PoseCreateCommand, service: LibraryService) -> Pose:
    return await service.create_pose(request)


@router.post("/poses/capture", response_model=Pose, status_code=status.HTTP_201_CREATED)
async def capture_pose(request: PoseCaptureCommand, service: LibraryService) -> Pose:
    return await service.capture_pose(request)


@router.get("/poses/{pose_id}", response_model=Pose)
async def get_pose(pose_id: UUID, service: LibraryService) -> Pose:
    return await service.get_pose(pose_id)


@router.patch("/poses/{pose_id}", response_model=Pose)
async def update_pose(pose_id: UUID, request: PosePatchCommand, service: LibraryService) -> Pose:
    return await service.update_pose(pose_id, request)


@router.delete("/poses/{pose_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pose(
    pose_id: UUID,
    service: LibraryService,
    expected_revision: ExpectedRevisionQuery,
) -> Response:
    await service.delete_pose(pose_id, expected_revision)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/poses/{pose_id}/duplicate", response_model=Pose, status_code=status.HTTP_201_CREATED)
async def duplicate_pose(
    pose_id: UUID, request: DuplicateEntityCommand, service: LibraryService
) -> Pose:
    return await service.duplicate_pose(pose_id, request)


@router.post(
    "/poses/{pose_id}/goto",
    response_model=MotionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(authorize_control_request)],
)
async def goto_pose(
    pose_id: UUID, request: GotoPoseCommand, service: LibraryService
) -> MotionAccepted:
    return await service.goto_pose(pose_id, request)


@router.get("/motions", response_model=MotionListResponse)
async def list_motions(
    service: LibraryService,
    page: Page = 1,
    page_size: PageSize = 24,
    search: Annotated[str | None, Query(max_length=200)] = None,
    tag: Annotated[list[Tag] | None, Query(max_length=32)] = None,
    sort: LibrarySort = "created_at",
    order: SortOrder = "desc",
) -> MotionListResponse:
    items, total = await service.list_motions(
        page=page,
        page_size=page_size,
        search=search,
        tags=tag or (),
        sort=sort,
        order=order,
    )
    summaries = []
    for item in items:
        transitions = [
            keyframe.incoming_transition
            for keyframe in item.keyframes
            if keyframe.incoming_transition is not None
        ]
        summaries.append(
            MotionSummary(
                id=item.id,
                name=item.name,
                description=item.description,
                robot_variant=item.robot_variant,
                keyframe_count=len(item.keyframes),
                total_duration_s=sum(frame.hold_s for frame in item.keyframes)
                + sum(transition.duration_s for transition in transitions),
                motion_types=sorted(
                    {transition.motion_mode for transition in transitions},
                    key=lambda mode: mode.value,
                ),
                tags=list(item.tags),
                created_at=item.created_at,
                updated_at=item.updated_at,
                revision=item.revision,
            )
        )
    return MotionListResponse(items=summaries, page=page, page_size=page_size, total=total)


@router.post("/motions", response_model=Motion, status_code=status.HTTP_201_CREATED)
async def create_motion(request: MotionCreateCommand, service: LibraryService) -> Motion:
    return await service.create_motion(request)


@router.get("/motions/{motion_id}", response_model=Motion)
async def get_motion(motion_id: UUID, service: LibraryService) -> Motion:
    return await service.get_motion(motion_id)


@router.patch("/motions/{motion_id}", response_model=Motion)
async def update_motion(
    motion_id: UUID, request: MotionPatchCommand, service: LibraryService
) -> Motion:
    return await service.update_motion(motion_id, request)


@router.delete("/motions/{motion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_motion(
    motion_id: UUID,
    service: LibraryService,
    expected_revision: ExpectedRevisionQuery,
) -> Response:
    await service.delete_motion(motion_id, expected_revision)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/motions/{motion_id}/duplicate",
    response_model=Motion,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_motion(
    motion_id: UUID, request: DuplicateEntityCommand, service: LibraryService
) -> Motion:
    return await service.duplicate_motion(motion_id, request)
