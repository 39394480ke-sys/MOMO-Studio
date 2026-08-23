# MOMO Studio v1 Autonomous Completion Report

- Repository: `/Users/ke/Library/Mobile Documents/com~apple~CloudDocs/Code/MOMO-Studio`
- Task starting commit: `32d0163431e229cb3c2e01a285e7e851124ce9c1`
- Working branch: `codex/v1-autonomous-completion`
- Report status: **LIVE — Stage 3 complete; Stages 4-8 pending**
- Final commit: Pending
- Remote branch: Pending
- Draft PR: Pending

This is the cumulative evidence ledger for the Stage 3-8 autonomous task. It is updated
after each Stage implementation and again after final verification. `Pending` means the
operation has not yet been truthfully recorded; it never means pass.

## Stage ledger

| Stage | Starting commit | Ending commit | Status | Tests | Browser verification | Safety verification | Known limitations |
|---|---|---|---|---|---|---|---|
| 3 - Kinematics and Control | `32d0163431e229cb3c2e01a285e7e851124ce9c1` | Recorded by the next update after commit creation | Complete | Pass: backend 226; frontend 54 | Pass | Pass | Provisional Dry Run kinematics; no physical authority |
| 4 - Library | Pending | Pending | Not started | Pending | Pending | Pending | Depends on Stage 3 gate |
| 5 - Trajectory and Playback | Pending | Pending | Not started | Pending | Pending | Pending | Depends on Stage 4 gate |
| 6 - Studio | Pending | Pending | Not started | Pending | Pending | Pending | Depends on Stage 5 gate |
| 7 - Vision Following | Pending | Pending | Not started | Pending | Pending | Pending | Synthetic/default only; live camera separately gated |
| 8 - Release Hardening | Pending | Pending | Not started | Pending | Pending | Pending | Real field acceptance remains required |

## Commit ledger

| Scope | Commit | Subject | Branch/remote state |
|---|---|---|---|
| Stage 1 | `961d5d522ddc6205a3feb480630eb6bbc1ac652e` | `chore: establish MOMO Studio foundation` | Existing baseline |
| Stage 2 | `32d0163431e229cb3c2e01a285e7e851124ce9c1` | `feat: establish dry-run robot core and safety foundation` | Existing baseline / `origin/main` |
| Stage 3 | Recorded after containing commit creation | `feat: add dry-run kinematics and safe motion control` | Local Stage commit packaging follows this report; no push claimed here |
| Stage 4 | Pending | `feat: add pose and motion library workflows` | Pending |
| Stage 5 | Pending | `feat: add trajectory compiler and playback engine` | Pending |
| Stage 6 | Pending | `feat: add studio timeline authoring` | Pending |
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

Every later Goto, Playback, Studio preview, Vision Follow, and Real command must reuse
the Stage 3 gateway and command ownership model. API routes never import raw drivers.
Hardware and camera factories remain deny-by-default and side-effect-free until their
complete authorization evidence is present.

## Domain evolution ledger

| Stage | Domain/contracts | Status |
|---|---|---|
| 1 | Robot variants, immutable Joint/TCP/Pose Snapshot/Pose/Motion/keyframe contracts | Complete baseline |
| 2 | Profile/Calibration/fingerprints, logical/raw mapping, Active Robot runtime/status | Complete baseline |
| 3 | Kinematics model/fingerprint/results, command/preflight/status, Jog lease | Complete |
| 4 | Repository results, capture consistency, import/conversion reports | Pending |
| 5 | PreparedTrajectory, compiler/preflight digest, playback session/status | Pending |
| 6 | Draft/timeline/undo/autosave contracts | Pending |
| 7 | Frame/box/selection/detection/tracking/follow/lease/capability contracts | Pending |
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

Stage 4-8 routes will be appended from the actual completed application. No table entry
authorizes a route before route enumeration and tests confirm it. No API may accept an
arbitrary server path, Python code, raw register/address, driver selector, auto-scan, or
hidden Real override.

## WebSocket and stream inventory

