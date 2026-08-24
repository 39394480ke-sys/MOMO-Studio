# MOMO Studio v1 Autonomous Completion Report

- Repository: `/Users/ke/Library/Mobile Documents/com~apple~CloudDocs/Code/MOMO-Studio`
- Task starting commit: `32d0163431e229cb3c2e01a285e7e851124ce9c1`
- Working branch: `codex/v1-autonomous-completion`
- Report status: **LIVE — Stages 3-6 complete and GREEN; Stage 7 implementation,
  browser, and independent audit GREEN P1=0/P2=0 with delivery Pending; Stage 8 pending**
- Final commit: Pending
- Remote branch: `origin/codex/v1-autonomous-completion` pushed through
  `37783bdf8c01146d3a312980dbe4a25716e5468c`
- Draft PR: Pending

This is the cumulative evidence ledger for the Stage 3-8 autonomous task. It is updated
after each Stage implementation and again after final verification. `Pending` means the
operation has not yet been truthfully recorded; it never means pass.

## Stage ledger

| Stage | Starting commit | Ending commit | Status | Tests | Browser verification | Safety verification | Known limitations |
|---|---|---|---|---|---|---|---|
| 3 - Kinematics and Control | `32d0163431e229cb3c2e01a285e7e851124ce9c1` | `133318e9437dff133a4c25bf01aec09cce5ae6e3` | Complete | Pass: backend 226; frontend 54 | Pass | Pass | Provisional Dry Run kinematics; no physical authority |
| 4 - Library | `133318e9437dff133a4c25bf01aec09cce5ae6e3` | `837369a0e3c43b756dfbaacc3bd21e5b1ae13d3b` | Complete / GREEN; audit PASS P1=0/P2=0 | Pass: backend 273; frontend 71/8 files; focused isolation 65 | Pass: full desktop/mobile workflow and responsive acceptance | Pass: Dry Run only; forbidden modules `[]` | Schema `1.0.0` requires explicit migration; single-process file writers |
| 5 - Trajectory and Playback | `837369a0e3c43b756dfbaacc3bd21e5b1ae13d3b` | `114f2a579df236b4824b23c9a0aae320a83a9a07` | Complete / GREEN; audit PASS P1=0/P2=0 | Pass: backend 352; frontend 85/8 files; focused isolation/integration 128 | Pass: preflight/preview/play/pause/resume/stop and responsive acceptance | Pass: Dry Run only; hardware accessed false | Process-local prepared cache/status; provisional Kinematics; Real blocked |
| 6 - Studio | `114f2a579df236b4824b23c9a0aae320a83a9a07` | `37783bdf8c01146d3a312980dbe4a25716e5468c` | Complete / GREEN; audit PASS P1=0/P2=0 | Backend PASS: 393; focused 36; frontend PASS: 174/12 files; focused 89 | Pass: isolated desktop/mobile plus real-backend conflict retention | Pass: Dry Run/Fake only; console `[]` | Local/single-process Draft persistence |
| 7 - Vision Following | `37783bdf8c01146d3a312980dbe4a25716e5468c` | Pending | Implementation/browser/audit GREEN P1=0/P2=0; delivery Pending | Backend PASS: 432; focused 34; frontend PASS: 190/14 files; focused 16/2 | Pass: 1440×960 + 390×844 Synthetic Select/Detect/Follow/Stop | Pass: Dry Run/Fake only; no camera open/enumeration; console `[]` | Synthetic fixture only; OpenCV absent; live camera/Real Follow blocked; commit/push Pending |
| 8 - Release Hardening | Pending | Pending | Not started | Pending | Pending | Pending | Real field acceptance remains required |

## Commit ledger

| Scope | Commit | Subject | Branch/remote state |
|---|---|---|---|
| Stage 1 | `961d5d522ddc6205a3feb480630eb6bbc1ac652e` | `chore: establish MOMO Studio foundation` | Existing baseline |
| Stage 2 | `32d0163431e229cb3c2e01a285e7e851124ce9c1` | `feat: establish dry-run robot core and safety foundation` | Existing baseline / `origin/main` |
| Stage 3 | `133318e9437dff133a4c25bf01aec09cce5ae6e3` | `feat: add dry-run kinematics and safe motion control` | Pushed to `origin/codex/v1-autonomous-completion` |
| Stage 4 | `837369a0e3c43b756dfbaacc3bd21e5b1ae13d3b` | `feat: add pose and motion library workflows` | GREEN; pushed to `origin/codex/v1-autonomous-completion` |
| Stage 5 | `114f2a579df236b4824b23c9a0aae320a83a9a07` | `feat: add trajectory compiler and playback engine` | GREEN; pushed to `origin/codex/v1-autonomous-completion` |
| Stage 6 | `37783bdf8c01146d3a312980dbe4a25716e5468c` | `feat: add studio timeline authoring` | GREEN; pushed to `origin/codex/v1-autonomous-completion` |
| Stage 7 | Pending | `feat: add safe vision following` | Pending |
| Stage 8 | Pending | `feat: harden real-hardware boundary and v1 release` | Pending |

No Stage row may receive an ending SHA until that Stage's required tests, documentation,
browser/safety evidence, review, and dedicated commit are complete.

## Product architecture

The target architecture preserves one dependency direction:

