# Architecture

## Context and current Stage

MOMO Studio is web-first and local-first. React supplies one operator UI that can run
in a browser now and may be wrapped by Tauri later. FastAPI owns transport concerns and
delegates use cases to application services. Domain code expresses product, kinematics,
and safety invariants without importing the web framework or a hardware SDK.

Stage 2 established one Active Robot, Profile/Calibration diagnostics, an in-memory Dry
Run driver, and atomic runtime state. Stage 3 adds Dry Run kinematics and control. Stage
4 adds Pose/Motion persistence and Library workflows. Stage 5 adds deterministic
whole-path trajectory compilation, immutable prepared-plan identity, preview, and
bounded Dry Run playback. Stage 6 Studio implementation is green across backend,
frontend, isolated browser acceptance, and final integrated audit P1=0/P2=0. Its
dedicated commit/push delivery remains open. Vision and Real hardware remain outside
the current boundary.

```text
React Control workspace
  -> versioned REST commands and REST status fallback
  -> bounded read-only RobotStatus WebSocket
      -> FastAPI routes and transport schemas
          -> Robot lifecycle / Kinematics / Motion application services
              -> MotionSafetyGateway (the only motion admission point)
                  -> preflight and prepared Dry Run work
                      -> DryRunMotionExecutor
                          -> primary RobotRuntime + atomic runtime-state repository
              -> Kinematics port
                  -> mesh-free serial-chain adapter
                      -> provisional V1/V2 model documents

React Library workspace
  -> bounded Pose/Motion REST DTOs (never server paths)
      -> LibraryApplicationService
          -> Pose/Motion repository ports
              -> UUID-only atomic JSON adapters
          -> coherent Capture via Robot + Kinematics services
          -> Goto as LIBRARY / MOVE_JOINTS
              -> Motion application service -> MotionSafetyGateway

  -> Motion preflight / preview / playback
      -> TrajectoryApplicationService
          -> TrajectoryCompiler -> immutable PreparedTrajectory + digest
          -> bounded process-local prepared-plan cache
          -> PlaybackService -> fresh MotionSafetyGateway validation
              -> high-level Dry Run logical-state sink

React Studio workspace
  -> small workspace composition facade
      -> directed-edge reducer + bounded undo/redo
      -> Draft Session: load/recovery/autosave/validate/compile/formal-save CAS
      -> Motion Session: playback/Goto/shared priority Stop epochs
      -> Pose Insertion Session + Dirty Navigation Guard
  -> bounded Studio REST DTOs
      -> StudioApplicationService: Draft/compile facade + sole Studio lock owner
          -> strict MotionDraft repository
          -> server-owned source provenance + canonical Legacy snapshot trust
          -> backend-only TrajectoryCompiler preview (`executable=false`)
          -> StudioFormalSaveCoordinator (lock-free transaction policy)
              -> fail-closed write-ahead Save/Save As -> Library revision lease
              -> exact marker abandon + provenance-preserving conflict fork
          -> StudioRobotActions (lock-free action policy)
              -> coherent Dry Run Capture
              -> persisted-keyframe STUDIO / MOVE_JOINTS
                  -> Motion application service -> MotionSafetyGateway
```

Dependencies point inward toward domain and port contracts. API routes do not import a
driver, executor implementation, serial package, or Legacy controller. The composition
root explicitly injects the Dry Run implementations. There is no module-global robot,
`arm_a` product assumption, Fleet surface, serial adapter, device scan, camera source,
or raw-control transport.

## Active Robot and lifecycle

The application owns one identity-aware runtime:

```text
robot_id = primary
active variant = configured V1 or V2
control mode = DRY_RUN
hardware access = DISABLED
driver/executor = in-memory Dry Run implementations
```

Construction may load reviewed Profile, example Calibration, provisional kinematics,
and compatible untracked Dry Run runtime data. It does not connect, scan, Home,
calibrate, import a Servo SDK, open a serial port, open a camera, or start an unbounded
worker. A persisted connection marker never reconnects after restart.

Lifecycle transitions, variant changes, motion admission, and Stop share explicit
coordination. Only one motion command or Jog lease may own execution at a time. A
variant change remains disconnected-only and replaces the runtime, Profile, and
kinematics context without auto-connecting.

## Kinematics boundary

