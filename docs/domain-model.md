# Domain model

## Robot identity, mode, and access

`RobotVariant` is `V1` or `V2`; these are hardware variants, not software releases.
`ControlMode` is `DRY_RUN` or `REAL`. `HardwareAccessPolicy` is a separate capability
gate with `DISABLED`, `READ_ONLY`, and `FULL`. Stage 7 continues to permit only
`DRY_RUN` plus disabled hardware access; the other enum members reserve vocabulary and
grant no current motion capability. Camera access is independently typed as `DISABLED`,
`SYNTHETIC_ONLY`, or `LIVE_CAMERA_ALLOWED`, with `SYNTHETIC_ONLY` as the tracked
default. A live policy value alone neither selects nor opens a camera.

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

Stage 7 still never returns effective Real readiness: `real_readiness` remains
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

These functions remain characterization and preflight inputs only. Stage 5 Dry Run
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
`hardware_accessed=false`. Stage 5 continues to return `raw_positions=null`; command and
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
Stage 5 adds digest-bound Playback ownership. Stage 6 admits one Studio movement intent:
persisted-keyframe Goto becomes a `STUDIO`-source `MOVE_JOINTS` command after Draft
revision and snapshot compatibility checks. Stage 7 admits only Follow-created
`VISION`-source `MOVE_JOINTS` commands after frame, lease, mapping, and fresh Robot
checks. An immutable
command carries a unique command ID, source, robot identity, expected state
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

## Vision frame, selection, and tracking

`FrameMetadata` is immutable observation identity: validated `frame_id`, `source_id`,
aware `captured_at`, `width_px`, and `height_px`. `VisionFrame` adds an explicitly
supported image media type and bounded encoded content. These are transient latest-value
observations, not persisted media entities.

`NormalizedBoundingBox` uses finite `x`, `y`, `width`, and `height` values in normalized
frame coordinates. Width/height must be positive and the complete box must stay inside
`[0, 1]`. It embeds the originating frame ID, source, capture time, and dimensions, so a
box cannot be detached from the pixels that gave it meaning. Pixel conversion returns
an enclosing rectangle and never infers dimensions from UI layout.

`TargetSelection` identifies `MANUAL`, `PERSON`, or `FACE`. `Detection` binds one
provider, target kind, confidence, and a box whose metadata exactly matches its result
frame. `TrackingResult` carries the complete frame metadata, `UNINITIALIZED`, `LOCKED`,
`LOST`, `STALE`, or `FAULTED`, optional matching box, confidence, and a bounded detail.
A locked result requires a box; non-locked results cannot retain one.

Provider capabilities report stable provider/kind IDs, `AVAILABLE` or `UNAVAILABLE`,
display name, model source, notice, and safe detail. The deterministic Synthetic
detectors/tracker are explicitly scenario fixtures, not general-purpose model claims.
Unavailable optional OpenCV capabilities remain visible rather than becoming invented
success.

## Vision Follow lease and controller

`FollowOperatorIntent` is confirmed and can request only `DRY_RUN`. Its complete
`FollowConfiguration` contains dead zones, EMA alpha, gain, maximum step/rate,
confidence threshold, frame freshness, target-loss interval, lease TTL, and
`FollowActuatorMapping`. Mapping names distinct pan/tilt joints and signs and requires
`VERIFIED_FOR_DRY_RUN`. Start checks both IDs against the Profile's explicit
`enabled_joints` and requires `REVOLUTE`/`deg`; it cannot map the V2 prismatic rail or an
unknown/disabled joint.

`FollowController` is pure. It computes bounding-box-center error relative to `(0.5,
0.5)`, updates EMA, applies per-axis dead zones, sign/gain, `max_step`, and elapsed-time
`max_rate`, and returns auditable `FollowMetrics` bound to frame ID/source/capture time.
The application factory combines the increment with a fresh complete Robot joint state
and produces only a high-level `VISION` + `MOVE_JOINTS` command for the normal motion
application/gateway path.

`FollowLease` has opaque UUID identity plus aware issued, heartbeat, and expiry times.
`FollowStatus` is `IDLE`, `ACTIVE`, or `STOPPED` and carries one lease/configuration,
latest metrics/command, explicit stop reason, `control_mode=DRY_RUN`,
`real_follow_allowed=false`, and `hardware_accessed=false`. Heartbeat renews only the
matching active lease. Stale/non-advancing frames, loss/low confidence, source/tracker/
browser failure, Robot disconnect/fault/staleness, motion conflict/rejection, expiry,
operator/Global Stop, or backend shutdown stop ownership. Backend monotonic deadlines,
not frontend timers, are the fail-safe.

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
those playable invariants rather than introducing an incomplete editing shape. Stage 6
uses a separate `MotionDraft`. Motion schema `2.0.0` may carry typed, bounded
`LegacyImportMetadata` for importer-owned provenance; Library API clients cannot set it.
Stage 3 Move Pose remains an explicit transient TCP target. Stage 4 adds storage and
Library workflows. Stage 5 compiles stored Motion revisions and plays only accepted
prepared plans.

