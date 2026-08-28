"""Crash-recoverable Studio formal-save transaction coordination."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from pydantic import ValidationError

from momo.application.services.library_service import TrustedLegacySnapshotDigests
from momo.domain.errors import (
    EntityInvalidError,
    EntityNotFoundError,
    MotionPreflightError,
    RevisionConflictError,
)
from momo.domain.motion import Motion
from momo.domain.motion_draft import MotionDraft, MotionDraftSaveIntent
from momo.domain.trajectory import TrajectoryCompileOutcome
from momo.ports.clock import Clock
from momo.ports.motion_draft_repository import MotionDraftRepository

RevisionEntity = Literal["MotionDraft", "Motion"]
FormalSaveKind = Literal["SAVE", "SAVE_AS"]


class MotionCompiler(Protocol):
    async def __call__(
        self,
        motion: Motion,
        *,
        sample_rate_hz: float,
    ) -> TrajectoryCompileOutcome: ...


class DraftFreshnessCheck(Protocol):
    async def __call__(self, draft: MotionDraft) -> None: ...


class FormalMotionLibrary(Protocol):
    async def get_motion(self, motion_id: UUID) -> Motion: ...

    async def persist_motion_candidate(
        self,
        motion: Motion,
        *,
        expected_revision: int | None,
        trusted_legacy_snapshot_sha256: TrustedLegacySnapshotDigests = frozenset(),
    ) -> Motion: ...


@dataclass(frozen=True, slots=True)
class DraftSaveResult:
    draft: MotionDraft
    motion: Motion
    outcome: TrajectoryCompileOutcome


def draft_from_data(data: object) -> MotionDraft:
    try:
        return MotionDraft.model_validate(data)
    except ValidationError as error:
        raise EntityInvalidError(
            "Motion draft request violates draft invariants",
            details={"entity": "motion_draft"},
        ) from error


def trusted_legacy_snapshot_digests(
    draft: MotionDraft,
) -> TrustedLegacySnapshotDigests:
    # The registry is server-owned and may originate either from an imported Motion or
    # from exact Legacy Pose entities selected in Studio. API commands cannot inject it.
    return frozenset(draft.trusted_legacy_snapshot_sha256)


def revision_conflict_with_entity(
    error: RevisionConflictError,
    entity: RevisionEntity,
) -> RevisionConflictError:
    """Attach a stable, bounded conflict scope without relaying arbitrary details."""

    details: dict[str, object] = {"entity": entity}
    if isinstance(error.details, dict):
        expected = error.details.get("expected_revision")
        actual = error.details.get("actual_revision")
        if isinstance(expected, int):
            details["expected_revision"] = expected
        if isinstance(actual, int) or actual is None:
            details["actual_revision"] = actual
    return RevisionConflictError(error.message, details=details)


class StudioFormalSaveCoordinator:
    """Coordinate the Studio-to-Library transaction without owning any locks.

    The route-facing Studio facade must call recovery and abandonment while it
    holds its mutation lock, and formal saves while it holds both its mutation
    and compile locks. Keeping lock ownership in one place prevents nested-lock
    deadlocks while this coordinator remains directly testable.
    """

    def __init__(
        self,
        drafts: MotionDraftRepository,
        library: FormalMotionLibrary,
        clock: Clock,
        compile_motion: MotionCompiler,
        require_draft_unchanged: DraftFreshnessCheck,
    ) -> None:
        self.drafts = drafts
        self.library = library
        self.clock = clock
        self._compile_motion = compile_motion
        self._require_draft_unchanged = require_draft_unchanged

    async def save_draft_entity(
        self,
        draft: MotionDraft,
        *,
        expected_revision: int | None = None,
    ) -> None:
        try:
            await self.drafts.save(draft, expected_revision=expected_revision)
        except RevisionConflictError as error:
            raise revision_conflict_with_entity(error, "MotionDraft") from error

    async def compile_persist_and_rebind(
        self,
        draft: MotionDraft,
        candidate: Motion,
        *,
        expected_motion_revision: int | None,
        sample_rate_hz: float,
        save_kind: FormalSaveKind,
    ) -> DraftSaveResult:
        outcome = await self._compile_motion(candidate, sample_rate_hz=sample_rate_hz)
        await self._require_draft_unchanged(draft)
        if outcome.prepared is None:
            raise MotionPreflightError(
                "Draft trajectory did not pass compiler preflight",
                details={
                    "reason": "DRAFT_COMPILE_REJECTED",
                    "violations": [item.code for item in outcome.report.violations[:32]],
                },
            )
        intent = MotionDraftSaveIntent(
            kind=save_kind,
            target_motion_id=candidate.id,
            target_motion_revision=candidate.revision,
            expected_motion_revision=expected_motion_revision,
            target_name=candidate.name,
            target_motion_created_at=candidate.created_at,
            started_at=self.clock.now(),
        )
        commit = asyncio.create_task(
            self._commit_formal_motion(
                draft,
                candidate,
                intent,
                expected_motion_revision=expected_motion_revision,
                outcome=outcome,
            ),
            name=f"studio-formal-save-{intent.operation_id}",
        )
        try:
            return await asyncio.shield(commit)
        except asyncio.CancelledError:
            # Once the write-ahead intent exists, request cancellation must not
            # strand an avoidable cross-repository half-commit. Process crashes
            # are reconciled from the persisted intent on the next draft read.
            with suppress(Exception):
                await commit
            raise

    async def _commit_formal_motion(
        self,
        draft: MotionDraft,
        candidate: Motion,
        intent: MotionDraftSaveIntent,
        *,
        expected_motion_revision: int | None,
        outcome: TrajectoryCompileOutcome,
    ) -> DraftSaveResult:
        intent_data = draft.model_dump(mode="python")
        intent_data.update(
            save_intent=intent,
            revision=draft.revision + 1,
            updated_at=self.clock.now(),
        )
        intent_draft = draft_from_data(intent_data)
        await self.save_draft_entity(intent_draft, expected_revision=draft.revision)

        try:
            await self.library.persist_motion_candidate(
                candidate,
                expected_revision=expected_motion_revision,
                trusted_legacy_snapshot_sha256=trusted_legacy_snapshot_digests(draft),
            )
        except RevisionConflictError as error:
            raise revision_conflict_with_entity(error, "Motion") from error
        rebound_data = intent_draft.model_dump(mode="python")
        rebound_data.update(
            source_motion_id=candidate.id,
            source_motion_revision=candidate.revision,
            name=intent.target_name,
            save_intent=None,
            revision=intent_draft.revision + 1,
            updated_at=self.clock.now(),
        )
        rebound = draft_from_data(rebound_data)
        await self.save_draft_entity(
            rebound,
            expected_revision=intent_draft.revision,
        )
        return DraftSaveResult(draft=rebound, motion=candidate, outcome=outcome)

    async def recover_save_intent(self, draft: MotionDraft) -> MotionDraft:
        """Complete or clear a crash-interrupted formal save before exposure."""

        intent = draft.save_intent
        if intent is None:
            return draft
        try:
            target = await self.library.get_motion(intent.target_motion_id)
        except EntityNotFoundError:
            target = None
        if target is not None and target.created_at != intent.target_motion_created_at:
            raise RevisionConflictError(
                "Formal save recovery found a different Motion identity",
                details=self._save_intent_conflict_details(
                    draft,
                    entity="Motion",
                    reason="FORMAL_SAVE_TARGET_IDENTITY_MISMATCH",
                    actual_target_revision=target.revision,
                ),
            )
        known_source_save = (
            intent.kind == "SAVE"
            and draft.source_motion_id is not None
            and intent.target_motion_id == draft.source_motion_id
        )
        committed = False
        if target is not None and target.revision == intent.target_motion_revision:
            if self._motion_matches_intent(target, draft, intent):
                committed = True
            elif not known_source_save:
                # A fresh UUID resolving to different content is an identity
                # collision. Preserve the marker and require operator recovery.
                raise RevisionConflictError(
                    "Formal save recovery found different content at the target revision",
                    details=self._save_intent_conflict_details(
                        draft,
                        entity="Motion",
                        reason="FORMAL_SAVE_TARGET_CONTENT_MISMATCH",
                        actual_target_revision=target.revision,
                    ),
                )
            # An update writer won the exact next revision. Clearing the intent
            # leaves the draft bound to its old revision, so the next Save 409s.
        elif target is not None and target.revision > intent.target_motion_revision:
            if not known_source_save:
                # A fresh save target has no pre-existing identity relationship
                # with the draft. Once it advances beyond the intended revision,
                # the interrupted write can no longer be proven to have committed.
                raise RevisionConflictError(
                    "Formal save recovery cannot verify an advanced fresh target",
                    details=self._save_intent_conflict_details(
                        draft,
                        entity="Motion",
                        reason="FORMAL_SAVE_TARGET_REVISION_ADVANCED",
                        actual_target_revision=target.revision,
                    ),
                )
            # A known-source Save retains its pre-existing identity relationship.
            # Bind the UUID but keep the intended revision so a later Save cannot
            # adopt and overwrite the newer writer.
            committed = True
        recovered_data = draft.model_dump(mode="python")
        recovered_data.update(
            save_intent=None,
            revision=draft.revision + 1,
            updated_at=self.clock.now(),
        )
        if committed and target is not None:
            recovered_data.update(
                source_motion_id=target.id,
                # Preserve the revision targeted by the interrupted operation.
                # A later writer must still force the next Save to conflict.
                source_motion_revision=intent.target_motion_revision,
                name=intent.target_name,
            )
        recovered = draft_from_data(recovered_data)
        await self.save_draft_entity(recovered, expected_revision=draft.revision)
        return recovered

    async def abandon_save_intent(
        self,
        draft_id: UUID,
        *,
        expected_revision: int,
        operation_id: UUID,
    ) -> MotionDraft:
        """Clear exactly one unresolved marker after operator acknowledgement."""

        # This is deliberately a raw read. Automatic recovery would either
        # clear the marker first or obscure the operation being acknowledged.
        current = await self._get_draft(draft_id)
        intent = current.save_intent
        if current.revision != expected_revision:
            raise RevisionConflictError(
                "Motion draft revision changed before save recovery was abandoned",
                details=self._save_intent_conflict_details(
                    current,
                    entity="MotionDraft",
                    reason="FORMAL_SAVE_DRAFT_REVISION_MISMATCH",
                    expected_revision=expected_revision,
                ),
            )
        if intent is None:
            raise RevisionConflictError(
                "Motion draft has no formal save recovery marker",
                details=self._save_intent_conflict_details(
                    current,
                    entity="MotionDraft",
                    reason="FORMAL_SAVE_INTENT_NOT_FOUND",
                ),
            )
        if intent.operation_id != operation_id:
            raise RevisionConflictError(
                "Formal save recovery operation changed",
                details=self._save_intent_conflict_details(
                    current,
                    entity="MotionDraft",
                    reason="FORMAL_SAVE_OPERATION_MISMATCH",
                    requested_operation_id=operation_id,
                ),
            )

        abandoned_data = current.model_dump(mode="python")
        abandoned_data.update(
            save_intent=None,
            revision=current.revision + 1,
            updated_at=self.clock.now(),
        )
        abandoned = draft_from_data(abandoned_data)
        await self.save_draft_entity(
            abandoned,
            expected_revision=current.revision,
        )
        return abandoned

    async def _get_draft(self, draft_id: UUID) -> MotionDraft:
        draft = await self.drafts.get(draft_id)
        if draft is None:
            raise EntityNotFoundError("Motion draft was not found")
        return draft

    @staticmethod
    def _motion_matches_intent(
        motion: Motion,
        draft: MotionDraft,
        intent: MotionDraftSaveIntent,
    ) -> bool:
        return (
            motion.id == intent.target_motion_id
            and motion.revision == intent.target_motion_revision
            and motion.created_at == intent.target_motion_created_at
            and motion.name == intent.target_name
            and motion.description == draft.description
            and motion.robot_variant is draft.robot_variant
            and tuple(motion.keyframes) == tuple(draft.keyframes)
            and motion.playback_defaults == draft.playback_defaults
            and tuple(motion.tags) == tuple(draft.tags)
            and motion.source_metadata == draft.source_metadata
        )

    @staticmethod
    def _save_intent_conflict_details(
        draft: MotionDraft,
        *,
        entity: RevisionEntity,
        reason: str,
        expected_revision: int | None = None,
        requested_operation_id: UUID | None = None,
        actual_target_revision: int | None = None,
    ) -> dict[str, object]:
        """Expose only the bounded transaction fields needed for safe recovery."""

        details: dict[str, object] = {
            "entity": entity,
            "reason": reason,
            "draft_id": str(draft.id),
            "draft_revision": draft.revision,
        }
        if expected_revision is not None:
            details["expected_revision"] = expected_revision
        if requested_operation_id is not None:
            details["requested_operation_id"] = str(requested_operation_id)
        intent = draft.save_intent
        if intent is not None:
            details.update(
                operation_id=str(intent.operation_id),
                kind=intent.kind,
                target_motion_id=str(intent.target_motion_id),
                target_motion_revision=intent.target_motion_revision,
                expected_motion_revision=intent.expected_motion_revision,
                started_at=intent.started_at.isoformat(),
            )
        if actual_target_revision is not None:
            details["actual_target_revision"] = actual_target_revision
        return details
