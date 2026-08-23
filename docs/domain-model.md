# Domain model

## Robot identity, mode, and access

`RobotVariant` is `V1` or `V2`; these are hardware variants, not software releases. `ControlMode` is `DRY_RUN` or `REAL`. `HardwareAccessPolicy` is a separate capability gate with `DISABLED`, `READ_ONLY`, and `FULL`. Stage 2 permits only `DRY_RUN` plus `DISABLED`; the other enum members reserve vocabulary and grant no current capability.

`RobotId` is a validated stable identifier. The Stage 2 composition root creates one `primary` robot in a `RobotManager`; it does not expose a global robot value, `arm_a`, Fleet, or coordination semantics.

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

Stage 2 never returns effective Real readiness: `real_readiness` remains `BLOCKED_BY_STAGE_POLICY`. A complete matching template can be structurally valid for diagnostics, but it cannot authorize hardware. Mapping mismatch is classified as `INCOMPLETE` and makes `calibration_valid=false`. The repository is read-only and loads only reviewed example filenames; no calibration-write use case or API exists.

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

These functions are characterization and future safety foundations only. Stage 2 has no API or application operation that supplies a target or emits raw commands.

## Runtime state and status

`RobotRuntimeState` (`RuntimeState` in code) is immutable persisted Dry Run data with:

- schema version, robot ID, variant, and Profile Fingerprint;
- exact keyed positions and units;
- last recorded connection state;
- timezone-aware update time and non-negative `state_sequence`.

The file repository constrains robot IDs and paths, writes atomically, and quarantines corrupt or rejected files. Restore additionally validates the active variant/fingerprint, exact joint and unit mappings, finite values, and logical limits. A failed startup restore uses Profile Home with sequence zero; a variant switch still advances from the current runtime sequence. A valid restore carries positions and sequence forward but never restores an active connection.

`RobotStatus` is the read-only API projection: identity, variant, mode/policy, connection state, connected flag, Profile identity/verification, Calibration status, positions, units, optional raw positions, last error, timestamp, sequence, stale marker, and `hardware_accessed=false`. Stage 2 always returns `raw_positions=null`.

Connection states are `DISCONNECTED`, `CONNECTING`, `CONNECTED`, `DISCONNECTING`, and `FAULTED`. One command lock serializes all lifecycle operations. The normal transitions are:

```text
DISCONNECTED -> CONNECTING -> CONNECTED
CONNECTED/FAULTED -> DISCONNECTING -> DISCONNECTED
```

Duplicate Connect is rejected without creating another driver. Disconnect while already disconnected returns the stable state. Stop returns `STOPPED` when connected and `NOT_CONNECTED` when disconnected; it does not alter positions. Driver failures enter `FAULTED`, record a safe error summary, and never expose a traceback. `state_sequence` increases monotonically for state changes and Stop events within the runtime lifecycle.

## State, Pose, and Motion contracts

`JointState.positions` is keyed by joint ID and may carry an explicit unit map. Validation against an explicit Profile rejects missing or unknown joints, wrong/missing units, booleans, non-finite values, and out-of-range values.

`TcpPose` contains a frame, `position_mm`, and canonical normalized `xyzw` quaternion. `PoseSnapshot` is the complete immutable-by-value capture of variant, keyed joint state, TCP, optional hardware safety snapshot, optional Calibration fingerprint provenance, and capture time. `Pose` adds UUID identity, display metadata, timestamps, revision, and schema version.

A `MotionKeyframe` embeds a complete `PoseSnapshot`; optional `source_pose_id` is provenance only. `Motion` owns those copies, so editing or deleting a source Pose cannot alter playback data. Motion transitions and playback defaults remain structural Stage 1 contracts. Stage 2 exposes no Pose/Motion repository adapter, CRUD, trajectory, playback, or motion endpoint.

Nested lists/maps are frozen using JSON-serializable immutable containers. JSON round trips preserve meaning and do not expose `mappingproxy` or another non-serializable type.

## Schema evolution

`schema_version` describes persisted shape; entity `revision` describes edits where the entity contract defines revisions. A persisted schema change requires compatibility analysis, round-trip tests, regenerated artifacts under `docs/schemas`, and an explicit Stage decision. Display names are never storage identities; persistent user entities use UUID filenames.