```text
React frontend
  -> REST and authenticated/bounded read-only WebSocket/stream transports
      -> FastAPI routes and schemas
          -> bounded application services and command coordinators
              -> one Motion Safety Gateway
                  -> prepared trajectory/work
                      -> injected Dry Run or separately gated Real executor
              -> ports
                  -> storage, kinematics, vision, and hardware adapters
```

The product owns one identity-aware Active Robot, not a global robot singleton or Fleet.
All joint membership comes from the active Profile's explicit `enabled_joints`. V1 is
rail-less J11-J15; V2 is J10-J15 with prismatic J10. Domain/UI units stay mm/deg;
kinematics uses m/rad only at named boundaries.

Every executable Goto, Playback, Studio Goto, Vision Follow, and Real command must reuse
the Stage 3 gateway and command ownership model. Draft preview is explicitly
non-executable and backend-compiled. API routes never import raw drivers.
Hardware and camera factories remain deny-by-default and side-effect-free until their
complete authorization evidence is present.

Stage 6 keeps its route-facing application service as the sole Studio lock owner and
Draft/compile facade. Lock-free formal-save and robot-action collaborators own their
cohesive transaction and motion-intent policies. The frontend workspace composes the
pure editor reducer with bounded Draft, Motion, Pose, and dirty-navigation sessions;
playback/Goto/priority Stop epochs stay together and revision/generation/CAS state is not
duplicated across hooks.

## Domain evolution ledger

| Stage | Domain/contracts | Status |
|---|---|---|
| 1 | Robot variants, immutable Joint/TCP/Pose Snapshot/Pose/Motion/keyframe contracts | Complete baseline |
| 2 | Profile/Calibration/fingerprints, logical/raw mapping, Active Robot runtime/status | Complete baseline |
| 3 | Kinematics model/fingerprint/results, command/preflight/status, Jog lease | Complete |
| 4 | Pose/Motion schema `2.0.0`, atomic/CAS repository results, capture consistency, structured entity errors, import/conversion reports | Complete / GREEN; audit PASS P1=0/P2=0 |
| 5 | Immutable TrajectoryPlan/Segment/Sample/Digest/PreparedTrajectory, structured whole-plan preflight, operator intent, playback lifecycle/status/events | Complete |
| 6 | MotionDraft `1.0.0`, directed edge/default metadata, server-owned source/trust provenance, bounded reducer/undo/autosave, fail-closed write-ahead Save intent/exact abandon, structured conflicts/fork, compiler preview, persisted-keyframe Studio Goto | Complete / GREEN P1=0/P2=0 in pushed commit `37783bdf8c01146d3a312980dbe4a25716e5468c` |
| 7 | Frame/box/selection/detection/tracking/capability contracts; pure controller; Profile-bound mapping; Follow lease/status/stop reasons | Implementation/browser/audit GREEN P1=0/P2=0; delivery Pending |
| 8 | ServoBus, readiness evidence, Operator Session, Real outcomes, backup/migration | Pending |

Persisted schema changes require compatibility analysis, round-trip tests, deterministic
regeneration, migration behavior, and an explicit Stage decision. A Stage cannot silently
change schema version or reinterpret existing fields.

## API inventory

### Existing baseline

| Method | Path | Purpose | State |
|---|---|---|---|
| GET | `/api/v1/health` | Safe product health/policy | Stage 2 baseline |
| GET | `/api/v1/meta` | Product/version/variant/mode metadata | Stage 2 baseline |
| GET | `/api/v1/meta/product-scope` | Included/excluded scope | Stage 2 baseline |
| GET | `/api/v1/robot` | Active Robot status | Stage 2 baseline |
| GET | `/api/v1/robot/profile` | Active Profile/fingerprint | Stage 2 baseline |
| GET | `/api/v1/robot/diagnostics` | Safe Dry Run diagnostics | Stage 2 baseline |
| POST | `/api/v1/robot/connect` | Explicit Dry Run connect | Stage 2 baseline |
| POST | `/api/v1/robot/disconnect` | Dry Run disconnect | Stage 2 baseline |
| POST | `/api/v1/robot/stop` | Lifecycle Dry Run Stop | Stage 2 baseline |
| PUT | `/api/v1/robot/variant` | Disconnected-only V1/V2 selection | Stage 2 baseline |
| GET | `/api/v1/calibration/status` | Compatibility/readiness report | Stage 2 baseline |

### Stage 3 verified surface

| Method | Path | Purpose | Verification |
|---|---|---|---|
| GET | `/api/v1/robot/fk` | Current state-consistent FK (`200`) | Verified |
| POST | `/api/v1/kinematics/ik` | Reachability/IK diagnostics (`200`) | Verified |
| POST | `/api/v1/motion/joints` | Move Joints through gateway (`202`) | Verified |
| POST | `/api/v1/motion/jog-step` | Bounded single Jog (`202`) | Verified |
| POST | `/api/v1/motion/jog/start` | Start renewable Jog lease (`202`) | Verified |
| POST | `/api/v1/motion/jog/{session_id}/heartbeat` | Renew matching lease (`200`) | Verified |
| POST | `/api/v1/motion/jog/{session_id}/stop` | Idempotent lease Stop (`200`) | Verified |
| POST | `/api/v1/motion/cartesian-jog` | Base/Tool Cartesian Jog (`202`) | Verified |
| POST | `/api/v1/motion/pose` | Move explicit TCP target (`202`) | Verified |
| POST | `/api/v1/motion/home` | Confirmed Dry Run Home (`202`) | Verified |
| POST | `/api/v1/motion/stop` | Highest-priority command Stop (`200`) | Verified |
| GET | `/api/v1/motion/commands/{command_id}` | Command/preflight/progress (`200`) | Verified |