## MotionDraft and editor contracts

`MotionDraft` schema `1.0.0` is recoverable authoring state, never a weakened Motion. It
contains its own UUID/revision/timestamps, optional coherent source Motion UUID/revision,
name/description/variant, zero to 1,000 embedded keyframes, playback defaults, tags,
bounded `MotionDraftEditorMetadata`, optional typed server-owned `source_metadata`, a
bounded server-owned `trusted_legacy_snapshot_sha256` registry, and an optional
`MotionDraftSaveIntent`. Zero or one keyframe is valid Draft state but cannot convert to
a formal Motion.

Draft keyframes retain the formal snapshot, variant, fingerprint, explicit-unit,
unique-ID, and transition-shape invariants. The first keyframe has no incoming
transition; every later keyframe has one. `source_pose_id` remains provenance only.
Editor metadata contains bounded selection/playhead/zoom/scroll values plus exact
`MotionDraftDefaultEdge(from_keyframe_id, to_keyframe_id)` values. Each default marker
must identify a current directed adjacency whose target transition is exactly one-second
Joint Smoothstep.

Opening an imported Motion seeds the trust registry with canonical SHA-256 identities
for its exact snapshots whose source state sequence is unavailable. Canonical sorted-key,
compact JSON makes mapping insertion order irrelevant while covering every snapshot
field and rejecting non-finite numbers. Reorder, duplicate, delete/autosave, and Undo
restoration of a trusted snapshot remain valid; replacement or fabrication does not.
API clients cannot set either server-owned provenance field, and autosave, recovery,
rebind, abandon, and conflict fork preserve them.

The frontend reducer owns segment settings as explicit directed edges. Reorder preserves
an edge only if the exact source-to-target adjacency survives; newly formed adjacencies
receive the explicit editor default, including a former first keyframe moved later.
Conversion to Motion attaches edges to target `incoming_transition` values only after
the ordered adjacency is known. Undo/Redo is bounded; autosave acknowledgements do not
become edit-history entries.

Draft validation and compilation remain backend operations. A compile candidate passes
through the Stage 5 compiler but returns `executable=false`, is not cached for playback,
and cannot be dispatched. Only a separately persisted formal Motion revision can enter
the normal preflight/digest/playback path.

`MotionDraftSaveIntent` is a write-ahead cross-repository reconciliation marker. It
binds operation kind, operation UUID, target Motion UUID/revision/name/creation time,
expected source revision, and start time. Save first advances the Draft with the marker,
then persists the formal Motion through the Library revision lease, then advances the
Draft again to bind the source and clear the marker. Recovery semantically matches the
target; it never creates a duplicate automatically or adopts a later revision for
overwrite. For a known-source Save, an advanced target binds the known UUID while
retaining the intended stale source revision so the next Save conflicts. For a fresh
Save or Save As, an advanced or semantically mismatched target cannot be proven and the
marker remains fail-closed. Semantic identity includes typed source metadata.

A retained marker can be released only by an exact operator request containing the
current Draft revision, the marker operation UUID, and the literal confirmation. The
raw Draft CAS clears only that marker and never creates, updates, adopts, or deletes a
Motion. Every Studio revision conflict carries bounded `MotionDraft` or `Motion` entity
scope; missing/unknown scope fails closed. Conflict Save As first captures the local
document, loads the authoritative Draft, exact-revision forks the server-owned entity,
PUTs the captured local content onto that fork, then rebinds and saves a fresh Motion.

## Trajectory, preflight, and playback

`TrajectoryPlan` is a complete immutable sample plan in domain units. It binds Motion
UUID/revision, variant, Profile/Kinematics fingerprints, start-state sequence, sample
rate, duration, ordered `TrajectorySegment` and `TrajectorySample` values, and a
deterministic SHA-256 `TrajectoryDigest`. Its semantic digest excludes only
`compiled_at`. Forged or internally inconsistent plans fail domain validation.

Segments are `JOINT`, `CARTESIAN_LINEAR`, or `HOLD`. Joint transitions apply the target
keyframe's `LINEAR`, `SMOOTHSTEP`, or `EASE_IN_OUT` setting. Cartesian position is
linear and orientation is shortest-path quaternion SLERP; IK is solved at every sample
using the prior accepted solution as seed. Holds are explicit stationary time segments.
Sample times are strictly increasing, adjacent segments share one boundary, and the
last sample equals exact total duration.

