# Stage 03: Kinematics, Dry Run Control, and Unified Motion Safety

- Date: 2026-08-24
- Repository: `/Users/ke/Library/Mobile Documents/com~apple~CloudDocs/Code/MOMO-Studio`
- Branch: `codex/v1-autonomous-completion`
- Status: **COMPLETE — implementation and evidence gate satisfied**
- Containing commit subject: `feat: add dry-run kinematics and safe motion control`

## Summary

Stage 3 adds the first motion-capable product slice while preserving the Stage 2
hardware-isolation boundary. It provides deterministic mesh-free FK/IK, Joint and
Cartesian Dry Run control, Home, command status, renewable hold-to-Jog, and bounded
read-only WebSocket state. Every movement is admitted by one `MotionSafetyGateway` and
executed only by a cancellable in-memory Dry Run executor.

Backend, frontend, schema, dependency, browser, resource-bound, API-isolation, and
hardware/camera-isolation evidence is complete. The exact SHA of the commit containing
this report cannot be written into the commit itself without changing that SHA. Stage 4
and the cumulative report record it after the Stage 3 commit is created. This report
does not claim a clean post-commit worktree, push, or remote branch state before those
operations occur.

## Starting and ending point

- Starting commit: `32d0163431e229cb3c2e01a285e7e851124ce9c1`
- Starting subject: `feat: establish dry-run robot core and safety foundation`
- Starting branch tip matched `origin/main` before Stage 3 changes.
- Stage 3 work remained on `codex/v1-autonomous-completion`; `main` was not modified or
  merged.
- Ending commit subject: `feat: add dry-run kinematics and safe motion control`
- Exact ending SHA: recorded by the next cumulative-report update after commit creation,
  because a commit cannot contain its own SHA.
- Post-commit clean-tree, push, and remote evidence: deliberately not asserted here.

## Legacy evidence boundary

- Read-only source: `MOMO_RobotARM`
- Pinned commit: `ff8bbda0c2222cb57951c7913f7f12f5777b98fa`
- Reviewed tracked areas: Legacy URDF kinematics, Web controller bridge/service,
  continuous joint streaming, safety checker, and V1/V2 Profiles.
- No Legacy program, PyBullet GUI, serial/Servo SDK, camera, device, local Calibration,
  tracked Calibration-backup contents, runtime file, ignored file, or untracked file was
  run or read for Stage 3.
- No URDF, STL, mesh, controller class, hardware driver, or third-party binary was copied.

Detailed observations and dispositions are recorded in
`docs/kinematics-model-audit.md`, `docs/legacy-kinematics-characterization.md`, and
`docs/legacy-migration-map.md`.

## Kinematics model and behavior

Stage 3 uses versioned mesh-free serial-chain documents:

- `kinematics_models/v1.provisional.yaml`
- `kinematics_models/v2.provisional.yaml`

Both record variant/provenance, `PROVISIONAL_DRY_RUN`, base/TCP frames, and ordered joint
type, axis, origin, and SI limits. The deterministic Kinematics fingerprint includes
compatibility-relevant geometry and excludes presentation prose.

- V1 is rail-less and contains exactly J11-J15.
- V2 contains J10-J15, with J10 prismatic.
- Product/UI values are `mm`/`deg`; the kinematics port uses `m`/`rad`.
- Conversion occurs only in named Profile-driven boundary functions, never by a J10
  name branch.
- Quaternions are normalized XYZW.
- Provisional models cannot authorize Real Cartesian motion, Cartesian playback, or
  Real vision follow.

The NumPy adapter implements deterministic homogeneous serial-chain FK for revolute and
prismatic joints with arbitrary axes and origin transforms. IK uses bounded damped least
squares with deterministic seeds, limit projection, adaptive damping, finite-difference
Jacobians, bounded iterations, position-only and full-pose modes, residuals, the best
solution, warnings, and a termination reason. A non-converged best effort is never
dispatched as reachable.