`kinematics_models/v1.provisional.yaml` and `v2.provisional.yaml` describe ordered,
mesh-free serial chains. Each model records schema version, variant, provenance,
verification status, base/TCP frames, and per-joint type, axis, origin transform, and SI
limits. A deterministic fingerprint covers compatibility-relevant geometry and excludes
presentation prose.

- V1 is exactly `j11`-`j15` and has no J10.
- V2 is exactly `j10`-`j15`; J10 is prismatic.
- Both models are `PROVISIONAL_DRY_RUN`.
- No model, FK result, or successful IK result authorizes Real Cartesian motion.

UI/domain joint values remain keyed maps in `mm` and `deg`; canonical TCP positions are
in `mm` with normalized XYZW quaternions. Named port helpers are the only conversion
boundary to adapter `m` and `rad`. Conversion never branches on the spelling `j10`, and
dictionary order never defines chain order.

The kinematics adapter performs deterministic serial-chain FK and bounded numerical IK.
IK reports success, best solution, iterations, position/orientation residuals,
termination reason, warnings, and the exact kinematics fingerprint. Position-only and
full-pose solves are distinct requests. Base increments compose in the base frame; Tool
increments rotate translation and orientation through the current TCP frame.

## Unified motion path

Every movement source—Joint Move, Joint Jog, Home, Cartesian Jog, Move Pose, Library
Goto, Playback, and Studio Goto, plus later Vision sources—must submit immutable intent
to the same
`MotionSafetyGateway`:

```text
command DTO
  -> source and idempotency ownership
  -> active robot / connected / DRY_RUN policy
  -> expected state sequence and monotonic observation freshness
  -> Profile and Kinematics fingerprints
  -> exact enabled-joint and explicit-unit validation
  -> finite/logical/provisional dynamic limits
  -> compatible-Calibration raw-derived limits, or explicit Dry Run logical-only fallback
  -> workspace, FK, IK residual and reachability checks
  -> conflict and cancellation checks
  -> prepared Dry Run execution
```

Routes cannot construct executor work directly. The gateway returns structured preflight
evidence or a typed rejection. Long operations return `202 Accepted` with a `command_id`;
command status exposes progress, outcome, cancellation, and a safe error code.

Freshness uses the monotonic age of the last successful high-level Dry Run driver
observation. UTC `updated_at` is display/persistence data only. A stale state gets one
bounded high-level observation attempt; failure or timeout remains stale.

Stage 4 permits exactly one additional source/type pair:
`LIBRARY` + `MOVE_JOINTS` for Goto Pose. The Library service validates the persisted
snapshot against the active variant, exact joint/unit set, Profile fingerprint, and
Kinematics fingerprint before submitting it to the normal motion application service.
Repositories never call a driver. Motion creation, duplication, listing, and deletion
are storage operations and do not dispatch movement.

Stage 5 extends the gateway with prepared-trajectory validation. Compilation binds the
Motion revision, variant, Profile/Kinematics fingerprints, start-state sequence, and
complete sampled plan. Playback consumes only the exact cached immutable object whose
digest was returned by preflight, rechecks mutable evidence immediately before
dispatch, and shares the normal motion slot. No API route accepts executable samples.
Stop cancels ordinary motion, trajectory compilation, or playback before lifecycle Stop
proceeds.

A gateway-owned admission coordinator makes the final check-and-claim transition atomic
across ordinary commands, trajectory preflight, and playback. Ordinary dispatch retains
the coordinator through executor submission; playback retains it through runner claim;
preflight claims its lifecycle state only while the shared slot is free. Playback also
rechecks exact prepared-object identity and preflight generation after every asynchronous
boundary, including after runner claim, so an evicted or superseded plan cannot execute.

The coordinator also provides the shared lifecycle epoch/count fence used by ordinary
submission, preflight, and Play. A request cannot start during Stop/Disconnect/Shutdown
or escape an epoch it began before. Playback Stop is completed by one shielded task;
caller cancellation leaves that cleanup running and later Stop calls join it through
runner cancellation, state flush, and terminal publication.

Ordinary dispatch rechecks the lifecycle epoch after awaited executor submission and
cancels that exact claim on mismatch before recording idempotency. Global Stop similarly
uses one shielded completion owner around executor and registered-hook cancellation, so
a disconnected caller cannot truncate the safety operation; another Stop joins it.

