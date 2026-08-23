# Domain model

## Robot identity, mode, and access

`RobotVariant` is `V1` or `V2`; these are hardware variants, not software releases.
`ControlMode` is `DRY_RUN` or `REAL`. `HardwareAccessPolicy` is a separate capability
gate with `DISABLED`, `READ_ONLY`, and `FULL`. Stage 4 continues to permit only
`DRY_RUN` plus `DISABLED`; the other enum members reserve vocabulary and grant no
current capability.

`RobotId` is a validated stable identifier. The composition root creates one `primary`
robot in a `RobotManager`; it does not expose a global robot value, `arm_a`, Fleet, or
coordination semantics.

## Robot Profile

`RobotProfile` is immutable, schema-versioned input to validation and runtime composition. It contains:

- variant, display metadata, rail capability, and an ordered `enabled_joints` list;
- one ordered `JointDefinition` for each enabled joint;
- optional URDF reference and explicit TCP link;
- `template`, `verification_status`, `source`, and `source_revision` provenance;
- typed logical bounds/Home and explicit, unit-neutral hardware-mapping inputs.

A joint definition declares its ID, type, domain unit, logical minimum/maximum/Home, Servo ID, motor-degrees-per-domain-unit scale, raw counts per motor revolution, direction, operating mode, optional Home raw, optional raw bounds, and whether raw reachability is asserted. IDs and Servo IDs are unique, and joint definitions must exactly match `enabled_joints` in order.

The product contract is enforced by the model:

| Variant | Rail | Enabled joints | Type and unit |
|---|---:|---|---|
| V1 | no | `j11`-`j15` | all `REVOLUTE` / `deg` |
| V2 | yes | `j10`-`j15` | `j10` is `PRISMATIC` / `mm`; `j11`-`j15` are `REVOLUTE` / `deg` |

A template Profile cannot claim `VERIFIED_FOR_REAL`. The committed Profiles are templates verified only for Dry Run. Their limits, scales, raw bounds, Home raw, and directions are synthetic characterization inputs, not authority for a physical robot.

Profile-dependent entity validation accepts an explicitly supplied Profile or Profile mapping through validation context. It never reads a process-global default Profile and never assumes six joints.

## Profile Fingerprint

`RobotProfile.fingerprint` is the lowercase SHA-256 digest of deterministic, compact, key-sorted JSON. The canonical payload contains variant, ordered enabled joints, and for every joint: ID, type, unit, Servo ID, scale, raw-count resolution, operating mode, direction, logical minimum/maximum/Home, Home raw, raw bounds, and `raw_reachable`.

Display name, description, template/verification/provenance fields, timestamps, schema version, URDF/TCP metadata, and the deprecated placeholder mapping are excluded. Rail capability is derived from the included variant contract rather than hashed twice. Changing display copy preserves compatibility; changing a mapping, range, Home, direction, mode, identity, or joint order produces a different fingerprint.

The fingerprint is stored by Calibration and Dry Run runtime documents. It identifies an exact motion/safety Profile contract; it is not proof that the data was physically verified.

## Kinematics model and fingerprint

`KinematicsModel` is a schema-versioned, immutable, mesh-free serial chain. It contains
the hardware variant, provenance, verification status, base and TCP frame names, ordered
joints, presentation metadata, and a declared `kinematics_fingerprint`. Each
`KinematicJoint` declares:

- `joint_id` and explicit `REVOLUTE` or `PRISMATIC` type;
- a finite normalized axis;
- a finite origin translation in metres;
- a finite normalized origin quaternion in XYZW order;
- ordered minimum and maximum values in SI units.

The model validates exact product membership and order. V1 is exactly `j11`-`j15`; V2
is exactly `j10`-`j15`, with only J10 prismatic. Unknown, duplicate, missing, reordered,
zero-axis, zero-quaternion, non-finite, wrong-type, or wrong-variant data fails closed.

`kinematics_fingerprint` is SHA-256 over deterministic compact JSON containing schema
version, variant, frames, and the complete ordered joint geometry/type/limits. Display
name, description, and source prose do not affect it; any geometry, joint identity,
frame, type, axis, origin, or limit change does. On model validation the declared
`kinematics_fingerprint` must equal the recomputed canonical digest; a missing or
mismatched value rejects model loading.