Base and Tool composition remain distinct: Base deltas compose in the base frame; Tool
translation follows current TCP orientation and Tool rotation post-composes locally.
Tests cover known poses, repeatability, round trips, unreachable targets, default and
explicit seeds, limits, quaternion normalization, units, V1/V2 membership, and Base/Tool
composition.

## Unified motion gateway and executor

The command domain defines explicit payloads for Move Joints, Joint Jog Step, Continuous
Jog, Base/Tool Cartesian Jog, Move Pose, and Home. Commands carry robot ID, source,
issued time, expected state sequence, Profile/Kinematics fingerprints, speed scale,
typed payload, explicit units, and an idempotency key.

Every source enters the single `MotionSafetyGateway`. Its preflight checks:

1. active, connected Dry Run identity and disabled hardware policy;
2. current expected sequence and fresh observed state;
3. exact Profile/Kinematics fingerprints and enabled joints/units;
4. finite logical values and provisional dynamic/workspace/path limits;
5. compatible-Calibration raw-derived limits, or an explicit Dry Run logical-only
   fallback when Calibration is absent;
6. finite FK and successful within-tolerance IK for Cartesian requests;
7. target delta, ownership, conflict, idempotency, lifecycle epoch, and cancellation.

Freshness is computed from the monotonic age of the last successful high-level Dry Run
driver observation. The UTC `updated_at` field is for display and persistence only; wall
clock movement cannot make a failed observation appear fresh. A stale read gets one
bounded high-level refresh attempt with a 0.25-second timeout. Failure or timeout remains
stale and fails closed.

The `DryRunMotionExecutor` accepts prepared values only, owns one task, schedules against
absolute monotonic deadlines, interpolates with smoothstep, skips missed ticks instead
of accumulating drift, advances runtime sequence, persists compatible logical state,
and cancels or faults without hardware access. Stop sets cancellation before requesting
the Dry Run stop operation and remains callable while ordinary admission is in flight.
Executor, persistence, lifecycle, cancellation, sequence, missed-tick, clock-failure,
fault, conflict, and no-real-sleep behavior are covered by tests.

## Jog deadman and status transport

Continuous Jog is a renewable backend lease:

```text
start -> jog_session_id
heartbeat -> renew bounded TTL
stop -> cancel immediately
expiry/network loss -> backend cancellation
```

Pointer release/cancel, blur, visibility loss, network loss, unmount, and route teardown
request Stop; backend lease expiry is the independent fail-safe. Duplicate Stop is
idempotent, and a lease cannot coexist with another motion owner. Tests cover expiry,
heartbeat, conflicts, cancellation races, repeated Stop, and frontend deadman events.

`WS /api/v1/ws/robot` is server-to-client only. It publishes RobotStatus, safe last
error, FK/TCP, latest command status/progress/error, sequence, and
`hardware_accessed=false`. It has a fixed 10 Hz source cap, no application queue, and a
one-second send timeout per client. It accepts no command or raw input. Rate, slow-client,
disconnect cleanup, terminal-state delivery, and REST fallback behavior are tested.
A 1.5-second watchdog (15 missed 10 Hz frames) clears a silent socket snapshot, closes
the stale connection, and enters bounded REST/reconnect behavior; only a valid complete
frame resets the timer.

## Complete API inventory

The generated application inventory contains these routes:

| Method | Path | Normal success |
|---|---|---:|
| GET | `/api/v1/health` | 200 |
| GET | `/api/v1/meta` | 200 |
| GET | `/api/v1/meta/product-scope` | 200 |
| GET | `/api/v1/robot` | 200 |
| GET | `/api/v1/robot/profile` | 200 |
| GET | `/api/v1/robot/diagnostics` | 200 |
| POST | `/api/v1/robot/connect` | 200 |
| POST | `/api/v1/robot/disconnect` | 200 |
| POST | `/api/v1/robot/stop` | 200 |
| PUT | `/api/v1/robot/variant` | 200 |
| GET | `/api/v1/calibration/status` | 200 |
| GET | `/api/v1/robot/fk` | 200 |
| POST | `/api/v1/kinematics/ik` | 200 |
| POST | `/api/v1/motion/joints` | 202 |
| POST | `/api/v1/motion/jog-step` | 202 |
| POST | `/api/v1/motion/cartesian-jog` | 202 |
| POST | `/api/v1/motion/pose` | 202 |
| POST | `/api/v1/motion/home` | 202 |
| POST | `/api/v1/motion/jog/start` | 202 |
| POST | `/api/v1/motion/jog/{session_id}/heartbeat` | 200 |
| POST | `/api/v1/motion/jog/{session_id}/stop` | 200 |
| GET | `/api/v1/motion/commands/{command_id}` | 200 |
| POST | `/api/v1/motion/stop` | 200 |
| WS | `/api/v1/ws/robot` | accepted socket |

