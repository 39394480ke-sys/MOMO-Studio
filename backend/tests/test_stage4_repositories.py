"""Atomic Stage 4 Pose/Motion file repository contracts."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest

import momo.adapters.storage.file_entity_repository as entity_repository_module
from momo.adapters.storage.file_entity_repository import MAX_ENTITY_BYTES
from momo.adapters.storage.file_motion_repository import FileMotionRepository
from momo.adapters.storage.file_pose_repository import FilePoseRepository
from momo.domain.errors import EntityInvalidError, RepositoryCapacityError, RevisionConflictError
from momo.domain.motion import Motion
from momo.domain.pose import Pose
from tests.factories import make_motion, make_snapshot
from tests.stage3_helpers import FakeClock


def make_pose(name: str = "Pose") -> Pose:
    return Pose(name=name, snapshot=make_snapshot())


def revised_pose(pose: Pose, name: str) -> Pose:
    data = pose.model_dump(mode="python")
    data.update(name=name, revision=pose.revision + 1)
    return Pose.model_validate(data)


def test_pose_and_motion_round_trip_uuid_filename_and_delete(tmp_path: Path) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        poses = FilePoseRepository(tmp_path / "poses", clock)
        motions = FileMotionRepository(tmp_path / "motions", clock)
        pose = make_pose()
        motion = make_motion()
        await poses.save(pose)
        await motions.save(motion)

        assert (tmp_path / "poses" / f"{pose.id}.json").is_file()
        assert (tmp_path / "motions" / f"{motion.id}.json").is_file()
        assert await poses.get(pose.id) == pose
        assert await motions.get(motion.id) == motion
        assert await poses.delete(pose.id, expected_revision=1) is True
        assert await poses.get(pose.id) is None

    asyncio.run(scenario())


def test_atomic_replace_failure_preserves_previous_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        repository = FilePoseRepository(tmp_path / "poses", FakeClock())
        original = make_pose("Original")
        await repository.save(original)
        old_bytes = (tmp_path / "poses" / f"{original.id}.json").read_bytes()

        def fail_replace(source: object, destination: object) -> None:
            del source, destination
            raise OSError("synthetic replace failure")

        monkeypatch.setattr(os, "replace", fail_replace)
        with pytest.raises(OSError, match="synthetic"):
            await repository.save(revised_pose(original, "New"), expected_revision=1)
        assert (tmp_path / "poses" / f"{original.id}.json").read_bytes() == old_bytes
        assert not tuple((tmp_path / "poses").glob("*.tmp"))

    asyncio.run(scenario())


def test_schema_failure_bad_uuid_oversize_symlink_and_fifo_are_quarantined(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        directory = tmp_path / "poses"
        repository = FilePoseRepository(directory, FakeClock())
        valid = make_pose()
        await repository.save(valid)

        bad_schema_id = uuid4()
        bad_schema = valid.model_dump(mode="json")
        bad_schema["id"] = str(bad_schema_id)
        del cast(dict[str, object], bad_schema["snapshot"])["profile_fingerprint"]
        (directory / f"{bad_schema_id}.json").write_text(json.dumps(bad_schema))
        (directory / "not-a-uuid.json").write_text("{}")

        oversized_id = uuid4()
        with (directory / f"{oversized_id}.json").open("wb") as stream:
            stream.truncate(MAX_ENTITY_BYTES + 1)

        symlink_id = uuid4()
        outside = tmp_path / "outside.json"
        outside.write_text('{"secret":"must-not-be-read"}')
        (directory / f"{symlink_id}.json").symlink_to(outside)

        fifo_id = uuid4()
        fifo = directory / f"{fifo_id}.json"
        os.mkfifo(fifo)

        listed = await asyncio.wait_for(repository.list(), timeout=1.0)
        assert listed == (valid,)
        assert outside.read_text() == '{"secret":"must-not-be-read"}'
        assert not fifo.exists()
        quarantined = tuple((directory / "quarantine").iterdir())
        assert len(quarantined) == 5
        assert all(os.path.lexists(path) for path in quarantined)

    asyncio.run(scenario())


def test_path_confinement_and_existing_broken_symlink_fail_closed(tmp_path: Path) -> None:
    async def scenario() -> None:
        directory = tmp_path / "poses"
        repository = FilePoseRepository(directory, FakeClock())
        with pytest.raises(EntityInvalidError, match="UUID"):
            await repository.get(cast(UUID, "../../escape"))

        pose = make_pose()
        directory.mkdir()
        link = directory / f"{pose.id}.json"
        link.symlink_to(tmp_path / "missing-target")
        with pytest.raises(EntityInvalidError, match="regular"):
            await repository.save(pose)
        assert not link.exists()

    asyncio.run(scenario())


def test_concurrent_compare_and_swap_allows_exactly_one_writer(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = FilePoseRepository(tmp_path / "poses", FakeClock())
        original = make_pose()
        await repository.save(original)
        results = await asyncio.gather(
            repository.save(revised_pose(original, "Writer A"), expected_revision=1),
            repository.save(revised_pose(original, "Writer B"), expected_revision=1),
            return_exceptions=True,
        )
        assert sum(result is None for result in results) == 1
        conflicts = [result for result in results if isinstance(result, RevisionConflictError)]
        assert len(conflicts) == 1
        stored = await repository.get(original.id)
        assert stored is not None
        assert stored.revision == 2
        assert stored.name in {"Writer A", "Writer B"}

    asyncio.run(scenario())


def test_json_schema_validator_runs_on_write_and_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        repository = FileMotionRepository(tmp_path / "motions", FakeClock())
        calls: list[object] = []
        original_validate = repository._validate_schema

        def record(value: object) -> None:
            calls.append(value)
            original_validate(value)

        monkeypatch.setattr(repository, "_validate_schema", record)
        motion = make_motion()
        await repository.save(motion)
        restored = await repository.get(motion.id)
        assert restored == motion
        assert len(calls) == 2

    asyncio.run(scenario())


def test_deleting_source_pose_does_not_change_embedded_motion(tmp_path: Path) -> None:
    async def scenario() -> None:
        clock = FakeClock()
        poses = FilePoseRepository(tmp_path / "poses", clock)
        motions = FileMotionRepository(tmp_path / "motions", clock)
        pose = make_pose()
        motion_data = make_motion().model_dump(mode="python")
        motion_data["keyframes"][0]["source_pose_id"] = pose.id
        motion_data["keyframes"][0]["pose_snapshot"] = pose.snapshot.model_dump(mode="python")
        motion = Motion.model_validate(motion_data)
        await poses.save(pose)
        await motions.save(motion)
        before = (await motions.get(motion.id)).model_dump_json()  # type: ignore[union-attr]
        await poses.delete(pose.id, expected_revision=1)
        after = (await motions.get(motion.id)).model_dump_json()  # type: ignore[union-attr]
        assert after == before

    asyncio.run(scenario())


def test_repository_list_has_entity_scan_and_aggregate_work_budgets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        entity_directory = tmp_path / "entity-cap"
        entity_repository = FilePoseRepository(entity_directory, FakeClock())
        await entity_repository.save(make_pose("One"))
        await entity_repository.save(make_pose("Two"))
        monkeypatch.setattr(entity_repository_module, "MAX_REPOSITORY_ENTITY_FILES", 1)
        with pytest.raises(RepositoryCapacityError) as entity_error:
            await entity_repository.list()
        assert entity_error.value.code == "REPOSITORY_CAPACITY_EXCEEDED"
        assert entity_error.value.details == {"resource": "entity_files", "limit": 1}
        assert str(tmp_path) not in str(entity_error.value)

        monkeypatch.setattr(entity_repository_module, "MAX_REPOSITORY_ENTITY_FILES", 5000)
        scan_directory = tmp_path / "scan-cap"
        scan_directory.mkdir()
        (scan_directory / "one.tmp").write_text("x")
        (scan_directory / "two.tmp").write_text("x")
        scan_repository = FilePoseRepository(scan_directory, FakeClock())
        monkeypatch.setattr(entity_repository_module, "MAX_REPOSITORY_SCAN_ENTRIES", 1)
        with pytest.raises(RepositoryCapacityError) as scan_error:
            await scan_repository.list()
        assert scan_error.value.details == {"resource": "directory_entries", "limit": 1}

        monkeypatch.setattr(entity_repository_module, "MAX_REPOSITORY_SCAN_ENTRIES", 10000)
        aggregate_directory = tmp_path / "aggregate-cap"
        aggregate_repository = FilePoseRepository(aggregate_directory, FakeClock())
        aggregate_pose = make_pose("Aggregate")
        await aggregate_repository.save(aggregate_pose)
        persisted_size = (aggregate_directory / f"{aggregate_pose.id}.json").stat().st_size
        monkeypatch.setattr(
            entity_repository_module,
            "MAX_REPOSITORY_AGGREGATE_BYTES",
            persisted_size - 1,
        )
        with pytest.raises(RepositoryCapacityError) as aggregate_error:
            await aggregate_repository.list()
        assert aggregate_error.value.details == {
            "resource": "aggregate_bytes",
            "limit": persisted_size - 1,
        }

    asyncio.run(scenario())


def test_repository_capacity_is_enforced_before_new_entity_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        repository = FilePoseRepository(tmp_path / "poses", FakeClock())
        await repository.save(make_pose("Existing"))
        monkeypatch.setattr(entity_repository_module, "MAX_REPOSITORY_ENTITY_FILES", 1)
        with pytest.raises(RepositoryCapacityError, match="capacity"):
            await repository.save(make_pose("Rejected"))
        assert len(tuple((tmp_path / "poses").glob("*.json"))) == 1

    asyncio.run(scenario())