The two initial documents are `PROVISIONAL_DRY_RUN`. This status permits deterministic
Dry Run FK/IK and UI behavior but is an explicit blocker for Real Cartesian motion,
Cartesian playback, and Real vision follow. A fingerprint proves exact software-model
identity, not physical correctness.

## Kinematics boundary and results

Product/domain joint values stay in `deg` and `mm`. `KinematicsJointState` carries only
adapter values: radians for revolute joints and metres for prismatic joints. Conversion
uses the active Profile's declared type/unit through named `to_kinematics_*` and
`from_kinematics_*` functions. It never special-cases a joint name. Canonical TCP output
uses millimetres and a normalized XYZW quaternion; the adapter boundary uses metres and
the same quaternion ordering.

`ForwardKinematicsResult` binds the TCP pose to robot identity, variant, state sequence,
Profile fingerprint, Kinematics fingerprint, and `hardware_accessed=false`.
`InverseKinematicsResult` distinguishes a converged solution from the best bounded
candidate and reports iterations, position error in millimetres, optional orientation
error in degrees, termination reason, warnings, and Kinematics fingerprint. An
unreachable or over-residual best candidate is diagnostic evidence, not a movement
target.

Base and Tool Cartesian increments are separate typed intents. Base translation and
rotation compose in the base frame. Tool translation is rotated by the current TCP
orientation and Tool rotation composes in the TCP frame; it must never be interpreted as
a Base delta.

## Calibration

`CalibrationDocument` is immutable and contains `schema_version`, UUID `id`, `robot_variant`, the exact `profile_fingerprint`, `template`, timezone-aware `generated_at`, notes, and a non-empty joint list. Joint and Servo IDs must be unique.

Each `CalibrationJoint` contains `joint_id`, `servo_id`, `MULTI_TURN` or `SINGLE_TURN` mode, direction `-1` or `1`, optional integer Home raw, optional integer phase, and optional ordered integer raw bounds. Home must be inside provided raw bounds. A joint is complete when it has Home raw and, for multi-turn operation, phase.

`CalibrationService` evaluates a document against the active Profile without mutating it. It checks exact variant, Profile Fingerprint, exact enabled-joint set, per-joint Servo ID and operating mode, overlapping raw bounds/Home, and completeness. The report exposes `mapping_match` separately. The status contract defines:

- `NOT_CONFIGURED`
- `TEMPLATE_ONLY`
- `VARIANT_MISMATCH`
- `PROFILE_MISMATCH`
- `JOINT_SET_MISMATCH`
- `INCOMPLETE`
- `VALID_FOR_DRY_RUN`
- `READY_FOR_REAL`

Stage 4 still never returns effective Real readiness: `real_readiness` remains
`BLOCKED_BY_STAGE_POLICY`. A complete matching template can be structurally valid for
diagnostics, but it cannot authorize hardware. Mapping mismatch is classified as
`INCOMPLETE` and makes `calibration_valid=false`. The repository is read-only and loads
only reviewed example filenames; no calibration-write use case or API exists.

## Logical and raw mapping

Mapping functions accept an explicit Profile joint definition and an explicit Calibration joint. They use neutral names such as `logical_value`, because a value may be millimetres or degrees. No conversion branch checks whether the ID happens to be `j10`.

```text
motor_degrees = logical_value
                * motor_degrees_per_domain_unit
                * profile_direction
                * calibration_direction

relative_raw = round(motor_degrees / 360 * raw_counts_per_motor_revolution)
goal_raw = calibration_home_present_raw + relative_raw
```

`logical_to_goal_raw`, `goal_raw_to_logical`, `validate_goal_raw`, and `effective_logical_limits_from_raw_bounds` are pure functions. Profile and Calibration raw bounds are intersected; the resulting raw range is converted in both directions and intersected with logical Profile limits. Inputs must be finite, scale/counts positive, direction valid, operating mode matching, Home configured, and the joint known. The rounding tolerance is derived from one half of a raw count in that joint's declared scale.

These functions remain characterization and preflight inputs only. Stage 4 Dry Run
commands never emit raw values and no API exposes raw mapping. A later reviewed Real
gateway may use raw-derived reachable limits, but no Stage 3 executor can write them.

