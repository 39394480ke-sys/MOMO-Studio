"""Stage 6 Studio API autosave, recovery, compiler, Save, and Save As workflows."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from momo.api.dependencies import authorize_real_joint_motion_request
from momo.domain.enums import DomainUnit, MotionCommandSource, RobotVariant
from momo.domain.errors import PoseIncompatibleError
from momo.domain.motion import LegacyImportMetadata, Motion, MotionKeyframe
from momo.domain.motion_draft import legacy_snapshot_sha256
from momo.domain.pose import Pose, PoseSnapshot, SnapshotJointState
from momo.domain.real_hardware import RealHardwareAuthorizationPurpose
from momo.domain.real_motion import RealExecutionAuthorization
from tests.stage4_helpers import api_request
from tests.stage6_helpers import make_stage6_app


async def connect_and_capture(app: Any) -> dict[str, Any]:
    connected = await api_request(app, "POST", "/api/v1/robot/connect")
    assert connected.status_code == 200, connected.text
    captured = await api_request(app, "POST", "/api/v1/studio/capture", json_data={})
    assert captured.status_code == 200, captured.text
    snapshot = cast(dict[str, Any], captured.json())
    assert snapshot["hardware_snapshot"] is None
    assert snapshot["calibration_fingerprint"] is None
    return snapshot


def keyframes(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "label": "Start",
            "pose_snapshot": deepcopy(snapshot),
            "source_pose_id": None,
            "hold_s": 0.0,
            "incoming_transition": None,
        },
        {
            "label": "End",
            "pose_snapshot": deepcopy(snapshot),
            "source_pose_id": None,
            "hold_s": 0.0,
            "incoming_transition": {
                "duration_s": 1.0,
                "motion_mode": "JOINT",
                "easing": "SMOOTHSTEP",
            },
        },
    ]


def create_body(
    *,
    frames: list[dict[str, Any]] | None = None,
    name: str = "Studio draft",
) -> dict[str, Any]:
    return {
        "name": name,
        "description": "Recovered authoring state",
        "robot_variant": "V2",
        "keyframes": frames or [],
        "playback_defaults": {"loop": False, "speed_multiplier": 1.0},
        "tags": ["studio"],
        "editor_metadata": {
            "selected_keyframe_id": None,
            "playhead_s": 0.0,
            "timeline_zoom": 1.0,
            "timeline_scroll_s": 0.0,
        },
    }


def autosave_body(draft: dict[str, Any], **changes: object) -> dict[str, Any]:
    body = {
        "expected_revision": draft["revision"],
        "name": draft["name"],
        "description": draft["description"],
        "robot_variant": draft["robot_variant"],
        "keyframes": draft["keyframes"],
        "playback_defaults": draft["playback_defaults"],
        "tags": draft["tags"],
        "editor_metadata": draft["editor_metadata"],
    }
    body.update(changes)
    return body


def legacy_metadata(*, digest_character: str = "a") -> dict[str, object]:
    return {
        "importer": "momo.tools.import_legacy_actions",
        "source_file_name": "legacy-motion.json",
        "source_sha256": digest_character * 64,
        "legacy_id": "legacy-motion-1",
        "legacy_source": "web_record:arm_a",
        "warnings": ["Imported without a runtime state sequence"],
    }


def test_incompatible_draft_reports_structured_keyframe_contract_diagnostics(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        snapshot = await connect_and_capture(app)
        frames = keyframes(snapshot)
        first_id = "11111111-1111-4111-8111-111111111111"
        second_id = "22222222-2222-4222-8222-222222222222"
        source_pose_id = "33333333-3333-4333-8333-333333333333"
        frames[0]["id"] = first_id
        frames[0]["label"] = "Legacy start"
        frames[0]["source_pose_id"] = source_pose_id
        frames[0]["pose_snapshot"]["state_sequence"] = None
        frames[0]["pose_snapshot"]["profile_fingerprint"] = "a" * 64
        frames[0]["pose_snapshot"]["kinematics_fingerprint"] = "b" * 64
        frames[1]["id"] = second_id
        frames[1]["label"] = "TCP drift"
        frames[1]["pose_snapshot"]["tcp_pose"]["position_mm"]["x"] += 1.0

        response = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data=create_body(frames=frames, name="Incompatible diagnostics"),
        )

        assert response.status_code == 422, response.text
        envelope = response.json()
        assert envelope["code"] == "POSE_INCOMPATIBLE"
        details = envelope["details"]
        assert details["error_code"] == "STUDIO_DRAFT_CONTRACT_INCOMPATIBLE"
        assert details["draft_variant"] == "V2"
        assert details["active_variant"] == "V2"
        assert details["checks"] == [
            "kinematics_fingerprint",
            "profile_fingerprint",
            "state_sequence",
            "tcp_pose",
        ]
        assert [item["keyframe_id"] for item in details["keyframes"]] == [
            first_id,
            second_id,
        ]

        first, second = details["keyframes"]
        assert first["keyframe_index"] == 0
        assert first["keyframe_name"] == "Legacy start"
        assert first["source_pose_id"] == source_pose_id
        assert first["state_sequence_issue"] is True
        assert first["provenance_issue"] is True
        assert first["tcp_mismatch"] is False
        assert first["expected_joint_ids"] == ["j10", "j11", "j12", "j13", "j14", "j15"]
        assert first["actual_joint_ids"] == ["j10", "j11", "j12", "j13", "j14", "j15"]
        assert first["missing_joint_ids"] == []
        assert first["extra_joint_ids"] == []
        assert first["expected_units"] == snapshot["joint_state"]["units"]
        assert first["actual_units"] == snapshot["joint_state"]["units"]
        assert first["expected_profile_fingerprint"] == snapshot["profile_fingerprint"]
        assert first["actual_profile_fingerprint"] == "a" * 64
        assert first["expected_kinematics_fingerprint"] == snapshot["kinematics_fingerprint"]
        assert first["actual_kinematics_fingerprint"] == "b" * 64

        assert second["keyframe_index"] == 1
        assert second["keyframe_name"] == "TCP drift"
        assert second["checks"] == ["tcp_pose"]
        assert second["tcp_mismatch"] is True
        assert second["state_sequence_issue"] is False
        assert second["provenance_issue"] is False

    asyncio.run(scenario())


def test_contract_diagnostics_preserve_wrong_variant_joint_and_unit_evidence(
    tmp_path: Path,
) -> None:
    """Even pre-schema/corrupt legacy data gets a complete, fail-closed report."""

    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        captured_data = await connect_and_capture(app)
        captured = PoseSnapshot.model_validate(captured_data)

        def keyframe(label: str, snapshot: PoseSnapshot) -> MotionKeyframe:
            return MotionKeyframe.model_construct(
                id=uuid4(),
                label=label,
                pose_snapshot=snapshot,
                source_pose_id=None,
                hold_s=0.0,
                incoming_transition=None,
            )

        wrong_variant = captured.model_copy(update={"robot_variant": RobotVariant.V1})

        missing_extra_positions = dict(captured.joint_state.positions)
        missing_extra_units = dict(captured.joint_state.units)
        missing_extra_positions.pop("j10")
        missing_extra_units.pop("j10")
        missing_extra_positions["j16"] = 0.0
        missing_extra_units["j16"] = DomainUnit.DEG
        missing_extra = captured.model_copy(
            update={
                "joint_state": SnapshotJointState.model_construct(
                    positions=missing_extra_positions,
                    units=missing_extra_units,
                )
            }
        )

        wrong_j10_units = dict(captured.joint_state.units)
        wrong_j10_units["j10"] = DomainUnit.DEG
        unit_mismatch = captured.model_copy(
            update={
                "joint_state": SnapshotJointState.model_construct(
                    positions=dict(captured.joint_state.positions),
                    units=wrong_j10_units,
                )
            }
        )

        with pytest.raises(PoseIncompatibleError) as raised:
            await app.state.studio_service._validate_client_keyframes(
                [
                    keyframe("Wrong variant", wrong_variant),
                    keyframe("Missing and extra", missing_extra),
                    keyframe("Wrong j10 units", unit_mismatch),
                ],
                draft_variant=RobotVariant.V2,
                trusted_legacy_snapshot_sha256=frozenset(),
            )

        details = cast(dict[str, Any], raised.value.details)
        first, second, third = details["keyframes"]
        assert "robot_variant" in first["checks"]
        assert second["missing_joint_ids"] == ["j10"]
        assert second["extra_joint_ids"] == ["j16"]
        assert {"missing_joint_ids", "extra_joint_ids", "joint_state"} <= set(second["checks"])
        assert third["expected_units"]["j10"] == "mm"
        assert third["actual_units"]["j10"] == "deg"
        assert {"joint_units", "joint_state"} <= set(third["checks"])

    asyncio.run(scenario())


async def seed_imported_motion(app: Any, snapshot: dict[str, Any]) -> Motion:
    imported_frames = keyframes(snapshot)
    for keyframe in imported_frames:
        keyframe["pose_snapshot"]["state_sequence"] = None
    imported_frames[1]["pose_snapshot"]["captured_at"] = "2000-01-01T00:00:00Z"
    motion = Motion.model_validate(
        {
            "name": "Imported source",
            "description": "Sanitized Legacy import",
            "robot_variant": "V2",
            "keyframes": imported_frames,
            "playback_defaults": {"loop": False, "speed_multiplier": 1.0},
            "tags": ["imported"],
            "source_metadata": legacy_metadata(),
        }
    )
    await app.state.library_service.motions.save(motion)
    return motion


def test_empty_one_frame_autosave_conflict_and_crash_recovery(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        rejected_source = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data={**create_body(), "source_motion_id": str(uuid4())},
        )
        assert rejected_source.status_code == 422

        created = await api_request(app, "POST", "/api/v1/studio/drafts", json_data=create_body())
        assert created.status_code == 201, created.text
        draft = created.json()
        assert draft["keyframes"] == []
        assert draft["revision"] == 1

        validation = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/validate",
            json_data={"expected_revision": 1},
        )
        assert validation.status_code == 200
        assert validation.json() == {
            "draft_id": draft["id"],
            "draft_revision": 1,
            "valid": False,
            "issues": [
                {
                    "code": "DRAFT_REQUIRES_TWO_KEYFRAMES",
                    "message": "A formal Motion requires at least two keyframes",
                }
            ],
        }
        compile_empty = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/compile",
            json_data={"expected_revision": 1},
        )
        assert compile_empty.status_code == 422
        assert compile_empty.json()["code"] == "ENTITY_INVALID"

        snapshot = await connect_and_capture(app)
        one_frame = keyframes(snapshot)[:1]
        autosaved = await api_request(
            app,
            "PUT",
            f"/api/v1/studio/drafts/{draft['id']}",
            json_data=autosave_body(draft, keyframes=one_frame, name="One frame"),
        )
        assert autosaved.status_code == 200, autosaved.text
        assert autosaved.json()["revision"] == 2
        stale = await api_request(
            app,
            "PUT",
            f"/api/v1/studio/drafts/{draft['id']}",
            json_data=autosave_body(draft, name="Stale"),
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "REVISION_CONFLICT"
        assert stale.json()["details"] == {
            "entity": "MotionDraft",
            "expected_revision": 1,
            "actual_revision": 2,
        }

        restarted = make_stage6_app(tmp_path)
        recovered = await api_request(restarted, "GET", f"/api/v1/studio/drafts/{draft['id']}")
        assert recovered.status_code == 200
        assert recovered.json()["name"] == "One frame"
        listing = await api_request(restarted, "GET", "/api/v1/studio/drafts?page_size=1")
        assert listing.json()["total"] == 1
        assert "keyframes" not in listing.json()["items"][0]

    asyncio.run(scenario())


def test_formal_save_rejects_a_different_content_draft_race_with_draft_scope(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        snapshot = await connect_and_capture(app)
        created = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data=create_body(frames=keyframes(snapshot), name="Local content"),
        )
        assert created.status_code == 201
        local = created.json()
        remote_frames = deepcopy(local["keyframes"])
        remote_frames[1]["label"] = "Other client content"
        advanced = await api_request(
            app,
            "PUT",
            f"/api/v1/studio/drafts/{local['id']}",
            json_data=autosave_body(
                local,
                name="Other client",
                keyframes=remote_frames,
            ),
        )
        assert advanced.status_code == 200
        assert advanced.json()["revision"] == 2

        stale_save = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{local['id']}/save",
            json_data={"expected_revision": 1},
        )
        assert stale_save.status_code == 409
        assert stale_save.json()["code"] == "REVISION_CONFLICT"
        assert stale_save.json()["details"] == {
            "entity": "MotionDraft",
            "expected_revision": 1,
            "actual_revision": 2,
        }
        authoritative = await api_request(
            app,
            "GET",
            f"/api/v1/studio/drafts/{local['id']}",
        )
        assert authoritative.status_code == 200
        assert authoritative.json()["name"] == "Other client"
        assert not tuple((tmp_path / "motions").glob("*.json"))

    asyncio.run(scenario())


def test_two_frames_compile_save_open_update_conflict_and_save_as(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        snapshot = await connect_and_capture(app)
        created = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data=create_body(frames=keyframes(snapshot)),
        )
        assert created.status_code == 201, created.text
        draft = created.json()

        validation = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/validate",
            json_data={"expected_revision": 1},
        )
        assert validation.json()["valid"] is True

        compiled = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/compile",
            json_data={"expected_revision": 1, "sample_rate_hz": 20.0},
        )
        assert compiled.status_code == 200, compiled.text
        compile_data = compiled.json()
        assert compile_data["preflight"]["passed"] is True
        assert compile_data["preview"]["sample_count"] >= 2
        assert compile_data["executable"] is False
        digest = compile_data["preflight"]["digest"]
        unpublished = await api_request(app, "GET", f"/api/v1/trajectory/{digest}/preview")
        assert unpublished.status_code == 404

        saved = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/save",
            json_data={"expected_revision": 1, "sample_rate_hz": 20.0},
        )
        assert saved.status_code == 200, saved.text
        saved_data = saved.json()
        motion = saved_data["motion"]
        rebound = saved_data["draft"]
        assert motion["revision"] == 1
        assert rebound["source_motion_id"] == motion["id"]
        assert rebound["source_motion_revision"] == 1
        assert rebound["revision"] == 3
        assert saved_data["preflight"]["passed"] is True

        edited = await api_request(
            app,
            "PUT",
            f"/api/v1/studio/drafts/{rebound['id']}",
            json_data=autosave_body(rebound, name="Saved edit"),
        )
        assert edited.status_code == 200
        updated_source = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{rebound['id']}/save",
            json_data={
                "expected_revision": 4,
                "expected_source_revision": 1,
                "sample_rate_hz": 20.0,
            },
        )
        assert updated_source.status_code == 200, updated_source.text
        updated_data = updated_source.json()
        motion = updated_data["motion"]
        assert motion["revision"] == 2
        assert motion["name"] == "Saved edit"
        assert updated_data["draft"]["revision"] == 6
        assert updated_data["draft"]["source_motion_revision"] == 2

        opened = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/from-motion/{motion['id']}",
            json_data={"expected_revision": 2},
        )
        assert opened.status_code == 201
        opened_draft = opened.json()
        assert opened_draft["id"] != rebound["id"]
        assert opened_draft["keyframes"] == motion["keyframes"]

        patched = await api_request(
            app,
            "PATCH",
            f"/api/v1/motions/{motion['id']}",
            json_data={"expected_revision": 2, "name": "External writer"},
        )
        assert patched.status_code == 200
        stale_save = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{opened_draft['id']}/save",
            json_data={"expected_revision": 1, "expected_source_revision": 2},
        )
        assert stale_save.status_code == 409
        assert stale_save.json()["code"] == "REVISION_CONFLICT"
        assert stale_save.json()["details"] == {
            "entity": "Motion",
            "expected_revision": 2,
            "actual_revision": 3,
        }

        save_as = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{opened_draft['id']}/save-as",
            json_data={"expected_revision": 1, "name": "Fresh copy"},
        )
        assert save_as.status_code == 201, save_as.text
        copied = save_as.json()
        assert copied["motion"]["id"] != motion["id"]
        assert copied["motion"]["revision"] == 1
        assert copied["motion"]["name"] == "Fresh copy"
        assert copied["draft"]["source_motion_id"] == copied["motion"]["id"]
        assert copied["draft"]["revision"] == 3

    asyncio.run(scenario())


def test_non_executable_compile_and_save_do_not_require_robot_connection(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        snapshot = await connect_and_capture(app)
        created = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data=create_body(frames=keyframes(snapshot), name="Disconnected compile"),
        )
        draft = created.json()
        disconnected = await api_request(app, "POST", "/api/v1/robot/disconnect")
        assert disconnected.status_code == 200

        compiled = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/compile",
            json_data={"expected_revision": 1},
        )
        assert compiled.status_code == 200, compiled.text
        compile_data = compiled.json()
        assert compile_data["preflight"]["passed"] is True
        assert compile_data["preview"] is not None
        assert compile_data["executable"] is False

        saved = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/save",
            json_data={"expected_revision": 1},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["preflight"]["passed"] is True
        assert len(tuple((tmp_path / "motions").glob("*.json"))) == 1

    asyncio.run(scenario())


def test_keyframe_goto_loads_persisted_snapshot_with_studio_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        snapshot = await connect_and_capture(app)
        created = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data=create_body(frames=keyframes(snapshot), name="Safe Goto"),
        )
        draft = created.json()
        keyframe = draft["keyframes"][0]

        missing = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/keyframes/{uuid4()}/goto",
            json_data={
                "expected_revision": 1,
                "duration_s": 1.0,
                "speed_scale": 0.5,
                "idempotency_key": "missing-keyframe",
            },
        )
        assert missing.status_code == 404

        submitted: list[Any] = []
        motion_service = app.state.motion_service
        original_submit = motion_service.submit

        async def observe_submit(command: Any) -> Any:
            submitted.append(command)
            return await original_submit(command)

        monkeypatch.setattr(motion_service, "submit", observe_submit)
        accepted = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/keyframes/{keyframe['id']}/goto",
            json_data={
                "expected_revision": 1,
                "duration_s": 1.0,
                "speed_scale": 0.5,
                "idempotency_key": "studio-keyframe-goto",
            },
        )
        assert accepted.status_code == 202, accepted.text
        checks = {item["name"]: item for item in accepted.json()["preflight"]["checks"]}
        assert checks["hardware_policy"]["passed"] is True
        assert checks["command_source"]["passed"] is True
        command_status = await api_request(
            app,
            "GET",
            f"/api/v1/motion/commands/{accepted.json()['command_id']}",
        )
        assert command_status.status_code == 200
        assert command_status.json()["hardware_accessed"] is False
        assert len(submitted) == 1
        assert submitted[0].source is MotionCommandSource.STUDIO
        assert (
            submitted[0].payload.joint_state.positions
            == keyframe["pose_snapshot"]["joint_state"]["positions"]
        )

        stopped = await api_request(app, "POST", "/api/v1/motion/stop", json_data={})
        assert stopped.status_code == 200
        revised = await api_request(
            app,
            "PUT",
            f"/api/v1/studio/drafts/{draft['id']}",
            json_data=autosave_body(draft, name="Revision two"),
        )
        assert revised.status_code == 200
        stale = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/keyframes/{keyframe['id']}/goto",
            json_data={
                "expected_revision": 1,
                "duration_s": 1.0,
                "speed_scale": 0.5,
                "idempotency_key": "stale-keyframe-goto",
            },
        )
        assert stale.status_code == 409
        assert len(submitted) == 1

    asyncio.run(scenario())


def test_keyframe_goto_passes_the_route_authorization_to_the_executor_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        snapshot = await connect_and_capture(app)
        created = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data=create_body(frames=keyframes(snapshot), name="Authorization binding"),
        )
        assert created.status_code == 201, created.text
        draft = created.json()
        keyframe = draft["keyframes"][0]

        authorization = cast(RealExecutionAuthorization, object())

        async def authorized_dependency() -> RealExecutionAuthorization:
            return authorization

        app.dependency_overrides[authorize_real_joint_motion_request] = authorized_dependency
        executor = app.state.motion_service.executor
        original_submit = executor.submit
        received: list[
            tuple[RealExecutionAuthorization | None, RealHardwareAuthorizationPurpose | None]
        ] = []

        async def observe_executor_submit(
            prepared: Any,
            *,
            authorization: RealExecutionAuthorization | None = None,
            execution_purpose: RealHardwareAuthorizationPurpose | None = None,
            continuous_write_guard: Any = None,
        ) -> Any:
            del continuous_write_guard
            received.append((authorization, execution_purpose))
            # The fixture executor is intentionally DRY_RUN. Execute without the
            # injected sentinel after observing the application boundary.
            return await original_submit(prepared)

        monkeypatch.setattr(executor, "submit", observe_executor_submit)
        accepted = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/keyframes/{keyframe['id']}/goto",
            json_data={
                "expected_revision": draft["revision"],
                "duration_s": 0.1,
                "speed_scale": 0.5,
                "idempotency_key": "studio-authorization-binding",
            },
        )

        assert accepted.status_code == 202, accepted.text
        assert len(received) == 1
        assert received[0][0] is authorization
        assert received[0][1] is RealHardwareAuthorizationPurpose.REAL_JOINT_MOTION

    asyncio.run(scenario())


def test_keyframe_goto_serializes_draft_revision_through_motion_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        snapshot = await connect_and_capture(app)
        created = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data=create_body(frames=keyframes(snapshot), name="Linearized Goto"),
        )
        assert created.status_code == 201, created.text
        draft = created.json()
        chosen_id = draft["keyframes"][0]["id"]
        motion = app.state.motion_service
        original_submit = motion.submit
        submit_entered = asyncio.Event()
        release_submit = asyncio.Event()

        async def delayed_submit(*args: Any, **kwargs: Any) -> Any:
            submit_entered.set()
            await release_submit.wait()
            return await original_submit(*args, **kwargs)

        monkeypatch.setattr(motion, "submit", delayed_submit)
        goto_task = asyncio.create_task(
            api_request(
                app,
                "POST",
                f"/api/v1/studio/drafts/{draft['id']}/keyframes/{chosen_id}/goto",
                json_data={
                    "expected_revision": 1,
                    "duration_s": 1.0,
                    "speed_scale": 0.5,
                    "idempotency_key": "linearized-studio-goto",
                },
            )
        )
        await asyncio.wait_for(submit_entered.wait(), timeout=1.0)

        replacement_frames = deepcopy(draft["keyframes"])
        replacement_frames[0]["id"] = str(uuid4())
        replacement_frames[0]["label"] = "Other client replacement"
        autosave_task = asyncio.create_task(
            api_request(
                app,
                "PUT",
                f"/api/v1/studio/drafts/{draft['id']}",
                json_data=autosave_body(
                    draft,
                    name="Advanced after Goto",
                    keyframes=replacement_frames,
                ),
            )
        )
        for _ in range(20):
            await asyncio.sleep(0)
        assert autosave_task.done() is False

        release_submit.set()
        goto, autosaved = await asyncio.wait_for(
            asyncio.gather(goto_task, autosave_task),
            timeout=2.0,
        )
        assert goto.status_code == 202, goto.text
        assert autosaved.status_code == 200, autosaved.text
        assert autosaved.json()["revision"] == 2
        assert autosaved.json()["keyframes"][0]["id"] != chosen_id
        stopped = await api_request(app, "POST", "/api/v1/motion/stop", json_data={})
        assert stopped.status_code == 200

    asyncio.run(scenario())


def test_save_waits_for_playback_revision_lease_then_stale_cas_rejects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        snapshot = await connect_and_capture(app)
        created = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data=create_body(frames=keyframes(snapshot), name="Lease fenced"),
        )
        draft = created.json()
        initial_save = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/save",
            json_data={"expected_revision": 1},
        )
        assert initial_save.status_code == 200
        rebound = initial_save.json()["draft"]
        motion = initial_save.json()["motion"]

        library = app.state.library_service
        original_persist = library.persist_motion_candidate
        persist_entered = asyncio.Event()

        async def observed_persist(*args: Any, **kwargs: Any) -> Any:
            persist_entered.set()
            return await original_persist(*args, **kwargs)

        monkeypatch.setattr(library, "persist_motion_candidate", observed_persist)
        async with library.motion_revision_lease(UUID(motion["id"]), 1) as leased:
            save_task = asyncio.create_task(
                api_request(
                    app,
                    "POST",
                    f"/api/v1/studio/drafts/{rebound['id']}/save",
                    json_data={
                        "expected_revision": 3,
                        "expected_source_revision": 1,
                    },
                )
            )
            await asyncio.wait_for(persist_entered.wait(), timeout=1.0)
            assert save_task.done() is False

            external_data = leased.model_dump(mode="python")
            external_data.update(name="External process", revision=2)
            external = Motion.model_validate(external_data)
            await library.motions.save(external, expected_revision=1)

        response = await save_task
        assert response.status_code == 409
        assert response.json()["code"] == "REVISION_CONFLICT"
        assert response.json()["details"] == {
            "entity": "Motion",
            "expected_revision": 1,
            "actual_revision": 2,
        }
        recovered = await api_request(
            app,
            "GET",
            f"/api/v1/studio/drafts/{rebound['id']}",
        )
        assert recovered.json()["revision"] == 5
        assert recovered.json()["source_motion_revision"] == 1
        saved_as_latest = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{rebound['id']}/save-as",
            json_data={"expected_revision": 5, "name": "CAS conflict copy"},
        )
        assert saved_as_latest.status_code == 201, saved_as_latest.text
        assert saved_as_latest.json()["motion"]["id"] != motion["id"]
        assert saved_as_latest.json()["motion"]["name"] == "CAS conflict copy"

    asyncio.run(scenario())


def test_advanced_fresh_save_fails_closed_and_exact_abandon_is_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        snapshot = await connect_and_capture(app)
        created = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data=create_body(frames=keyframes(snapshot), name="Recover transaction"),
        )
        draft = created.json()
        repository = app.state.studio_service.drafts
        original_save = repository.save
        failed = False

        async def fail_first_rebind(entity: Any, *, expected_revision: int | None = None) -> None:
            nonlocal failed
            if (
                not failed
                and entity.revision == 3
                and entity.save_intent is None
                and expected_revision == 2
            ):
                failed = True
                raise OSError("injected final draft rebind failure")
            await original_save(entity, expected_revision=expected_revision)

        monkeypatch.setattr(repository, "save", fail_first_rebind)
        interrupted = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/save",
            json_data={"expected_revision": 1},
        )
        assert interrupted.status_code == 500
        assert len(tuple((tmp_path / "motions").glob("*.json"))) == 1
        intent_draft = await repository.get(UUID(draft["id"]))
        assert intent_draft is not None
        assert intent_draft.revision == 2
        assert intent_draft.save_intent is not None
        target_motion_id = str(intent_draft.save_intent.target_motion_id)

        advanced = await api_request(
            app,
            "PATCH",
            f"/api/v1/motions/{target_motion_id}",
            json_data={"expected_revision": 1, "name": "Advanced before recovery"},
        )
        assert advanced.status_code == 200, advanced.text
        assert advanced.json()["revision"] == 2

        monkeypatch.setattr(repository, "save", original_save)
        restarted = make_stage6_app(tmp_path)
        blocked = await api_request(restarted, "GET", f"/api/v1/studio/drafts/{draft['id']}")
        assert blocked.status_code == 409, blocked.text
        conflict = blocked.json()["details"]
        assert conflict["reason"] == "FORMAL_SAVE_TARGET_REVISION_ADVANCED"
        assert conflict["entity"] == "Motion"
        assert conflict["draft_id"] == draft["id"]
        assert conflict["draft_revision"] == 2
        assert conflict["operation_id"] == str(intent_draft.save_intent.operation_id)
        assert conflict["kind"] == "SAVE"
        assert conflict["target_motion_revision"] == 1
        assert conflict["actual_target_revision"] == 2
        assert len(tuple((tmp_path / "motions").glob("*.json"))) == 1

        blocked_fork = await api_request(
            restarted,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/fork",
            json_data={"expected_revision": 2},
        )
        assert blocked_fork.status_code == 409
        assert blocked_fork.json()["details"]["reason"] == "FORMAL_SAVE_TARGET_REVISION_ADVANCED"

        wrong_confirm = await api_request(
            restarted,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/save-intent/abandon",
            json_data={
                "expected_revision": 2,
                "operation_id": conflict["operation_id"],
                "confirm": "abandon",
            },
        )
        assert wrong_confirm.status_code == 422

        wrong_revision = await api_request(
            restarted,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/save-intent/abandon",
            json_data={
                "expected_revision": 1,
                "operation_id": conflict["operation_id"],
                "confirm": "ABANDON_FORMAL_SAVE",
            },
        )
        assert wrong_revision.status_code == 409
        assert wrong_revision.json()["details"]["entity"] == "MotionDraft"
        assert wrong_revision.json()["details"]["reason"] == "FORMAL_SAVE_DRAFT_REVISION_MISMATCH"

        wrong_operation = await api_request(
            restarted,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/save-intent/abandon",
            json_data={
                "expected_revision": 2,
                "operation_id": str(uuid4()),
                "confirm": "ABANDON_FORMAL_SAVE",
            },
        )
        assert wrong_operation.status_code == 409
        assert wrong_operation.json()["details"]["entity"] == "MotionDraft"
        assert wrong_operation.json()["details"]["reason"] == "FORMAL_SAVE_OPERATION_MISMATCH"

        abandoned = await api_request(
            restarted,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/save-intent/abandon",
            json_data={
                "expected_revision": 2,
                "operation_id": conflict["operation_id"],
                "confirm": "ABANDON_FORMAL_SAVE",
            },
        )
        assert abandoned.status_code == 200, abandoned.text
        abandoned_draft = abandoned.json()
        assert abandoned_draft["revision"] == 3
        assert abandoned_draft["save_intent"] is None
        assert abandoned_draft["source_motion_id"] is None
        before_abandon = intent_draft.model_dump(mode="json")
        after_abandon = deepcopy(abandoned_draft)
        for field in ("save_intent", "revision", "updated_at"):
            before_abandon.pop(field)
            after_abandon.pop(field)
        assert after_abandon == before_abandon

        target = await api_request(restarted, "GET", f"/api/v1/motions/{target_motion_id}")
        assert target.status_code == 200
        assert target.json()["revision"] == 2
        assert target.json()["name"] == "Advanced before recovery"

        no_marker = await api_request(
            restarted,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/save-intent/abandon",
            json_data={
                "expected_revision": 3,
                "operation_id": conflict["operation_id"],
                "confirm": "ABANDON_FORMAL_SAVE",
            },
        )
        assert no_marker.status_code == 409
        assert no_marker.json()["details"] == {
            "entity": "MotionDraft",
            "reason": "FORMAL_SAVE_INTENT_NOT_FOUND",
            "draft_id": draft["id"],
            "draft_revision": 3,
        }
        assert len(tuple((tmp_path / "motions").glob("*.json"))) == 1

    asyncio.run(scenario())


def test_cancelled_formal_save_finishes_shielded_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        snapshot = await connect_and_capture(app)
        created = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data=create_body(frames=keyframes(snapshot), name="Cancelled request"),
        )
        draft = created.json()
        library = app.state.library_service
        original_persist = library.persist_motion_candidate
        persist_entered = asyncio.Event()
        release_persist = asyncio.Event()

        async def delayed_persist(*args: Any, **kwargs: Any) -> Any:
            persist_entered.set()
            await release_persist.wait()
            return await original_persist(*args, **kwargs)

        monkeypatch.setattr(library, "persist_motion_candidate", delayed_persist)
        request_task = asyncio.create_task(
            api_request(
                app,
                "POST",
                f"/api/v1/studio/drafts/{draft['id']}/save",
                json_data={"expected_revision": 1},
            )
        )
        await asyncio.wait_for(persist_entered.wait(), timeout=1.0)
        request_task.cancel()
        await asyncio.sleep(0)
        assert request_task.done() is False
        release_persist.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(request_task, timeout=2.0)

        recovered = await api_request(app, "GET", f"/api/v1/studio/drafts/{draft['id']}")
        assert recovered.status_code == 200, recovered.text
        recovered_draft = recovered.json()
        assert recovered_draft["revision"] == 3
        assert recovered_draft["source_motion_id"] is not None
        assert recovered_draft["source_motion_revision"] == 1
        assert recovered_draft["save_intent"] is None
        assert len(tuple((tmp_path / "motions").glob("*.json"))) == 1

    asyncio.run(scenario())


def test_concurrent_compile_and_save_have_no_lock_inversion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        snapshot = await connect_and_capture(app)
        created = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data=create_body(frames=keyframes(snapshot), name="Lock order"),
        )
        draft = created.json()
        service = app.state.studio_service
        original_compile = service._compile
        compile_entered = asyncio.Event()
        release_compile = asyncio.Event()
        calls = 0

        async def delayed_first_compile(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            if calls == 1:
                compile_entered.set()
                await release_compile.wait()
            return await original_compile(*args, **kwargs)

        monkeypatch.setattr(service, "_compile", delayed_first_compile)
        compile_task = asyncio.create_task(
            api_request(
                app,
                "POST",
                f"/api/v1/studio/drafts/{draft['id']}/compile",
                json_data={"expected_revision": 1},
            )
        )
        await asyncio.wait_for(compile_entered.wait(), timeout=1.0)
        save_task = asyncio.create_task(
            api_request(
                app,
                "POST",
                f"/api/v1/studio/drafts/{draft['id']}/save",
                json_data={"expected_revision": 1},
            )
        )

        async def wait_for_save_to_hold_mutation_lock() -> None:
            while not service._mutation_lock.locked():
                await asyncio.sleep(0)

        await asyncio.wait_for(wait_for_save_to_hold_mutation_lock(), timeout=1.0)
        release_compile.set()
        compiled, saved = await asyncio.wait_for(
            asyncio.gather(compile_task, save_task),
            timeout=2.0,
        )
        assert compiled.status_code == 200, compiled.text
        assert saved.status_code == 200, saved.text

    asyncio.run(scenario())


def test_advanced_save_as_target_preserves_marker_until_exact_abandon(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        snapshot = await connect_and_capture(app)
        created = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data=create_body(frames=keyframes(snapshot), name="Save As source"),
        )
        first_save = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{created.json()['id']}/save",
            json_data={"expected_revision": 1},
        )
        assert first_save.status_code == 200, first_save.text
        source_draft = first_save.json()["draft"]
        source_motion = first_save.json()["motion"]

        repository = app.state.studio_service.drafts
        original_save = repository.save
        failed = False

        async def fail_save_as_rebind(
            entity: Any,
            *,
            expected_revision: int | None = None,
        ) -> None:
            nonlocal failed
            if (
                not failed
                and entity.revision == 5
                and entity.save_intent is None
                and expected_revision == 4
            ):
                failed = True
                raise OSError("injected Save As rebind failure")
            await original_save(entity, expected_revision=expected_revision)

        monkeypatch.setattr(repository, "save", fail_save_as_rebind)
        interrupted = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{source_draft['id']}/save-as",
            json_data={"expected_revision": 3, "name": "Interrupted copy"},
        )
        assert interrupted.status_code == 500
        intent_draft = await repository.get(UUID(source_draft["id"]))
        assert intent_draft is not None
        assert intent_draft.save_intent is not None
        assert intent_draft.save_intent.kind == "SAVE_AS"
        copy_id = intent_draft.save_intent.target_motion_id

        advanced = await api_request(
            app,
            "PATCH",
            f"/api/v1/motions/{copy_id}",
            json_data={"expected_revision": 1, "name": "Advanced copy"},
        )
        assert advanced.status_code == 200, advanced.text
        monkeypatch.setattr(repository, "save", original_save)

        blocked = await api_request(app, "GET", f"/api/v1/studio/drafts/{source_draft['id']}")
        assert blocked.status_code == 409
        details = blocked.json()["details"]
        assert details["entity"] == "Motion"
        assert details["reason"] == "FORMAL_SAVE_TARGET_REVISION_ADVANCED"
        assert details["kind"] == "SAVE_AS"
        assert details["actual_target_revision"] == 2

        abandoned = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{source_draft['id']}/save-intent/abandon",
            json_data={
                "expected_revision": details["draft_revision"],
                "operation_id": details["operation_id"],
                "confirm": "ABANDON_FORMAL_SAVE",
            },
        )
        assert abandoned.status_code == 200, abandoned.text
        assert abandoned.json()["source_motion_id"] == source_motion["id"]
        assert abandoned.json()["source_motion_revision"] == source_motion["revision"]
        assert abandoned.json()["save_intent"] is None
        assert advanced.json()["revision"] == 2

    asyncio.run(scenario())


def test_abandon_serializes_behind_in_flight_formal_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        snapshot = await connect_and_capture(app)
        created = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data=create_body(frames=keyframes(snapshot), name="Serialized abandon"),
        )
        draft = created.json()
        library = app.state.library_service
        original_persist = library.persist_motion_candidate
        persist_entered = asyncio.Event()
        release_persist = asyncio.Event()

        async def delayed_persist(*args: Any, **kwargs: Any) -> Any:
            persist_entered.set()
            await release_persist.wait()
            return await original_persist(*args, **kwargs)

        monkeypatch.setattr(library, "persist_motion_candidate", delayed_persist)
        save_task = asyncio.create_task(
            api_request(
                app,
                "POST",
                f"/api/v1/studio/drafts/{draft['id']}/save",
                json_data={"expected_revision": 1},
            )
        )
        await asyncio.wait_for(persist_entered.wait(), timeout=1.0)
        intent_draft = await app.state.studio_service.drafts.get(UUID(draft["id"]))
        assert intent_draft is not None
        assert intent_draft.save_intent is not None

        abandon_task = asyncio.create_task(
            api_request(
                app,
                "POST",
                f"/api/v1/studio/drafts/{draft['id']}/save-intent/abandon",
                json_data={
                    "expected_revision": intent_draft.revision,
                    "operation_id": str(intent_draft.save_intent.operation_id),
                    "confirm": "ABANDON_FORMAL_SAVE",
                },
            )
        )
        await asyncio.sleep(0)
        assert abandon_task.done() is False

        release_persist.set()
        saved, abandoned = await asyncio.wait_for(
            asyncio.gather(save_task, abandon_task),
            timeout=2.0,
        )
        assert saved.status_code == 200, saved.text
        assert abandoned.status_code == 409, abandoned.text
        assert abandoned.json()["details"]["entity"] == "MotionDraft"
        assert abandoned.json()["details"]["reason"] == "FORMAL_SAVE_DRAFT_REVISION_MISMATCH"
        assert len(tuple((tmp_path / "motions").glob("*.json"))) == 1
        persisted_motion = await api_request(
            app,
            "GET",
            f"/api/v1/motions/{saved.json()['motion']['id']}",
        )
        assert persisted_motion.status_code == 200
        assert persisted_motion.json() == saved.json()["motion"]

    asyncio.run(scenario())


def test_imported_draft_exact_snapshot_trust_and_provenance_survive_save_flows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        snapshot = await connect_and_capture(app)
        imported = await seed_imported_motion(app, snapshot)

        injected_create = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data={**create_body(), "source_metadata": legacy_metadata()},
        )
        assert injected_create.status_code == 422
        injected_registry = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data={
                **create_body(),
                "trusted_legacy_snapshot_sha256": ["a" * 64],
            },
        )
        assert injected_registry.status_code == 422

        fabricated_frames = keyframes(snapshot)
        for keyframe in fabricated_frames:
            keyframe["pose_snapshot"]["state_sequence"] = None
        fabricated = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data=create_body(frames=fabricated_frames, name="Fabricated Legacy"),
        )
        assert fabricated.status_code == 422
        assert "state_sequence" in fabricated.json()["details"]["checks"]

        opened = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/from-motion/{imported.id}",
            json_data={"expected_revision": 1},
        )
        assert opened.status_code == 201, opened.text
        draft = opened.json()
        assert draft["source_metadata"] == legacy_metadata()
        assert len(draft["trusted_legacy_snapshot_sha256"]) == 2
        assert all(frame["pose_snapshot"]["state_sequence"] is None for frame in draft["keyframes"])

        injected_autosave = await api_request(
            app,
            "PUT",
            f"/api/v1/studio/drafts/{draft['id']}",
            json_data={
                **autosave_body(draft),
                "trusted_legacy_snapshot_sha256": draft["trusted_legacy_snapshot_sha256"],
            },
        )
        assert injected_autosave.status_code == 422

        duplicated_frames = deepcopy(draft["keyframes"])
        duplicated_frames[0]["pose_snapshot"], duplicated_frames[1]["pose_snapshot"] = (
            duplicated_frames[1]["pose_snapshot"],
            duplicated_frames[0]["pose_snapshot"],
        )
        duplicate = deepcopy(duplicated_frames[1])
        duplicate["id"] = str(uuid4())
        duplicate["label"] = "Duplicate trusted snapshot"
        duplicated_frames.append(duplicate)
        for frame in duplicated_frames:
            joint_state = frame["pose_snapshot"]["joint_state"]
            for mapping_name in ("positions", "units"):
                joint_state[mapping_name] = dict(reversed(tuple(joint_state[mapping_name].items())))
        duplicated = await api_request(
            app,
            "PUT",
            f"/api/v1/studio/drafts/{draft['id']}",
            json_data=autosave_body(
                draft,
                keyframes=duplicated_frames,
                name="Imported duplicate",
            ),
        )
        assert duplicated.status_code == 200, duplicated.text
        trusted_draft = duplicated.json()
        assert trusted_draft["source_metadata"] == legacy_metadata()
        assert (
            trusted_draft["trusted_legacy_snapshot_sha256"]
            == draft["trusted_legacy_snapshot_sha256"]
        )

        deleted_frames = await api_request(
            app,
            "PUT",
            f"/api/v1/studio/drafts/{draft['id']}",
            json_data=autosave_body(trusted_draft, keyframes=[]),
        )
        assert deleted_frames.status_code == 200, deleted_frames.text
        empty_draft = deleted_frames.json()
        assert empty_draft["keyframes"] == []
        assert (
            empty_draft["trusted_legacy_snapshot_sha256"] == draft["trusted_legacy_snapshot_sha256"]
        )

        restored = await api_request(
            app,
            "PUT",
            f"/api/v1/studio/drafts/{draft['id']}",
            json_data=autosave_body(empty_draft, keyframes=duplicated_frames),
        )
        assert restored.status_code == 200, restored.text
        restored_draft = restored.json()
        assert restored_draft["keyframes"] == duplicated_frames

        stale_fork = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/fork",
            json_data={"expected_revision": empty_draft["revision"]},
        )
        assert stale_fork.status_code == 409
        assert stale_fork.json()["details"] == {
            "entity": "MotionDraft",
            "expected_revision": empty_draft["revision"],
            "actual_revision": restored_draft["revision"],
        }

        forked = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/fork",
            json_data={"expected_revision": restored_draft["revision"]},
        )
        assert forked.status_code == 201, forked.text
        forked_draft = forked.json()
        assert forked_draft["id"] != draft["id"]
        assert forked_draft["revision"] == 1
        assert forked_draft["save_intent"] is None
        assert forked_draft["source_motion_id"] == draft["source_motion_id"]
        assert forked_draft["source_motion_revision"] == draft["source_motion_revision"]
        assert forked_draft["source_metadata"] == draft["source_metadata"]
        assert (
            forked_draft["trusted_legacy_snapshot_sha256"]
            == draft["trusted_legacy_snapshot_sha256"]
        )

        fabricated_fork_frames = deepcopy(forked_draft["keyframes"])
        fabricated_fork_frames[0]["pose_snapshot"]["captured_at"] = "2025-01-01T00:00:00Z"
        fabricated_fork = await api_request(
            app,
            "PUT",
            f"/api/v1/studio/drafts/{forked_draft['id']}",
            json_data=autosave_body(forked_draft, keyframes=fabricated_fork_frames),
        )
        assert fabricated_fork.status_code == 422
        assert "state_sequence" in fabricated_fork.json()["details"]["checks"]

        local_fork = await api_request(
            app,
            "PUT",
            f"/api/v1/studio/drafts/{forked_draft['id']}",
            json_data=autosave_body(forked_draft, name="Conflict-preserving fork"),
        )
        assert local_fork.status_code == 200, local_fork.text
        fork_saved_as = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{forked_draft['id']}/save-as",
            json_data={
                "expected_revision": local_fork.json()["revision"],
                "name": "Conflict-preserving Motion",
            },
        )
        assert fork_saved_as.status_code == 201, fork_saved_as.text
        assert fork_saved_as.json()["motion"]["source_metadata"] == legacy_metadata()
        assert (
            fork_saved_as.json()["draft"]["trusted_legacy_snapshot_sha256"]
            == draft["trusted_legacy_snapshot_sha256"]
        )
        unchanged_source_draft = await api_request(
            app,
            "GET",
            f"/api/v1/studio/drafts/{draft['id']}",
        )
        assert unchanged_source_draft.status_code == 200
        assert unchanged_source_draft.json() == restored_draft
        unchanged_source_motion = await api_request(
            app,
            "GET",
            f"/api/v1/motions/{imported.id}",
        )
        assert unchanged_source_motion.status_code == 200
        assert unchanged_source_motion.json() == imported.model_dump(mode="json")

        altered_frames = deepcopy(restored_draft["keyframes"])
        altered_frames[0]["pose_snapshot"]["captured_at"] = "2026-01-01T00:00:00Z"
        altered = await api_request(
            app,
            "PUT",
            f"/api/v1/studio/drafts/{draft['id']}",
            json_data=autosave_body(restored_draft, keyframes=altered_frames),
        )
        assert altered.status_code == 422
        assert "state_sequence" in altered.json()["details"]["checks"]

        compiled_metadata: list[LegacyImportMetadata | None] = []
        studio = app.state.studio_service
        original_compile = studio._compile

        async def observe_compile(candidate: Motion, *, sample_rate_hz: float) -> Any:
            compiled_metadata.append(candidate.source_metadata)
            return await original_compile(candidate, sample_rate_hz=sample_rate_hz)

        monkeypatch.setattr(studio, "_compile", observe_compile)
        compiled = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/compile",
            json_data={"expected_revision": restored_draft["revision"]},
        )
        assert compiled.status_code == 200, compiled.text
        assert compiled.json()["preflight"]["passed"] is True
        assert compiled_metadata == [imported.source_metadata]

        saved = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/save",
            json_data={
                "expected_revision": restored_draft["revision"],
                "expected_source_revision": 1,
            },
        )
        assert saved.status_code == 200, saved.text
        saved_data = saved.json()
        assert saved_data["motion"]["source_metadata"] == legacy_metadata()
        assert saved_data["draft"]["source_metadata"] == legacy_metadata()
        assert (
            saved_data["draft"]["trusted_legacy_snapshot_sha256"]
            == draft["trusted_legacy_snapshot_sha256"]
        )

        deleted = await api_request(
            app,
            "DELETE",
            f"/api/v1/motions/{imported.id}?expected_revision=2",
        )
        assert deleted.status_code == 204
        saved_as = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/save-as",
            json_data={
                "expected_revision": saved_data["draft"]["revision"],
                "name": "Imported recovery copy",
            },
        )
        assert saved_as.status_code == 201, saved_as.text
        assert saved_as.json()["motion"]["source_metadata"] == legacy_metadata()
        assert saved_as.json()["draft"]["source_metadata"] == legacy_metadata()
        assert (
            saved_as.json()["draft"]["trusted_legacy_snapshot_sha256"]
            == draft["trusted_legacy_snapshot_sha256"]
        )

    asyncio.run(scenario())


def test_exact_imported_library_pose_is_server_trusted_when_added_to_studio(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        captured = await connect_and_capture(app)
        legacy_snapshot_data = deepcopy(captured)
        legacy_snapshot_data["state_sequence"] = None
        legacy_snapshot = PoseSnapshot.model_validate(legacy_snapshot_data)
        source_pose = Pose(
            name="Reviewed Legacy V2 Pose",
            description="Imported by the reviewed Legacy Pose workflow.",
            snapshot=legacy_snapshot,
            tags=["legacy-import", "legacy-v2"],
        )
        await app.state.library_service.poses.save(source_pose)

        created = await api_request(
            app,
            "POST",
            "/api/v1/studio/drafts",
            json_data=create_body(name="Legacy Pose composition"),
        )
        assert created.status_code == 201, created.text
        draft = created.json()
        frames = keyframes(legacy_snapshot.model_dump(mode="json"))
        for frame in frames:
            frame["source_pose_id"] = str(source_pose.id)

        autosaved = await api_request(
            app,
            "PUT",
            f"/api/v1/studio/drafts/{draft['id']}",
            json_data=autosave_body(draft, keyframes=frames),
        )
        assert autosaved.status_code == 200, autosaved.text
        trusted_draft = autosaved.json()
        assert trusted_draft["trusted_legacy_snapshot_sha256"] == [
            legacy_snapshot_sha256(legacy_snapshot)
        ]

        altered_frames = deepcopy(frames)
        altered_frames[0]["pose_snapshot"]["captured_at"] = "2026-01-01T00:00:00Z"
        altered = await api_request(
            app,
            "PUT",
            f"/api/v1/studio/drafts/{draft['id']}",
            json_data=autosave_body(trusted_draft, keyframes=altered_frames),
        )
        assert altered.status_code == 422
        assert "state_sequence" in altered.json()["details"]["checks"]

        compiled = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/compile",
            json_data={"expected_revision": trusted_draft["revision"]},
        )
        assert compiled.status_code == 200, compiled.text
        assert compiled.json()["preflight"]["passed"] is True

        saved_as = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/save-as",
            json_data={
                "expected_revision": trusted_draft["revision"],
                "name": "Legacy Pose composition",
            },
        )
        assert saved_as.status_code == 201, saved_as.text
        assert saved_as.json()["motion"]["source_metadata"] is None
        assert saved_as.json()["draft"]["trusted_legacy_snapshot_sha256"] == [
            legacy_snapshot_sha256(legacy_snapshot)
        ]

    asyncio.run(scenario())


def test_recovery_semantic_match_includes_legacy_source_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        app = make_stage6_app(tmp_path)
        snapshot = await connect_and_capture(app)
        imported = await seed_imported_motion(app, snapshot)
        opened = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/from-motion/{imported.id}",
            json_data={"expected_revision": 1},
        )
        assert opened.status_code == 201
        draft = opened.json()
        library = app.state.library_service

        async def persist_with_different_metadata(
            candidate: Motion,
            *,
            expected_revision: int | None,
            trusted_legacy_snapshot_sha256: frozenset[str],
        ) -> Motion:
            del trusted_legacy_snapshot_sha256
            assert expected_revision is None
            candidate_data = candidate.model_dump(mode="python")
            candidate_data["source_metadata"] = LegacyImportMetadata(
                source_file_name="different.json",
                source_sha256="b" * 64,
            )
            foreign = Motion.model_validate(candidate_data)
            await library.motions.save(foreign)
            raise OSError("simulated crash after semantically different write")

        monkeypatch.setattr(library, "persist_motion_candidate", persist_with_different_metadata)
        interrupted = await api_request(
            app,
            "POST",
            f"/api/v1/studio/drafts/{draft['id']}/save-as",
            json_data={"expected_revision": 1, "name": "Metadata-sensitive copy"},
        )
        assert interrupted.status_code == 500

        blocked = await api_request(app, "GET", f"/api/v1/studio/drafts/{draft['id']}")
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["details"]["entity"] == "Motion"
        assert blocked.json()["details"]["reason"] == "FORMAL_SAVE_TARGET_CONTENT_MISMATCH"
        raw = await app.state.studio_service.drafts.get(UUID(draft["id"]))
        assert raw is not None
        assert raw.save_intent is not None
        assert raw.source_metadata == imported.source_metadata

    asyncio.run(scenario())
