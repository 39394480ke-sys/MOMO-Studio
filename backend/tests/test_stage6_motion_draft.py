"""MotionDraft cardinality, immutability, provenance, and schema contracts."""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from momo.domain.enums import RobotVariant
from momo.domain.motion import LegacyImportMetadata, Motion, MotionKeyframe, MotionTransition
from momo.domain.motion_draft import (
    EDITOR_DEFAULT_TRANSITION,
    MotionDraft,
    MotionDraftDefaultEdge,
    MotionDraftEditorMetadata,
    MotionDraftSaveIntent,
    legacy_snapshot_sha256,
)
from momo.domain.pose import PoseSnapshot
from momo.settings import repository_root
from tests.factories import make_snapshot, make_transition


def test_empty_and_one_frame_drafts_do_not_weaken_motion_cardinality() -> None:
    empty = MotionDraft(name="Empty", robot_variant=RobotVariant.V2)
    one = MotionDraft(
        name="One",
        robot_variant=RobotVariant.V2,
        keyframes=[MotionKeyframe(label="Only", pose_snapshot=make_snapshot())],
    )

    assert empty.keyframes == []
    assert len(one.keyframes) == 1
    with pytest.raises(ValidationError, match="at least 2"):
        Motion(
            name=one.name,
            robot_variant=one.robot_variant,
            keyframes=list(one.keyframes),
        )


def test_two_frame_draft_keeps_motion_edge_and_snapshot_invariants() -> None:
    first = MotionKeyframe(label="Start", pose_snapshot=make_snapshot())
    second = MotionKeyframe(
        label="End",
        pose_snapshot=make_snapshot(),
        incoming_transition=make_transition(),
    )
    draft = MotionDraft(
        name="Ready",
        robot_variant=RobotVariant.V2,
        keyframes=[first, second],
        editor_metadata=MotionDraftEditorMetadata(selected_keyframe_id=second.id),
    )

    formal = Motion(
        id=uuid4(),
        name=draft.name,
        robot_variant=draft.robot_variant,
        keyframes=list(draft.keyframes),
    )
    assert len(formal.keyframes) == 2
    with pytest.raises(TypeError):
        draft.keyframes.append(first)

    missing_edge = draft.model_dump(mode="python")
    missing_edge["keyframes"][1]["incoming_transition"] = None
    with pytest.raises(ValidationError, match="must have an incoming_transition"):
        MotionDraft.model_validate(missing_edge)


def test_source_pair_selection_and_draft_bounds_fail_closed() -> None:
    source_id = uuid4()
    with pytest.raises(ValidationError, match="must be set together"):
        MotionDraft(
            name="Broken source",
            robot_variant=RobotVariant.V2,
            source_motion_id=source_id,
        )
    with pytest.raises(ValidationError, match="selected_keyframe_id"):
        MotionDraft(
            name="Broken selection",
            robot_variant=RobotVariant.V2,
            editor_metadata=MotionDraftEditorMetadata(selected_keyframe_id=uuid4()),
        )
    with pytest.raises(ValidationError, match="less than or equal to 8"):
        MotionDraftEditorMetadata(timeline_zoom=9.0)
    with pytest.raises(ValidationError, match="source_metadata requires"):
        MotionDraft(
            name="Fabricated provenance",
            robot_variant=RobotVariant.V2,
            source_metadata=LegacyImportMetadata(
                source_file_name="legacy.json",
                source_sha256="a" * 64,
            ),
        )


def test_imported_snapshot_trust_registry_is_bounded_unique_and_round_trips() -> None:
    source_id = uuid4()
    snapshot_data = make_snapshot().model_dump(mode="python")
    snapshot_data["state_sequence"] = None
    imported_snapshot = PoseSnapshot.model_validate(snapshot_data)
    digest = legacy_snapshot_sha256(imported_snapshot)
    metadata = LegacyImportMetadata(
        source_file_name="legacy.json",
        source_sha256="a" * 64,
    )
    trusted = MotionDraft(
        name="Trusted import",
        robot_variant=RobotVariant.V2,
        source_motion_id=source_id,
        source_motion_revision=1,
        source_metadata=metadata,
        trusted_legacy_snapshot_sha256=[digest],
        keyframes=[MotionKeyframe(label="Imported", pose_snapshot=imported_snapshot)],
    )

    assert MotionDraft.model_validate(trusted.model_dump(mode="python")) == trusted
    with pytest.raises(ValidationError, match="not a trusted Legacy snapshot"):
        MotionDraft(
            name="Missing registry",
            robot_variant=RobotVariant.V2,
            source_motion_id=source_id,
            source_motion_revision=1,
            source_metadata=metadata,
            keyframes=[MotionKeyframe(label="Imported", pose_snapshot=imported_snapshot)],
        )
    with pytest.raises(ValidationError, match="must be unique"):
        MotionDraft(
            name="Duplicate registry",
            robot_variant=RobotVariant.V2,
            source_motion_id=source_id,
            source_motion_revision=1,
            source_metadata=metadata,
            trusted_legacy_snapshot_sha256=[digest, digest],
        )
    with pytest.raises(ValidationError, match="require typed source_metadata"):
        MotionDraft(
            name="Unowned registry",
            robot_variant=RobotVariant.V2,
            source_motion_id=source_id,
            source_motion_revision=1,
            trusted_legacy_snapshot_sha256=[digest],
        )