| Path | Direction/payload | Safety/resource contract | State |
|---|---|---|---|
| `/api/v1/ws/robot` | Server-to-client Robot/FK/latest-command/sequence; safe errors are embedded, with no separate fault-list field | Read-only; fixed 10 Hz source cap; no application queue; one-second send timeout; 1.5-second/15-frame silent-socket watchdog; REST fallback | Stage 3 verified |
| Vision metadata socket | Pending exact path | Follow Lease ownership, bounded rate, LAN auth | Stage 7 Pending |
| Vision local stream | Pending exact path | FPS/resolution/queue caps, no recording, disconnect cleanup, LAN auth | Stage 7 Pending |

No WebSocket is a raw or alternate motion-control transport.

## Schema inventory

| Artifact | Model | Current state |
|---|---|---|
| `docs/schemas/pose.schema.json` | Pose | Stage 1 baseline |
| `docs/schemas/motion.schema.json` | Motion | Stage 1 baseline |
| `docs/schemas/robot-profile.schema.json` | RobotProfile | Stage 2 baseline |
| `docs/schemas/calibration.schema.json` | CalibrationDocument | Stage 2 baseline |
| `docs/schemas/robot-status.schema.json` | RobotStatus | Stage 2 baseline |
| `docs/schemas/runtime-state.schema.json` | RuntimeState | Stage 2 baseline |
| `docs/schemas/kinematics-model.schema.json` | KinematicsModel schema `1.0.0` | Present; consecutive generation byte-identical |
| Later Stage schemas | Library/trajectory/draft/vision/backup as applicable | Pending |

Stage 3 schema deterministic-generation evidence: **PASS**. Later schema artifacts remain
subject to their own Stage gates.

## Data directories and exclusion policy

| Location | Purpose | Git policy |
|---|---|---|
| `robot_profiles/` | Reviewed V1/V2 Profile examples | Tracked examples only |
| `calibration/examples/` | Synthetic template Calibration | Tracked examples only; never Real |
| `kinematics_models/` | Provisional mesh-free Dry Run models | Tracked reviewed documents |
| `data/runtime/` | Active Dry Run runtime state | Ignored |
| `data/poses/` | Future user Pose entities by UUID | Ignored runtime data |
| `data/motions/` | Future user Motion entities by UUID | Ignored runtime data |
| Draft/audit/backup locations | Future operational data | Pending design; ignored by default |
| `config/local*`, local Calibration/Profile | Device/operator-local state | Ignored; default settings loading does not read it; explicit caller opt-in only |

Tokens, serial ports, secrets, runtime connections, logs, real Calibration, camera paths,
and unselected device data never belong in a config-free backup or Git.

## Third-party dependency ledger

| Dependency/artifact | Use | License/provenance state | Stage |
|---|---|---|---|
| Existing Python/JS lock dependencies | Backend/frontend foundation | Notices current for Stage 3; npm production audit found 0 vulnerabilities and locked Python runtime audit found no known vulnerabilities; final release-time review remains required | 1-3 |
| NumPy | Mesh-free FK/IK numerical math | Lock resolves `2.4.6` for Python <3.12 and `2.5.2` for Python >=3.12; installed Python 3.11 / NumPy `2.4.6` metadata reports `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`; the 2.5.2 wheel's bundled licenses remain a distribution review item | 3 |
| Optional OpenCV | Tracker/person/face providers only | Not yet added; exact package/model/cascade notices required, no auto-download | 7 |
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
| Action/recording code | Deferred/retired by scope | Stage 4-6 implement new immutable workflows |
| Legacy Vision | Rewrite later | Stage 7 Synthetic-first, no recording/gesture/direct driver |
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
| Backend pytest count | 226 passed | Pending | Pending | Pending | Pending | Pending | Pending |
| Frontend Vitest count | 54 passed / 7 files | Pending | Pending | Pending | Pending | Pending | Pending |
| Ruff | Pass | Pending | Pending | Pending | Pending | Pending | Pending |
| Mypy | Pass / 98 files | Pending | Pending | Pending | Pending | Pending | Pending |
| Ruff format check | Pass / 98 files | Pending | Pending | Pending | Pending | Pending | Pending |
| ESLint | Pass | Pending | Pending | Pending | Pending | Pending | Pending |
| TypeScript | Pass | Pending | Pending | Pending | Pending | Pending | Pending |
| Vite build | Pass / 1,616 modules; JS 242.41 kB (gzip 76.45 kB) | Pending | Pending | Pending | Pending | Pending | Pending |
| Schema determinism | Pass / byte-identical | Pending | Pending | Pending | Pending | Pending | Pending |
| `uv lock --check` | Pass / 38 packages | Pending | Pending | Pending | Pending | Pending | Pending |
| npm audit | Pass / 0 vulnerabilities | Pending | Pending | Pending | Pending | Pending | Pending |
| Python runtime audit | Pass / no known vulnerabilities | Pending | Pending | Pending | Pending | Pending | Pending |
| Hardware isolation | Pass / focused 20-test suite | Pending | Pending | Pending | Pending | Pending | Pending |
| Camera isolation | Pass | Pending | Pending | Pending | Pending | Pending | Pending |
| Browser desktop/mobile/boundary | Pass | Pending | Pending | Pending | Pending | Pending | Pending |
| Console unhandled errors | Pass / `[]` | Pending | Pending | Pending | Pending | Pending | Pending |

