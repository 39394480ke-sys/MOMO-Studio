# Legacy action import

Stage 4 provides one explicit, offline conversion tool for characterized Legacy action
JSON. It is not a discovery, recovery, playback, or hardware utility. It never scans a
Legacy checkout or user directory, accepts no browser request, and defaults to a
report-only dry run.

## Safety contract

- The operator supplies exactly one source file or directory with `--source`.
- The source root cannot be a symlink. A directory is not searched recursively; only
  direct, non-symlink `.json` children are considered in filename order.
- A single explicit file must have a `.json` suffix. Non-JSON directory entries are
  ignored.
- Each selected entry is opened read-only with no-follow/nonblocking flags when the host
  provides them, then verified as a regular file with `fstat`; a FIFO/device/symlink is
  never consumed as JSON.
- No serial/Servo/camera/microphone package or device is imported, enumerated, or opened.
- The tool does not load Legacy code, local Calibration, runtime state, ignored config,
  recorded media, or a Legacy checkout automatically.
- No HTTP or WebSocket route accepts `--source`, a server path, an import path, or import
  content.
- Default mode performs no Motion write. `--write` must be chosen explicitly after the
  operator reviews a dry-run report.
- Output contains source basenames and content digests, never an absolute source path.
- Imported Motion receives a fresh UUID filename. A Legacy ID is bounded provenance
  only and never controls the filename.

The importer reads the repository's reviewed V1/V2 Profiles and provisional Dry Run
Kinematics models so it can validate typed Joint state and recompute TCP. That does not
authorize Real movement or establish physical accuracy.

## Commands

From `backend/` with the locked environment installed:

```bash
uv run python -m momo.tools.import_legacy_actions \
  --source /operator-reviewed/export
```

`--dry-run` is optional because it is the default:

```bash
uv run python -m momo.tools.import_legacy_actions \
  --source /operator-reviewed/export/action.json \
  --dry-run
```

Only after reviewing that JSON report, explicitly request writes:

```bash
uv run python -m momo.tools.import_legacy_actions \
  --source /operator-reviewed/export/action.json \
  --write
```

`--dry-run` and `--write` are mutually exclusive. The Motion destination is the
server-owned `motion_library_directory` from the normal safe settings chain; the CLI has
no destination-path flag. Normal settings loading does not probe ignored
`config/local.yaml`.

## Accepted top-level shapes

One JSON file may contain:

- one action object;
- an array of action objects; or
- an object whose `actions` field is an array of action objects.

Each action must declare `schema_version: "arm_replay_sequence_v1"` and explicitly
identify its hardware variant through `robot_variant` or
`variant`. After trimming/case normalization, the only accepted values are:

| Input | Domain variant |
|---|---|
| `V1` | `V1` |
| `V2` | `V2` |

`source` is bounded provenance only. It is never interpreted as a hardware variant, so
tracked values such as `arm_a`/`arm_b` cannot silently select V1/V2. When present it must
be an identifier-like label made from ASCII letters, digits, `_`, or `-`, optionally as
two such segments separated by one `:`; path-like values are rejected rather than
persisted.

Every action must also declare a top-level `joint_order` whose normalized IDs exactly
match the selected Profile's ordered `enabled_joints`, plus an integer `pose_count` that
exactly equals the frame-array length. The action must contain 2-1000 frame objects under
the first available `poses`, `keyframes`, `frames`, `sequence`, or `samples` field. Each
frame must contain one supported target field, except for the characterized matching
primary/replay pair described below:

| Target field | Unit behavior |
|---|---|
| `joint_targets_deg` | Uses the active Profile's domain units; V2 J10 remains `mm`, all revolute joints remain `deg`; the misleading Legacy suffix is recorded as a warning |
| `replay_joint_targets_deg` | Same explicit product-domain interpretation and warning |
| `positions` | Requires explicit per-joint `units` |
| `joints` | Requires explicit per-joint `units` |

Tracked frames may contain both `joint_targets_deg` and
`replay_joint_targets_deg`. The importer normalizes and compares them. An exact match is
de-duplicated with a warning; any disagreement is ambiguous and rejects the action.

A target may be an object keyed by recognized aliases or an array matching the required
top-level `joint_order`. Generic `positions`/`joints` units may be an alias-keyed object
or an array matching that order; they must exactly cover the active Profile's
enabled-joint set and each value must be exactly `deg` or `mm`. A frame-level order may
not replace or contradict the required top-level order.

The first frame has no incoming transition. Every later frame requires a finite positive
duration, capped at 600 seconds. Resolution order is `duration_s`, then
`transition_duration_s`; otherwise a positive `duration_sec` is used. A non-positive
`duration_sec` is the tracked sentinel for `playback.default_duration_sec` and is
accepted only when that positive fallback exists, with a warning. If no frame duration
field exists, action-level `step_duration_s` is the final fallback. Optional `hold_s` or
`hold_sec` is finite and 0-600 seconds. Imported transitions are `JOINT` with
`SMOOTHSTEP` easing. Frame labels default to `Keyframe N`. The action name comes from
`name`, then `action_name`, then a safe default.

## Joint aliases

Joint aliases are case-insensitive after surrounding whitespace is removed. They normalize to
canonical lowercase IDs before exact Profile validation:

| Legacy input | Canonical Joint |
|---|---|
| `J10` ... `J15` | `j10` ... `j15` |
| `J0` ... `J5` | `j10` ... `j15` |
| integer or string `0` ... `5` | `j10` ... `j15` |
| `SHOULDER_PAN` | `j11` |
| `SHOULDER_LIFT` | `j12` |
| `ELBOW_FLEX` | `j13` |
| `WRIST_FLEX` | `j14` |
| `WRIST_ROLL` | `j15` |

