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
evidence. The dedicated Stage 3 commit is
`133318e9437dff133a4c25bf01aec09cce5ae6e3` and is pushed to the working remote branch.

## Stage 4 - Pose and Motion Library (complete)

Stage 4 implements:

- independent Pose/Motion schema `2.0.0` with exact Profile/Kinematics capture evidence;
- UUID-only atomic JSON repositories, expected-revision conflicts, four-MiB entity caps,
  stable sorting, and corrupt-file quarantine/list continuation;
- bounded coherent Capture and compatibility-checked Goto through the existing Motion
  Safety Gateway;
- CRUD/search/Tag/sort/pagination APIs with no client filesystem path;
- a responsive POSES/MOTIONS Library with inline confirmations, offline/conflict states,
  actual Capture, two-Pose Motion creation, and Stage 5 Play disabled;
- an explicit-source Legacy action importer that defaults to dry-run reporting, uses new
  UUIDs, and rejects rather than guesses incomplete/ambiguous input.

Playback, incomplete Motion editing, and any Real behavior remain outside Stage 4. The
final backend/frontend, lint/type/format/build/schema/lock/dependency, browser, and
safety-isolation gates pass. The independent audit passes P1=0/P2=0. Stage 4 is GREEN
and complete; the next Stage records the dedicated containing commit's exact SHA/remote
state because a commit cannot embed its own SHA.

## Stage 5 - Trajectory and playback (complete)

Stage 5 implements deterministic Joint, explicit-hold, and true TCP-space
Cartesian-linear compilation; whole-plan checks and semantic digest; an immutable exact
prepared-plan cache; bounded preview; monotonic absolute-deadline scheduling;
pause/resume/Stop/rate/closed-loop control; one Active Playback; and Dry Run execution
through the shared gateway and motion-slot ownership. The Library exposes structured
preflight, responsive path charts, controls, status, and safe errors. Backend/frontend,
lint/type/format/build/schema/lock/dependency, focused isolation, and desktop/mobile
browser checks are green. Cartesian behavior remains provisional until physical
kinematics acceptance.

## Stage 6 - Studio (implementation green; delivery pending)

The current Stage 6 worktree implements:

- independent recursively strict `MotionDraft` schema `1.0.0` with zero-or-more
  keyframes, typed server-owned source metadata, bounded canonical Legacy-snapshot trust,
  and no weakening of formal Motion cardinality;
- UUID/atomic/CAS autosave, bounded recovery/quarantine, recursively required persisted
  fields, and pairwise-disjoint storage roots including case/Unicode aliases;
- directed-edge reorder semantics with persisted editor-default provenance and a pure
  bounded Undo/Redo reducer;
- Capture, add from Pose, replace, reorder, duplicate/delete, duration/hold/easing/mode,
  keyboard editing, and desktop/mobile Studio workspace implementation;
- backend-only validation/compile with `executable=false`, fail-closed write-ahead
  Save/Save As reconciliation, exact operator marker release, structured Draft/Motion
  conflict scope, and provenance-preserving conflict forks that retain local edits;
- persisted-keyframe `STUDIO` Goto through the existing Dry Run Motion Safety Gateway;
- formal Motion handoff to the existing revision/digest-bound Stage 5 playback path.

Current implementation evidence is GREEN: 393 backend tests, a focused 36-test
Stage 6 domain/repository/coordinator/actions/API selection, 174 frontend tests across 12
files, a focused 89-test Studio selection, Ruff/format over 141 files, strict mypy over
141 source files, ESLint/TypeScript/build, schema determinism, lock/npm-audit gates, isolated
desktop/mobile browser acceptance, and final independent integrated audit P1=0/P2=0.
The oversized service/hook findings were closed by bounded backend coordinators/actions
and composed frontend session hooks. The dedicated commit and push evidence remain
Pending; Stage 6 is not complete until that delivery gate closes.

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

- Stage 6 dedicated commit/push, and Stage 7-8 implementation, verification, and one
  dedicated commit per remaining Stage;
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