## Runtime state and status

`RobotRuntimeState` (`RuntimeState` in code) is immutable persisted Dry Run data with:

- schema version, robot ID, variant, and Profile Fingerprint;
- exact keyed positions and units;
- last recorded connection state;
- timezone-aware update time and non-negative `state_sequence`.

The file repository constrains robot IDs and paths, writes atomically, and quarantines corrupt or rejected files. Restore additionally validates the active variant/fingerprint, exact joint and unit mappings, finite values, and logical limits. A failed startup restore uses Profile Home with sequence zero; a variant switch still advances from the current runtime sequence. A valid restore carries positions and sequence forward but never restores an active connection.

`RobotStatus` is the read-only API projection: identity, variant, mode/policy, connection
state, connected flag, Profile identity/verification, Calibration status, positions,
units, optional raw positions, last error, timestamp, sequence, stale marker, and
`hardware_accessed=false`. Stage 4 continues to return `raw_positions=null`; command and
TCP status may extend the transport projection without changing the persisted runtime
schema.

The stale marker is computed from monotonic time since the last successful high-level
Dry Run driver observation. UTC `updated_at` remains display and persistence data; it is
not the freshness clock, so wall-clock rollback cannot revive failed or timed-out state.

Connection states are `DISCONNECTED`, `CONNECTING`, `CONNECTED`, `DISCONNECTING`, and `FAULTED`. One command lock serializes all lifecycle operations. The normal transitions are:

```text
DISCONNECTED -> CONNECTING -> CONNECTED
CONNECTED/FAULTED -> DISCONNECTING -> DISCONNECTED
```

Duplicate Connect is rejected without creating another driver. Disconnect while already
disconnected returns the stable state. Stop returns `STOPPED` when connected and
`NOT_CONNECTED` when disconnected. During Dry Run motion it first cancels the active
prepared command or Jog lease, then leaves the runtime at its last completed Dry Run
sample. Driver/executor failures enter `FAULTED`, record a safe error summary, and never
expose a traceback. `state_sequence` increases monotonically for lifecycle changes,
accepted execution samples, and Stop events.

## Motion command, preflight, and command status

Stage 3 defines one command vocabulary for Joint Move, Joint Jog, Home, Cartesian Jog,
and Move Pose. Stage 4 admits exactly one Library movement intent: Goto is a
`LIBRARY`-source `MOVE_JOINTS` command after persisted-snapshot compatibility checks.
Playback, Studio, and Vision sources remain reserved. An
immutable command carries a unique command ID, source, robot identity, expected state
sequence, Profile and Kinematics fingerprints, explicit unit-bearing target or delta,
timing intent, and idempotency identity. Clients cannot select a concrete executor or
driver.

`MotionPreflight` is the typed evidence produced only by the Motion Safety Gateway. It
records policy/identity/freshness/fingerprint checks; exact joint and unit membership;
finite, logical, provisional dynamic and workspace checks; conditional raw-derived
checks; FK/IK evidence; conflict/idempotency/cancellation status; and safe warnings. If
no Calibration is configured, the raw-derived check records an explicit Dry Run-only
`not_applicable` result and logical Profile limits remain authoritative. A configured
but incompatible Calibration rejects admission. Neither path authorizes Real motion. A
rejected preflight never becomes executor work.

Command status has exactly five states: `ACCEPTED`, `RUNNING`, `COMPLETED`, `CANCELLED`,
and `FAULTED`. It exposes bounded progress plus a safe error summary. Only one command
may be active. Repeating the same idempotent request returns the established command;
reusing an idempotency identity for different intent is rejected.

## Jog lease

A continuous Jog session is a short-lived backend `JogLease`, identified by an opaque
session ID and owned by one active robot/command source. Heartbeat extends the bounded
expiry; explicit Stop, command conflict, disconnect, fault, backend shutdown, or expiry
cancels it. Duplicate Stop is stable and idempotent. Browser pointer release is a normal
stop signal, not the safety guarantee—network loss is covered by backend expiry.

## State, Pose, and Motion contracts

`JointState.positions` is keyed by joint ID and may carry an explicit unit map in transient
internal contexts. Persisted `PoseSnapshot` uses `SnapshotJointState`, which requires a
non-null unit for every enabled Joint. Validation against an explicit Profile rejects
missing or unknown joints, wrong/missing units, booleans, non-finite values, and
out-of-range values.

