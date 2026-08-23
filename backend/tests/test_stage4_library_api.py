"""Stage 4 coherent capture, Library CRUD, bounded lists, and safe Goto APIs."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.robot_service import RobotApplicationService
from momo.domain.enums import RobotVariant
from momo.domain.pose import Pose, PoseSnapshot
from tests.factories import make_snapshot
from tests.stage4_helpers import api_request, make_stage4_app


async def capture(app: Any, name: str, tags: list[str] | None = None) -> dict[str, Any]:
    response = await api_request(
        app,
        "POST",
        "/api/v1/poses/capture",
        json_data={"name": name, "tags": tags or []},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def motion_body(
    first: dict[str, Any], second: dict[str, Any], name: str = "Motion"
) -> dict[str, Any]:
    return {
        "name": name,
        "robot_variant": first["snapshot"]["robot_variant"],
        "tags": ["demo"],
        "keyframes": [
            {
                "label": "Start",
                "source_pose_id": first["id"],
                "pose_snapshot": deepcopy(first["snapshot"]),
                "hold_s": 0.0,
                "incoming_transition": None,
            },
            {
                "label": "End",
                "source_pose_id": second["id"],
                "pose_snapshot": deepcopy(second["snapshot"]),
                "hold_s": 0.5,
                "incoming_transition": {
                    "duration_s": 1.0,
                    "motion_mode": "JOINT",
                    "easing": "SMOOTHSTEP",
                },
            },
        ],
    }


def test_capture_requires_connected_fresh_state_and_persists_coherent_fk(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        unavailable = await api_request(
            app,
            "POST",
            "/api/v1/poses/capture",
            json_data={"name": "Unavailable"},
        )
        assert unavailable.status_code == 409
        assert unavailable.json()["code"] == "CAPTURE_STATE_CHANGED"

        connected = await api_request(app, "POST", "/api/v1/robot/connect")
        status = connected.json()["status"]
        pose = await capture(app, "Captured", ["hero"])
        snapshot = pose["snapshot"]
        assert snapshot["state_sequence"] == status["state_sequence"]
        assert snapshot["profile_fingerprint"] == status["profile_fingerprint"]
        assert snapshot["hardware_snapshot"] is None
        assert snapshot["calibration_fingerprint"] is None
        fk = await api_request(app, "GET", "/api/v1/robot/fk")
        assert snapshot["tcp_pose"] == fk.json()["tcp_pose"]
        assert snapshot["kinematics_fingerprint"] == fk.json()["kinematics_fingerprint"]

    asyncio.run(scenario())


def test_capture_retries_then_rejects_when_sequence_changes_during_fk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await api_request(app, "POST", "/api/v1/robot/connect")
        robot: RobotApplicationService = app.state.robot_service
        kinematics: KinematicsService = app.state.kinematics_service
        original = kinematics.forward
        calls = 0

        async def moving_forward(*args: object, **kwargs: object) -> object:
            nonlocal calls
            result = await original(*args, **kwargs)  # type: ignore[arg-type]
            _, _, state = await robot.get_motion_snapshot()
            await robot.apply_motion_state(uuid4(), state)
            calls += 1
            return result

        monkeypatch.setattr(kinematics, "forward", moving_forward)
        response = await api_request(
            app,
            "POST",
            "/api/v1/poses/capture",
            json_data={"name": "Racing"},
        )
        assert response.status_code == 409
        assert response.json()["details"] == {"attempts": 3}
        assert calls == 3

    asyncio.run(scenario())


def test_pose_crud_duplicate_revision_search_sort_tag_and_path_safe_errors(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await api_request(app, "POST", "/api/v1/robot/connect")
        first = await capture(app, "Zulu", ["shared", "z"])
        second = await capture(app, "Alpha", ["shared", "a"])

        listing = await api_request(
            app,
            "GET",
            "/api/v1/poses?search=alp&tag=shared&sort=name&order=asc&page_size=1",
        )
        assert listing.status_code == 200
        assert listing.json()["total"] == 1
        summary = listing.json()["items"][0]
        assert summary["name"] == "Alpha"
        assert "snapshot" not in summary
        assert "hardware_snapshot" not in listing.text

        duplicate = await api_request(
            app,
            "POST",
            f"/api/v1/poses/{second['id']}/duplicate",
            json_data={"expected_revision": 1, "name": "Alpha"},
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["name"] == "Alpha"
        assert duplicate.json()["id"] != second["id"]

        updated = await api_request(
            app,
            "PATCH",
            f"/api/v1/poses/{first['id']}",
            json_data={"expected_revision": 1, "name": "Updated"},
        )
        assert updated.status_code == 200
        assert updated.json()["revision"] == 2
        conflict = await api_request(
            app,
            "PATCH",
            f"/api/v1/poses/{first['id']}",
            json_data={"expected_revision": 1, "name": "Stale"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "REVISION_CONFLICT"
        assert str(tmp_path) not in conflict.text

        deleted = await api_request(
            app,
            "DELETE",
            f"/api/v1/poses/{first['id']}?expected_revision=2",
        )
        assert deleted.status_code == 204
        missing = await api_request(app, "GET", f"/api/v1/poses/{first['id']}")
        assert missing.status_code == 404
        assert missing.json()["code"] == "ENTITY_NOT_FOUND"
        traversal = await api_request(app, "GET", "/api/v1/poses/..%2F..%2Fsecret")
        assert traversal.status_code in {404, 422}
        assert str(tmp_path) not in traversal.text

    asyncio.run(scenario())


def test_motion_crud_summary_and_pose_deletion_preserve_embedded_snapshots(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await api_request(app, "POST", "/api/v1/robot/connect")
        first = await capture(app, "Start")
        second = await capture(app, "End")
        created = await api_request(
            app,
            "POST",
            "/api/v1/motions",
            json_data=motion_body(first, second, "Demo motion"),
        )
        assert created.status_code == 201, created.text
        motion = created.json()
        embedded = motion["keyframes"]

        listing = await api_request(app, "GET", "/api/v1/motions?tag=demo")
        assert listing.status_code == 200
        summary = listing.json()["items"][0]
        assert summary["keyframe_count"] == 2
        assert summary["total_duration_s"] == 1.5
        assert summary["motion_types"] == ["JOINT"]
        assert "keyframes" not in summary

        await api_request(
            app,
            "DELETE",
            f"/api/v1/poses/{first['id']}?expected_revision=1",
        )
        restored = await api_request(app, "GET", f"/api/v1/motions/{motion['id']}")
        assert restored.json()["keyframes"] == embedded

        duplicate = await api_request(
            app,
            "POST",
            f"/api/v1/motions/{motion['id']}/duplicate",
            json_data={"expected_revision": 1},
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["id"] != motion["id"]
        patched = await api_request(
            app,
            "PATCH",
            f"/api/v1/motions/{motion['id']}",
            json_data={"expected_revision": 1, "name": "Renamed"},
        )
        assert patched.json()["revision"] == 2
        deleted = await api_request(
            app,
            "DELETE",
            f"/api/v1/motions/{motion['id']}?expected_revision=2",
        )
        assert deleted.status_code == 204

    asyncio.run(scenario())


def test_goto_rejects_fingerprint_and_variant_mismatch_then_uses_gateway(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await api_request(app, "POST", "/api/v1/robot/connect")
        captured = await capture(app, "Compatible")
        accepted = await api_request(
            app,
            "POST",
            f"/api/v1/poses/{captured['id']}/goto",
            json_data={
                "expected_revision": 1,
                "duration_s": 0.1,
                "speed_scale": 1.0,
                "idempotency_key": "library-goto",
            },
        )
        assert accepted.status_code == 202, accepted.text
        checks = {item["name"]: item for item in accepted.json()["preflight"]["checks"]}
        assert checks["command_source"]["passed"] is True
        await api_request(app, "POST", "/api/v1/motion/stop")

        bad_snapshot_data = captured["snapshot"].copy()
        bad_snapshot_data["profile_fingerprint"] = "f" * 64
        bad_pose = Pose(
            name="Wrong profile",
            snapshot=PoseSnapshot.model_validate(bad_snapshot_data),
        )
        await app.state.library_service.poses.save(bad_pose)
        rejected = await api_request(
            app,
            "POST",
            f"/api/v1/poses/{bad_pose.id}/goto",
            json_data={"expected_revision": 1, "idempotency_key": "bad-goto"},
        )
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "POSE_INCOMPATIBLE"
        assert "profile_fingerprint" in rejected.json()["details"]["checks"]

        v1_snapshot = make_snapshot(RobotVariant.V1).model_dump(mode="json")
        wrong_variant = Pose(
            name="V1",
            snapshot=PoseSnapshot.model_validate(v1_snapshot),
        )
        await app.state.library_service.poses.save(wrong_variant)
        variant_rejected = await api_request(
            app,
            "POST",
            f"/api/v1/poses/{wrong_variant.id}/goto",
            json_data={"expected_revision": 1, "idempotency_key": "variant-goto"},
        )
        assert variant_rejected.status_code == 422
        assert "robot_variant" in variant_rejected.json()["details"]["checks"]

    asyncio.run(scenario())


def test_public_create_rejects_hardware_provenance_and_profile_returns_kinematics(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        profile = await api_request(app, "GET", "/api/v1/robot/profile")
        assert len(profile.json()["kinematics_fingerprint"]) == 64

        snapshot = make_snapshot().model_dump(mode="json")
        snapshot["hardware_snapshot"] = {"raw": {"j10": 1}}
        pose = await api_request(
            app,
            "POST",
            "/api/v1/poses",
            json_data={"name": "Forbidden", "snapshot": snapshot},
        )
        assert pose.status_code == 422
        assert pose.json()["code"] == "POSE_INCOMPATIBLE"

    asyncio.run(scenario())


def test_list_resource_bounds_omit_large_pose_hardware_snapshot(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        repository = app.state.library_service.poses
        snapshot_data = make_snapshot().model_dump(mode="python")
        snapshot_data["hardware_snapshot"] = {"blob": "x" * 60000}
        from momo.domain.pose import PoseSnapshot

        for index in range(10):
            await repository.save(
                Pose(name=f"Large {index}", snapshot=PoseSnapshot.model_validate(snapshot_data))
            )
        response = await api_request(app, "GET", "/api/v1/poses?page_size=50")
        assert response.status_code == 200
        assert len(response.content) < 100_000
        assert b"hardware_snapshot" not in response.content

    asyncio.run(scenario())


def test_patch_nulls_and_normalized_duplicate_tags_are_request_errors(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)

        duplicate_capture_tags = await api_request(
            app,
            "POST",
            "/api/v1/poses/capture",
            json_data={"name": "Duplicate tags", "tags": ["Demo", " demo "]},
        )
        assert duplicate_capture_tags.status_code == 422
        assert duplicate_capture_tags.json()["code"] == "REQUEST_VALIDATION_ERROR"

        await api_request(app, "POST", "/api/v1/robot/connect")
        first = await capture(app, "First")
        second = await capture(app, "Second")

        duplicate_pose_tags = await api_request(
            app,
            "POST",
            "/api/v1/poses",
            json_data={
                "name": "Duplicate pose tags",
                "tags": ["Hero", " hero"],
                "snapshot": first["snapshot"],
            },
        )
        assert duplicate_pose_tags.status_code == 422
        assert duplicate_pose_tags.json()["code"] == "REQUEST_VALIDATION_ERROR"

        duplicate_motion_body = motion_body(first, second, "Duplicate motion tags")
        duplicate_motion_body["tags"] = ["Demo", "demo"]
        duplicate_motion_tags = await api_request(
            app,
            "POST",
            "/api/v1/motions",
            json_data=duplicate_motion_body,
        )
        assert duplicate_motion_tags.status_code == 422
        assert duplicate_motion_tags.json()["code"] == "REQUEST_VALIDATION_ERROR"

        for field in ("name", "description", "tags"):
            rejected = await api_request(
                app,
                "PATCH",
                f"/api/v1/poses/{first['id']}",
                json_data={"expected_revision": 1, field: None},
            )
            assert rejected.status_code == 422
            assert rejected.json()["code"] == "REQUEST_VALIDATION_ERROR"

        created_motion = await api_request(
            app,
            "POST",
            "/api/v1/motions",
            json_data=motion_body(first, second),
        )
        assert created_motion.status_code == 201, created_motion.text
        motion = created_motion.json()
        for field in (
            "name",
            "description",
            "robot_variant",
            "keyframes",
            "playback_defaults",
            "tags",
        ):
            rejected = await api_request(
                app,
                "PATCH",
                f"/api/v1/motions/{motion['id']}",
                json_data={"expected_revision": 1, field: None},
            )
            assert rejected.status_code == 422
            assert rejected.json()["code"] == "REQUEST_VALIDATION_ERROR"

    asyncio.run(scenario())


def test_default_duplicate_names_are_bounded_for_maximum_length_entities(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await api_request(app, "POST", "/api/v1/robot/connect")
        pose_name = "P" * 200
        first = await capture(app, pose_name)
        second = await capture(app, "Second")

        pose_copy = await api_request(
            app,
            "POST",
            f"/api/v1/poses/{first['id']}/duplicate",
            json_data={"expected_revision": 1},
        )
        assert pose_copy.status_code == 201, pose_copy.text
        assert pose_copy.json()["name"] == f"{'P' * 195} Copy"
        assert len(pose_copy.json()["name"]) == 200

        motion_name = "M" * 200
        created_motion = await api_request(
            app,
            "POST",
            "/api/v1/motions",
            json_data=motion_body(first, second, motion_name),
        )
        assert created_motion.status_code == 201, created_motion.text
        motion_copy = await api_request(
            app,
            "POST",
            f"/api/v1/motions/{created_motion.json()['id']}/duplicate",
            json_data={"expected_revision": 1},
        )
        assert motion_copy.status_code == 201, motion_copy.text
        assert motion_copy.json()["name"] == f"{'M' * 195} Copy"
        assert len(motion_copy.json()["name"]) == 200

    asyncio.run(scenario())


def test_public_snapshots_require_units_owned_provenance_and_canonical_tcp(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await api_request(app, "POST", "/api/v1/robot/connect")
        first = await capture(app, "First")
        second = await capture(app, "Second")

        for missing_units in ("omitted", "null"):
            unitless = deepcopy(first["snapshot"])
            if missing_units == "omitted":
                del unitless["joint_state"]["units"]
            else:
                unitless["joint_state"]["units"] = None
            rejected = await api_request(
                app,
                "POST",
                "/api/v1/poses",
                json_data={"name": f"Units {missing_units}", "snapshot": unitless},
            )
            assert rejected.status_code == 422
            assert rejected.json()["code"] == "REQUEST_VALIDATION_ERROR"

        valid = await api_request(
            app,
            "POST",
            "/api/v1/poses",
            json_data={"name": "Valid clone", "snapshot": first["snapshot"]},
        )
        assert valid.status_code == 201, valid.text
        goto = await api_request(
            app,
            "POST",
            f"/api/v1/poses/{valid.json()['id']}/goto",
            json_data={"expected_revision": 1, "idempotency_key": "unit-safe-goto"},
        )
        assert goto.status_code == 202, goto.text
        await api_request(app, "POST", "/api/v1/motion/stop")

        calibration = deepcopy(first["snapshot"])
        calibration["calibration_fingerprint"] = "c" * 64
        forbidden_calibration = await api_request(
            app,
            "POST",
            "/api/v1/poses",
            json_data={"name": "Forged calibration", "snapshot": calibration},
        )
        assert forbidden_calibration.status_code == 422
        assert forbidden_calibration.json()["code"] == "POSE_INCOMPATIBLE"
        assert (
            "calibration_fingerprint_must_be_null"
            in forbidden_calibration.json()["details"]["checks"]
        )

        forged_tcp = deepcopy(first["snapshot"])
        forged_tcp["tcp_pose"]["position_mm"]["x"] += 500
        forbidden_tcp = await api_request(
            app,
            "POST",
            "/api/v1/poses",
            json_data={"name": "Forged TCP", "snapshot": forged_tcp},
        )
        assert forbidden_tcp.status_code == 422
        assert forbidden_tcp.json()["code"] == "POSE_INCOMPATIBLE"
        assert "tcp_pose" in forbidden_tcp.json()["details"]["checks"]

        hardware_motion = motion_body(first, second, "Hardware provenance")
        hardware_motion["keyframes"][1]["pose_snapshot"]["hardware_snapshot"] = {"raw": 1}
        forbidden_hardware_motion = await api_request(
            app,
            "POST",
            "/api/v1/motions",
            json_data=hardware_motion,
        )
        assert forbidden_hardware_motion.status_code == 422
        assert forbidden_hardware_motion.json()["code"] == "POSE_INCOMPATIBLE"

        calibration_motion = motion_body(first, second, "Calibration provenance")
        calibration_motion["keyframes"][0]["pose_snapshot"]["calibration_fingerprint"] = "d" * 64
        forbidden_calibration_motion = await api_request(
            app,
            "POST",
            "/api/v1/motions",
            json_data=calibration_motion,
        )
        assert forbidden_calibration_motion.status_code == 422
        assert forbidden_calibration_motion.json()["code"] == "POSE_INCOMPATIBLE"

        tcp_motion = motion_body(first, second, "Forged Cartesian TCP")
        tcp_motion["keyframes"][1]["incoming_transition"]["motion_mode"] = "CARTESIAN_LINEAR"
        tcp_motion["keyframes"][1]["pose_snapshot"]["tcp_pose"]["position_mm"]["x"] += 500
        forbidden_tcp_motion = await api_request(
            app,
            "POST",
            "/api/v1/motions",
            json_data=tcp_motion,
        )
        assert forbidden_tcp_motion.status_code == 422
        assert forbidden_tcp_motion.json()["code"] == "POSE_INCOMPATIBLE"
        assert "tcp_pose" in forbidden_tcp_motion.json()["details"]["checks"]

    asyncio.run(scenario())


def test_aggregate_motion_invariants_are_structured_entity_errors(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = make_stage4_app(tmp_path)
        await api_request(app, "POST", "/api/v1/robot/connect")
        first = await capture(app, "First")
        second = await capture(app, "Second")

        mismatched = motion_body(first, second, "Mismatch")
        mismatched["robot_variant"] = "V1"
        rejected_create = await api_request(
            app,
            "POST",
            "/api/v1/motions",
            json_data=mismatched,
        )
        assert rejected_create.status_code == 422
        assert rejected_create.json()["code"] == "ENTITY_INVALID"
        assert rejected_create.json()["message"] == "Motion request violates entity invariants"
        assert rejected_create.json()["details"] == {"entity": "motion"}

        created = await api_request(
            app,
            "POST",
            "/api/v1/motions",
            json_data=motion_body(first, second, "Valid"),
        )
        assert created.status_code == 201, created.text
        rejected_patch = await api_request(
            app,
            "PATCH",
            f"/api/v1/motions/{created.json()['id']}",
            json_data={"expected_revision": 1, "robot_variant": "V1"},
        )
        assert rejected_patch.status_code == 422
        assert rejected_patch.json()["code"] == "ENTITY_INVALID"
        assert "V2" not in rejected_patch.text

    asyncio.run(scenario())