Route enumeration and isolation tests prove that routes import application services,
not raw drivers. No route accepts raw Servo values, a driver/Real-mode selector, serial
port, register/address, arbitrary filesystem path, or Python expression. Structured
validation rejects absent/wrong units, non-finite numbers, invalid booleans, stale
sequences, mismatched fingerprints, unknown joints, limits, conflicts, and unreachable
IK without dispatch.

## Resource bounds

| Resource | Verified bound |
|---|---|
| Speed scale | `0.05`-`1.0` |
| Effective command duration | `0.1`-`60` seconds |
| Motion update rate | 25 Hz default; configurable 20-100 Hz |
| Motion ownership/history | One active task; 256 retained command statuses; no waiting queue |
| Admission idempotency | 512 retained idempotency records |
| Continuous Jog request speed | At least `0.1`; capped by per-unit continuous limits |
| Continuous Jog maximum | 45 deg/s revolute; 100 mm/s prismatic |
| Jog lease | 400 ms default; configurable 250-500 ms; 256 retained sessions |
| State freshness | 5-second monotonic observation-age limit; 0.25-second refresh timeout |
| Workspace | X/Y `-750..750` mm; Z `-500..750` mm |
| Per-command target delta | 120 deg revolute; 150 mm prismatic |
| Path safety sample spacing | At most 5 deg revolute or 10 mm prismatic |
| Smoothstep peak speed | 90 deg/s revolute; 100 mm/s prismatic |
| Smoothstep acceleration | 720 deg/s² revolute; 800 mm/s² prismatic |
| WebSocket | 10 Hz source cap; no application queue; one-second send timeout |

The resource regressions cover rate, duration, histories, command conflict, lease expiry,
path midpoint sampling, dynamic envelopes, and bounded failure behavior.

## Frontend and browser acceptance

The Control workspace is backend-driven and includes connected/offline/stale/busy state,
always-visible Stop, variant-specific Joint controls, TCP/XYZ/RPY, Base/Tool Cartesian
controls, IK, Move Pose, Home confirmation, accepted preflight evidence, progress, and
safe structured errors. V1 renders exactly J11-J15 with no J10; V2 renders J10 in `mm`
and J11-J15 in `deg`.

Live browser acceptance exercised:

- connected V2 and V1, including the exact variant joint/unit presentation;
- Move Joints and step Jog;
- Base and Tool Cartesian Jog;
- converged and unreachable IK results;
- Move Pose;
- inline Home cancel and confirm;
- command progress and Stop from `RUNNING 2%` to `CANCELLED 2%`;
- backend-unavailable REST-fallback state with every motion action, including Stop,
  disabled;
- WebSocket recovery after transport availability returned.

Component regressions additionally cover hold-Jog pointer release/cancel, blur,
visibility, unmount, network-loss/TTL cleanup, and WebSocket-close REST polling with
fresh-sequence recovery.

The first live run correctly fell back to REST but exposed a missing Vite WebSocket
proxy. Browser-led fixes added the proxy, made repeated preflight names use stable unique
render keys, changed accepted evidence wording to truthful positive statements, replaced
blocking native Home confirmation with an inline confirmation, contained status-header
overflow, locked motion during lifecycle actions, enforced the 0.1-second duration
minimum, and made bootstrap single-flight/generation-aware with a 900 ms timeout.

