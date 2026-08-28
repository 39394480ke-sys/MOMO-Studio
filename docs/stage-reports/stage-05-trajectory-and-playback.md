# Stage 05: Trajectory compiler and playback engine

- Date: 2026-08-24
- Repository: `/Users/ke/Library/Mobile Documents/com~apple~CloudDocs/Code/MOMO-Studio`
- Branch: `codex/v1-autonomous-completion`
- Status: **GREEN / COMPLETE — final gates PASS**
- Starting commit: `837369a0e3c43b756dfbaacc3bd21e5b1ae13d3b`
- Dedicated containing commit subject: `feat: add trajectory compiler and playback engine`

## Summary

Stage 5 converts a stored Motion revision into one deterministic, immutable, fully
preflighted Dry Run trajectory. Joint interpolation, explicit holds, and true TCP-space
Cartesian-linear interpolation share one bounded compiler. A successful preflight
returns a SHA-256 digest bound to the exact prepared samples; preview and playback use
that same in-memory object and never compile a substitute.

Playback has an explicit lifecycle, monotonic absolute-deadline scheduling, pause/resume,
bounded rate and closed-loop controls, progress reporting, and highest-priority Stop.
Fresh Motion, Profile, Kinematics, state, connection, freshness, policy, and ownership
evidence is revalidated through the existing Motion Safety Gateway immediately before
execution. The implementation remains strictly Dry Run: it has no ServoBus, serial,
camera, raw-register, or client-supplied sample path.

The root gate passes 352 backend and 85 frontend tests. Ruff, strict mypy, Ruff format,
ESLint, TypeScript, Vite build, schema determinism, lock checks, production npm audit,
focused 128-test isolation/integration coverage, and `git diff --check` pass. Browser
acceptance passed the Stage 5 workflow at desktop and mobile/breakpoint layouts with no
horizontal overflow and no console warnings/errors.

The exact ending SHA and pushed state are recorded by Stage 6 after this dedicated
commit exists. A commit cannot truthfully contain its own SHA.

## Legacy evidence boundary

Stage 5 characterized only tracked text from the pinned Legacy commit
`ff8bbda0c2222cb57951c7913f7f12f5777b98fa`, obtained with `git show`:

- `仿真控制系统/动作播放器_action_player.py`;
- `动作录制与回放增强/动作回放器_sequence_player.py`;
- `动作录制与回放增强/动作插值器_motion_interpolator.py`.

Observed facts include synchronous wall-clock sleeps, mutable pause/stop flags, direct
controller/file coupling, ordered Joint arrays, J10 unit guessing, and raw/multi-turn
state. Those facts informed retirement and rewrite decisions only. No Legacy program,
driver, SDK, Motion, numeric sample, local Calibration, runtime data, ignored/untracked
file, asset, camera path, or operator data was executed, opened, or copied.

## Domain and compiler

Stage 5 adds immutable `TrajectoryPlan`, `TrajectorySegment`, `TrajectorySample`,
`TrajectoryDigest`, `TrajectoryPreflightReport`, `TrajectoryViolation`, and
`PreparedTrajectory` contracts. The semantic SHA-256 digest covers Motion UUID/revision,
variant, Profile/Kinematics fingerprints, start-state sequence, sampling parameters,
segments, and every unit-bearing domain sample. Only `compiled_at` is excluded. Domain
validation recomputes and rejects a forged digest.

The first active state must already equal the first embedded keyframe within `1e-6`;
there is no implicit entry move. Joint segments support `LINEAR`, cubic `SMOOTHSTEP`,
and quintic `EASE_IN_OUT`. Holds are explicit stationary segments. Adjacent segments
share one boundary, times increase strictly, and the final sample is at exact duration.

`CARTESIAN_LINEAR` interpolates TCP position linearly and orientation with shortest-path
normalized quaternion SLERP. Every intermediate point uses IK seeded from the preceding
accepted solution, followed by FK verification, logical and applicable raw-derived
limits, workspace, residual, continuity, velocity, and acceleration checks. Any failure
rejects the whole trajectory; Cartesian never falls back to Joint interpolation.

Detailed semantics and exact limits are in `docs/trajectory-semantics.md`. The principal
resource bounds are:

| Resource | Bound |
|---|---:|
| HTTP sample rate | 5-50 Hz; default 20 Hz |
| Compiler defensive sample rate | 1-100 Hz |
| Duration | 600 seconds |
| Samples | 20,000 |
| Segments | 2,000 |
| Prepared cache | 16 exact plans |
| Preview | 1,000 selected points per path/series |
| Playback rate | 0.25-2.0x |
| Loop traversals | 100, closed trajectories only |

## Prepared identity and safety admission

`TrajectoryApplicationService` owns the bounded process-local LRU and all preflight
generation/cancellation. A new preflight invalidates older prepared values for that
Motion. Lifecycle Stop cancels compilation cooperatively and rejects late results.
Restart or cache eviction requires preflight again.