def test_default_edge_metadata_must_match_a_current_exact_editor_default() -> None:
    first = MotionKeyframe(label="Start", pose_snapshot=make_snapshot())
    second = MotionKeyframe(
        label="End",
        pose_snapshot=make_snapshot(),
        incoming_transition=EDITOR_DEFAULT_TRANSITION,
    )
    marker = MotionDraftDefaultEdge(
        from_keyframe_id=first.id,
        to_keyframe_id=second.id,
    )
    accepted = MotionDraft(
        name="Defaults",
        robot_variant=RobotVariant.V2,
        keyframes=[first, second],
        editor_metadata=MotionDraftEditorMetadata(default_edges=[marker]),
    )
    assert accepted.editor_metadata.default_edges == [marker]

    edited = accepted.model_dump(mode="python")
    edited["keyframes"][1]["incoming_transition"] = MotionTransition(
        duration_s=2.0,
        motion_mode=EDITOR_DEFAULT_TRANSITION.motion_mode,
        easing=EDITOR_DEFAULT_TRANSITION.easing,
    )
    with pytest.raises(ValidationError, match="exact editor default"):
        MotionDraft.model_validate(edited)

    non_adjacent = accepted.model_dump(mode="python")
    non_adjacent["editor_metadata"]["default_edges"][0]["from_keyframe_id"] = uuid4()
    with pytest.raises(ValidationError, match="current directed adjacencies"):
        MotionDraft.model_validate(non_adjacent)


def test_save_intent_enforces_exact_transaction_shape() -> None:
    source_id = uuid4()
    source = MotionDraft(
        name="Opened source",
        robot_variant=RobotVariant.V2,
        source_motion_id=source_id,
        source_motion_revision=4,
    )
    valid_update = source.model_copy(
        update={
            "save_intent": MotionDraftSaveIntent(
                kind="SAVE",
                target_motion_id=source_id,
                target_motion_revision=5,
                expected_motion_revision=4,
                target_name="Opened source",
                target_motion_created_at=source.created_at,
            )
        }
    )
    assert MotionDraft.model_validate(valid_update).save_intent is not None

    invalid_save_as = source.model_dump(mode="python")
    invalid_save_as["save_intent"] = MotionDraftSaveIntent(
        kind="SAVE_AS",
        target_motion_id=uuid4(),
        target_motion_revision=5,
        expected_motion_revision=4,
        target_name="Copy",
        target_motion_created_at=source.created_at,
    )
    with pytest.raises(ValidationError, match="Save As intent"):
        MotionDraft.model_validate(invalid_save_as)

    source_overwrite = source.model_dump(mode="python")
    source_overwrite["save_intent"] = MotionDraftSaveIntent(
        kind="SAVE_AS",
        target_motion_id=source_id,
        target_motion_revision=1,
        target_name="Copy",
        target_motion_created_at=source.created_at,
    )
    with pytest.raises(ValidationError, match="must not overwrite"):
        MotionDraft.model_validate(source_overwrite)

    new_draft_update = MotionDraft(
        name="Unsaved",
        robot_variant=RobotVariant.V2,
    ).model_dump(mode="python")
    new_draft_update["save_intent"] = MotionDraftSaveIntent(
        kind="SAVE",
        target_motion_id=uuid4(),
        target_motion_revision=2,
        expected_motion_revision=1,
        target_name="Unsaved",
        target_motion_created_at=new_draft_update["created_at"],
    )
    with pytest.raises(ValidationError, match="new Save intent"):
        MotionDraft.model_validate(new_draft_update)


def test_generated_draft_schema_is_current_and_deterministic() -> None:
    schema_path = repository_root() / "docs/schemas/motion-draft.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == "1.0.0"
    assert schema["properties"]["keyframes"]["maxItems"] == 1000
    assert "minItems" not in schema["properties"]["keyframes"]
    assert set(schema["required"]) == set(schema["properties"])
    assert "id" in schema["$defs"]["MotionKeyframe"]["required"]
    assert "operation_id" in schema["$defs"]["MotionDraftSaveIntent"]["required"]
    assert "target_motion_created_at" in schema["$defs"]["MotionDraftSaveIntent"]["required"]
    assert "source_metadata" in schema["required"]
    assert "trusted_legacy_snapshot_sha256" in schema["required"]
    assert schema["properties"]["trusted_legacy_snapshot_sha256"]["maxItems"] == 1000
    assert "source_file_name" in schema["$defs"]["LegacyImportMetadata"]["required"]
