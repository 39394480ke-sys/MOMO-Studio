# Roadmap

This roadmap records sequencing and safety gates. A named capability is not complete
until its Stage implements, tests, documents, commits, and records browser/safety
evidence. V1 and V2 are hardware variants, not software versions.

## Stage 1 - Foundation (complete)

Established the independent repository, web-first shell, domain/ports/adapters
direction, product and variant contracts, immutable Pose Snapshot/Motion schemas, safe
configuration, Legacy audit, initial schemas, and reproducible developer commands. It
exposed metadata only and no robot lifecycle or motion behavior.

## Stage 2 - Robot Core and Dry Run (complete)

Added formal V1/V2 Profiles and fingerprints, immutable example Calibration and
compatibility diagnostics, unit-neutral logical/raw characterization, one `primary`
runtime, the in-memory Dry Run driver, serialized lifecycle, atomic ignored runtime
state, REST lifecycle/status APIs, and backend-backed Control/Settings views.

Stage 2 remains the safety foundation: default `DRY_RUN`, hardware access `DISABLED`,
real motion false, no serial/Servo adapter, no device scan, and no Real readiness.

## Stage 3 - Kinematics and safe Dry Run control (complete)

Stage 3 completed:

- mesh-free V1/V2 serial-chain model documents with deterministic fingerprints;
- rail-less V1 `j11`-`j15` and V2 `j10`-`j15` with prismatic J10;
- explicit `mm`/`deg` to `m`/`rad` boundaries and normalized XYZW quaternions;
- deterministic FK and bounded numerical IK with best result, residuals, and reason;
- distinct Base and Tool Cartesian increments;
- one Motion Safety Gateway for Joint Move/Jog, Home, Cartesian Jog, and Move Pose;
- cancellable, interpolated Dry Run execution with an injected monotonic Clock;
- one Active Motion and Stop-first cancellation semantics;
- renewable backend Jog lease/deadman for hold-to-Jog and network-loss expiry;
- bounded read-only robot-status WebSocket with REST fallback;
- a responsive Control workspace driven only by backend status.

Both models are `PROVISIONAL_DRY_RUN`; they cannot authorize Real Cartesian motion,
Cartesian playback, or Real vision follow. Stage 3 remains hardware/camera isolated.

All Stage 3 kinematics, safety, executor, Jog, WebSocket, hardware/camera-isolation,
frontend, build, schema, lock/audit, and desktop/mobile browser checks are green: 226
backend tests and 54 frontend tests pass, checked responsive widths have no horizontal
overflow, and the final browser console is empty. The Stage report records exact
evidence. Stage 4 begins only after the dedicated Stage 3 commit exists.

## Stage 4 - Pose and Motion Library (not started)

Planned scope: UUID-based atomic Pose/Motion repositories, optimistic revisions,
corruption quarantine, capture of a sequence-consistent Joint/TCP snapshot, list/search,
duplicate/delete, Goto through the existing Motion Safety Gateway, and a reviewed Legacy
import preview. It may not add playback or bypass the Stage 3 gateway.

## Stage 5 - Trajectory and playback (not started)

Planned scope: deterministic Joint and Cartesian-linear compilation, sampled
preflight/digest, bounded scheduling, pause/resume/stop/loop, one Active Playback, and
Dry Run playback through the same gateway/executor ownership. Cartesian behavior remains
provisional until physical kinematics acceptance.

## Stage 6 - Studio (not started)

Planned scope: Draft persistence, timeline/keyframes, reorder/duplicate/delete,
duration/hold/easing/mode editing, bounded undo/redo and autosave, preview/preflight,
playback integration, and Save/Save As without mutating embedded snapshots.

## Stage 7 - Vision and safe following (not started)

Planned scope: deny-by-default Camera Access Policy, Synthetic source, manual ROI,
honest optional tracking/detector capabilities, bounded local stream, EMA/dead zone,
Follow Lease, and immediate lost/stale/disconnect Stop. Vision may submit only through
the Stage 3 Motion Safety Gateway. Photography, recording, gestures, and Cinematic
Director remain excluded.

## Stage 8 - Real boundary and release hardening (not started)

Planned scope: minimal ServoBus port, Fake Bus, gated optional Feetech shell, multi-factor
Real readiness, short-lived Operator Session, explicit-ID/no-scan connection,
read-only diagnostics, protected Calibration workflow, Fake-Bus Real executor,
uncertain Stop semantics, LAN security, backup/migration, CI, operator/field acceptance
documents, packaging plan, and `0.1.0-rc1` with
`FIELD_ACCEPTANCE_REQUIRED`.

No field item will be executed autonomously. Real Joint, Cartesian, Playback, and Vision
capabilities remain independently blocked until every applicable verified Profile,
Calibration, Kinematics, device, operator, and field-acceptance gate is satisfied.

## Evidence still required

- Stage 4-8 implementation, verification, and one dedicated commit per Stage;
- physically verified V1/V2 geometry, frames, joint limits, Homes, directions, Servo
  IDs, scales, raw bounds, modes, workspace, FK references, IK tolerances, and dynamics;
- reviewed production Calibration lifecycle and independent device/field acceptance;
- exact dependency/license provenance for every optional hardware, vision, model, mesh,
  or binary artifact;
- LAN authentication, backup/migration, reproducible release, and packaging evidence;
- final combined verification, clean tree, push, and Draft PR.

All later work must preserve domain/application/ports/adapters/API boundaries, explicit
enabled-joint/unit contracts, bounded resources, one motion safety entry point, and the
deny-by-default hardware/camera policies. The retirement register for Fleet, multi-arm,
AI/voice, gestures, gripper, Teach Mode, PyBullet product UI, community, Camera Hub,
photography, and recording remains in force.