Play accepts the Motion UUID, expected revision, digest, loop flag, and rate only. The
service resolves the exact cached `PreparedTrajectory`, verifies identity, reloads the
Motion revision, creates explicit `PLAYBACK` operator intent, and asks the shared
gateway for fresh execution evidence. The gateway verifies prepared bindings,
connection/freshness, stop capability, `DRY_RUN`, disabled hardware, provisional Real
block, and the shared ordinary/playback motion slot. A final ordinary-motion dispatch
check closes the reciprocal admission race. API routes never import a driver or accept
raw/sample arrays.

## Playback engine

The lifecycle is:

```text
IDLE -> PREFLIGHTING -> READY -> PLAYING
                                 |  |
                                 |  +-> PAUSED -> PLAYING
                                 +----> STOPPING -> STOPPED
                                 +----> COMPLETED
                                 +----> FAULTED
```

An injected monotonic Clock and absolute deadlines prevent cumulative relative-sleep
drift. If processing is late, the runner advances to the current logical sample rather
than applying an overdue burst. Pause is acknowledged at a sample boundary; resume and
rate changes rebase logical time. Looping requires exact endpoint closure, skips the
duplicate boundary application, is capped, and remains cancellable. Stop cancels
validation, sleep, paused waits, state application, compilation, or looping and flushes
the high-level Dry Run state sink.

Playback events use a synchronous latest-value observer with no queue. REST is the
frontend control/status surface; the existing read-only robot WebSocket also publishes
the latest typed playback status and still accepts no command.

## API surface

