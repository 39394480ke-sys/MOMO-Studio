"""Validated, explicit-path, default-dry-run Legacy action importer contracts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

import momo.tools.import_legacy_actions as importer_module
from momo.adapters.kinematics.model_repository import FileKinematicsModelRepository
from momo.adapters.kinematics.serial_chain import SerialChainKinematics
from momo.adapters.storage.file_motion_repository import FileMotionRepository
from momo.adapters.storage.profile_repository import FileProfileRepository
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.profile_service import ProfileService
from momo.domain.motion import Motion
from momo.settings import repository_root
from momo.tools.import_legacy_actions import (
    ImportReport,
    LegacyImportError,
    import_legacy_actions,
    main,
    parse_args,
)
from tests.stage3_helpers import FakeClock


def importer_dependencies(
    tmp_path: Path,
) -> tuple[FileMotionRepository, ProfileService, KinematicsService, FakeClock]:
    root = repository_root()
    clock = FakeClock()
    return (
        FileMotionRepository(tmp_path / "motions", clock),
        ProfileService(FileProfileRepository(root / "robot_profiles")),
        KinematicsService(
            FileKinematicsModelRepository(root / "kinematics_models"),
            SerialChainKinematics(),
        ),
        clock,
    )


def tracked_shape(*, conflicting_replay: bool = False) -> dict[str, object]:
    first = {"J10": 10.0, "J11": 0.0, "J12": 0.0, "J13": 0.0, "J14": 0.0, "J15": 0.0}
    second = {"J10": 20.0, "J11": 2.0, "J12": 3.0, "J13": 4.0, "J14": 5.0, "J15": 6.0}
    replay_second = dict(second)
    if conflicting_replay:
        replay_second["J11"] = 9.0
    return {
        "schema_version": "arm_replay_sequence_v1",
        "id": "legacy-file-id-must-not-be-filename",
        "name": "Tracked-shape fixture",
        "robot_variant": "V2",
        "source": "web_record:arm_a",
        "joint_order": ["J10", "J11", "J12", "J13", "J14", "J15"],
        "pose_count": 2,
        "playback": {"default_duration_sec": 1.25},
        "raw_present_position": {"11": 1234},
        "poses": [
            {
                "label": "Start",
                "joint_targets_deg": {**first, "gripper": 0.5},
                "replay_joint_targets_deg": {**first, "gripper": 0.5},
                "duration_sec": 0.0,
                "hold_sec": 0.1,
                "tcp_pose": {"xyz": [0.1, 0.2, 0.3], "rpy": [0, 0, 0]},
            },
            {
                "label": "End",
                "joint_targets_deg": second,
                "replay_joint_targets_deg": replay_second,
                "duration_sec": 0.0,
                "hold_sec": 0.2,
                "replay_multi_turn_continuous_raw": {"J11": 9999},
            },
        ],
    }


async def run_import(
    tmp_path: Path, source: Path, *, dry_run: bool
) -> tuple[ImportReport, FileMotionRepository]:
    repository, profiles, kinematics, clock = importer_dependencies(tmp_path)
    report = await import_legacy_actions(
        source,
        repository=repository,
        profiles=profiles,
        kinematics=kinematics,
        clock=clock,
        dry_run=dry_run,
    )
    return report, repository


def test_tracked_shape_aliases_gripper_raw_tcp_and_timing_dry_run(tmp_path: Path) -> None:
    async def scenario() -> None:
        source = tmp_path / "explicit.json"
        source.write_text(json.dumps(tracked_shape()), encoding="utf-8")
        report, repository = await run_import(tmp_path, source, dry_run=True)
        assert report.dry_run is True
        assert report.valid_count == 1
        assert report.imported_count == 0
        assert report.quarantined_count == 0
        assert report.entries[0].status == "WOULD_IMPORT"
        warnings = report.entries[0].warnings
        assert any("gripper" in warning for warning in warnings)
        assert any("raw/multi-turn" in warning for warning in warnings)
        assert any("TCP" in warning for warning in warnings)
        assert any("de-duplicated" in warning for warning in warnings)
        assert any("default_duration_sec" in warning for warning in warnings)
        assert await repository.list() == ()

    asyncio.run(scenario())


def test_write_uses_new_uuid_sanitized_metadata_and_fk_snapshot(tmp_path: Path) -> None:
    async def scenario() -> None:
        source_directory = tmp_path / "explicit source"
        source_directory.mkdir()
        source = source_directory / "motion.json"
        raw = tracked_shape()
        source.write_text(json.dumps(raw), encoding="utf-8")
        report, repository = await run_import(tmp_path, source, dry_run=False)
        assert report.imported_count == 1
        motion_id = report.entries[0].motion_id
        assert motion_id is not None
        assert motion_id != raw["id"]
        stored = await repository.get(__import__("uuid").UUID(motion_id))
        assert isinstance(stored, Motion)
        assert stored.source_metadata is not None
        assert stored.source_metadata.source_file_name == "motion.json"
        assert str(source_directory) not in stored.model_dump_json()
        assert stored.source_metadata.legacy_source == "web_record:arm_a"
        assert stored.keyframes[0].pose_snapshot.state_sequence is None
        assert stored.keyframes[0].pose_snapshot.hardware_snapshot is None
        assert stored.keyframes[1].incoming_transition is not None
        assert stored.keyframes[1].incoming_transition.duration_s == 1.25
        legacy_tcp = cast(dict[str, object], cast(list[object], raw["poses"])[0])["tcp_pose"]
        assert stored.keyframes[0].pose_snapshot.tcp_pose.model_dump(mode="json") != legacy_tcp
        assert (tmp_path / "motions" / f"{motion_id}.json").is_file()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda item: item.update(schema_version="unknown"), "schema"),
        (lambda item: item.update(pose_count=3), "pose_count"),
        (lambda item: item.pop("robot_variant"), "robot_variant"),
        (
            lambda item: cast(list[dict[str, object]], item["poses"])[1].update(
                replay_joint_targets_deg={
                    "J10": 30.0,
                    "J11": 99.0,
                    "J12": 3.0,
                    "J13": 4.0,
                    "J14": 5.0,
                    "J15": 6.0,
                }
            ),
            "disagree",
        ),
    ],
)
def test_invalid_or_ambiguous_actions_are_quarantined(
    tmp_path: Path,
    mutate: Callable[[dict[str, object]], object],
    reason: str,
) -> None:
    async def scenario() -> None:
        raw = tracked_shape()
        mutate(raw)
        source = tmp_path / f"{reason}.json"
        source.write_text(json.dumps(raw))
        report, repository = await run_import(tmp_path, source, dry_run=False)
        assert report.imported_count == 0
        assert report.quarantined_count == 1
        assert reason.lower() in report.entries[0].reasons[0].lower()
        assert await repository.list() == ()

    asyncio.run(scenario())


def test_generic_units_unknown_and_ambiguous_array_are_rejected(tmp_path: Path) -> None:
    async def scenario() -> None:
        generic = tracked_shape()
        poses = cast(list[dict[str, object]], generic["poses"])
        for frame in poses:
            frame.pop("joint_targets_deg")
            frame.pop("replay_joint_targets_deg")
            frame["positions"] = [100, 0, 0, 0, 0, 0]
            frame["units"] = ["mm", "deg", "deg", "deg", "deg", "radians"]
        source = tmp_path / "unknown-units.json"
        source.write_text(json.dumps(generic))
        unknown, _ = await run_import(tmp_path, source, dry_run=True)
        assert unknown.quarantined_count == 1
        assert "Unknown Legacy units" in unknown.entries[0].reasons[0]

        ambiguous = tracked_shape()
        ambiguous.pop("joint_order")
        frames = cast(list[dict[str, object]], ambiguous["poses"])
        for frame in frames:
            frame.pop("joint_targets_deg")
            frame.pop("replay_joint_targets_deg")
            frame["positions"] = [0, 0, 0, 0, 0]
            frame["units"] = ["deg"] * 5
        ambiguous["robot_variant"] = "V1"
        second = tmp_path / "ambiguous.json"
        second.write_text(json.dumps(ambiguous))
        rejected, _ = await run_import(tmp_path, second, dry_run=True)
        assert rejected.quarantined_count == 1
        assert "joint_order" in rejected.entries[0].reasons[0]

    asyncio.run(scenario())


def test_semantic_aliases_require_exact_enabled_joint_set(tmp_path: Path) -> None:
    async def scenario() -> None:
        aliases = ["SHOULDER_PAN", "SHOULDER_LIFT", "ELBOW_FLEX", "WRIST_FLEX", "WRIST_ROLL"]
        action: dict[str, object] = {
            "schema_version": "arm_replay_sequence_v1",
            "name": "V1 aliases",
            "robot_variant": "V1",
            "source": "web_record:arm_b",
            "joint_order": aliases,
            "pose_count": 2,
            "poses": [
                {"joint_targets_deg": dict.fromkeys(aliases, 0.0)},
                {"joint_targets_deg": dict.fromkeys(aliases, 1.0), "duration_s": 1.0},
            ],
        }
        source = tmp_path / "aliases.json"
        source.write_text(json.dumps(action))
        report, repository = await run_import(tmp_path, source, dry_run=False)
        assert report.imported_count == 1
        motion_id = report.entries[0].motion_id
        assert motion_id is not None
        from uuid import UUID

        motion = await repository.get(UUID(motion_id))
        assert motion is not None
        assert set(motion.keyframes[0].pose_snapshot.joint_state.positions) == {
            "j11",
            "j12",
            "j13",
            "j14",
            "j15",
        }

    asyncio.run(scenario())


def test_cli_defaults_to_dry_run_and_expected_failures_are_bounded_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert parse_args(["--source", "fixture.json"]).dry_run is True
    assert parse_args(["--source", "fixture.json", "--write"]).dry_run is False

    missing = tmp_path / "missing" / "secret.json"
    with pytest.raises(SystemExit) as exited:
        main(["--source", str(missing)])
    assert exited.value.code == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert payload["code"] == "LEGACY_IMPORT_FAILED"
    assert str(missing) not in captured.err
    assert "Traceback" not in captured.err


def test_huge_numeric_values_and_json_integers_quarantine_without_overflow(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        huge = 10**1000
        for field in ("joint", "duration", "hold"):
            raw = tracked_shape()
            frames = cast(list[dict[str, object]], raw["poses"])
            if field == "joint":
                for target_key in ("joint_targets_deg", "replay_joint_targets_deg"):
                    cast(dict[str, object], frames[1][target_key])["J11"] = huge
            elif field == "duration":
                frames[1]["duration_sec"] = huge
            else:
                frames[1]["hold_sec"] = huge
            source = tmp_path / f"huge-{field}.json"
            source.write_text(json.dumps(raw))
            report, repository = await run_import(tmp_path / field, source, dry_run=False)
            assert report.quarantined_count == 1
            assert "finite number" in report.entries[0].reasons[0]
            assert await repository.list() == ()

        oversized_literal = tmp_path / "oversized-literal.json"
        oversized_literal.write_text('{"value":' + ("9" * 5000) + "}")
        report, _ = await run_import(tmp_path / "literal", oversized_literal, dry_run=True)
        assert report.quarantined_count == 1
        assert report.entries[0].status == "QUARANTINED"
        assert "Traceback" not in report.model_dump_json()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "legacy_source", ["../secret", "/private/secret", r"C:\secret", "C:secret"]
)
def test_path_like_legacy_source_provenance_is_rejected_without_leakage(
    tmp_path: Path, legacy_source: str
) -> None:
    async def scenario() -> None:
        raw = tracked_shape()
        raw["source"] = legacy_source
        source = tmp_path / "source.json"
        source.write_text(json.dumps(raw))
        report, repository = await run_import(tmp_path, source, dry_run=False)
        assert report.quarantined_count == 1
        assert report.imported_count == 0
        assert "bounded label, not a path" in report.entries[0].reasons[0]
        assert legacy_source not in report.model_dump_json()
        assert await repository.list() == ()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("constant_name", "limit", "reason"),
    [
        ("MAX_TOTAL_ACTIONS", 1, "total action limit"),
        ("MAX_TOTAL_KEYFRAMES", 3, "total keyframe limit"),
        ("MAX_REPORT_ENTRIES", 1, "report-entry limit"),
    ],
)
def test_import_scope_has_global_action_keyframe_and_report_budgets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    constant_name: str,
    limit: int,
    reason: str,
) -> None:
    async def scenario() -> None:
        source = tmp_path / "actions.json"
        source.write_text(json.dumps({"actions": [tracked_shape(), tracked_shape()]}))
        repository, profiles, kinematics, clock = importer_dependencies(tmp_path)
        monkeypatch.setattr(importer_module, constant_name, limit)
        with pytest.raises(LegacyImportError, match=reason):
            await import_legacy_actions(
                source,
                repository=repository,
                profiles=profiles,
                kinematics=kinematics,
                clock=clock,
            )
        assert await repository.list() == ()

    asyncio.run(scenario())


def test_import_source_scan_file_and_aggregate_byte_budgets_stop_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        scan_directory = tmp_path / "scan"
        scan_directory.mkdir()
        for index in range(3):
            (scan_directory / f"ignored-{index}.txt").write_text("x")
        repository, profiles, kinematics, clock = importer_dependencies(tmp_path / "scan-run")
        monkeypatch.setattr(importer_module, "MAX_SOURCE_DIRECTORY_ENTRIES", 2)
        with pytest.raises(LegacyImportError, match="directory-entry scan limit"):
            await import_legacy_actions(
                scan_directory,
                repository=repository,
                profiles=profiles,
                kinematics=kinematics,
                clock=clock,
            )

        monkeypatch.setattr(importer_module, "MAX_SOURCE_DIRECTORY_ENTRIES", 2000)
        file_directory = tmp_path / "files"
        file_directory.mkdir()
        for index in range(2):
            (file_directory / f"{index}.json").write_text(json.dumps(tracked_shape()))
        monkeypatch.setattr(importer_module, "MAX_SOURCE_FILES", 1)
        with pytest.raises(LegacyImportError, match="file limit"):
            await import_legacy_actions(
                file_directory,
                repository=repository,
                profiles=profiles,
                kinematics=kinematics,
                clock=clock,
            )

        monkeypatch.setattr(importer_module, "MAX_SOURCE_FILES", 1000)
        aggregate = tmp_path / "aggregate.json"
        aggregate.write_text(json.dumps(tracked_shape()))
        monkeypatch.setattr(
            importer_module,
            "MAX_AGGREGATE_SOURCE_BYTES",
            aggregate.stat().st_size - 1,
        )
        with pytest.raises(LegacyImportError, match="aggregate byte limit"):
            await import_legacy_actions(
                aggregate,
                repository=repository,
                profiles=profiles,
                kinematics=kinematics,
                clock=clock,
            )

    asyncio.run(scenario())
