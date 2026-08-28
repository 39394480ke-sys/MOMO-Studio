"""Validate explicit Legacy action JSON paths into immutable MOMO Motion entities.

The command is dry-run by default. It never discovers Legacy installations, user
directories, devices, or local configuration. Use ``--write`` only after reviewing
the JSON report.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Mapping, Sequence
from math import isfinite
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from momo.adapters.kinematics.model_repository import FileKinematicsModelRepository
from momo.adapters.kinematics.serial_chain import SerialChainKinematics
from momo.adapters.storage.file_motion_repository import FileMotionRepository
from momo.adapters.storage.profile_repository import FileProfileRepository
from momo.adapters.time.system_clock import SystemClock
from momo.application.services.kinematics_service import KinematicsService
from momo.application.services.profile_service import ProfileService
from momo.domain.enums import DomainUnit, Easing, MotionMode, RobotVariant
from momo.domain.errors import RobotApplicationError
from momo.domain.motion import (
    LegacyImportMetadata,
    Motion,
    MotionKeyframe,
    MotionTransition,
)
from momo.domain.pose import PoseSnapshot, SnapshotJointState
from momo.domain.robot import JointState, RobotProfile
from momo.ports.clock import Clock
from momo.ports.motion_repository import MotionRepository
from momo.settings import Settings, load_settings, repository_root

MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_SOURCE_FILES = 1000
MAX_SOURCE_DIRECTORY_ENTRIES = 2000
MAX_AGGREGATE_SOURCE_BYTES = 32 * 1024 * 1024
MAX_ACTIONS_PER_FILE = 1000
MAX_KEYFRAMES = 1000
MAX_TOTAL_ACTIONS = 2000
MAX_TOTAL_KEYFRAMES = 20000
MAX_REPORT_ENTRIES = 2000

TARGET_KEYS = ("joint_targets_deg", "replay_joint_targets_deg", "positions", "joints")
KNOWN_DOMAIN_TARGET_KEYS = frozenset({"joint_targets_deg", "replay_joint_targets_deg"})
IGNORED_GRIPPER_KEYS = frozenset({"gripper", "gripper_target", "gripper_position", "claw", "hand"})
IGNORED_RAW_KEYS = frozenset(
    {
        "raw",
        "raw_positions",
        "servo_positions",
        "multi_turn",
        "multi_turn_state",
        "raw_present_position",
        "replay_multi_turn_continuous_raw",
    }
)
IGNORED_LEGACY_TCP_KEYS = frozenset(
    {"tcp", "tcp_pose", "xyz", "rpy", "cartesian", "end_effector_pose"}
)

JOINT_ALIASES: dict[str, str] = {
    **{f"J{joint}": f"j{joint}" for joint in range(10, 16)},
    **{f"J{index}": f"j{index + 10}" for index in range(6)},
    **{str(index): f"j{index + 10}" for index in range(6)},
    "SHOULDER_PAN": "j11",
    "SHOULDER_LIFT": "j12",
    "ELBOW_FLEX": "j13",
    "WRIST_FLEX": "j14",
    "WRIST_ROLL": "j15",
}

VARIANT_ALIASES: dict[str, RobotVariant] = {
    "V1": RobotVariant.V1,
    "V2": RobotVariant.V2,
}

SAFE_LEGACY_SOURCE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}(?::[A-Za-z0-9][A-Za-z0-9_-]{0,31})?$"
)


class ImportEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_file_name: str
    action_index: int
    action_name: str
    status: Literal["WOULD_IMPORT", "IMPORTED", "QUARANTINED"]
    motion_id: str | None = None
    warnings: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class ImportReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dry_run: bool
    source_file_count: int
    action_count: int
    valid_count: int
    imported_count: int
    quarantined_count: int
    entries: list[ImportEntry]


class LegacyImportError(ValueError):
    pass


def _explicit_source_files(source: Path) -> tuple[Path, ...]:
    try:
        mode = source.lstat().st_mode
    except OSError:
        raise LegacyImportError("The explicit source path does not exist") from None
    if stat.S_ISLNK(mode):
        raise LegacyImportError("Symbolic-link source paths are not accepted")
    if stat.S_ISREG(mode):
        if source.suffix.lower() != ".json":
            raise LegacyImportError("The explicit source file must be JSON")
        if source.lstat().st_size > MAX_AGGREGATE_SOURCE_BYTES:
            raise LegacyImportError("Source selection exceeds the aggregate byte limit")
        return (source,)
    if not stat.S_ISDIR(mode):
        raise LegacyImportError("The explicit source path must be a file or directory")
    files: list[Path] = []
    scanned = 0
    aggregate_bytes = 0
    try:
        with os.scandir(source) as entries:
            for entry in entries:
                scanned += 1
                if scanned > MAX_SOURCE_DIRECTORY_ENTRIES:
                    raise LegacyImportError(
                        "Source directory exceeds the directory-entry scan limit"
                    )
                try:
                    child_metadata = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                path = Path(entry.path)
                if not stat.S_ISREG(child_metadata.st_mode) or path.suffix.lower() != ".json":
                    continue
                files.append(path)
                if len(files) > MAX_SOURCE_FILES:
                    raise LegacyImportError(
                        f"Source directory exceeds the {MAX_SOURCE_FILES}-file limit"
                    )
                aggregate_bytes += child_metadata.st_size
                if aggregate_bytes > MAX_AGGREGATE_SOURCE_BYTES:
                    raise LegacyImportError("Source selection exceeds the aggregate byte limit")
    except LegacyImportError:
        raise
    except OSError as error:
        raise LegacyImportError(
            "The explicit source directory could not be scanned safely"
        ) from error
    files.sort(key=lambda item: item.name)
    return tuple(files)


def _read_source(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise LegacyImportError("Every source entry must be a regular file")
            if metadata.st_size > MAX_SOURCE_BYTES:
                raise LegacyImportError("Source file exceeds the 4 MiB limit")
            chunks: list[bytes] = []
            remaining = MAX_SOURCE_BYTES + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            if len(payload) > MAX_SOURCE_BYTES:
                raise LegacyImportError("Source file exceeds the 4 MiB limit")
            return payload
        finally:
            os.close(descriptor)
    except LegacyImportError:
        raise
    except OSError as error:
        raise LegacyImportError("Source file could not be read safely") from error


def _actions_from_payload(payload: bytes) -> tuple[Mapping[str, object], ...]:
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeError, ValueError, OverflowError, RecursionError) as error:
        raise LegacyImportError("Source file is not valid UTF-8 JSON") from error
    actions: object
    if isinstance(raw, Mapping) and "actions" in raw:
        actions = raw["actions"]
    elif isinstance(raw, Mapping):
        actions = [raw]
    else:
        actions = raw
    if not isinstance(actions, list):
        raise LegacyImportError("Source JSON must be an action object or action array")
    if len(actions) > MAX_ACTIONS_PER_FILE:
        raise LegacyImportError(f"Source file exceeds the {MAX_ACTIONS_PER_FILE}-action limit")
    if not all(isinstance(action, Mapping) for action in actions):
        raise LegacyImportError("Every Legacy action must be an object")
    return tuple(cast(Mapping[str, object], action) for action in actions)


def _action_keyframe_count(action: Mapping[str, object]) -> int:
    raw = next(
        (
            action[key]
            for key in ("poses", "keyframes", "frames", "sequence", "samples")
            if key in action
        ),
        None,
    )
    return len(raw) if isinstance(raw, list) else 0


def _validate_import_scope(files: Sequence[Path]) -> None:
    aggregate_bytes = 0
    action_count = 0
    keyframe_count = 0
    report_entries = 0
    for path in files:
        try:
            payload = _read_source(path)
        except LegacyImportError:
            report_entries += 1
            if report_entries > MAX_REPORT_ENTRIES:
                raise LegacyImportError("Import scope exceeds the report-entry limit") from None
            continue
        aggregate_bytes += len(payload)
        if aggregate_bytes > MAX_AGGREGATE_SOURCE_BYTES:
            raise LegacyImportError("Source selection exceeds the aggregate byte limit")
        try:
            actions = _actions_from_payload(payload)
        except LegacyImportError:
            report_entries += 1
        else:
            action_count += len(actions)
            report_entries += len(actions)
            keyframe_count += sum(_action_keyframe_count(action) for action in actions)
        if action_count > MAX_TOTAL_ACTIONS:
            raise LegacyImportError("Import scope exceeds the total action limit")
        if keyframe_count > MAX_TOTAL_KEYFRAMES:
            raise LegacyImportError("Import scope exceeds the total keyframe limit")
        if report_entries > MAX_REPORT_ENTRIES:
            raise LegacyImportError("Import scope exceeds the report-entry limit")


def _canonical_key(value: object) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise LegacyImportError("Joint identifiers must be strings or integers")
    if isinstance(value, int) and not -9999 <= value <= 9999:
        raise LegacyImportError("Legacy joint identifier is outside the supported range")
    normalized = str(value).strip().upper()
    alias = JOINT_ALIASES.get(normalized)
    if alias is None:
        raise LegacyImportError(f"Unknown Legacy joint alias: {str(value)[:32]}")
    return alias


def _variant_for(action: Mapping[str, object]) -> RobotVariant:
    raw = next(
        (
            action[key]
            for key in ("robot_variant", "variant")
            if key in action and action[key] is not None
        ),
        None,
    )
    if not isinstance(raw, str):
        raise LegacyImportError("Legacy action must explicitly declare robot_variant or variant")
    variant = VARIANT_ALIASES.get(raw.strip().upper().replace("-", "_"))
    if variant is None:
        raise LegacyImportError("Legacy robot variant/source alias is unknown")
    return variant


def _frames_for(action: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    raw = next(
        (
            action[key]
            for key in ("poses", "keyframes", "frames", "sequence", "samples")
            if key in action
        ),
        None,
    )
    if not isinstance(raw, list):
        raise LegacyImportError("Legacy action must contain an explicit keyframe array")
    if not 2 <= len(raw) <= MAX_KEYFRAMES:
        raise LegacyImportError("Legacy action must contain 2 to 1000 keyframes")
    if not all(isinstance(frame, Mapping) for frame in raw):
        raise LegacyImportError("Every Legacy keyframe must be an object")
    pose_count = action.get("pose_count")
    if isinstance(pose_count, bool) or not isinstance(pose_count, int) or pose_count != len(raw):
        raise LegacyImportError("pose_count must exactly match the keyframe array length")
    return tuple(cast(Mapping[str, object], frame) for frame in raw)


def _warnings_for(
    action: Mapping[str, object], frames: Sequence[Mapping[str, object]]
) -> list[str]:
    warnings: list[str] = []
    keys = set(action)
    for frame in frames:
        keys.update(frame)
    if keys & IGNORED_GRIPPER_KEYS:
        warnings.append("Legacy gripper fields were ignored")
    if keys & IGNORED_RAW_KEYS:
        warnings.append("Legacy raw/multi-turn fields were ignored")
    if keys & IGNORED_LEGACY_TCP_KEYS:
        warnings.append("Legacy TCP fields were ignored; TCP was recomputed with MOMO FK")
    return warnings


def _numeric(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LegacyImportError(f"{field} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise LegacyImportError(f"{field} must be a finite number") from None
    if not isfinite(result):
        raise LegacyImportError(f"{field} must be a finite number")
    return result


def _legacy_id(value: object) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        if value.bit_length() > 665:
            raise LegacyImportError("Legacy action id exceeds the 200-character limit")
        return str(value)[:200]
    if isinstance(value, str):
        return value[:200]
    return None


def _legacy_source(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LegacyImportError("Legacy source provenance must be a safe label")
    normalized = value.strip()
    windows_drive_path = bool(re.match(r"^[A-Za-z]:", normalized))
    if (
        len(normalized) > 64
        or windows_drive_path
        or SAFE_LEGACY_SOURCE.fullmatch(normalized) is None
    ):
        raise LegacyImportError("Legacy source provenance must be a bounded label, not a path")
    return normalized


def _unit(value: object) -> DomainUnit:
    if not isinstance(value, str):
        raise LegacyImportError("Generic Legacy positions require explicit units per joint")
    normalized = value.strip().lower()
    if normalized == "deg":
        return DomainUnit.DEG
    if normalized == "mm":
        return DomainUnit.MM
    raise LegacyImportError("Unknown Legacy units are rejected")


def _explicit_order(
    frame: Mapping[str, object], action: Mapping[str, object]
) -> tuple[str, ...] | None:
    action_raw = action.get("joint_order")
    frame_raw = frame.get("joint_order")
    raw = frame_raw if frame_raw is not None else action_raw
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise LegacyImportError("joint_order must be an array")
    canonical = tuple(_canonical_key(value) for value in raw)
    if len(canonical) != len(set(canonical)):
        raise LegacyImportError("joint_order contains alias collisions")
    if action_raw is not None and frame_raw is not None:
        if not isinstance(action_raw, list):
            raise LegacyImportError("top-level joint_order must be an array")
        action_order = tuple(_canonical_key(value) for value in action_raw)
        if action_order != canonical:
            raise LegacyImportError("Per-frame joint_order disagrees with the action order")
    return canonical


def _canonical_units(
    raw: object,
    order: Sequence[str],
) -> dict[str, DomainUnit]:
    if isinstance(raw, Mapping):
        units: dict[str, DomainUnit] = {}
        for key, value in raw.items():
            canonical = _canonical_key(key)
            if canonical in units:
                raise LegacyImportError("Unit aliases collide after normalization")
            units[canonical] = _unit(value)
        if set(units) != set(order):
            raise LegacyImportError("Units must exactly cover the enabled joint set")
        return units
    if isinstance(raw, list):
        if len(raw) != len(order):
            raise LegacyImportError("Unit array must match joint_order")
        return {joint: _unit(value) for joint, value in zip(order, raw, strict=True)}
    raise LegacyImportError("Generic Legacy positions require explicit units per joint")


def _joint_state(
    frame: Mapping[str, object],
    action: Mapping[str, object],
    profile: RobotProfile,
    warnings: list[str],
) -> JointState:
    order = _explicit_order(frame, action)
    if order is not None and order != tuple(profile.enabled_joints):
        raise LegacyImportError("joint_order must exactly match profile enabled_joints")

    def positions_for(targets: object) -> dict[str, float]:
        pairs: list[tuple[object, object]]
        if isinstance(targets, Mapping):
            pairs = list(targets.items())
        elif isinstance(targets, list):
            if order is None:
                raise LegacyImportError("Array targets require an explicit joint_order")
            if len(targets) != len(order):
                raise LegacyImportError("Target array length must match joint_order")
            pairs = list(zip(order, targets, strict=True))
        else:
            raise LegacyImportError("Legacy targets must be an object or array")
        result: dict[str, float] = {}
        ignored_gripper = False
        for raw_key, raw_value in pairs:
            normalized = str(raw_key).strip().lower()
            if normalized in IGNORED_GRIPPER_KEYS:
                ignored_gripper = True
                continue
            canonical = _canonical_key(raw_key)
            if canonical in result:
                raise LegacyImportError("Joint aliases collide after normalization")
            result[canonical] = _numeric(raw_value, canonical)
        if ignored_gripper and "Legacy gripper fields were ignored" not in warnings:
            warnings.append("Legacy gripper fields were ignored")
        return result

    keys = [key for key in TARGET_KEYS if key in frame]
    if not keys:
        raise LegacyImportError("Each keyframe requires a supported product-domain target")
    duplicate_known = set(keys) == KNOWN_DOMAIN_TARGET_KEYS
    if duplicate_known:
        primary = positions_for(frame["joint_targets_deg"])
        replay = positions_for(frame["replay_joint_targets_deg"])
        if primary != replay:
            raise LegacyImportError("Legacy primary and replay targets disagree")
        positions = replay
        key = "replay_joint_targets_deg"
        warnings.append("Matching primary/replay Legacy targets were de-duplicated")
    elif len(keys) == 1:
        key = keys[0]
        positions = positions_for(frame[key])
    else:
        raise LegacyImportError("Conflicting supported target fields are ambiguous")

    expected = set(profile.enabled_joints)
    if set(positions) != expected:
        missing = sorted(expected - set(positions))
        unknown = sorted(set(positions) - expected)
        raise LegacyImportError(
            f"Joint set must exactly match enabled_joints; missing={missing}, unknown={unknown}"
        )

    if key in KNOWN_DOMAIN_TARGET_KEYS:
        units = {
            definition.joint_id: definition.domain_unit for definition in profile.joint_definitions
        }
        warning = (
            "Legacy '*_deg' target key was interpreted using product domain units "
            "(V2 j10 mm, revolute joints deg)"
        )
        if warning not in warnings:
            warnings.append(warning)
    else:
        raw_units = frame.get("units", action.get("units"))
        units = _canonical_units(raw_units, profile.enabled_joints)

    return JointState(positions=positions, units=units).validate_against(profile)


def _duration(
    frame: Mapping[str, object],
    action: Mapping[str, object],
    index: int,
    warnings: list[str],
) -> float | None:
    if index == 0:
        return None
    raw = frame.get("duration_s", frame.get("transition_duration_s"))
    if raw is None and "duration_sec" in frame:
        raw = frame["duration_sec"]
        if _numeric(raw, "duration_sec") <= 0:
            playback = action.get("playback")
            if not isinstance(playback, Mapping):
                raise LegacyImportError(
                    "Non-positive duration_sec requires playback.default_duration_sec"
                )
            raw = playback.get("default_duration_sec")
            warnings.append("Non-positive duration_sec used playback.default_duration_sec")
    if raw is None:
        raw = action.get("step_duration_s")
    if raw is None:
        raise LegacyImportError("Every non-first keyframe requires an explicit duration_s")
    value = _numeric(raw, "duration_s")
    if not 0 < value <= 600:
        raise LegacyImportError("duration_s must be greater than 0 and at most 600")
    return value


async def _convert_action(
    action: Mapping[str, object],
    *,
    source_name: str,
    source_sha256: str,
    profiles: ProfileService,
    kinematics: KinematicsService,
    clock: Clock,
) -> tuple[Motion, list[str]]:
    if action.get("schema_version") != "arm_replay_sequence_v1":
        raise LegacyImportError("Only the explicit arm_replay_sequence_v1 schema is supported")
    if "joint_order" not in action:
        raise LegacyImportError("arm_replay_sequence_v1 requires top-level joint_order")
    variant = _variant_for(action)
    profile = profiles.get_profile(variant)
    model = kinematics.model_for(profile)
    frames = _frames_for(action)
    warnings = _warnings_for(action, frames)
    keyframes: list[MotionKeyframe] = []
    for index, frame in enumerate(frames):
        state = _joint_state(frame, action, profile, warnings)
        forward = await kinematics.forward(
            profile,
            state,
            state_sequence=0,
            robot_id="legacy-import",
        )
        snapshot = PoseSnapshot(
            robot_variant=variant,
            joint_state=SnapshotJointState.model_validate(
                state.model_dump(mode="python", round_trip=True)
            ),
            tcp_pose=forward.tcp_pose,
            profile_fingerprint=profile.fingerprint,
            kinematics_fingerprint=model.fingerprint,
            state_sequence=None,
            hardware_snapshot=None,
            calibration_fingerprint=None,
            captured_at=clock.now(),
        )
        duration = _duration(frame, action, index, warnings)
        hold = _numeric(frame.get("hold_s", frame.get("hold_sec", 0.0)), "hold_s")
        if not 0 <= hold <= 600:
            raise LegacyImportError("hold_s must be between 0 and 600")
        raw_label = frame.get("label", f"Keyframe {index + 1}")
        if not isinstance(raw_label, str):
            raise LegacyImportError("Keyframe labels must be strings")
        keyframes.append(
            MotionKeyframe(
                label=raw_label,
                pose_snapshot=snapshot,
                hold_s=hold,
                incoming_transition=(
                    None
                    if duration is None
                    else MotionTransition(
                        duration_s=duration,
                        motion_mode=MotionMode.JOINT,
                        easing=Easing.SMOOTHSTEP,
                    )
                ),
            )
        )

    raw_name = action.get("name", action.get("action_name", "Imported Legacy action"))
    if not isinstance(raw_name, str):
        raise LegacyImportError("Legacy action name must be a string")
    raw_id = action.get("id", action.get("action_id"))
    legacy_id = _legacy_id(raw_id)
    legacy_source = _legacy_source(action.get("source"))
    warnings = list(dict.fromkeys(warnings))
    metadata = LegacyImportMetadata(
        source_file_name=source_name,
        source_sha256=source_sha256,
        legacy_id=legacy_id,
        legacy_source=legacy_source,
        warnings=warnings,
    )
    return (
        Motion(
            name=raw_name,
            description="Imported by the validated MOMO Legacy action importer.",
            robot_variant=variant,
            keyframes=keyframes,
            tags=["legacy-import"],
            source_metadata=metadata,
            created_at=clock.now(),
            updated_at=clock.now(),
        ),
        warnings,
    )


async def import_legacy_actions(
    source: Path,
    *,
    repository: MotionRepository,
    profiles: ProfileService,
    kinematics: KinematicsService,
    clock: Clock,
    dry_run: bool = True,
) -> ImportReport:
    files = _explicit_source_files(source)
    _validate_import_scope(files)
    entries: list[ImportEntry] = []
    action_count = 0
    valid_count = 0
    imported_count = 0
    quarantined_count = 0
    aggregate_bytes = 0
    total_keyframes = 0
    report_entries = 0
    for path in files:
        try:
            payload = _read_source(path)
        except LegacyImportError as error:
            report_entries += 1
            if report_entries > MAX_REPORT_ENTRIES:
                raise LegacyImportError("Import scope exceeds the report-entry limit") from None
            quarantined_count += 1
            entries.append(
                ImportEntry(
                    source_file_name=path.name,
                    action_index=0,
                    action_name="Unreadable action file",
                    status="QUARANTINED",
                    reasons=[str(error)[:200]],
                )
            )
            continue
        aggregate_bytes += len(payload)
        if aggregate_bytes > MAX_AGGREGATE_SOURCE_BYTES:
            raise LegacyImportError("Source selection exceeds the aggregate byte limit")
        try:
            actions = _actions_from_payload(payload)
        except LegacyImportError as error:
            report_entries += 1
            if report_entries > MAX_REPORT_ENTRIES:
                raise LegacyImportError("Import scope exceeds the report-entry limit") from None
            quarantined_count += 1
            entries.append(
                ImportEntry(
                    source_file_name=path.name,
                    action_index=0,
                    action_name="Unreadable action file",
                    status="QUARANTINED",
                    reasons=[str(error)[:200]],
                )
            )
            continue
        if action_count + len(actions) > MAX_TOTAL_ACTIONS:
            raise LegacyImportError("Import scope exceeds the total action limit")
        keyframes_in_file = sum(_action_keyframe_count(action) for action in actions)
        if total_keyframes + keyframes_in_file > MAX_TOTAL_KEYFRAMES:
            raise LegacyImportError("Import scope exceeds the total keyframe limit")
        if report_entries + len(actions) > MAX_REPORT_ENTRIES:
            raise LegacyImportError("Import scope exceeds the report-entry limit")
        action_count += len(actions)
        total_keyframes += keyframes_in_file
        report_entries += len(actions)
        digest = hashlib.sha256(payload).hexdigest()
        for action_index, action in enumerate(actions):
            raw_name = action.get("name", action.get("action_name", "Legacy action"))
            action_name = raw_name[:200] if isinstance(raw_name, str) else "Invalid action"
            try:
                motion, warnings = await _convert_action(
                    action,
                    source_name=path.name,
                    source_sha256=digest,
                    profiles=profiles,
                    kinematics=kinematics,
                    clock=clock,
                )
                valid_count += 1
                status: Literal["WOULD_IMPORT", "IMPORTED"] = "WOULD_IMPORT"
                if not dry_run:
                    await repository.save(motion)
                    imported_count += 1
                    status = "IMPORTED"
                entries.append(
                    ImportEntry(
                        source_file_name=path.name,
                        action_index=action_index,
                        action_name=motion.name,
                        status=status,
                        motion_id=str(motion.id),
                        warnings=warnings,
                    )
                )
            except (RobotApplicationError, OSError):
                quarantined_count += 1
                entries.append(
                    ImportEntry(
                        source_file_name=path.name,
                        action_index=action_index,
                        action_name=action_name,
                        status="QUARANTINED",
                        reasons=["Persistence failed safely; no entity was replaced"],
                    )
                )
            except (LegacyImportError, ValueError) as error:
                quarantined_count += 1
                entries.append(
                    ImportEntry(
                        source_file_name=path.name,
                        action_index=action_index,
                        action_name=action_name,
                        status="QUARANTINED",
                        reasons=[str(error)[:200]],
                    )
                )
    return ImportReport(
        dry_run=dry_run,
        source_file_count=len(files),
        action_count=action_count,
        valid_count=valid_count,
        imported_count=imported_count,
        quarantined_count=quarantined_count,
        entries=entries,
    )


def _resolve(value: str, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Explicit JSON file/directory")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true")
    mode.add_argument("--write", dest="dry_run", action="store_false")
    parser.set_defaults(dry_run=True)
    return parser.parse_args(argv)


async def _run_cli(args: argparse.Namespace) -> ImportReport:
    settings: Settings = load_settings()
    root = repository_root()
    clock = SystemClock()
    profiles = ProfileService(FileProfileRepository(_resolve(settings.profile_directory, root)))
    kinematics = KinematicsService(
        FileKinematicsModelRepository(_resolve(settings.kinematics_model_directory, root)),
        SerialChainKinematics(),
    )
    repository = FileMotionRepository(
        _resolve(settings.motion_library_directory, root),
        clock,
    )
    return await import_legacy_actions(
        cast(Path, args.source),
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
            "code": "LEGACY_IMPORT_FAILED",
            "message": str(error)[:200],
            "details": {},
        }
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        raise SystemExit(2) from None
    except (OSError, ValueError):
        payload = {
            "code": "LEGACY_IMPORT_FAILED",
            "message": "Legacy import could not start",
            "details": {},
        }
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        raise SystemExit(2) from None
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