Library Motion mutations and execution validation share a process-local revision lock.
The validator holds the exact revision lease through repository read, gateway awaits,
and the `PLAYING` transition, so update/delete and execution have an explicit atomic
ordering. Mutation after the claim cannot alter immutable prepared samples.

Stage 6 adds one persisted-keyframe source/type pair: `STUDIO` + `MOVE_JOINTS`. The
Studio service accepts only Draft/keyframe UUIDs plus the expected Draft revision and
bounded operator intent. It reloads the embedded snapshot, validates the active variant,
exact enabled-joint/unit set, Profile/Kinematics fingerprints, and domain limits, then
submits the high-level command through the ordinary motion service and gateway. A route
cannot submit browser-owned Joint targets for Studio Goto. The sole Studio mutation lock
linearizes Draft read/recovery, revision/keyframe checks, and command submission, so an
autosave cannot replace the persisted target in that interval.

The `DryRunMotionExecutor` uses an injected monotonic clock, absolute deadlines, a fixed
bounded update rate, and a cancellation signal. It interpolates single moves instead of
teleporting state, advances `state_sequence` monotonically, persists compatible runtime
state, and faults closed on executor errors. It performs no raw mapping or hardware I/O.

Stop has priority over ordinary admission: cancellation is set before the Dry Run stop
operation is requested. Later Real Stop semantics must use a separately verified result
contract and cannot inherit a physical-safety claim from Dry Run behavior.

## Continuous Jog deadman

Continuous Jog is a renewable backend lease, not a frontend-only pointer gesture:

```text
start -> jog_session_id and expiry
heartbeat -> bounded lease renewal
stop -> immediate cancellation
expiry -> backend cancellation even after network loss
```

The lease duration is short and bounded. Pointer release/cancel, window blur,
visibility loss, route teardown, and component unmount request Stop; server expiry is the
fail-safe if none arrives. Duplicate Stop is idempotent. A Jog lease cannot coexist with
another active motion command.

## HTTP and WebSocket surface

Stage 2 lifecycle and diagnostic routes remain. Stage 3 adds FK,
IK/reachability, joint move/jog, renewable Jog sessions, Cartesian Jog, Move Pose, Home,
motion Stop, command status, and a robot-status WebSocket. Generated enumeration and
route-isolation tests passed; the exact final inventory is recorded in the Stage report.

Stage 4 adds bounded CRUD routes for `/api/v1/poses` and
`/api/v1/motions`, plus Capture, Duplicate, and Goto subresources. List requests are
page-based, cap a page at 50 entities, bound search and Tag filters, and provide stable
created/updated/name sorting. Lists return bounded Pose/Motion summaries; complete
snapshots/keyframes require one UUID detail request. Updates and deletes carry an
expected revision and return typed conflicts. No route accepts a client disk path.
Executed enumeration records 37 method/path combinations across 31 unique HTTP paths
plus the existing read-only robot WebSocket; the focused 65-test
route/import/hardware-isolation suite passes.

Stage 5 adds Motion preflight/play, playback status/pause/resume/stop/rate/loop, and
digest-bound preview routes. Preflight returns structured checks and violations.
Preview down-samples only for transport and never recompiles; Play accepts only Motion
UUID, expected revision, digest, loop, and bounded rate. The robot WebSocket remains
read-only and now carries typed playback status.

Stage 6 adds bounded `/api/v1/studio` Draft list/create/open/detail/autosave/delete,
exact-revision fork, exact save-intent abandon, validate/compile/Save/Save As, coherent
Capture, and persisted-keyframe Goto routes. Draft compile returns `executable=false`
and never populates the Stage 5 prepared-plan cache. Formal Save uses exact Draft/source
revisions; every revision conflict names the bounded entity scope `MotionDraft` or
`Motion`; no route accepts a client disk path or executable samples. Executed
enumeration records 14 Stage 6 method/path combinations across 11 unique paths and 60
combined combinations across 51 unique HTTP paths, plus the existing read-only
WebSocket.