Recorded viewport evidence:

- screenshots at 1440×960 and 390×844;
- width checks at 1201, 1200, 981, 980, 841, 840, and 390 pixels;
- no horizontal overflow at any checked size;
- final browser console errors/warnings: `[]`.

## Commands and results

| Check | Result |
|---|---|
| `make test` | PASS — backend 226 passed; frontend 54 passed in 7 files |
| `make lint` | PASS — Ruff; strict mypy over 98 source files; ESLint; TypeScript |
| `make format-check` | PASS — all 98 Python files formatted |
| `make build` | PASS — Vite built 1,616 modules; index 0.56 kB (gzip 0.34 kB), CSS 21.86 kB (gzip 5.15 kB), JS 242.41 kB (gzip 76.45 kB) |
| `make schemas` twice | PASS — consecutive generated artifacts were byte-identical |
| `uv lock --check --project backend` | PASS — 38 packages resolved |
| `npm --prefix frontend audit --omit=dev --audit-level=moderate` | PASS — 0 vulnerabilities |
| Python `pip-audit` of locked runtime export | PASS — no known vulnerabilities found |
| `git diff --check` | PASS |
| Focused route/import/hardware isolation | PASS — 20 tests |
| Targeted independent API/WebSocket review suite | PASS — 67 tests |
| Independent read-only review | PASS — no actionable P1/P2 findings |

The only test-suite warning is Starlette `TestClient`'s httpx deprecation warning. The
Python audit also normalized an invalid legacy package-metadata specifier while parsing;
it still completed with no known vulnerability finding.

NumPy is lock-resolved as `2.4.6` for Python below 3.12 and `2.5.2` for Python 3.12 and
newer. The verified Python 3.11 environment installed `2.4.6`; its aggregate license
metadata is recorded in `THIRD_PARTY_NOTICES.md`. The 2.5.2 wheel's bundled license
files remain a downstream distribution review item, not a Stage 3 code gate.

## Hardware, camera, and microphone isolation

- App creation and every command used only Dry Run/Fake adapters.
- The focused isolation/API suite passed all 20 tests.
- No `serial`, `cv2`, RealSense, Feetech, `scservo`, or `pyaudio` module was loaded.
- No serial port/device enumeration, Servo scan/register/torque/Home/movement operation,
  camera open/enumeration, or microphone open occurred.
- Status, FK, command status, Stop, diagnostics, lifecycle, and WebSocket contracts that
  carry hardware evidence report `hardware_accessed=false`; raw positions remain absent.
- The generated route inventory contains no Real/raw/file/code bypass.
- The pinned Legacy checkout and all excluded ignored/local data remained untouched.

All Stage 3 motion verification used Dry Run or Fake adapters.

## Known limitations

- Both models and their geometry/dynamic/workspace parameters are provisional software
  characterization, not physically verified robot truth.
- V1 rail removal is a product-correct reconstruction, not an authoritative measured V1
  model.
- Successful Dry Run FK/IK does not establish physical reachability. There is no mesh,
  self-collision, environment-collision, or swept-volume checker.
- Cartesian Jog and Move Pose solve endpoint IK and then interpolate joints; they do not
  promise a Cartesian-linear TCP path.
- Command, idempotency, and Jog histories are bounded in memory and reset on restart.
- The WebSocket is a local unauthenticated status channel; authenticated LAN transport
  remains later scope.
- No application-level HTTP request-body byte limit beyond server/framework behavior is
  documented in Stage 3.
- Dry Run Stop is not a physical emergency stop.
- Real hardware, Calibration writes, Pose/Motion CRUD, playback, Studio, Vision, LAN,
  packaging, and physical/field acceptance remain unavailable.

## Stage transition gate

The Stage 3 implementation and evidence gate is **COMPLETE / GREEN**. Stage 4 may begin
after the dedicated Stage 3 commit is created and its SHA is recorded by the next report
update. All later motion sources must reuse the Stage 3 gateway and ownership model.
