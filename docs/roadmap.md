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

## Stage 6 - Studio (complete)

Stage 6 implements:

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
and composed frontend session hooks. Commit
`37783bdf8c01146d3a312980dbe4a25716e5468c` contains the Stage and is pushed to
`origin/codex/v1-autonomous-completion`.

## Stage 7 - Vision and safe following (complete / green)

The Stage 7 worktree implements:

- independent `DISABLED` / `SYNTHETIC_ONLY` / `LIVE_CAMERA_ALLOWED` camera policy with
  Synthetic default and a policy-first, lazy-import optional OpenCV camera shell;
- strict frame identity, normalized frame-bound boxes, manual ROI, deterministic
  Synthetic person/face fixtures and tracker, and honest unavailable live capabilities;
- a no-store bounded local stream with 12 fps/640×360 defaults, 30 fps/1280×720 maxima,
  4 default/16 maximum clients, one latest-value slot, and 64-frame/32-MiB history caps;
- center error, EMA, dead zone, sign/gain, maximum step/rate, explicit Profile-bound
  pan/tilt mapping, one renewable Follow lease, and complete automatic Stop reasons;
- high-level Vision commands only through the motion application service and Stage 3
  Motion Safety Gateway; Real Follow remains blocked;
- the responsive Vision workspace with frame-bound selection, overlays, provider/status
  evidence, tuning, heartbeat, and priority Stop.

Current automated evidence passes 432 backend tests, a 34-test focused Stage 7
core/Follow/API suite, 190 frontend tests across 14 files, a focused 16-test Vision
client/page suite, backend/frontend static/build/schema/lock/npm gates, and real-app
desktop/mobile browser acceptance with empty warning/error logs. No OpenCV dependency
was added; no camera was opened/enumerated and no model was downloaded. Final independent
audit closes P1=0/P2=0. Stage 7 is complete in pushed commit
`dedbdabb9a35aefea01df05f0652214428305a93`.

## Stage 8 - Real boundary and release hardening (software complete / green; delivery pending)

The current worktree implements:

- a minimal explicit-ID/no-scan `ServoBus` port, deterministic Fake Bus, and a lazy
  optional Feetech shell that remains `PENDING_ADAPTER_VERIFICATION` and disables goal
  writes until its package/API/license/cancellation/physical semantics are reviewed;
- a pure multi-factor Real readiness matrix, separate capability readiness, a bounded
  context-bound Operator Session, explicit-connect/read-only diagnostics, and backend
  expiry cleanup without automatic connect, Home, torque, scan, or movement;
- a selected-joint current-angle Calibration workflow with complete preview, immutable
  revision/fingerprint, atomic V1/V2 file replacement, prior-revision backup, and
  explicit rollback; examples cannot be promoted to Real;
- an exact-PreparedTrajectory Real executor exercised only through Fake Bus contracts,
  including raw mapping/bounds, monotonic deadlines, readback/divergence, partial-write,
  cancellation, session expiry, and truthful Stop uncertainty;
- loopback-by-default serving, opt-in authenticated LAN, exact same-host HTTP Origin,
  bounded HttpOnly sessions, ongoing WebSocket/Vision authorization, request/body/rate
  bounds, and structured redacted audit;
- deterministic config-free backup/export/preview/migration, one-use preview grants,
  exact-revision import, atomic Calibration batch handling, and a durable write-ahead
  journal with startup recovery for process-crash atomic restore;
- same-backend relative SPA hosting, no CDN-backed API docs or runtime asset dependency,
  CI isolation checks, operator/security/recovery/field documentation, and release
  identity `0.1.0-rc1` / `FIELD_ACCEPTANCE_REQUIRED`.

No field item has been or will be executed autonomously. The shipped defaults remain
Dry Run, hardware Disabled, real motion false, Synthetic camera, and field acceptance
Pending. Real Joint, Cartesian, Playback, and Vision capabilities remain independently
blocked until every applicable verified Profile, Calibration, Kinematics, adapter,
device, operator, and field-acceptance gate is satisfied.

Final software evidence is GREEN: 563 backend tests, 201 frontend tests across 17 files,
Ruff/format/strict mypy, ESLint/TypeScript/build, deterministic schemas, lock/dependency,
52-test isolation, secret-scan, and npm-audit gates pass. The complete V2 Dry Run workflow
passes at 1440×960 and 390×844, with 850/830 breakpoint checks, no horizontal overflow,
and console warnings/errors `[]`. The final independent audit closes P1=0/P2=0 after 74
focused tests. The dedicated Stage 8 commit/push and Draft PR disposition remain pending.

## Evidence still required

- dedicated Stage 8 commit/push and Draft PR disposition;
- physically verified V1/V2 geometry, frames, joint limits, Homes, directions, Servo
  IDs, scales, raw bounds, modes, workspace, FK references, IK tolerances, and dynamics;
- reviewed production Calibration lifecycle and independent device/field acceptance;
- exact dependency/license provenance for every optional hardware, vision, model, mesh,
  or binary artifact;
- deployment-topology LAN/TLS/firewall evidence and independent backup disaster-recovery
  exercise outside the automated fixture environment;
- reproducible packaged distribution, repository license decision, and native packaging
  evidence if Tauri is later introduced.

All later work must preserve domain/application/ports/adapters/API boundaries, explicit
enabled-joint/unit contracts, bounded resources, one motion safety entry point, and the
deny-by-default hardware/camera policies. The retirement register for Fleet, multi-arm,
AI/voice, gestures, gripper, Teach Mode, PyBullet product UI, community, Camera Hub,
photography, and recording remains in force.
