"""Direct branch-table tests for Studio's lock-free formal-save coordinator."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import timedelta
from typing import Literal
from uuid import UUID, uuid4

import pytest

from momo.application.services.studio_formal_save_coordinator import (
    StudioFormalSaveCoordinator,
)
from momo.domain.errors import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
    RevisionConflictError,
)
from momo.domain.motion import Motion
from momo.domain.motion_draft import MotionDraft, MotionDraftSaveIntent
from momo.domain.trajectory import TrajectoryCompileOutcome
from tests.factories import make_motion
from tests.stage3_helpers import FakeClock

TargetState = Literal["missing", "below", "exact", "advanced", "identity"]
RecoveryAction = Literal["clear", "bind", "conflict"]


class MemoryDraftRepository:
    def __init__(self) -> None:
        self.entities: dict[UUID, MotionDraft] = {}

    async def get(self, draft_id: UUID) -> MotionDraft | None:
        return self.entities.get(draft_id)

    async def list(self) -> Sequence[MotionDraft]:
        return tuple(self.entities.values())

    async def save(
        self,
        draft: MotionDraft,
        *,
        expected_revision: int | None = None,
    ) -> None:
        current = self.entities.get(draft.id)
        if expected_revision is not None and (
            current is None or current.revision != expected_revision
        ):
            raise RevisionConflictError(
                "Entity revision changed",
                details={
                    "expected_revision": expected_revision,
                    "actual_revision": current.revision if current is not None else None,
                },
            )
        self.entities[draft.id] = draft

    async def import_exact(self, draft: MotionDraft) -> bool:
        if draft.id in self.entities:
            raise EntityAlreadyExistsError("Motion draft already exists")
        self.entities[draft.id] = draft
        return False

    async def delete(self, draft_id: UUID, *, expected_revision: int) -> bool:
        current = self.entities.get(draft_id)
        if current is None:
            return False
        if current.revision != expected_revision:
            raise RevisionConflictError(
                "Entity revision changed",
                details={
                    "expected_revision": expected_revision,
                    "actual_revision": current.revision,
                },
            )
        del self.entities[draft_id]
        return True


class RecoveryLibrary:
    def __init__(self) -> None:
        self.motions: dict[UUID, Motion] = {}

    async def get_motion(self, motion_id: UUID) -> Motion:
        try:
            return self.motions[motion_id]
        except KeyError as error:
            raise EntityNotFoundError("Motion was not found") from error

    async def persist_motion_candidate(
        self,
        motion: Motion,
        *,
        expected_revision: int | None,
        trusted_legacy_snapshot_sha256: frozenset[str] = frozenset(),
    ) -> Motion:
        del motion, expected_revision, trusted_legacy_snapshot_sha256
        raise AssertionError("recovery must not persist a Motion")


async def unused_compile(
    motion: Motion,
    *,
    sample_rate_hz: float,
) -> TrajectoryCompileOutcome:
    del motion, sample_rate_hz
    raise AssertionError("recovery must not compile")


async def unused_freshness_check(draft: MotionDraft) -> None:
    del draft
    raise AssertionError("recovery must not run the compile freshness check")


def make_coordinator_fixture(
    *,
    kind: Literal["SAVE", "SAVE_AS"],
    has_source: bool,
    target_state: TargetState,
    semantic_match: bool,
) -> tuple[
    StudioFormalSaveCoordinator,
    MemoryDraftRepository,
    RecoveryLibrary,
    MotionDraft,
    Motion | None,
]:
    clock = FakeClock()
    repository = MemoryDraftRepository()
    library = RecoveryLibrary()
    source_motion_id = uuid4() if has_source else None
    source_motion_revision = 1 if has_source else None
    known_source_save = kind == "SAVE" and source_motion_id is not None
    target_motion_id = source_motion_id if known_source_save else uuid4()
    assert target_motion_id is not None
    target_motion_revision = 2 if known_source_save else 1
    expected_motion_revision = 1 if known_source_save else None
    target_created_at = clock.now()
    base = make_motion()
    intent = MotionDraftSaveIntent(
        kind=kind,
        target_motion_id=target_motion_id,
        target_motion_revision=target_motion_revision,
        expected_motion_revision=expected_motion_revision,
        target_name="Intended formal name",
        target_motion_created_at=target_created_at,
        started_at=clock.now(),
    )
    draft = MotionDraft(
        source_motion_id=source_motion_id,
        source_motion_revision=source_motion_revision,
        name="Draft before recovery",
        description="Exact embedded document",
        robot_variant=base.robot_variant,
        keyframes=list(base.keyframes),
        playback_defaults=base.playback_defaults,
        tags=["recovery"],
        save_intent=intent,
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    repository.entities[draft.id] = draft

    target: Motion | None = None
    if target_state != "missing":
        if target_state == "below":
            revision = target_motion_revision - 1
        elif target_state == "advanced":
            revision = target_motion_revision + 1
        else:
            revision = target_motion_revision
        target = Motion(
            id=target_motion_id,
            name=intent.target_name,
            description=(draft.description if semantic_match else "Different concurrent content"),
            robot_variant=draft.robot_variant,
            keyframes=list(draft.keyframes),
            playback_defaults=draft.playback_defaults,
            tags=list(draft.tags),
            created_at=(
                target_created_at + timedelta(seconds=1)
                if target_state == "identity"
                else target_created_at
            ),
            updated_at=clock.now() + timedelta(seconds=1),
            revision=revision,
        )
        library.motions[target.id] = target

    coordinator = StudioFormalSaveCoordinator(
        repository,
        library,
        clock,
        unused_compile,
        unused_freshness_check,
    )
    return coordinator, repository, library, draft, target


@pytest.mark.parametrize(
    (
        "kind",
        "has_source",
        "target_state",
        "semantic_match",
        "expected_action",
        "expected_reason",
    ),
    [
        ("SAVE", False, "missing", True, "clear", None),
        ("SAVE_AS", False, "exact", True, "bind", None),
        (
            "SAVE",
            False,
            "exact",
            False,
            "conflict",
            "FORMAL_SAVE_TARGET_CONTENT_MISMATCH",
        ),
        (
            "SAVE_AS",
            False,
            "advanced",
            True,
            "conflict",
            "FORMAL_SAVE_TARGET_REVISION_ADVANCED",
        ),
        (
            "SAVE",
            False,
            "identity",
            True,
            "conflict",
            "FORMAL_SAVE_TARGET_IDENTITY_MISMATCH",
        ),
        ("SAVE", True, "below", False, "clear", None),
        ("SAVE", True, "exact", False, "clear", None),
        ("SAVE", True, "exact", True, "bind", None),
        ("SAVE", True, "advanced", False, "bind", None),
    ],
    ids=(
        "fresh-save-missing-clears",
        "save-as-exact-match-binds",
        "fresh-save-exact-mismatch-fails-closed",
        "save-as-advanced-fails-closed",
        "fresh-identity-mismatch-fails-closed",
        "known-save-behind-clears",
        "known-save-exact-mismatch-clears",
        "known-save-exact-match-binds",
        "known-save-advanced-binds-intended-revision",
    ),
)
def test_recovery_branch_table_directly(
    kind: Literal["SAVE", "SAVE_AS"],
    has_source: bool,
    target_state: TargetState,
    semantic_match: bool,
    expected_action: RecoveryAction,
    expected_reason: str | None,
) -> None:
    async def scenario() -> None:
        coordinator, repository, _, draft, target = make_coordinator_fixture(
            kind=kind,
            has_source=has_source,
            target_state=target_state,
            semantic_match=semantic_match,
        )
        intent = draft.save_intent
        assert intent is not None

        if expected_action == "conflict":
            with pytest.raises(RevisionConflictError) as raised:
                await coordinator.recover_save_intent(draft)
            assert target is not None
            assert raised.value.details == {
                "entity": "Motion",
                "reason": expected_reason,
                "draft_id": str(draft.id),
                "draft_revision": draft.revision,
                "operation_id": str(intent.operation_id),
                "kind": intent.kind,
                "target_motion_id": str(intent.target_motion_id),
                "target_motion_revision": intent.target_motion_revision,
                "expected_motion_revision": intent.expected_motion_revision,
                "started_at": intent.started_at.isoformat(),
                "actual_target_revision": target.revision,
            }
            assert repository.entities[draft.id] == draft
            return

        recovered = await coordinator.recover_save_intent(draft)
        assert recovered.save_intent is None
        assert recovered.revision == draft.revision + 1
        assert repository.entities[draft.id] == recovered
        if expected_action == "bind":
            assert target is not None
            assert recovered.source_motion_id == target.id
            assert recovered.source_motion_revision == intent.target_motion_revision
            assert recovered.name == intent.target_name
        else:
            assert recovered.source_motion_id == draft.source_motion_id
            assert recovered.source_motion_revision == draft.source_motion_revision
            assert recovered.name == draft.name

    asyncio.run(scenario())


def test_abandon_directly_is_exact_cas_and_coordinator_owns_no_lock() -> None:
    async def scenario() -> None:
        coordinator, repository, library, draft, _ = make_coordinator_fixture(
            kind="SAVE_AS",
            has_source=False,
            target_state="advanced",
            semantic_match=False,
        )
        assert "_mutation_lock" not in vars(coordinator)
        assert "_compile_lock" not in vars(coordinator)
        intent = draft.save_intent
        assert intent is not None
        motions_before = dict(library.motions)

        abandoned = await coordinator.abandon_save_intent(
            draft.id,
            expected_revision=draft.revision,
            operation_id=intent.operation_id,
        )

        assert abandoned.save_intent is None
        assert abandoned.revision == draft.revision + 1
        assert repository.entities[draft.id] == abandoned
        assert library.motions == motions_before
        before = draft.model_dump(mode="python")
        after = abandoned.model_dump(mode="python")
        for field in ("save_intent", "revision", "updated_at"):
            before.pop(field)
            after.pop(field)
        assert after == before

    asyncio.run(scenario())