`TcpPose` contains a frame, `position_mm`, and canonical normalized `xyzw` quaternion.
`PoseSnapshot` schema `2.0.0` is the complete immutable-by-value capture of variant,
keyed joint state, TCP, exact Profile and Kinematics fingerprints, an observation state
sequence, optional hardware safety snapshot, optional Calibration fingerprint
provenance, and capture time. A live Stage 4 Capture always stores a non-null sequence;
an explicit Legacy import may store `null` only when no coherent source counter exists.
Public snapshot writes also require canonical current-FK TCP and cannot claim hardware or
Calibration provenance. `Pose` adds UUID identity, display metadata, timestamps,
revision, and schema version.

Capture obtains a connected, fresh robot snapshot, computes FK against that exact
Profile/state/sequence, then obtains a second snapshot. It retries a bounded three times
unless sequence, variant/Profile, joint state, and FK evidence remain coherent. It never
combines Joint state and TCP from different observations. Stage 4 Dry Run records
`hardware_snapshot=null` and `calibration_fingerprint=null` rather than inventing
hardware evidence.

A `MotionKeyframe` embeds a complete `PoseSnapshot`; optional `source_pose_id` is
provenance only. `Motion` owns those copies, so editing or deleting a source Pose cannot
alter playback data. A formal Motion contains at least two keyframes; its first
keyframe has no incoming transition and every later keyframe has one. Stage 4 preserves
those playable invariants rather than introducing an incomplete editing shape; Stage 6
will use a separate `MotionDraft`. Motion schema `2.0.0` may carry typed, bounded
`LegacyImportMetadata` for importer-owned provenance; Library API clients cannot set it.
Stage 3 Move Pose remains an explicit transient
TCP target; Stage 4 adds storage and Library workflows but no trajectory compiler or
playback.

## Entity repositories and revisions

Pose and Motion persist independently under UUID filenames. Every read validates the
generated JSON Schema, Pydantic model, and filename/document UUID equality. Every create
starts at revision 1. An update or delete carries `expected_revision`; an update advances
exactly once, and stale revisions return a structured conflict rather than overwriting.
Duplicate display names are valid because identity is the UUID.

Storage writes a bounded JSON payload to a temporary sibling, flushes and `fsync`s the
file, atomically replaces the destination, then `fsync`s the directory. Corrupt,
unsupported, oversized, symlinked, or mismatched entries are quarantined when possible;
one bad entry never fails the full list. Sorting uses a stable UUID tie-break. Work is
bounded at 5,000 root JSON entities, 10,000 scanned root entries, 64 MiB aggregate
regular-entity bytes, and four MiB per entity; overflow raises a structured capacity
error instead of a partial result. The repository lock protects a single backend
process/repository instance only.

Goto loads an immutable Pose, requires the expected entity revision, and compares
variant, exact enabled-joint/unit set, Profile fingerprint, Kinematics fingerprint, and
joint-state validity against the active robot. Only then does it create a Joint Motion
for the normal Motion application service and gateway. A repository cannot dispatch an
executor or driver.

Nested lists/maps are frozen using JSON-serializable immutable containers. JSON round trips preserve meaning and do not expose `mappingproxy` or another non-serializable type.

## Schema evolution

`schema_version` describes persisted shape; entity `revision` describes edits where the
entity contract defines revisions. A persisted schema change requires compatibility
analysis, round-trip tests, regenerated artifacts under `docs/schemas`, and an explicit
Stage decision. Display names are never storage identities; persistent user entities
use UUID filenames.

Stage 4 changes Pose and Motion independently from `1.0.0` to `2.0.0`. The change is
intentionally incompatible because the old snapshot shape lacks Profile/Kinematics
fingerprints and state-sequence evidence. Repository loading does not synthesize those
fields or reinterpret old documents; `1.0.0` files are rejected/quarantined and require
an explicit reviewed migration path. The exact decision is recorded in ADR 0011. Stage
4 round-trip and compatibility tests pass, and two consecutive generated Pose/Motion
schema artifacts were byte-identical; their exact SHA-256 values are recorded in the
Stage report.
