# Roadmap

This roadmap records sequencing and safety gates. A named future capability is not present until its own Stage implements, tests, documents, and commits it.

## Stage 1 - Foundation

Established the independent repository, web-first shell, domain/ports/adapters direction, product and variant contracts, immutable Pose Snapshot/Motion schemas, safe configuration, Legacy audit, initial schemas, and reproducible developer commands. It exposed metadata only and no robot lifecycle or motion behavior.

## Stage 2 - Robot Core and Dry Run (current)

The current Stage is limited to robot identity, state, and safety foundations:

- formal V1/V2 Profile repository, source/verification metadata, and stable Profile Fingerprints;
- immutable Calibration model, read-only example repository, and structured compatibility/readiness diagnostics;
- characterized logical/raw mapping and dynamic effective-limit calculations using synthetic data;
- one `primary` active robot, an in-memory Dry Run driver, serialized lifecycle state machine, and monotonic compatible-runtime sequence;
- safe Connect, idempotent Disconnect, idempotent Dry Run Stop, and disconnected-only V1/V2 switching;
- atomic untracked runtime-state persistence with strict restore checks and corruption quarantine;
- REST status/Profile/Calibration/diagnostic/lifecycle APIs with structured errors and `hardware_accessed=false`;
- Control and Settings pages backed by the API, using 1 Hz polling and explicit offline/stale behavior.

Stage 2 remains `DRY_RUN` with hardware access `DISABLED` and real motion false. It contains no position command, FK, IK, Jog, Move, Home, Pose workflow, Motion workflow, playback, WebSocket, camera, real hardware adapter, Calibration write, Fleet, or coordination feature.

## Stage 3 - Kinematics and Motion Safety (future)

Stage 3 has not started. Its exact scope requires review before implementation. Candidate work includes explicit `mm`/`deg` to `m`/`rad` conversion boundaries, verified V1/V2 kinematics models, deterministic Dry Run FK/IK, reachability/residual contracts, and one application motion-safety entry point before any Joint Jog, Cartesian Jog, Move Pose, Home, or related command is exposed.

Stage 3 must remain hardware-isolated unless a separate hardware Stage is explicitly approved. It must not reuse the Legacy six-joint V1 assumption, treat the rail-equipped Legacy V1 URDF as authoritative, or let an API route call a driver directly. Any command surface needs cancellation/Stop semantics, concurrency tests, limit/rate checks, and browser verification.

## Later increments

1. **Pose workflow:** atomic UUID-based Pose storage, capture of complete immutable snapshots, revisions/conflicts, list/delete, and a separately reviewed Goto preflight.
2. **Studio and Motion Library:** embedded keyframes, transition/hold/easing authoring, deterministic sampling, timeline/library persistence, compatibility reports, and safe Dry Run playback.
3. **Reviewed hardware integration:** one physical variant at a time, verified non-template Profile and Calibration identity, optional hardware dependencies, connection/diagnostics/Stop before motion, one deny-by-default safety gateway, and explicit operator-only Real authorization.
4. **Vision following:** camera provider, target selection/detection, freshness, EMA/dead zone, bounded planning, and immediate target-loss motion inhibition. Photography and recording remain excluded.
5. **Packaging and deployment:** Tauri evaluation, local network authentication, backup/migration, release provenance, and third-party license review after the trust boundaries stabilize.

No increment adds multi-arm product UI, coordination, AI/voice control, gesture control, gripper, Teach Mode, PyBullet product UI, community, Camera Hub media management, photography, or recording unless product scope is explicitly revised.

## Evidence still required

- physically verified joint limits, Homes, directions, Servo IDs, scales, raw bounds, modes, and multi-turn representation for each variant;
- an authoritative rail-less V1 model and an authoritative V2 model, including axes, TCP links, reference FK poses, IK tolerances, and asset provenance/license;
- a reviewed production Calibration lifecycle and independent hardware identity/acceptance procedure;
- motion sampling, rate, workspace, cancellation, Stop, and uncertain-safety contracts;
- local-network authentication and later desktop packaging decisions;
- source and redistribution approval for every migrated third-party line, model, mesh, or binary asset.

Each future Stage must preserve applicable earlier checks, add focused negative and isolation tests, update schemas/ADRs/audits as needed, record browser and command evidence, and stop at its approved boundary.
