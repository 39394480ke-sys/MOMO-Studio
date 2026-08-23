# MOMO Studio agent rules

These rules apply to every later Stage and every automated contributor.

## Repository and scope

- Treat `MOMO_RobotARM` and commit `ff8bbda0c2222cb57951c7913f7f12f5777b98fa` as read-only Legacy Source unless a later Stage explicitly records a newer source commit.
- Work only within the current Stage. Do not pre-build later features or add anything listed as out of scope.
- V1 and V2 are robot hardware variants, never software release versions.
- Use English for file and module names. Product UI copy may be Chinese or English.
- Preserve domain/application/ports/adapters/API boundaries; API routes must never import raw servo drivers.
- Do not introduce a global robot singleton, `arm_a` assumptions, or product-facing fleet controls.

## Motion safety

- Default to `DRY_RUN`. Stage 1 must keep `real_motion_enabled=false` and expose no real-motion API.
- Never automatically connect to, scan, home, calibrate, or move real hardware.
- All future real motion must pass through one reviewed safety entry point with profile, calibration, limits, reachability, playback, and operator-intent checks.
- Never provide a debug bypass, arbitrary Python execution, arbitrary file access, or raw-servo HTTP/WebSocket endpoint.
- Do not modify real calibration automatically. Do not commit serial ports, device-local calibration, multi-turn runtime state, runtime poses/motions, or secrets.

## Domain and data contracts

- Work from a profile's explicit `enabled_joints`; never assume all robots contain `j10` or exactly six joints.
- Keep UI/domain units (`mm`, `deg`) distinct from kinematics adapter units (`m`, `rad`). Convert only in named boundary functions.
- A Pose Snapshot is immutable captured data. A Motion embeds complete snapshots; `source_pose_id` is provenance only, so later Pose changes or deletion cannot alter playback data.
- Persist entities by UUID filename, not display name. Keep `schema_version` and revision fields.
- Do not change a persisted-data schema without round-trip tests, compatibility analysis, regenerated JSON Schema, and a Stage decision record.

## Quality and evidence

- Every Stage must run and truthfully record applicable backend/frontend checks.
- Preserve Legacy facts separately from new product contracts and unverified migration decisions.
- Never copy Legacy local calibration, serial settings, runtime data, or third-party assets without provenance and review.