### Stage 4 verified surface

| Method | Path | Purpose | Verification |
|---|---|---|---|
| GET | `/api/v1/poses` | Bounded Pose list/search/Tag/sort | Verified |
| POST | `/api/v1/poses` | Create a validated Pose from an explicit snapshot | Verified |
| POST | `/api/v1/poses/capture` | Capture one coherent active Dry Run snapshot | Verified |
| GET | `/api/v1/poses/{pose_id}` | Read Pose by UUID | Verified |
| PATCH | `/api/v1/poses/{pose_id}` | Expected-revision metadata update | Verified |
| DELETE | `/api/v1/poses/{pose_id}` | Expected-revision delete | Verified |
| POST | `/api/v1/poses/{pose_id}/duplicate` | Duplicate under a fresh UUID | Verified |
| POST | `/api/v1/poses/{pose_id}/goto` | Compatibility-check and submit Dry Run Joint Goto | Verified |
| GET | `/api/v1/motions` | Bounded Motion list/search/Tag/sort | Verified |
| POST | `/api/v1/motions` | Create a valid embedded-snapshot Motion | Verified |
| GET | `/api/v1/motions/{motion_id}` | Read Motion by UUID | Verified |
| PATCH | `/api/v1/motions/{motion_id}` | Expected-revision Motion update | Verified |
| DELETE | `/api/v1/motions/{motion_id}` | Expected-revision delete | Verified |
| POST | `/api/v1/motions/{motion_id}/duplicate` | Duplicate embedded data under a fresh UUID | Verified |

### Stage 5 verified surface

| Method | Path | Purpose | Verification |
|---|---|---|---|
| POST | `/api/v1/motions/{motion_id}/preflight` | Compile and whole-plan preflight a stored revision | Verified |
| POST | `/api/v1/motions/{motion_id}/play` | Play exact prepared digest/revision | Verified |
| POST | `/api/v1/playback/pause` | Pause at a sample boundary | Verified |
| POST | `/api/v1/playback/resume` | Resume with rebased timing | Verified |
| POST | `/api/v1/playback/stop` | Stop preflight/playback | Verified |
| PUT | `/api/v1/playback/rate` | Set 0.25-2.0x rate | Verified |
| PUT | `/api/v1/playback/loop` | Set bounded closed-loop behavior | Verified |
| GET | `/api/v1/playback` | Read playback status | Verified |
| GET | `/api/v1/trajectory/{digest}/preview` | Read bounded exact-plan preview | Verified |

### Stage 6 implemented and integration-verified surface

| Method | Path | Purpose | Verification |
|---|---|---|---|
| GET | `/api/v1/studio/drafts` | Bounded Draft recovery list | Verified |
| POST | `/api/v1/studio/drafts` | Create zero-or-more-frame Draft | Verified |
| POST | `/api/v1/studio/drafts/from-motion/{motion_id}` | Copy an expected Motion revision into a Draft | Verified |
| GET | `/api/v1/studio/drafts/{draft_id}` | Recover/read one Draft | Verified |
| PUT | `/api/v1/studio/drafts/{draft_id}` | Full-document expected-revision autosave | Verified |
| POST | `/api/v1/studio/drafts/{draft_id}/fork` | Exact-revision provenance-preserving conflict fork | Verified |
| DELETE | `/api/v1/studio/drafts/{draft_id}` | Expected-revision Draft delete | Verified |
| POST | `/api/v1/studio/drafts/{draft_id}/save-intent/abandon` | Exact operation-bound release of a retained formal-save marker | Verified |
| POST | `/api/v1/studio/drafts/{draft_id}/validate` | Validate formal-Motion conversion | Verified |
| POST | `/api/v1/studio/drafts/{draft_id}/compile` | Backend compile and non-executable preview | Verified |
| POST | `/api/v1/studio/drafts/{draft_id}/save` | Compile and revision-safe formal Save | Verified |
| POST | `/api/v1/studio/drafts/{draft_id}/save-as` | Compile and create a fresh formal Motion | Verified |
| POST | `/api/v1/studio/drafts/{draft_id}/keyframes/{keyframe_id}/goto` | Persisted-keyframe Dry Run Studio Goto | Verified |
| POST | `/api/v1/studio/capture` | Coherent current Dry Run snapshot | Verified |

### Stage 7 implemented and verified surface