Stage 5 adds nine method/path combinations:

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/motions/{motion_id}/preflight` | Compile and return whole-plan checks/violations and digest |
| POST | `/api/v1/motions/{motion_id}/play` | Execute the exact revision/digest-bound prepared plan |
| POST | `/api/v1/playback/pause` | Acknowledge pause at a sample boundary |
| POST | `/api/v1/playback/resume` | Resume with rebased monotonic timing |
| POST | `/api/v1/playback/stop` | Highest-priority playback/preflight Stop |
| PUT | `/api/v1/playback/rate` | Set bounded playback rate |
| PUT | `/api/v1/playback/loop` | Enable/disable bounded closed-loop playback |
| GET | `/api/v1/playback` | Read current bounded playback status |
| GET | `/api/v1/trajectory/{digest}/preview` | Read a bounded preview of the exact prepared plan |

Executed OpenAPI enumeration contains 46 HTTP method/path combinations across 40
unique HTTP paths, plus `/api/v1/ws/robot`. Stage 5 responses keep
`hardware_accessed=false`, `real_motion_ready=false`, and
`field_acceptance_ready=false` where those fields apply.

## Library UI and browser acceptance

Motion cards now enter a revision-bound playback workspace. The panel presents
Preflight, structured checks/violations, digest, duration/sample/segment evidence,
preview, Play/Pause/Resume/Stop, five bounded rate choices, loop, progress, elapsed time,
current keyframe/segment/sample, and safe fault text. Active playback locks conflicting
Library mutations while retaining an online Stop; status polling continues across tabs
so a completed session releases the lock. Offline, disconnected,
stale, busy, missing-preflight, stale-revision, and backend-error states fail closed.

The preview renders responsive bounded SVG Joint-versus-time traces, TCP top-view/path
summary, segment types, and keyframe markers. Client decoding defensively caps 32 Joint
series, 20,000 points, and 2,000 segments; rendering samples at most 600 points per
trace. It never derives executable interpolation.

Browser verification used an isolated backend and temporary operational data. At
desktop 1440 x 960 it created two synthetic Dry Run Poses and a Cartesian Motion,
preflighted all 31 checks into 41 samples at 20 Hz, opened the digest preview, played at
0.25x with loop, observed progress, paused, resumed, and stopped. Playback and preflight
reported `hardware_accessed=false`. Mobile/breakpoint verification confirmed collapsed
one-column preview, bounded two-column controls/metrics, wrapped long content, and no
page-level horizontal overflow. Console warnings/errors were `[]`. Temporary fixtures
were removed through a recoverable Trash operation.

## Independent audit and fix closure

Independent read-only audit examined compiler/application ownership, prepared-plan
identity, scheduler timing, safe errors, REST/WebSocket isolation, and frontend state.
The initial pass found no P1 issue and eight actionable P2 issues:

1. CPU-only sampled kinematics did not yield, delaying lifecycle Stop until compilation
   finished;
2. concurrent preflights had no single latest-generation owner;
3. synchronous preview could touch the LRU from a FastAPI worker thread while preflight
   mutated it on the event loop;
4. runtime exception text could enter public playback status and the state sink;
5. repeated rate changes rebased from the last emitted sample and accumulated phase
   loss;
6. switching to the Poses tab stopped polling and could retain a stale Library lock;
7. a healthy poll immediately erased an actionable command rejection;
8. Play/rate/loop/Stop availability did not exactly follow PREFLIGHTING/STOPPING state.

All eight were fixed. Re-review then found two additional P2 admission races: ordinary
motion and playback could each pass a non-atomic final check before claiming separate
executors, and a locally captured prepared object could resume after a newer failed
preflight evicted it. Both now use one gateway-owned atomic admission coordinator.
Prepared identity and preflight generation are rechecked after every Play await boundary.

A second re-review found two further lifecycle P2 issues: a preflight starting after the
trajectory cancellation hook could overtake an unfinished global Stop, and cancellation
of the caller awaiting playback Stop could strand the state and motion slot in
`STOPPING`. The shared coordinator now also owns the lifecycle epoch/count fence for
ordinary submissions, preflight, and Play. Playback Stop has one shielded cleanup owner,
and every later Stop joins that same completion task until state-sink flush and terminal
publication finish.

The final interleaving review found one more P2 at the point where preflight had already
published `PREFLIGHTING` but an awaited claim returned after lifecycle Stop changed the
epoch. That cancellation was briefly mapped to `FAULTED`. Every lifecycle recheck after
preflight claim now performs idempotent playback Stop before propagating the structured
epoch conflict, so the lifecycle outcome remains `STOPPED`.

The next reciprocal review found two P2 gaps: ordinary executor submission lacked a
post-await lifecycle fence/rollback, and canceling the first global Stop caller could
interrupt hook iteration before trajectory cancellation. Ordinary submit now rechecks
the epoch after executor claim and cancels that exact command before returning conflict.
Global Stop now has one shielded completion owner, so caller cancellation cannot abort
ordinary/Jog/trajectory hooks and repeated Stop joins the same operation.

The last independent boundary audit found one P2 Motion-revision TOCTOU between the
validator's repository read and the later `PLAYING` claim. Library Motion mutations now
share one process-local lock with an exact revision lease held through fresh repository
read, gateway validation, and the `PLAYING` transition. Update or deletion therefore
linearizes entirely before validation (and rejects the stale plan) or after execution
has atomically claimed the reviewed immutable plan.

New regressions cover production serial-chain cancellation before acceptance, serialized latest-generation preflight with stale-result exclusion, preview
event-loop affinity, sanitized HTTP/WebSocket/sink faults, repeated-rate integrated
timing, cross-tab completion, durable dismissible errors, lifecycle-exact controls, and
priority Stop superseding an in-flight preflight, reciprocal ordinary/playback admission,
preflight versus delayed ordinary submission, evicted-digest rejection, post-hook global
Stop fencing, cancellation-safe Stop completion/retry, and mid-claim lifecycle Stop
precedence over generic preflight failure, ordinary post-submit rollback, and
cancellation-safe global Stop hook completion, plus Motion update/delete fencing through
the execution claim. Final independent re-review passes **P1=0/P2=0**.

## Commands and results

| Check | Result |
|---|---|
| Backend pytest | PASS — 352 passed; one known Starlette `TestClient`/httpx2 deprecation warning |
| Frontend Vitest | PASS — 85 passed across 8 files |
| Focused Stage 2-5 isolation/integration suite | PASS — 128 passed |
| Independent audit | PASS — P1=0/P2=0 |
| Ruff | PASS |
| Strict mypy | PASS — 125 source files |
| Ruff format check | PASS — 125 files |
| ESLint | PASS — zero findings |
| TypeScript | PASS |
| Vite build | PASS — 1,624 modules; CSS 40.70 kB (8.59 gzip); JS 305.54 kB (91.97 gzip) |
| Schema determinism | PASS — two fresh directories byte-identical and equal to tracked artifacts |
| `uv lock --check` | PASS — 44 packages resolved |
| npm production audit | PASS — zero vulnerabilities |
| Python locked-runtime audit | PASS — no known vulnerabilities |
| `git diff --check` | PASS |
| Browser desktop/mobile/boundary | PASS — Dry Run only; no overflow; console `[]` |

No runtime dependency was added in Stage 5. Existing lockfiles therefore remain
unchanged. Trajectory and playback are ephemeral domain contracts, not new persisted
user schemas; the seven existing generated JSON Schemas remain byte-identical to two
fresh generations.

## Known limitations

- The prepared cache, playback state, and latest-value observer are process-local; one
  backend process is supported.
- Prepared plans disappear on restart/eviction and must be re-preflighted.
- The frontend polls playback status every 750 ms rather than consuming the WebSocket
  field; the socket nevertheless exposes the typed latest value.
- Sample rate uses the backend default in the current UI.
- SVG traces normalize each Joint independently and display its range in the legend;
  they are review aids, not metrology.
- Provisional dynamics, workspace, Profile, Calibration, and Kinematics values authorize
  only Dry Run. Real playback and physical accuracy remain blocked pending Stage 8 and
  field acceptance.
- Studio draft/timeline authoring is Stage 6.

## Safety statement

No serial port was opened.
No serial device enumeration was performed.
No servo scan was performed.
No servo register was read.
No servo register was written.
No torque command was sent.
No real Home command was sent.
No real motion command was sent.
No real calibration was read or modified.
No physical robot was moved.
No real camera was opened.
No camera enumeration was performed.
No microphone was opened.
All autonomous motion verification used Dry Run or Fake adapters.
Real-hardware field acceptance remains required.