The WebSocket is read-only. Its payload carries RobotStatus (including its safe last-error
summary), TCP pose/FK, the latest command status/progress/error, state sequence, and
top-level `hardware_accessed=false`; it has no separate fault-list field. The current
implementation has a fixed 10 Hz source cap, no application queue, and a one-second
timeout around each client send. A slow client can therefore block only its own handler,
which exits on timeout or disconnect. It never accepts raw values or motion commands,
and REST remains the status fallback. Dedicated rate, slow-client, terminal-delivery,
disconnect, and REST-fallback tests pass. A 1.5-second watchdog (15 missed 10 Hz frames)
clears a silent socket snapshot, closes the stale socket, and enters bounded
REST/reconnect behavior; only a valid complete frame resets the watchdog.

## Frontend data flow

The Control workspace consumes backend state rather than computing or fabricating robot
state locally. It presents variant-specific Joint controls, TCP and
Cartesian controls, Base/Tool selection, explicit step/speed/duration parameters, IK and
preflight results, command progress, and an always-visible Stop.

V1 never renders J10. V2 renders J10 in `mm`; arm joints use `deg`. Motion controls are
disabled while disconnected, offline, stale, busy, or faulted. Home requires explicit
confirmation. The UI states that software Stop is not a physical emergency stop and
offers no Real selector. REST polling/fetch remains available when the read-only
WebSocket is unavailable.

Stage 3 Control component tests and desktop/mobile/breakpoint browser acceptance pass.
The checked widths have no horizontal overflow and the final browser console is empty.

The Stage 4 Library workspace uses backend entities rather than browser-local files. It
provides POSES and MOTIONS tabs, search/Tag/sort controls, bounded pagination, coherent
Capture, a valid two-snapshot Motion creation path, on-demand full entity details,
duplicate/delete confirmations, and Dry Run Goto confirmation. Motion creation obtains
fresh full snapshots for two selected summaries and verifies their revisions before
submit. A post-delete out-of-range page is clamped and refetched without a false empty
state. Motion cards link into Studio by UUID. Stage 5 adds Preflight, bounded trajectory
charts, digest/violation display, Play, Pause, Resume, Stop, rate, loop, and progress.
Controls follow backend playback state and remain disabled when admission facts are
missing. Offline, stale response, and revision-conflict states fail closed in the
frontend suite. Desktop and exact 390 x 844 mobile browser QA passed with no horizontal
overflow or console warning/error; the Stage report distinguishes tested browser flows
from component/integration-only coverage.

The Stage 6 Studio workspace separates Viewer, Timeline, Inspector, and dialogs. A small
workspace hook composes the pure editor reducer with bounded Draft, Motion, Pose, and
dirty-navigation hooks; revision/generation/CAS state stays cohesive in the Draft
Session, while playback/Goto/priority Stop epochs stay together in the Motion Session.
Segment settings belong to explicit directed adjacencies;
only surviving adjacencies retain settings and newly formed ones receive a visible
default. Draft metadata persists those default markers. Autosave uses full-document CAS
without adding undo history, and late responses are fenced from a newly loaded Draft.
Desktop uses a side Inspector; narrow layouts use a drawer while horizontal scroll stays
inside the Timeline. Structured conflicts fail closed on missing/unknown scope. For an
ordinary Draft or Motion conflict, Save As captures the local document before any
request, recovers the authoritative Draft, exact-revision forks it, PUTs the captured
local content, rebinds the URL, and then saves a fresh Motion; server-owned provenance
never traverses the client. Automated frontend and isolated desktop/mobile browser
acceptance pass, including focus restoration, container-local timeline overflow, and a
real-backend external-Motion conflict with local post-conflict edits retained.

## Configuration and persistence

Safe default loading uses typed defaults, tracked `config/default.yaml`, then `MOMO_*`
environment values. It does **not** probe or read ignored `config/local.yaml`. A caller
may opt in to one specific local file only by explicitly passing `local_config_path` to
the settings loader; that explicit file is then merged before environment overrides.
Throughout Stage 6:

```text
control_mode: DRY_RUN
real_motion_enabled: false
hardware_access_policy: DISABLED
```

Selecting `REAL`, `READ_ONLY`, `FULL`, or real motion fails before any adapter is built.
The serial-port field remains inert. Kinematics models are reviewed repository inputs,
not local hardware configuration.