| Method | Path | Purpose | Verification |
|---|---|---|---|
| GET | `/api/v1/vision/capabilities` | Honest source/tracker/detector/stream capabilities | Verified |
| GET | `/api/v1/vision/status` | Latest frame/selection/tracking/Follow/Robot state | Verified |
| GET | `/api/v1/vision/frame` | One exact no-store frame | Verified |
| GET | `/api/v1/vision/stream` | Bounded no-store latest-value stream | Verified |
| POST / DELETE | `/api/v1/vision/selection` | Select exact-frame normalized ROI / clear selection | Verified |
| POST | `/api/v1/vision/detect/{detector}` | Synthetic `person` or `face` fixture detection | Verified |
| POST | `/api/v1/vision/tracking/reset` | Reset tracking state | Verified |
| POST | `/api/v1/vision/follow/start` | Start one confirmed Dry Run Follow lease | Verified |
| POST | `/api/v1/vision/follow/{lease_id}/heartbeat` | Renew matching lease | Verified |
| POST | `/api/v1/vision/follow/{lease_id}/stop` | Stop matching lease/command | Verified |

Executed Stage 5 OpenAPI enumeration contains 46 method/path combinations across 40
unique HTTP paths, plus the existing read-only WebSocket. Stage 6 adds 14 combinations
across 11 unique paths. Stage 7 adds 11 combinations across 10 unique paths; the
combined inventory is 71 method/path combinations across 61 unique HTTP paths, plus the
same read-only WebSocket. Stage 8 routes will be appended only from completed
application evidence. No API may accept an arbitrary
server path, Python code, raw register/address, driver selector, auto-scan, client
trajectory samples, or hidden Real override.

## WebSocket and stream inventory

| Path | Direction/payload | Safety/resource contract | State |
|---|---|---|---|
| `/api/v1/ws/robot` | Server-to-client Robot/FK/latest-command/playback/sequence; safe errors are embedded, with no separate fault-list field | Read-only; fixed 10 Hz source cap; latest-value playback observer; no application queue; one-second send timeout; 1.5-second/15-frame silent-socket watchdog; REST fallback | Stage 5 verified |
| Vision metadata | REST `/api/v1/vision/status`; no Vision WebSocket | Latest-value frame/selection/tracking/Follow/Robot state; LAN auth remains Stage 8 | Stage 7 verified |
| `/api/v1/vision/stream` | Server-to-client multipart encoded frames | 12 fps/640×360 default; 30/1280×720 max; 4 default/16 max clients; one latest slot; no-store/recording; disconnect cleanup | Stage 7 verified |

No WebSocket is a raw or alternate motion-control transport.

## Schema inventory

| Artifact | Model | Current state |
|---|---|---|
| `docs/schemas/pose.schema.json` | Pose schema `2.0.0` with compatibility fingerprints/sequence | Round-trip tests pass; consecutive generation byte-identical |
| `docs/schemas/motion.schema.json` | Motion schema `2.0.0` with embedded snapshots/source metadata | Round-trip tests pass; consecutive generation byte-identical |
| `docs/schemas/robot-profile.schema.json` | RobotProfile | Stage 2 baseline |
| `docs/schemas/calibration.schema.json` | CalibrationDocument | Stage 2 baseline |
| `docs/schemas/robot-status.schema.json` | RobotStatus | Stage 2 baseline |
| `docs/schemas/runtime-state.schema.json` | RuntimeState | Stage 2 baseline |
| `docs/schemas/kinematics-model.schema.json` | KinematicsModel schema `1.0.0` | Present; consecutive generation byte-identical |
| Stage 5 trajectory/playback | Ephemeral validated domain/transport contracts; no persisted user schema | No generated artifact required; existing seven artifacts unchanged |
| `docs/schemas/motion-draft.schema.json` | MotionDraft schema `1.0.0`; zero-or-more keyframes; recursively strict persisted recovery fields including source/trust/intent identity | Artifact and schema-current/missing-nested-identity tests pass; two fresh generations are byte-identical and a final temporary generation matches tracked artifacts |
| `docs/schemas/vision-frame-metadata.schema.json` | Transient exact frame identity/dimensions | Stage 7 deterministic/current generation passes |
| `docs/schemas/vision-tracking-result.schema.json` | Transient frame-bound tracking result | Stage 7 deterministic/current generation passes |
| `docs/schemas/vision-follow-status.schema.json` | Transient Dry Run Follow lease/controller status | Stage 7 deterministic/current generation passes |
| Later Stage schemas | Backup/Real as applicable | Pending |

Stage 3 schema deterministic-generation evidence: **PASS**. Stage 4 deliberately rejects
and quarantines `1.0.0` Pose/Motion documents rather than inventing missing evidence; an
explicit migration is required. Stage 4 deterministic generation and round-trip evidence
also **PASS**; exact Pose/Motion SHA-256 values are in the Stage 4 report. Stage 5 adds
no persisted schema and two fresh full generations remain byte-identical to each other
and to the tracked seven artifacts. Stage 6 adds the independent MotionDraft artifact
without changing formal Motion `2.0.0`. API construction may use documented defaults,
but on-disk recovery requires every serialized field recursively and quarantines
incomplete nested identity rather than inventing past state.
Stage 7 adds three transient Vision schemas without changing a persisted user-data
contract or introducing media persistence.

## Data directories and exclusion policy

