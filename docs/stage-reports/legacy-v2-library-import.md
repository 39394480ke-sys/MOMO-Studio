# Legacy V2 Library Import

Date: 2026-08-28

## Outcome

The current local MOMO Studio resource library received eight V2 Motion entities and
eleven V2 Pose entities from the read-only Legacy source at commit
`ff8bbda0c2222cb57951c7913f7f12f5777b98fa`.

Imported motions:

- `testj14`
- `V2 演示`
- `v2双臂演示`
- `拉布布出现`
- `未命名1`
- `未命名2`
- `环绕`
- `近远`

Imported poses:

- `-50mm环绕左`
- `50mm环绕右`
- `拉布布视角`
- `拉布布视角 2`
- `拉布布视角 3`
- `拉布布视角远`
- `拉布布视角近`
- `空镜`
- `-38mm`
- `人脸视角`
- `v2拉布布视角`

Two explicitly tagged V1 poses (`v1 拉布布视角`, `v1人脸视角`) were skipped. Four
old-format poses (`-70mm平移`, `70mm平移右`, `-70环绕左`, `70环绕右`) were quarantined
because their V2 `j10` values are approximately ±71 mm, outside the current profile's
[-50, 50] mm limit. No value was clamped and no safety validation was bypassed.

## Migration boundary

The eight actions came only from the Legacy formal action-library directory. The pose
source was the Legacy named-pose library with SHA-256
`028e2dc97f8b192be0d2e095fcc0758bd6b5f6dcbf026c2e69958167c72de88c`.
Twelve pose entries lacked variant and joint-order metadata; the explicit operator
selection `--variant V2` supplied that metadata and produced warnings. Entries with an
explicit different variant were not reinterpreted.

Every accepted entity received a fresh UUID filename. TCP values were recomputed with
the current kinematics model. Legacy gripper, raw/multi-turn, TCP, hardware, calibration,
serial, and absolute-path data were excluded. Imported snapshots have null live state
sequence, hardware snapshot, and calibration fingerprint.

Runtime entity files remain under ignored `data/poses` and `data/motions`; they are not
committed product fixtures.

## Studio trust decision

The reviewed `legacy-import` Pose entities may be selected as Studio keyframes even
though their immutable snapshots intentionally have `state_sequence=null`. Trust is
granted only by the backend when `source_pose_id` resolves to a server-owned Pose with
the `legacy-import` tag and the embedded snapshot is exactly identical to that Pose.
The resulting snapshot digest is stored in the draft's server-owned trust registry;
clients still cannot submit or extend that registry directly.

This does not relax Profile, Kinematics, enabled-joint/unit, logical-limit, null
hardware/Calibration, or recomputed-TCP checks. Editing any field of the embedded
snapshot changes its digest and is rejected. A Studio composition can therefore retain
Pose-level provenance without pretending to be a single imported Legacy action or
fabricating a live robot state sequence. Motion Draft schema version remains `1.0.0`;
the generated JSON Schema is unchanged because this decision narrows service-owned
trust semantics rather than changing serialized fields.

## Verification

- Importer regression tests: 22 passed.
- Full backend suite: 670 passed, one existing Starlette/httpx deprecation warning.
- Full frontend suite: 289 passed across 30 files.
- Ruff, mypy, ESLint, TypeScript, backend format check, and production build passed.
- Running API returned totals of 11 poses and 8 motions.
- Every runtime filename was UUID-based and every imported entity was V2.
- Runtime health remained `DRY_RUN`, hardware policy `DISABLED`, and
  `real_motion_enabled=false` before and after import.
- The Legacy repository remained clean at the pinned commit.

The production build retained its existing advisory that two generated JavaScript
chunks exceed 500 kB; the build itself passed.
