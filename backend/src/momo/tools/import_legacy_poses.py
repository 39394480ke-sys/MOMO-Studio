"""Validate explicit Legacy pose-library JSON into immutable MOMO Pose entities.

The command is dry-run by default and requires an operator-selected hardware variant.
It never discovers Legacy installations, reads local device configuration, or contacts
hardware. Use ``--write`` only after reviewing the JSON report.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from momo.adapters.kinematics.model_repository import FileKinematicsModelRepository
from momo.adapters.kinematics.serial_chain import SerialChainKinematics
from momo.adapters.storage.file_pose_repository import FilePoseRepository
from momo.adapters.storage.profile_repository import FileProfileRepository
from momo.adapters.time.system_clock import SystemClock
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.profile_service import ProfileService
from momo.domain.enums import RobotVariant
from momo.domain.errors import RobotApplicationError
from momo.domain.pose import Pose, PoseSnapshot, SnapshotJointState
from momo.ports.clock import Clock
from momo.ports.pose_repository import PoseRepository
from momo.settings import Settings, load_settings, repository_root
from momo.tools.import_legacy_actions import (
    IGNORED_GRIPPER_KEYS,
    IGNORED_LEGACY_TCP_KEYS,
    IGNORED_RAW_KEYS,
    MAX_AGGREGATE_SOURCE_BYTES,
    MAX_REPORT_ENTRIES,
    TARGET_KEYS,
    VARIANT_ALIASES,
    LegacyImportError,
    _explicit_source_files,
    _joint_state,
    _read_source,
    _resolve,
)

MAX_POSES_PER_FILE = 1000
MAX_TOTAL_POSES = 2000
LEGACY_ANGLE_KEY = "关节角度"
LEGACY_DESCRIPTION_KEYS = ("说明", "description")
LEGACY_GRIPPER_KEYS = frozenset({"夹爪", "夹爪角度", "夹爪位置"})


class PoseImportEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_file_name: str
    source_sha256: str
    pose_index: int
    pose_name: str
    status: Literal["WOULD_IMPORT", "IMPORTED", "SKIPPED_VARIANT", "QUARANTINED"]
    pose_id: str | None = None
    warnings: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class PoseImportReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dry_run: bool
    selected_variant: RobotVariant
    source_file_count: int
    pose_count: int
    valid_count: int
    imported_count: int
    skipped_count: int
    quarantined_count: int
    entries: list[PoseImportEntry]


def _pose_library(payload: bytes) -> tuple[tuple[str, Mapping[str, object]], ...]:
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeError, ValueError, OverflowError, RecursionError) as error:
        raise LegacyImportError("Source file is not valid UTF-8 JSON") from error
    if not isinstance(raw, Mapping):
        raise LegacyImportError("Legacy pose library must be a name-to-pose JSON object")
    library: object = raw.get("poses") if set(raw) == {"poses"} else raw
    if not isinstance(library, Mapping):
        raise LegacyImportError("Legacy pose library must be a name-to-pose JSON object")
    if len(library) > MAX_POSES_PER_FILE:
        raise LegacyImportError(f"Source file exceeds the {MAX_POSES_PER_FILE}-pose limit")
    result: list[tuple[str, Mapping[str, object]]] = []
    for raw_name, raw_pose in library.items():
        if not isinstance(raw_name, str) or not 1 <= len(raw_name.strip()) <= 200:
            raise LegacyImportError("Every Legacy pose name must contain 1 to 200 characters")
        if not isinstance(raw_pose, Mapping):
            raise LegacyImportError("Every Legacy pose must be an object")
        result.append((raw_name.strip(), cast(Mapping[str, object], raw_pose)))
    return tuple(result)


def _entry_variant(entry: Mapping[str, object]) -> RobotVariant | None:
    raw = next(
        (
            entry[key]
            for key in ("robot_variant", "variant")
            if key in entry and entry[key] is not None
        ),
        None,
    )
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise LegacyImportError("Legacy pose robot_variant must be V1 or V2")
    variant = VARIANT_ALIASES.get(raw.strip().upper().replace("-", "_"))
    if variant is None:
        raise LegacyImportError("Legacy pose robot_variant is unknown")
    return variant


def _description(entry: Mapping[str, object]) -> str:
    for key in LEGACY_DESCRIPTION_KEYS:
        value = entry.get(key)
        if value is not None:
            if not isinstance(value, str):
                raise LegacyImportError("Legacy pose description must be a string")
            return value
    return ""


async def _convert_pose(
    name: str,
    entry: Mapping[str, object],
    *,
    selected_variant: RobotVariant,
    source_name: str,
    source_sha256: str,
    profiles: ProfileService,
    kinematics: KinematicsService,
    clock: Clock,
) -> tuple[Pose, list[str]]:
    explicit_variant = _entry_variant(entry)
    if explicit_variant is not None and explicit_variant is not selected_variant:
        raise LegacyImportError("Legacy pose belongs to a different explicit robot_variant")
    profile = profiles.get_profile(selected_variant)
    model = kinematics.model_for(profile)
    warnings: list[str] = []
    if explicit_variant is None:
        warnings.append(
            f"Operator-selected --variant {selected_variant.value} supplied missing pose variant"
        )

    frame = dict(entry)
    if LEGACY_ANGLE_KEY in frame:
        if any(key in frame for key in TARGET_KEYS):
            raise LegacyImportError("Legacy pose contains ambiguous joint target fields")
        frame["joint_targets_deg"] = frame[LEGACY_ANGLE_KEY]
    if not any(key in frame for key in TARGET_KEYS):
        raise LegacyImportError("Legacy pose requires a supported product-domain joint target")

    raw_order = entry.get("joint_order")
    if raw_order is None:
        raw_order = list(profile.enabled_joints)
        warnings.append(
            "Operator-selected variant supplied missing joint_order for the Legacy pose array"
        )
    action_context: dict[str, object] = {"joint_order": raw_order}
    if "units" in entry:
        action_context["units"] = entry["units"]
    state = _joint_state(frame, action_context, profile, warnings)

    keys = set(entry)
    if keys & (IGNORED_GRIPPER_KEYS | LEGACY_GRIPPER_KEYS):
        warnings.append("Legacy gripper fields were ignored")
    if keys & IGNORED_RAW_KEYS:
        warnings.append("Legacy raw/multi-turn fields were ignored")
    if keys & IGNORED_LEGACY_TCP_KEYS:
        warnings.append("Legacy TCP fields were ignored; TCP was recomputed with MOMO FK")
    warnings = list(dict.fromkeys(warnings))

    forward = await kinematics.forward(
        profile,
        state,
        state_sequence=0,
        robot_id="legacy-pose-import",
    )
    now = clock.now()
    source_kind = "explicit" if explicit_variant is not None else "operator-selected"
    provenance = (
        f"Legacy pose import: {source_name}; sha256={source_sha256}; "
        f"variant={selected_variant.value} ({source_kind})."
    )
    description = _description(entry)
    combined_description = f"{description}\n\n{provenance}" if description else provenance
    return (
        Pose(
            name=name,
            description=combined_description,
            tags=["legacy-import", f"legacy-{selected_variant.value.lower()}"],
            snapshot=PoseSnapshot(
                robot_variant=selected_variant,
                joint_state=SnapshotJointState.model_validate(
                    state.model_dump(mode="python", round_trip=True)
                ),
                tcp_pose=forward.tcp_pose,
                profile_fingerprint=profile.fingerprint,
                kinematics_fingerprint=model.fingerprint,
                state_sequence=None,
                hardware_snapshot=None,
                calibration_fingerprint=None,
                captured_at=now,
            ),
            created_at=now,
            updated_at=now,
        ),
        warnings,
    )


async def import_legacy_poses(
    source: Path,
    *,
    selected_variant: RobotVariant,
    repository: PoseRepository,
    profiles: ProfileService,
    kinematics: KinematicsService,
    clock: Clock,
    dry_run: bool = True,
) -> PoseImportReport:
    files = _explicit_source_files(source)
    entries: list[PoseImportEntry] = []
    pose_count = 0
    valid_count = 0
    imported_count = 0
    skipped_count = 0
    quarantined_count = 0
    aggregate_bytes = 0
    for path in files:
        try:
            payload = _read_source(path)
            aggregate_bytes += len(payload)
            if aggregate_bytes > MAX_AGGREGATE_SOURCE_BYTES:
                raise LegacyImportError("Source selection exceeds the aggregate byte limit")
            poses = _pose_library(payload)
        except LegacyImportError as error:
            quarantined_count += 1
            entries.append(
                PoseImportEntry(
                    source_file_name=path.name,
                    source_sha256="0" * 64,
                    pose_index=0,
                    pose_name="Unreadable pose library",
                    status="QUARANTINED",
                    reasons=[str(error)[:200]],
                )
            )
            continue
        if pose_count + len(poses) > MAX_TOTAL_POSES:
            raise LegacyImportError("Import scope exceeds the total pose limit")
        if len(entries) + len(poses) > MAX_REPORT_ENTRIES:
            raise LegacyImportError("Import scope exceeds the report-entry limit")
        pose_count += len(poses)
        digest = hashlib.sha256(payload).hexdigest()
        for pose_index, (name, raw_pose) in enumerate(poses):
            try:
                explicit_variant = _entry_variant(raw_pose)
                if explicit_variant is not None and explicit_variant is not selected_variant:
                    skipped_count += 1
                    entries.append(
                        PoseImportEntry(
                            source_file_name=path.name,
                            source_sha256=digest,
                            pose_index=pose_index,
                            pose_name=name,
                            status="SKIPPED_VARIANT",
                            reasons=[
                                f"Explicit {explicit_variant.value} pose excluded from "
                                f"selected {selected_variant.value} import"
                            ],
                        )
                    )
                    continue
                pose, warnings = await _convert_pose(
                    name,
                    raw_pose,
                    selected_variant=selected_variant,
                    source_name=path.name,
                    source_sha256=digest,
                    profiles=profiles,
                    kinematics=kinematics,
                    clock=clock,
                )
                valid_count += 1
                status: Literal["WOULD_IMPORT", "IMPORTED"] = "WOULD_IMPORT"
                if not dry_run:
                    await repository.save(pose)
                    imported_count += 1
                    status = "IMPORTED"
                entries.append(
                    PoseImportEntry(
                        source_file_name=path.name,
                        source_sha256=digest,
                        pose_index=pose_index,
                        pose_name=pose.name,
                        status=status,
                        pose_id=str(pose.id),
                        warnings=warnings,
                    )
                )
            except (RobotApplicationError, OSError):
                quarantined_count += 1
                entries.append(
                    PoseImportEntry(
                        source_file_name=path.name,
                        source_sha256=digest,
                        pose_index=pose_index,
                        pose_name=name,
                        status="QUARANTINED",
                        reasons=["Persistence failed safely; no entity was replaced"],
                    )
                )
            except (LegacyImportError, ValueError) as error:
                quarantined_count += 1
                entries.append(
                    PoseImportEntry(
                        source_file_name=path.name,
                        source_sha256=digest,
                        pose_index=pose_index,
                        pose_name=name,
                        status="QUARANTINED",
                        reasons=[str(error)[:200]],
                    )
                )
    return PoseImportReport(
        dry_run=dry_run,
        selected_variant=selected_variant,
        source_file_count=len(files),
        pose_count=pose_count,
        valid_count=valid_count,
        imported_count=imported_count,
        skipped_count=skipped_count,
        quarantined_count=quarantined_count,
        entries=entries,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Explicit JSON file/directory")
    parser.add_argument(
        "--variant",
        required=True,
        choices=[variant.value for variant in RobotVariant],
        help="Operator-selected product variant; never inferred from array length",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true")
    mode.add_argument("--write", dest="dry_run", action="store_false")
    parser.set_defaults(dry_run=True)
    return parser.parse_args(argv)


async def _run_cli(args: argparse.Namespace) -> PoseImportReport:
    settings: Settings = load_settings()
    root = repository_root()
    clock = SystemClock()
    profiles = ProfileService(FileProfileRepository(_resolve(settings.profile_directory, root)))
    kinematics = KinematicsService(
        FileKinematicsModelRepository(_resolve(settings.kinematics_model_directory, root)),
        SerialChainKinematics(),
    )
    repository = FilePoseRepository(_resolve(settings.pose_directory, root), clock)
    return await import_legacy_poses(
        cast(Path, args.source),
        selected_variant=RobotVariant(cast(str, args.variant)),
        repository=repository,
        profiles=profiles,
        kinematics=kinematics,
        clock=clock,
        dry_run=cast(bool, args.dry_run),
    )


def main(argv: Sequence[str] | None = None) -> None:
    try:
        report = asyncio.run(_run_cli(parse_args(argv)))
    except LegacyImportError as error:
        payload = {
            "code": "LEGACY_POSE_IMPORT_FAILED",
            "message": str(error)[:200],
            "details": {},
        }
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        raise SystemExit(2) from None
    except (OSError, ValueError):
        payload = {
            "code": "LEGACY_POSE_IMPORT_FAILED",
            "message": "Legacy pose import could not start",
            "details": {},
        }
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        raise SystemExit(2) from None
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