Alias recognition does not weaken the variant contract. V1 must resolve to exactly
J11-J15 and rejects J10; V2 must resolve to exactly J10-J15. Duplicate aliases that
collapse to the same Joint, missing Joints, extra Joints, and fixed-six assumptions that
do not match the declared variant are rejected.

## Conversion behavior

For each valid frame the importer:

1. normalizes aliases and validates a finite exact Joint set/units against the selected
   Profile;
2. computes TCP from that typed state with the selected mesh-free Kinematics model;
3. embeds a complete schema `2.0.0` Pose Snapshot with exact Profile/Kinematics
   fingerprints, `state_sequence=null`, and null hardware/Calibration evidence;
4. constructs a valid formal Motion with at least two embedded keyframes;
5. assigns a new Motion UUID, revision 1, tag `legacy-import`, and sanitized provenance.

The importer ignores Legacy TCP-like fields (`tcp`, `tcp_pose`, `xyz`, `rpy`,
`cartesian`, `end_effector_pose`) and reports that TCP was recomputed. It reports but
does not reinterpret gripper fields (`gripper`, `gripper_target`, `gripper_position`,
`claw`, `hand`) or raw/multi-turn fields (`raw`, `raw_positions`, `servo_positions`,
`multi_turn`, `multi_turn_state`, `raw_present_position`,
`replay_multi_turn_continuous_raw`). A valid logical target must still contain every
arm Joint; raw-only data cannot substitute for it.

Unknown units, unknown aliases/variants, booleans, NaN/infinity, alias collisions,
missing/extra/reordered Joints, a missing or mismatched `pose_count`, invalid
range/profile values, ambiguous multiple target fields, missing later durations,
malformed frames, or domain-incompatible Motion invariants are report-quarantined. The
importer does not guess, crop, zero-fill, convert raw counts, or repair an incomplete
action.

## Report

The CLI prints one JSON `ImportReport` to stdout:

- `dry_run`;
- `source_file_count`;
- `action_count`;
- `valid_count`;
- `imported_count`;
- `quarantined_count`;
- one entry per action, or one file-level entry when a file cannot be parsed.

An entry contains source basename, action index/name, status, optional generated Motion
UUID, warnings, and bounded reasons. Status is:

- `WOULD_IMPORT` for a valid default-dry-run conversion;
- `IMPORTED` after an explicit successful `--write` repository save;
- `QUARANTINED` for a rejected file/action. This is a report status, not a copy of the
  source into the Motion repository's corrupt-file quarantine.

The importer never moves, renames, edits, or deletes a source file.

An invalid source root (missing, symlinked, wrong single-file suffix, unsupported file
type, or a selection over a scan/file/byte/action/keyframe/report cap) is a command-level
error and exits with status 2 and a bounded `LEGACY_IMPORT_FAILED` JSON object on stderr.
It exposes no input path or traceback. File/action validation failures and a bounded
per-entity persistence failure inside an accepted source are represented by
`QUARANTINED` entries and conversion continues.

Persisted import metadata is typed and bounded: importer identity, source basename,
source SHA-256, optional Legacy ID, optional Legacy source alias, and warnings. Original
JSON and absolute paths are not embedded.

## Resource bounds and write semantics

| Resource | Bound |
|---|---|
| One source JSON file | Four MiB |
| Scanned entries in one source directory | 2,000 |
| Selected direct JSON children | 1,000 |
| Aggregate selected input | 32 MiB |
| Actions | 1,000 per file; 2,000 per invocation |
| Keyframes | 2-1,000 per action; 20,000 per invocation |
| Report entries | 2,000 per invocation |
| Transition/hold | Transition `(0, 600]` seconds; hold `[0, 600]` seconds |
| Metadata warning list | At most 32 warnings, 200 characters each |
| Legacy ID/source metadata | 200 / 64 characters |

`--write` saves each valid Motion independently through `FileMotionRepository`. A batch
is not a cross-file transaction: earlier valid entries remain written if a later entry
is rejected or a later save fails safely. Therefore always preserve the original source,
review the dry-run report, keep runtime Library backups as appropriate, and do not rerun
`--write` expecting idempotent IDs; every valid conversion intentionally gets a fresh
UUID.

## Compatibility and limitations

- Only the documented tracked-format aliases are supported; unknown Legacy formats are
  rejected rather than heuristically inferred.
- The `*_deg` field name is not trusted for V2 J10: its value is interpreted in the
  Profile-declared product unit `mm` and the report records that decision.
- Source `state_sequence` cannot be established, so imported snapshots carry null. Goto
  still requires exact current Profile/Kinematics compatibility and passes through the
  Stage 3 gateway.
- TCP is provisional Dry Run FK, not imported device truth or a physical verification.
- Gripper, raw/multi-turn, Cartesian, Calibration, Real playback, and media data are not
  migrated.
- The source path is operator-authorized CLI input. Do not run the tool on an unreviewed
  directory or expose it through a network API.
- Scope validation and conversion are separate bounded passes. A hostile local writer
  could mutate an explicitly selected source between them; that is outside the intended
  single-operator workstation threat model. Preserve and review a stable export before
  import.
- Post-fix synthetic importer coverage passes within the final 273-test backend gate and
  65-test focused route/import/hardware suite. The independent Stage 4 re-review passes
  P1=0/P2=0, and the Stage 4 report is GREEN; Stage 5 records the dedicated containing
  commit's exact SHA/remote state.