| Location | Purpose | Git policy |
|---|---|---|
| `robot_profiles/` | Reviewed V1/V2 Profile examples | Tracked examples only |
| `calibration/examples/` | Synthetic template Calibration | Tracked examples only; never Real |
| `kinematics_models/` | Provisional mesh-free Dry Run models | Tracked reviewed documents |
| `data/runtime/` | Active Dry Run runtime state | Ignored |
| `data/poses/` | Stage 4 user Pose entities by UUID plus server quarantine | Ignored operational data; four-MiB/entity cap; single-process writer only |
| `data/motions/` | Stage 4 user Motion entities by UUID plus server quarantine | Ignored operational data; four-MiB/entity cap; single-process writer only |
| `data/drafts/` | Stage 6 MotionDraft entities, save-intent recovery, temporary files, and quarantine | Ignored operational data; UUID/CAS/atomic, four-MiB/entity cap, single-process writer only; root disjoint from Motion/Pose and all configured storage roots |
| Audit/backup locations | Future operational data | Pending design; ignored by default |
| `config/local*`, local Calibration/Profile | Device/operator-local state | Ignored; default settings loading does not read it; explicit caller opt-in only |

Tokens, serial ports, secrets, runtime connections, logs, real Calibration, camera paths,
and unselected device data never belong in a config-free backup or Git.

Stage 6 configuration rejects any equal or ancestor/descendant storage pair before
repository construction, including resolved/symlink identity and conservative
case-folded/NFC-Unicode aliases. This prevents one entity repository from reading and
quarantining another entity type.

## Third-party dependency ledger

| Dependency/artifact | Use | License/provenance state | Stage |
|---|---|---|---|
| Existing Python/JS lock dependencies | Backend/frontend foundation | Notices current for Stage 3; npm production audit found 0 vulnerabilities and locked Python runtime audit found no known vulnerabilities; final release-time review remains required | 1-3 |
| NumPy | Mesh-free FK/IK numerical math | Lock resolves `2.4.6` for Python <3.12 and `2.5.2` for Python >=3.12; installed Python 3.11 / NumPy `2.4.6` metadata reports `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`; the 2.5.2 wheel's bundled licenses remain a distribution review item | 3 |
| jsonschema and transitives | Stored Pose/Motion Draft 2020-12 validation | Lock resolves jsonschema `4.26.0`, attrs `26.1.0`, jsonschema-specifications `2025.9.1`, referencing `0.37.0`, rpds-py `2026.6.3` (installed metadata: MIT); dev stubs types-jsonschema `4.26.0.20260518` (Apache-2.0). Lock check passes at 44 packages; locked-runtime audit reports no known vulnerabilities; distribution license-file review remains required | 4 |
| Stage 5 additions | No new runtime dependency | Existing Python/npm lockfiles unchanged; npm production audit 0 vulnerabilities | 5 |
| Stage 6 additions | No new runtime dependency in the current diff | Python/npm lockfiles unchanged; `uv lock --project backend --check` passes for 44 packages; npm audit reports 0 vulnerabilities; Python runtime vulnerability audit not rerun and no pass inferred | 6 |
| Optional OpenCV shell/capabilities | Explicit-ID camera shell plus tracker/HOG/Haar capability descriptions | No package/lock addition; lazy import only after full grant; unavailable in Stage 7; no download/open/enumeration; exact package/HOG/Haar provenance remains required | 7 |
| Optional Feetech SDK | Gated ServoBus adapter shell | Not yet selected/verified; no vendor copy, default install optional | 8 |
| Legacy URDF/STL/models | Evidence only | Files/assets not copied; numerical joint geometry facts were transcribed into provisional mesh-free models; provenance/redistribution/physical verification unresolved | Deferred |

Every new dependency requires a lock update, exact purpose, license review, vulnerability
check, notice update, and confirmation that it adds no unrelated framework, model
download, CDN, or vendored unknown binary.

## Legacy migration disposition summary

| Legacy area | Disposition | Current result |
|---|---|---|
| Profiles and mappings | Rewrite/characterize | Explicit V1/V2 joints/units and Profile-driven mapping |
| V1/V2 URDF kinematics | Rewrite with characterization | Mesh-free provisional chains; V1 phantom J10 removed |
| PyBullet FK/IK | Rewrite | Complete NumPy deterministic serial-chain/DLS implementation |
| Controller bridge/service | Retire as architecture | Small services/ports; one gateway contract |
| Continuous joint stream | Rewrite with characterization | Complete absolute-deadline Dry Run executor/Jog lease |
| Real driver/Calibration tooling | Deferred to Stage 8 boundary | No device code executed or copied |
| Action/recording code | Legacy architecture retired; tracked format characterized | Stage 4 has an independently written explicit/default-dry-run importer. Stage 5 independently rewrites playback as immutable digest-bound compilation and bounded monotonic Dry Run execution. Stage 6 independently adds strict Draft/timeline authoring with directed-edge semantics and write-ahead recovery; recording remains excluded |
| Legacy Vision | Rewritten only for approved slice | Stage 7 deterministic Synthetic source/fixture detectors/tracker, frame-bound ROI, bounded stream, and gateway-only Dry Run Follow; no Legacy code/model, recording, gesture, direct driver, or general-model claim |
| Fleet/multi-arm/AI/voice/gripper/Teach/community/media | Out of scope | No product surface |

The detailed per-file tables remain in `docs/legacy-migration-map.md` and Stage-specific
characterization documents.

## Real readiness and field acceptance