Dry Run runtime state remains schema-versioned, path-confined, ignored operational data
written with a same-directory temporary file, flush, `fsync`, and replace. Restore
requires robot identity, variant, Profile fingerprint, exact joint/unit set, finite
values, and logical limits; Stage 3 must additionally reject motion against mismatched
kinematics fingerprints and stale state sequences.

Stage 4 Pose and Motion repositories use independent schema `2.0.0` documents under
server-owned `data/poses/<uuid>.json` and `data/motions/<uuid>.json`. They validate both
generated JSON Schema and domain invariants, require UUID filename/document equality,
perform expected-revision compare-and-swap, and write by same-directory temporary file,
flush, file `fsync`, atomic replace, and directory `fsync`. Invalid documents are moved
to a server-owned quarantine when possible and omitted without aborting the list. The
four-MiB cap is per entity; traversal is additionally capped at 5,000 root JSON entity
files, 10,000 scanned root entries, and 64 MiB aggregate regular-entity bytes. Capacity
overflow is a structured 507, not a partial page. Repository locking is single-process
only; multi-process writers are unsupported. Schema `1.0.0` Pose/Motion documents are
quarantined rather than silently assigned missing compatibility evidence.

Stage 6 adds independent `MotionDraft` schema `1.0.0` documents under
`data/drafts/<uuid>.json`; they never share a repository root with formal Motions. The
persisted schema recursively requires every serialized field, including nested UUID,
default-edge, server-owned source metadata/Legacy trust, and save-intent identity, so
recovery cannot synthesize missing past state. The bounded trust registry stores
canonical SHA-256 identities of exact imported null-sequence snapshots; sorted-key JSON
means mapping order is irrelevant while any field mutation remains rejected.
Configuration rejects equal, ancestor/descendant, resolved/symlink, case-folded, or
NFC-Unicode-aliased storage roots before repository construction.

Draft writes reuse UUID naming, four-MiB entity and repository traversal/aggregate
bounds, atomic replace, directory durability, CAS, symlink rejection, and corrupt-file
quarantine. Formal Save/Save As first CAS-persist a write-ahead intent, write the exact
Motion through the Library mutation/revision lease, then CAS-rebind and clear the
marker. Cancellation cannot stop an in-flight intent-backed commit; later Draft access
semantically reconciles crash-interrupted markers without automatically creating a
second Motion. Exact intended content may be rebound; an advanced fresh/Save-As target
or mismatched creation/content remains retained and fail-closed. The operator may clear
only that exact marker through a revision/operation-bound confirmation API, which uses a
raw Draft CAS and never mutates a Motion.

## Repository structure

- `backend/src/momo/domain/kinematics` — model/fingerprint and FK/IK result contracts.
- `backend/src/momo/ports/kinematics.py` — SI adapter protocol and named unit boundaries.
- `backend/src/momo/adapters/kinematics` — mesh-free FK/IK implementation.
- `backend/src/momo/application/services` — lifecycle, kinematics, gateway, executor
  coordination, command status, Jog lease, Library, trajectory, playback, and bounded
  Studio Draft/compile, formal-save, and robot-action use cases.
- `backend/src/momo/adapters/playback` — bounded latest-value playback observation.
- `backend/src/momo/api` — versioned REST/read-only WebSocket transport only.
- `backend/src/momo/adapters/hardware` — Dry Run adapter only in Stage 3.
- `backend/src/momo/adapters/storage` — Profile, example Calibration, runtime state, and
  atomic UUID Pose/Motion/MotionDraft adapters.
- `kinematics_models` — V1/V2 provisional mesh-free documents.
- `frontend/src` — typed transport, shared runtime state, responsive pages/components,
  and composed Studio Draft/Motion/Pose/navigation hooks.

Stage 3 design decisions are recorded in ADR 0009 and ADR 0010. Stage 4 persistence and
schema compatibility are recorded in ADR 0011; importer operation is documented in
`legacy-action-import.md`. Stage 5 compiled identity and scheduling are recorded in ADR
0012 and `trajectory-semantics.md`. Stage 6 draft, edge, recovery, and compiler decisions
are recorded in ADR 0013 and `studio-user-workflow.md`. Executed evidence and known
limitations are in each Stage report; the Stage 6 report explicitly separates green
implementation/integrated-audit evidence from Pending commit/push delivery evidence.