`TrajectoryPreflightReport` carries named checks and typed blocking violations. It can
expose a digest only when the complete plan is accepted. `PreparedTrajectory` binds that
report to the exact plan. The cache is bounded and process-local; preview uses that same
prepared value and never compiles a second path. Execution rechecks repository revision,
variant, fingerprints, state sequence, connection/freshness, Stop capability, Dry Run
policy, and single-motion ownership through `MotionSafetyGateway`.

`PlaybackOperatorIntent` is explicit and digest-bound. `PlaybackStatus` has `IDLE`,
`PREFLIGHTING`, `READY`, `PLAYING`, `PAUSED`, `STOPPING`, `STOPPED`, `COMPLETED`, and
`FAULTED` states plus bounded progress/rate/loop data. Scheduling uses monotonic absolute
deadlines; pause/resume and rate changes rebase time without backlog bursts. Looping
requires a closed plan and is bounded to 100 traversals. Latest-value playback events
extend the read-only robot WebSocket and never form a command queue.

The full interpolation, residual, dynamics, workspace, resource, and timing rules are
specified in `docs/trajectory-semantics.md`. All Stage 5 results remain
`hardware_accessed=false`; no plan grants Real readiness.

## Entity repositories and revisions

Pose, Motion, and MotionDraft persist independently under UUID filenames and disjoint
server-owned roots. Every read validates the generated JSON Schema, Pydantic model, and
filename/document UUID equality. Every create starts at revision 1. An update or delete
carries `expected_revision`; an ordinary update advances exactly once, and stale
revisions return a structured conflict rather than overwriting. A successful formal
Draft save advances twice—intent then rebind—because both durable states are explicit.
A provenance-preserving fork takes only the exact authoritative Draft revision, clones
it under a fresh UUID at revision 1 with any formal-save marker cleared, and leaves the
original untouched.
Duplicate display names are valid because identity is the UUID.

Storage writes a bounded JSON payload to a temporary sibling, flushes and `fsync`s the
file, atomically replaces the destination, then `fsync`s the directory. Corrupt,
unsupported, oversized, symlinked, or mismatched entries are quarantined when possible;
one bad entry never fails the full list. Sorting uses a stable UUID tie-break. Work is
bounded at 5,000 root JSON entities, 10,000 scanned root entries, 64 MiB aggregate
regular-entity bytes, and four MiB per entity; overflow raises a structured capacity
error instead of a partial result. The repository lock protects a single backend
process/repository instance only.

The MotionDraft recovery schema is stricter than an API create schema: every serialized
field is required recursively, including defaulted fields, server-owned provenance/trust,
and nested keyframe/edge/save-intent identities. Recovery never reconstructs omitted
past state from current defaults.
Configured runtime/Profile/Calibration/Kinematics/Pose/Motion/Draft roots are validated
as pairwise disjoint before repository construction, including equal, nested,
resolved/symlink, NFC-Unicode-normalized, and case-folded aliases.

Goto loads an immutable Pose, requires the expected entity revision, and compares
variant, exact enabled-joint/unit set, Profile fingerprint, Kinematics fingerprint, and
joint-state validity against the active robot. Only then does it create a Joint Motion
for the normal Motion application service and gateway. A repository cannot dispatch an
executor or driver.

Studio Goto applies the same pattern to a Draft/keyframe pair. It requires the expected
persisted Draft revision, reloads the embedded keyframe snapshot, validates variant,
exact joint/unit membership, Profile/Kinematics fingerprints, and joint state, then
submits `STUDIO` + `MOVE_JOINTS` through the normal motion service and safety gateway.
The browser does not supply the Joint target. The Studio mutation lock linearizes Draft
recovery, revision/keyframe checks, and command submission against autosave, so the
checked persisted frame cannot be replaced inside the check-to-submit interval.

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

Stage 6 adds MotionDraft schema `1.0.0` without modifying Motion schema `2.0.0`. Its
generated artifact is `docs/schemas/motion-draft.schema.json`. Round-trip, corrupt-file,
missing nested identity, and schema-current tests are included in the current 393-test
backend pass. Two fresh temporary generations were byte-identical, and a final generated
temporary tree matched the tracked schema artifacts.

Stage 7 adds generated schemas for transient `FrameMetadata`, `TrackingResult`, and
`FollowStatus` at `docs/schemas/vision-frame-metadata.schema.json`,
`vision-tracking-result.schema.json`, and `vision-follow-status.schema.json`. They do not
change Pose, Motion, MotionDraft, or another persisted user schema and create no media
storage contract. Full deterministic generation and schema-current tests pass in the
432-test backend gate.