- Current control mode: `DRY_RUN`
- Current hardware policy: `DISABLED`
- `real_motion_enabled`: `false`
- Real Joint readiness: **BLOCKED / Stage 8 not complete**
- Real Cartesian readiness: **BLOCKED / provisional Kinematics**
- Real Playback readiness: **BLOCKED**
- Real Vision Follow readiness: **BLOCKED**
- Operator Session: unavailable
- Field Acceptance: **REQUIRED / NOT PERFORMED**

No committed example Profile, Calibration, Kinematics document, synthetic test record,
environment variable, or frontend click may promote this status.

## Verification ledger

| Evidence | Stage 3 | Stage 4 | Stage 5 | Stage 6 | Stage 7 | Stage 8 | Final |
|---|---|---|---|---|---|---|---|
| Backend pytest count | 226 passed | 273 passed; one known Starlette `TestClient`/httpx deprecation warning | 352 passed; same warning | 393 passed; same warning | 432 passed; same warning | Pending | Pending |
| Focused backend suite | 20 isolation tests | 65 route/import/storage/isolation tests | 128 isolation/integration tests | 36 Stage 6 domain/repository/coordinator/actions/API tests passed | 34 Vision core/Follow/API tests passed | Pending | Pending |
| Frontend Vitest count | 54 passed / 7 files | 71 passed / 8 files | 85 passed / 8 files | 174 passed / 12 files; focused Studio 89/4 files | 190 passed / 14 files; focused Vision 16/2 files | Pending | Pending |
| Ruff | Pass | Pass | Pass | Pass | Pass | Pending | Pending |
| Mypy | Pass / 98 files | Pass / 112 files | Pass / 125 source files | Pass / 141 source files | Pass / 168 source files | Pending | Pending |
| Ruff format check | Pass / 98 files | Pass / 112 files | Pass / 125 files | Pass / 141 files | Pass / 168 files | Pending | Pending |
| ESLint | Pass | Pass | Pass | Pass | Pass | Pending | Pending |
| TypeScript | Pass | Pass | Pass | Pass | Pass | Pending | Pending |
| Vite build | Pass / 1,616 modules; JS 242.41 kB (gzip 76.45 kB) | Pass / 1,621 modules; CSS 32.80/7.10 gzip kB; JS 278.61/85.19 gzip kB | Pass / 1,624 modules; CSS 40.70/8.59 gzip kB; JS 305.54/91.97 gzip kB | Pass / 1,635 modules; HTML 0.56/0.33 gzip kB; CSS 57.26/11.47 gzip kB; JS 394.58/114.40 gzip kB | Pass / Vite 6.4.3, 1,638 modules; HTML 0.56/0.34 gzip kB; CSS 64.19/12.87; JS 422.12/121.76 | Pending | Pending |
| Schema determinism | Pass / byte-identical | Pass / byte-identical with hashes recorded | Pass / unchanged seven artifacts | Pass / two fresh generations byte-identical; final temp tree matches tracked | Pass / three Vision artifacts included; full tree deterministic/current | Pending | Pending |
| `uv lock --check` | Pass / 38 packages | Pass / 44 packages | Pass / 44 packages | Pass / 44 packages | Pass / 44 packages | Pending | Pending |
| npm audit | Pass / 0 vulnerabilities | Pass / 0 vulnerabilities | Pass / 0 vulnerabilities | Pass / 0 vulnerabilities | Pass / 0 vulnerabilities | Pending | Pending |
| Python runtime audit | Pass / no known vulnerabilities | Pass / no known vulnerabilities | Pass / no known vulnerabilities | Not rerun; dependencies/lockfiles unchanged, no pass inferred | Not rerun; dependencies/lockfiles unchanged, no pass inferred | Pending | Pending |
| Independent audit | Pass | Pass / P1=0/P2=0 | Pass / P1=0/P2=0 | Pass / integrated and code-quality P1=0/P2=0 | Pass / P1=0/P2=0 | Pending | Pending |
| Hardware isolation | Pass / focused 20-test suite | Pass / focused 65-test route/import/hardware suite; forbidden modules `[]` | Pass / focused 128-test suite | Pass / Dry Run/Fake only; no hardware access | Pass / Dry Run/Fake only; gateway command reports hardware false | Pending | Pending |
| Camera isolation | Pass | Pass / forbidden modules `[]`; no camera path used | Pass / no camera path or dependency | Pass / no camera path or dependency used | Pass / OpenCV absent; lazy policy-first Spy; no open/enumeration | Pending | Pending |
| Browser desktop/mobile/boundary | Pass | Pass at 1440 x 960 and exact 390 x 844; no horizontal overflow | Pass / workflow and responsive acceptance | Pass / 1440×960, 390×844, focus/overflow/conflict | Pass / real app 1440×960 and 390×844 Synthetic Select/Detect/Follow/Stop | Pending | Pending |
| Console unhandled errors | Pass / `[]` | Pass / warnings and errors `[]` | Pass / warnings and errors `[]` | Pass / warnings and errors `[]` | Pass / warning and error logs `[]` | Pending | Pending |

Exact commands, counts, versions, durations, failures/fixes, and skipped items are added
only after execution. Stage 4 values are the final post-fix root/focused gates. Stage 5
values are the final root/frontend-agent gates before its dedicated commit. Stage 6
values are the final post-refactor implementation gates before its dedicated commit.

## Browser workflow ledger

