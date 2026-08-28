"""Explicit-variant, default-dry-run Legacy pose importer contracts."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from momo.adapters.kinematics.model_repository import FileKinematicsModelRepository
from momo.adapters.kinematics.serial_chain import SerialChainKinematics
from momo.adapters.storage.file_pose_repository import FilePoseRepository
from momo.adapters.storage.profile_repository import FileProfileRepository
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.profile_service import ProfileService
from momo.domain.enums import DomainUnit, RobotVariant
from momo.settings import repository_root
from momo.tools.import_legacy_poses import (
    import_legacy_poses,
    main,
    parse_args,
)
from tests.stage3_helpers import FakeClock


def dependencies(
    tmp_path: Path,
) -> tuple[FilePoseRepository, ProfileService, KinematicsService, FakeClock]:
    root = repository_root()
    clock = FakeClock()
    return (
        FilePoseRepository(tmp_path / "poses", clock),
        ProfileService(FileProfileRepository(root / "robot_profiles")),
        KinematicsService(
            FileKinematicsModelRepository(root / "kinematics_models"),
            SerialChainKinematics(),
        ),
        clock,
    )


def pose_library() -> dict[str, object]:
    return {
        "Old array": {
            "关节角度": [10.0, 1.0, 2.0, 3.0, 4.0, 5.0],
            "夹爪": 0.5,
            "说明": "legacy description",
        },
        "Explicit V2": {
            "robot_variant": "V2",
            "joint_order": ["J10", "J11", "J12", "J13", "J14", "J15"],
            "关节角度": [20.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        },
        "Explicit V1": {
            "robot_variant": "V1",
            "joint_order": ["J11", "J12", "J13", "J14", "J15"],
            "关节角度": [0.0, 0.0, 0.0, 0.0, 0.0],
        },
    }


def test_dry_run_requires_selected_variant_and_does_not_write(tmp_path: Path) -> None:
    async def scenario() -> None:
        source = tmp_path / "姿态库.json"
        source.write_text(json.dumps(pose_library()), encoding="utf-8")
        repository, profiles, kinematics, clock = dependencies(tmp_path)
        report = await import_legacy_poses(
            source,
            selected_variant=RobotVariant.V2,
            repository=repository,
            profiles=profiles,
            kinematics=kinematics,
            clock=clock,
        )
        assert report.dry_run is True
        assert report.pose_count == 3
        assert report.valid_count == 2
        assert report.imported_count == 0
        assert report.skipped_count == 1
        assert report.quarantined_count == 0
        assert report.entries[0].status == "WOULD_IMPORT"
        assert any("Operator-selected --variant V2" in item for item in report.entries[0].warnings)
        assert any("missing joint_order" in item for item in report.entries[0].warnings)
        assert any("gripper" in item for item in report.entries[0].warnings)
        assert report.entries[2].status == "SKIPPED_VARIANT"
        assert await repository.list() == ()

    asyncio.run(scenario())


def test_write_uses_fresh_uuid_fk_and_sanitized_provenance(tmp_path: Path) -> None:
    async def scenario() -> None:
        source_directory = tmp_path / "private legacy directory"
        source_directory.mkdir()
        source = source_directory / "poses.json"
        encoded = json.dumps(pose_library()).encode()
        source.write_bytes(encoded)
        repository, profiles, kinematics, clock = dependencies(tmp_path)
        report = await import_legacy_poses(
            source,
            selected_variant=RobotVariant.V2,
            repository=repository,
            profiles=profiles,
            kinematics=kinematics,
            clock=clock,
            dry_run=False,
        )
        assert report.imported_count == 2
        stored = await repository.list()
        assert len(stored) == 2
        first = next(item for item in stored if item.name == "Old array")
        assert (tmp_path / "poses" / f"{first.id}.json").is_file()
        assert UUID(str(first.id))
        assert first.snapshot.robot_variant is RobotVariant.V2
        assert first.snapshot.joint_state.units["j10"] is DomainUnit.MM
        assert first.snapshot.state_sequence is None
        assert first.snapshot.hardware_snapshot is None
        assert first.snapshot.calibration_fingerprint is None
        assert first.snapshot.tcp_pose.position_mm.model_dump() != {"x": 0, "y": 0, "z": 0}
        assert "legacy description" in first.description
        assert "poses.json" in first.description
        assert hashlib.sha256(encoded).hexdigest() in first.description
        assert str(source_directory) not in first.model_dump_json()
        assert set(first.tags) == {"legacy-import", "legacy-v2"}

    asyncio.run(scenario())


def test_out_of_limit_pose_is_quarantined_without_partial_entity(tmp_path: Path) -> None:
    async def scenario() -> None:
        source = tmp_path / "poses.json"
        source.write_text(json.dumps({"Too far": {"关节角度": [70, 0, 0, 0, 0, 0]}}))
        repository, profiles, kinematics, clock = dependencies(tmp_path)
        report = await import_legacy_poses(
            source,
            selected_variant=RobotVariant.V2,
            repository=repository,
            profiles=profiles,
            kinematics=kinematics,
            clock=clock,
            dry_run=False,
        )
        assert report.imported_count == 0
        assert report.quarantined_count == 1
        assert "outside [-50.0, 50.0]" in report.entries[0].reasons[0]
        assert await repository.list() == ()

    asyncio.run(scenario())


def test_cli_defaults_to_dry_run_and_missing_path_error_is_bounded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert parse_args(["--source", "fixture.json", "--variant", "V2"]).dry_run is True
    assert parse_args(["--source", "fixture.json", "--variant", "V2", "--write"]).dry_run is False
    missing = tmp_path / "private" / "secret.json"
    with pytest.raises(SystemExit) as exited:
        main(["--source", str(missing), "--variant", "V2"])
    assert exited.value.code == 2
    captured = capsys.readouterr()
    assert json.loads(captured.err)["code"] == "LEGACY_POSE_IMPORT_FAILED"
    assert str(missing) not in captured.err
    assert "Traceback" not in captured.err
