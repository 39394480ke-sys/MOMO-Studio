# Domain model

## Robot identity and profile

`RobotVariant` is `V1` or `V2`. `ControlMode` is only `DRY_RUN` or `REAL`; test doubles are adapters, not product modes. `RobotId` identifies a runtime robot through the manager port.

A `RobotProfile` carries a schema version, variant, display name, linear-rail flag, ordered `enabled_joints`, `joint_definitions`, optional URDF reference, and TCP link. Each joint declares its ID, revolute/prismatic type, explicit `deg`/`mm` unit, bounds, home, and an untrusted hardware-mapping placeholder. IDs must be unique and definitions must exactly cover the enabled set. The profile itself enforces the V1/V2 joint-set, rail, type, and unit contract: V1 joints are revolute/deg; V2 J10 is prismatic/mm and J11-J15 are revolute/deg.

Example numeric limits are scaffolding, not calibrated truth. No Stage 1 profile is safe for a device.

## State and pose

`JointState.positions` is keyed by joint ID. Validation against a profile rejects missing or unknown joints, non-finite numbers, and values outside the joint's declared bounds. Keyed data remains meaningful when a variant has no rail or a future profile changes joint count.

`TcpPose` contains a frame, `position_mm` vector, and canonical quaternion `orientation_quaternion_xyzw`. Components must be finite. Zero-length quaternions are rejected; non-zero quaternions are normalized once at model construction and the normalized value is serialized.

The unit contract is explicit:

- UI and domain: `mm`, `deg`;
- canonical orientation: normalized quaternion, `xyzw` order;
- kinematics adapter: `m`, `rad`;
- conversion: named functions at the adapter boundary only.

`PoseSnapshot` is the complete immutable-by-value capture used to reproduce a camera position: robot variant, full keyed joint state, canonical TCP pose, optional hardware safety snapshot, optional calibration fingerprint, and capture time. Its keyed state and nested JSON hardware data are copied and deeply frozen. `Pose` adds UUID identity, display metadata, timestamps, revision, and schema version. Names are not identifiers and may repeat.

## Motion

`MotionTransition` defines positive `duration_s`, `JOINT` or `CARTESIAN_LINEAR` mode, and `LINEAR`, `SMOOTHSTEP`, or `EASE_IN_OUT` easing. It is a description, not a trajectory implementation.

Each `MotionKeyframe` has its own UUID, label, an embedded full `PoseSnapshot`, optional provenance-only `source_pose_id`, non-negative `hold_s`, and an incoming transition. The first frame has no incoming transition; every later frame has one describing travel from the prior frame.

A playable `Motion` has at least two keyframes. All snapshots match its variant; every state validates against the canonical product profile; timings are finite and non-negative/positive as appropriate. Motion stores playback defaults, tags, timestamps, revision, and schema version and supports JSON round trips.

Crucially, a Motion owns copies of snapshots. Editing or deleting a source Pose can never change an already saved Motion, and playback must not open a referenced Pose file.

Profiles, settings, Poses, Motions, snapshots, keyframe lists, tags, and safety-relevant mappings are immutable after validation. An application edit creates and fully validates a new entity revision; it does not mutate a model in place and bypass construction-time invariants.

## Repository contracts

Pose and Motion repository ports accept domain entities and UUIDs. Later file adapters will preserve schema version and revision and use atomic replacement. The ports do not expose arbitrary filesystem paths.

## Schema evolution

`schema_version` describes persisted shape; `revision` describes entity edits. A later schema change requires migration/compatibility analysis, round-trip tests, regenerated artifacts under `docs/schemas`, and an explicit Stage decision.