- Stage 3 Control workflow: Pass — V1/V2, Move Joints, step Jog, Base/Tool Cartesian,
  reachable/unreachable IK, Move Pose, inline Home cancel/confirm, progress/Stop,
  REST fallback, offline disablement, and WebSocket recovery
- Stage 4 Library workflow: Pass — connected Dry Run Capture, search, Tag filtering,
  sorting, detail, Motion creation, UUID handoff, duplicate/delete cancel-confirm, Goto
  confirm, immutable snapshot retention after source deletion, Revision Conflict/Reload,
  offline cached Motion with disabled mutations, and automatic recovery
- Stage 4 responsive acceptance: Pass — 1440 x 960 widths exactly 1440 and 390 x 844
  widths exactly 390, no horizontal overflow, responsive navigation present, stored
  Motion visible, and final console warnings/errors `[]`
- Stage 5 Playback workflow: Pass — isolated Dry Run two-Pose Cartesian Motion,
  31-check preflight, 41-sample digest preview, Play/progress at 0.25x loop,
  Pause/Resume/Stop, and `hardware_accessed=false`
- Stage 5 responsive acceptance: Pass — desktop plus mobile/breakpoint collapsed charts
  and controls, long-text wrapping, no page horizontal overflow, console `[]`
- Stage 6 Studio workflow: Pass — final post-refactor isolated real-backend run used
  `/tmp/momo-stage6-refactor-browser.PJBPjG`; Dry Run Connect, blank-Draft auto-create,
  Capture, Duplicate, autosave revision 4, and formal Save revision 1 passed; an external
  Motion update to revision 2 produced the exact UI conflict without overwrite;
  post-conflict local name/keyframe edits survived authoritative recovery, Draft fork,
  URL rebind, and Save As into a fresh Draft revision 4/Motion revision 1; the original
  Motion remained external revision 2, both Draft intents were null, and the preceding
  full workflow also displayed the retained formal-save recovery gate
- Stage 6 responsive acceptance: Pass — exact desktop 1440×960 document/timeline widths
  1440/1440 and 755/755; exact mobile 390×844 document width 390/390 and Timeline
  322/680 with container-local overflow; final post-refactor fresh 390×844 tab had no
  desktop-layout residue and a focusable/closable Inspector drawer; focus restoration
  was verified in the preceding pass; all desktop/mobile/conflict consoles `[]`
- Stage 7 Synthetic Vision/Follow workflow: Pass — real app at 1440×960 and 390×844
  completed exact-frame Select, person Detect, Follow, gateway completion, operator Stop,
  and navigation/unmount lease cleanup; Target Lost/auto-stop passed backend/component
  automation; browser warning/error logs `[]`
- Stage 8 blocked Real/session/diagnostic UI workflow: Pending
- Final combined Dry Run workflow at 1440×960: Pending
- Final combined workflow at 390×844: Pending
- Main responsive breakpoint sizes: Stage 3 pass at 1201/1200/981/980/841/840/390;
  final combined check Pending
- Full error workflow: Stage 3 pass; final combined check Pending
- Console/network exception review: Stage 3 final errors/warnings `[]`; final combined
  check Pending

All browser movement must remain Dry Run. Browser-tool unavailability is recorded as an
unrun item with reason, never converted into a pass.

## Resource-bound ledger

| Resource | Configured bound | Tests/evidence |
|---|---|---|
| WebSocket update rate/queue | Fixed 10 Hz source cap; no application queue; one-second send timeout; 1.5-second/15-frame client watchdog | Stage 3 verified |
| Motion update rate/history/one active command | 25 Hz default, configurable 20-100 Hz; 256 statuses; one active; 0.1-60 s effective duration | Stage 3 verified |
| Motion admission/idempotency | No waiting command queue; conflicts rejected; 512 idempotency records | Stage 3 verified |
| Jog lease TTL/session history | 400 ms default, configurable 250-500 ms; 256 session records | Stage 3 verified |
| Compiled trajectory plan/cache/preview | 1-100 Hz compiler and 5-50 Hz HTTP; 600 s; 20,000 samples; 2,000 segments; 16 cached prepared plans; 1,000 preview points; 0.25-2x; 100 closed-loop traversals | Stage 5 compiler/playback/API/frontend tests pass |
| Draft/recovery/list | 0-1,000 keyframes; 999 default-edge markers; at most 1,000 trusted Legacy snapshot digests; four MiB/entity; 5,000 root JSON entities; 10,000 scanned entries; 64 MiB aggregate; list page 1-50; compile 5-50 Hz | Stage 6 backend/integration tests and audit evidence |
| Studio undo/redo | Default 100 documents; defensive configurable cap 500; autosave acknowledgements add no history | Reducer, frontend integration, and browser evidence pass |
| Vision FPS/resolution/queue/one source/follow | One Synthetic source; 12 fps/640×360 default; 30 fps/1280×720 max; 4 default/16 max clients; one latest slot; 64 frames + 32 MiB history; 8 MiB/frame; one Follow lease; public TTL 0.25-2 s | Stage 7 backend/component/resource tests and desktop/mobile browser evidence pass |
| Pose/Motion persistence/list bounds | Four MiB/entity; 5,000 root JSON entities; 10,000 scanned root entries; 64 MiB aggregate; page size 1-50; page 1-100000; search max 200; at most 32 Tag filters; stable UUID tie-break | Final repository/API/root gates and independent audit pass |
| Motion-creation source list | First 50 Pose summaries by name; full entities fetched and revisions rechecked on submit | Stage 4 frontend tests pass |
| Legacy import | One explicit file/directory; immediate regular JSON only; four MiB/file; 2,000 scanned entries; 1,000 selected files; 32 MiB aggregate; 1,000 actions/file and 2,000 total; 2-1,000 keyframes/action and 20,000 total; 2,000 report entries | Final importer/root gates and independent audit pass |
| Quarantine retention | Best-effort isolation; no automatic count/age/byte pruning | Known Stage 4 limitation |
| Importer local mutation window | Explicit source can be changed by a hostile local writer between bounded validation/conversion passes | Outside single-operator threat model; known limitation |
| General API body bound | No Stage 4 application-wide request-body byte cap beyond server/framework behavior; entity persistence enforces four MiB only after validation/serialization | Known limitation; Stage 8 hardening Pending |
| One Real Session | Pending Stage 8 | Pending |
| Logs/retries/workers | Pending final inventory | Pending |