Exact commands, counts, versions, durations, failures/fixes, and skipped items are added
only after execution.

## Browser workflow ledger

- Stage 3 Control workflow: Pass — V1/V2, Move Joints, step Jog, Base/Tool Cartesian,
  reachable/unreachable IK, Move Pose, inline Home cancel/confirm, progress/Stop,
  REST fallback, offline disablement, and WebSocket recovery
- Stage 4 Library workflow: Pending
- Stage 5 Playback workflow: Pending
- Stage 6 Studio workflow: Pending
- Stage 7 Synthetic Vision/Follow/Target Lost workflow: Pending
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
| Compiled trajectory sample count/duration | Pending Stage 5 | Pending |
| Draft/undo history | Pending Stage 6 | Pending |
| Vision FPS/resolution/queue/one source/follow | Pending Stage 7 | Pending |
| API body/search bounds | Pending Stage 4/8; no Stage 3 application-level body byte cap documented | Pending |
| One Real Session | Pending Stage 8 | Pending |
| Logs/retries/workers | Pending final inventory | Pending |

## Stage report paths

| Stage | Report |
|---|---|
| 1 | `docs/stage-reports/stage-01-foundation.md` |
| 2 | `docs/stage-reports/stage-02-robot-core.md` |
| 3 | `docs/stage-reports/stage-03-kinematics-and-control.md` |
| 4 | Pending |
| 5 | Pending |
| 6 | Pending |
| 7 | Pending |
| 8 | Pending |

## Unresolved items

1. Create the dedicated Stage 3 commit and record its SHA in the next cumulative update.
2. Execute Stages 4-8 in order without pre-building out-of-scope behavior.
3. Extend resource, route, and schema inventories only from completed later Stages.
4. Repeat dependency/license/vulnerability review for later additions and final release.
5. Run later and final browser/error workflows without unauthorized hardware/camera access.
6. Run final make/lock/audit/isolation commands from the completed branch.
7. Record final branch SHA, clean status, remote branch and Draft PR or exact failure.
8. Keep Real readiness blocked and generate—not execute—field acceptance procedures.

## Git and delivery status

- Current branch: `codex/v1-autonomous-completion`
- `main` modified or merged: **No by task policy; final verification Pending**
- Final worktree status: Pending
- Final commit: Pending
- Six Stage commits present: Pending
- Remote branch URL: Pending
- Draft PR URL/reason: Pending

## Safety evidence status

Stage 3 isolation evidence is complete: all motion verification used Dry Run/Fake
adapters; no forbidden serial/camera/microphone module was loaded or operation performed.
The final response must still include the exact user-required statement after later
Stages and final isolation verification. No Stage 3 pass implies a later or final pass.

The autonomous task must stop and report if a test opens a serial port or camera, a
default gate cannot remain closed, an adapter import accesses hardware, migration risks
destructive data loss, the one safety entry point cannot be preserved, or sensitive data
enters a prepared commit.
