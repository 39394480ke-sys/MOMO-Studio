"""Atomic draft autosave and corrupt crash-recovery isolation."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from momo.adapters.storage.file_motion_draft_repository import FileMotionDraftRepository
from momo.domain.enums import RobotVariant
from momo.domain.errors import RevisionConflictError
from momo.domain.motion import MotionKeyframe
from momo.domain.motion_draft import MotionDraft, MotionDraftSaveIntent
from tests.factories import make_snapshot
from tests.stage3_helpers import FakeClock


def revised(draft: MotionDraft, *, name: str) -> MotionDraft:
    data = draft.model_dump(mode="python")
    data.update(name=name, revision=draft.revision + 1)
    return MotionDraft.model_validate(data)


def test_draft_round_trip_uuid_filename_cas_and_delete(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = FileMotionDraftRepository(tmp_path / "drafts", FakeClock())
        draft = MotionDraft(name="Recover me", robot_variant=RobotVariant.V2)
        await repository.save(draft)
        path = tmp_path / "drafts" / f"{draft.id}.json"
        assert path.is_file()
        assert await repository.get(draft.id) == draft

        updated = revised(draft, name="Autosaved")
        await repository.save(updated, expected_revision=1)
        with pytest.raises(RevisionConflictError):
            await repository.save(revised(draft, name="Stale"), expected_revision=1)
        assert await repository.get(draft.id) == updated
        assert await repository.delete(draft.id, expected_revision=2) is True

    asyncio.run(scenario())


def test_corrupt_draft_is_quarantined_while_valid_recovery_continues(tmp_path: Path) -> None:
    async def scenario() -> None:
        directory = tmp_path / "drafts"
        repository = FileMotionDraftRepository(directory, FakeClock())
        valid = MotionDraft(name="Valid", robot_variant=RobotVariant.V2)
        await repository.save(valid)
        corrupt_id = uuid4()
        (directory / f"{corrupt_id}.json").write_text(
            json.dumps({"schema_version": "1.0.0", "id": str(corrupt_id)}),
            encoding="utf-8",
        )
        missing_keyframe_id = MotionDraft(
            name="Missing nested identity",
            robot_variant=RobotVariant.V2,
            keyframes=[MotionKeyframe(label="Only", pose_snapshot=make_snapshot())],
        ).model_dump(mode="json")
        missing_keyframe_id_value = uuid4()
        missing_keyframe_id["id"] = str(missing_keyframe_id_value)
        del missing_keyframe_id["keyframes"][0]["id"]
        (directory / f"{missing_keyframe_id_value}.json").write_text(
            json.dumps(missing_keyframe_id),
            encoding="utf-8",
        )
        missing_intent_identity = MotionDraft(
            name="Missing transaction identity",
            robot_variant=RobotVariant.V2,
            save_intent=MotionDraftSaveIntent(
                kind="SAVE_AS",
                target_motion_id=uuid4(),
                target_motion_revision=1,
                target_name="Candidate",
                target_motion_created_at=valid.created_at,
            ),
        ).model_dump(mode="json")
        missing_intent_id = uuid4()
        missing_intent_identity["id"] = str(missing_intent_id)
        del missing_intent_identity["save_intent"]["operation_id"]
        (directory / f"{missing_intent_id}.json").write_text(
            json.dumps(missing_intent_identity),
            encoding="utf-8",
        )

        assert await repository.list() == (valid,)
        assert not (directory / f"{corrupt_id}.json").exists()
        quarantined = tuple((directory / "quarantine").glob("*.corrupt.json"))
        assert len(quarantined) == 3

    asyncio.run(scenario())