## Stage report paths

| Stage | Report |
|---|---|
| 1 | `docs/stage-reports/stage-01-foundation.md` |
| 2 | `docs/stage-reports/stage-02-robot-core.md` |
| 3 | `docs/stage-reports/stage-03-kinematics-and-control.md` |
| 4 | `docs/stage-reports/stage-04-library.md` (GREEN / complete) |
| 5 | `docs/stage-reports/stage-05-trajectory-and-playback.md` (GREEN / complete) |
| 6 | `docs/stage-reports/stage-06-studio-timeline.md` (complete in pushed `37783bdf8c01146d3a312980dbe4a25716e5468c`) |
| 7 | `docs/stage-reports/stage-07-vision-following.md` (implementation/browser/audit GREEN; commit/push Pending) |
| 8 | Pending |

## Unresolved items

1. Create and push the Stage 7 dedicated commit without fabricating that commit's
   self-SHA inside its own contents.
2. Execute Stage 8 without pre-building out-of-scope behavior.
3. Append Stage 8 route/schema/resource inventories only from exact executed results and
   completed Stages.
4. Repeat dependency/license/vulnerability review for later additions and final release.
5. Run later and final browser/error workflows without unauthorized hardware/camera access.
6. Run final make/lock/audit/isolation commands from the completed branch.
7. Record final branch SHA, clean status, remote branch and Draft PR or exact failure.
8. Keep Real readiness blocked and generate—not execute—field acceptance procedures.

## Git and delivery status

- Current branch: `codex/v1-autonomous-completion`
- `main` modified or merged: **No by task policy; final verification Pending**
- Stage 4 remote tip: `837369a0e3c43b756dfbaacc3bd21e5b1ae13d3b`
- Stage 4 remote branch: `origin/codex/v1-autonomous-completion` (pushed)
- Stage 5 remote tip: `114f2a579df236b4824b23c9a0aae320a83a9a07`
- Stage 5 remote branch: `origin/codex/v1-autonomous-completion` (pushed)
- Stage 6 remote tip: `37783bdf8c01146d3a312980dbe4a25716e5468c`
- Stage 6 remote branch: `origin/codex/v1-autonomous-completion` (pushed)
- Final worktree status: Pending; Stage 7 changes are intentionally uncommitted during
  implementation
- Final commit: Pending
- Six Stage commits present: Pending
- Remote branch URL: Pending
- Draft PR URL/reason: Pending

## Safety evidence status

Stage 3 isolation evidence is complete: all motion verification used Dry Run/Fake
adapters; no forbidden serial/camera/microphone module was loaded or operation performed.
Stage 4 executed Capture, Goto, repositories, UI, and importer only through Dry Run/Fake
or offline synthetic-fixture paths. Its focused 65-test isolation suite passes, the
forbidden loaded-module inventory is `[]`, and no serial/Servo/camera/microphone path was
used. Stage 5 compiled and played only immutable logical Dry Run samples; its focused
128-test suite used no serial/Servo/camera/microphone path and browser playback reported
`hardware_accessed=false`. Stage 6's 393-test backend gate, focused 36-test selection,
174-test frontend gate, focused 89-test Studio selection, isolated browser evidence, and
final independent audit P1=0/P2=0 keep Draft compile non-executable and persisted-keyframe
Goto on the Dry Run/Fake gateway path. Goto read/recovery/check/submit is linearized
against autosave, and the God-Object findings are closed by bounded backend collaborators
and composed frontend sessions. The final response must still include the exact user-required statement
after later Stages and final isolation verification. Stage 7's 432-test backend gate,
focused 34-test Vision core/Follow/API selection, 190-test frontend gate, focused 16-test
Vision selection, desktop/mobile browser evidence, and independent audit P1=0/P2=0 used
only Synthetic/Dry Run/Fake paths. OpenCV is absent, no camera was opened/enumerated,
and all Vision motion entered the shared safety gateway. A Stage pass does not imply a later
or final pass.

The autonomous task must stop and report if a test opens a serial port or camera, a
default gate cannot remain closed, an adapter import accesses hardware, migration risks
destructive data loss, the one safety entry point cannot be preserved, or sensitive data
enters a prepared commit.
