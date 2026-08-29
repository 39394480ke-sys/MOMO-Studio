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
bounded Dry Run playback. Stage 6 Studio is complete in pushed commit
`37783bdf8c01146d3a312980dbe4a25716e5468c`. Stage 7 adds the Synthetic Vision and
lease-bound Dry Run Follow slice; automated/static and desktop/mobile browser gates are
green with final independent audit P1=0/P2=0 and pushed commit
`dedbdabb9a35aefea01df05f0652214428305a93`. Stage 8 implements a deny-by-default
Real-hardware/Calibration boundary, local/LAN security, deterministic backup with
process-crash recovery, same-backend offline SPA hosting, CI, and release-candidate
identity. Physical use, Feetech adapter verification, and field acceptance remain
outside autonomous evidence. Final Stage 8 combined/browser gates and the P1=0/P2=0
audit pass; dedicated Stage 8 commit
`4f7a75606aacb3fc93128445d7487ff196ce9efb` is pushed and Draft PR
[#1](https://github.com/39394480ke-sys/MOMO-Studio/pull/1) is open.

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

React Vision workspace
  -> bounded no-store Synthetic frame/stream + REST status
  -> exact-frame manual ROI / Synthetic fixture detection and tracking
  -> VisionApplicationService (latest-value frame/selection/tracking state)
      -> FrameSource / TargetDetector / FaceDetector / TargetTracker ports
          -> deterministic Synthetic adapters
          -> honest unavailable optional provider capabilities
      -> VisionFollowService (one renewable Dry Run lease)
          -> pure FollowController + Profile-bound command factory
          -> VisionCommandCoordinator
              -> Motion application service -> MotionSafetyGateway

React Settings / release workspace
  -> readiness, stable unit identity, staged acceptance, Operator Session, diagnostics,
     Calibration, and restricted commissioning-motion workflow
      -> DeviceDiagnosticsService / CalibrationWorkflowCoordinator
          -> RealHardwareAuthorization (pure all-gates decision)
          -> OperatorSessionService (bounded, context-bound, expiring)
          -> ReadOnlyServoBus (explicit device + explicit IDs; no write/scan/register API)
      -> CommissioningMotionTestService
          -> immutable safety-envelope snapshot + backend deadman
          -> CommissioningMotionServoBus (one prepared joint goal only)
              -> FakeCommissioningMotionBus in automated evidence
              -> optional Feetech shell: Pending Adapter Verification / writes disabled
      -> FieldAcceptanceBundle + KinematicsVerificationEvidence repositories
          -> ignored, UUID-owned, exact-unit/fingerprint-bound local evidence
  -> RealSessionContext
      -> HttpOnly operator cookie transport
      -> backend summary/capability matrix/expiry/blocked reasons only
      -> shared by Control, Library, Studio, and Vision
  -> LAN browser session exchange and revoke
      -> one SecurityService for REST, control, WebSocket, and Vision

Backup / recovery surface
  -> deterministic byte envelope -> dry-run preview -> one-use digest/options grant
      -> shared repository maintenance gate
          -> durable restore WAL before first create
          -> exact-revision Pose/Motion/MotionDraft imports
          -> bounded absent-only Calibration batch
          -> compensation on failure/cancellation or before startup traffic after crash

Release hosting
  -> one FastAPI process may serve versioned API + locally built relative React assets
      -> SPA refresh fallback only for extensionless non-API GET/HEAD
      -> no CDN-backed interactive API docs; missing APIs/assets stay 404
```

Dependencies point inward toward domain and port contracts. API routes do not import a
driver, executor implementation, serial package, or Legacy controller. The default
composition explicitly injects the Dry Run implementations and gives the device service
no Real bus factory. A separately reviewed field composition would inject only the
`ServoBusFactory` port after all gates pass. There is no module-global robot, `arm_a`
product assumption, Fleet surface, device scan, startup serial/camera open/enumeration,
or raw-control transport.

## Product execution compositions

MOMO Studio is one product rather than a redesigned frontend layered over a second
Legacy control application.  Control, Library, Studio, Playback, and Vision keep one
set of routes, application services, domain contracts, and safety admission rules.

The current executable product graph is intentionally named as simulation composition:

```text
build_simulation_robot_service
  + build_simulation_product_services
      -> SimulationProductServices
          -> DryRunRobotDriver
          -> MotionSafetyGateway
          -> DryRunMotionExecutor
```

Real-device commissioning is a separate outer graph in `release_bootstrap.py`.  Its
read-only, Raw-direction, and single-joint buses are purpose-limited field tools, not a
second product runtime and not a production REAL executor.

Future REAL product motion must replace only the outer lifecycle/executor adapters while
retaining the same inward product chain.  It may reuse reviewed Legacy low-level behavior
only through those adapters; no frontend, API route, application service, or domain
module may import the Legacy controller.  Requested REAL execution must fail closed when
that reviewed composition is unavailable and must never silently run the simulation
backend.  See [ADR 0022](adr/0022-unified-product-motion-runtime.md) and the
[architecture cleanup ledger](architecture-cleanup.md).

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

## Stage 8 Real-hardware boundary

Authorization is a pure decision over a complete `RealHardwareContext` plus one immutable
purpose-bound Operator Session. `COMMISSIONING_READ_ONLY` requires `REAL`, `READ_ONLY`,
startup/local opt-ins, a verified non-template Profile, an available identified adapter,
one explicit device/protocol and exactly the Profile's ordered Servo IDs, and operator
confirmation. It deliberately omits `real_motion_enabled`, Calibration, acceptance, and
Kinematics prerequisites. Its readiness is exposed separately as commissioning
diagnostics and Calibration capture.

`COMMISSIONING_MOTION_TEST` is a third, independent purpose. It requires `REAL`, `FULL`,
the separate `commissioning_motion_test_enabled` switch, both opt-ins, a non-empty local
`robot_unit_id`, verified Profile, complete matching Calibration, exact Device identity,
pre-motion evidence, and explicit operator/E-stop/workspace confirmations. It does not
require final Field Acceptance, production `real_motion_enabled`, or verified
Kinematics. It exposes only `COMMISSIONING_SINGLE_JOINT_TEST` and cannot call the
production executor.

`REAL_MOTION` requires `REAL`, `FULL`, production motion/startup/local opt-ins, a
verified non-template Profile, complete matching non-template Calibration, current
capability-specific Field Acceptance, available adapter, exact Device, and a new operator
confirmation. Joint, Cartesian, Playback, and Vision Follow are derived separately;
provisional Kinematics blocks geometry-dependent scopes. Purpose cannot change, so
neither commissioning token becomes a production token after evidence changes.

The full `ServoBus` port is deliberately bounded, but commissioning services never
receive it. They receive `ReadOnlyServoBus`, exposing only explicit open/close, exact-ID
ping, and typed present-position/mode/torque reads. It has no goal, Stop/Hold, torque
write, arbitrary register, raw SDK, scan, enumeration, Home, or motion surface. Connect
opens only the configured device, pings only configured IDs, validates bounded reads,
and does not move. Any partial connection failure closes and clears authorization.

The restricted write workflow receives only `CommissioningMotionServoBus`. The service
reads one selected joint, calculates a relative target from fresh readback, validates the
session-snapshotted hard envelope plus logical/raw limits, maps through the exact Profile
and Calibration, and emits one immutable prepared command. The port can write only that
explicitly authorized joint and request the typed Stop/Hold behavior; multi-joint,
Home, Cartesian, Playback, Vision, raw-register, scan, enumeration, mode, torque, and
arbitrary-ID operations are absent. A backend-owned renewable deadman ends/faults the
attempt on timeout even when the browser cannot send Stop.

Physical identity is separate from model identity. `robot_unit_id` comes only from
ignored local configuration and enters Device/Calibration/session/evidence/audit binding
and Device fingerprinting. It is deliberately excluded from `RobotProfile.fingerprint`,
because a Profile describes a variant rather than one physical specimen.
The Device fingerprint is canonical SHA-256 over the unit ID, explicit serial port,
protocol, and ordered Servo-ID allowlist; those transport fields never generate the unit
ID.

Field Acceptance is a bundle of independent pre-motion, Joint, Cartesian, Playback, and
Vision Follow evidence. Full completion is derived, not written. Schema-v1/global
records remain audit history as `STALE_LEGACY_EVIDENCE`; an old `PASSED` value cannot
authorize. Kinematics uses a separate multi-point ignored local evidence overlay while
the tracked V1/V2 YAML stays `PROVISIONAL_DRY_RUN`.

File-loaded Field Acceptance records are non-authoritative until an application service
semantically resolves their embedded/referenced evidence and creates a transient
validated bundle. Joint evidence must resolve to current positive and negative passing
tests for every Profile-enabled joint, each embedded prepared command, and the exact
current commissioning envelope; matching fingerprints or a hand-authored UUID list are
insufficient.

Pre-motion evidence embeds a typed read-only diagnostic snapshot with session/time and
exact per-joint Servo ping, mode, raw/logical value, bounds, and torque-off state.
Bootstrap verifies exact enabled-joint/Servo coverage, Calibration mapping/mode/bounds,
capture-to-acceptance timing, and current context before restoring the capability. This
survives the required READ_ONLY → FULL restart without a fingerprint-only trust path.
Later CARTESIAN, PLAYBACK, and VISION_FOLLOW acceptance records remain audit-only because
this release has no typed field-test repositories/resolvers for them.

PRE_MOTION/JOINT transition publication is linearized under the Device Diagnostics
guard: reauthorize the same token/session/operator and current context, durably persist,
invalidate/close, then publish the resolved bundle before unlocking. A concurrent revoke
that wins first leaves no pass record; a transition that wins commits before revoke may
continue. Kinematics is intentionally audit-first: it persists, then reauthorizes under
the Device guard before live publication. A losing Kinematics race may leave only a local
audit record, never live or restart authority.

Kinematics measurement similarly rejects a browser-supplied joint state. A field adapter
must provide a fresh server-owned snapshot bound to the current unit, Profile,
Calibration, Device, and Operator Session; the service reauthorizes after capture and
computes FK/residuals itself. The `0.1.0-rc1` release composition has no such physical
adapter and bootstrap does not promote persisted Kinematics JSON. Those records are
audit-only after restart, so Real Kinematics remains fail-closed pending a reviewed
adapter and fresh verification.

Operator authority is transported in an HttpOnly, SameSite=Strict API cookie (Secure
under HTTPS). The frontend global context never stores the raw token; it restores only
the backend session summary, capability matrix, expiry, and structured blocked reasons.
All product pages consume that one view. Refresh does not create a session and restart
invalidates it.

Audit note: there is no unsafe or module-global God Object, but
`DeviceDiagnosticsService` remains a 974-line app-scoped, guard-locked Stage 8
coordinator covering sessions/readiness, connection/diagnostics, Calibration/Profile
invalidation, Field/Kinematics publication, Stop, and shutdown. The final audit classifies
this as P3 post-merge decomposition debt: current paths remain fail-closed behind typed
ports, and no safety bypass was found.

The Feetech implementation is an independently written optional shell. Import is lazy
inside a fully granted factory, construction/open are separate, and the release
composition does not instantiate it. Exact SDK/API/license/cancellation and physical
Stop semantics remain Pending Adapter Verification; goal writes are disabled and Stop
reports `SAFETY_STATE_UNCERTAIN`. Automated executor coverage uses only Fake Bus.

The Real executor accepts the exact immutable `PreparedTrajectory` and digest; it does
not compile browser samples. It maps each logical sample through the verified
Profile/Calibration, checks raw bounds, schedules with monotonic deadlines, writes the
explicit ID map, reads back, checks divergence, and updates high-level state through an
observer. Authorization/context/sequence/position evidence is rechecked at boundaries.
Partial writes, timeout, bus fault, readback mismatch, cancellation, disconnect, and
expiry enter a typed terminal/fault state and request a truthful typed Stop.

Calibration authoring is a separate protected commissioning workflow over an explicitly
connected read-only bus. With no current Calibration it creates an incomplete draft from
the exact Profile; missing captured/operator values remain absent. It reads only the one
selected Profile joint/Servo ID, accepts the operator's observed logical value, previews
direction/Home/phase/raw bounds and round-trip evidence, and requires explicit per-joint
confirmation. Saving the first complete validated document creates Revision 1 through
the same atomic repository path; recalibration creates Revision N+1 after preserving the
previous revision in a fixed backup directory. After any persistence attempt begins—success, failure, or
replace-then-fsync uncertainty—the coordinator closes/revokes hardware authorization in
`finally`. Rollback restores old content as another new revision; it never rewinds
history or promotes an example. Cancellation cannot release the workflow guard before
connection/session cleanup reaches a terminal state.

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

Field verification never rewrites those tracked documents. An ignored local
`KinematicsVerificationEvidence` overlay binds at least three measured points and frozen
residual thresholds to the exact unit, Profile, Calibration, model fingerprint/schema,
checklist, Device, operator, software commit, and server-owned snapshot provenance. Only
a current overlay applied by the live workflow derives effective Real Kinematics
readiness, and only alongside independent Cartesian/Playback/Vision evidence. Persisted
overlay files are not bootstrap authority in `0.1.0-rc1`.

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
Goto, Playback, Studio Goto, and Vision Follow—must submit immutable intent
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

Stage 7 admits `VISION` + `MOVE_JOINTS` only from the Follow command factory. It begins
with a fresh Robot/Profile/Joint snapshot; the configured pan/tilt IDs must both be in
the Profile's explicit `enabled_joints`, distinct, `REVOLUTE`, and `deg`. The factory
applies bounded controller increments to the current complete keyed state. Its narrow
coordinator calls only the injected motion application/gateway-facing protocol and owns
late-acceptance cancellation; Vision never receives an executor or driver reference.

The pure Follow controller computes target-center error, EMA, dead zone, configured
sign/gain, maximum step, and elapsed-time rate limit. One heartbeat-renewed lease owns
Follow. Stale/non-advancing frames, target loss/low confidence, source/tracker/browser
loss, Robot disconnect/fault/staleness, motion conflict/rejection, expiry, Stop, or
shutdown end ownership. Same-frame loss corrections cancel the previous direction.
Lifecycle epochs prevent a start awaiting Robot evidence from publishing after Global
Stop or shutdown; shutdown permanently closes the service.

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

Stage 7 adds capability/status/frame/stream, exact-frame selection/clear, detector,
tracking-reset, and Follow start/heartbeat/stop routes below `/api/v1/vision`. These are
11 method/path combinations across 10 unique paths; the combined application inventory
is 71 method/path combinations across 61 unique HTTP paths plus the same read-only
Robot WebSocket. There is no Vision command WebSocket, live-camera-open route, raw
camera identifier, recording route, or alternate motion path.

The later read-only-camera slice adds `POST /vision/camera/open` and
`POST /vision/camera/close`. They accept no device identifier: the ID exists only in the
selected ignored local configuration. Open requires a literal read-only confirmation
and normal control admission; Close uses the priority-stop authorization boundary so an
ordinary control-rate bucket cannot prevent release. There remains no Vision command
WebSocket, enumeration, recording, raw-camera, or motion route.

Stage 8 adds release/security session exchange, readiness/session/connect/diagnostic/
Stop device endpoints, protected Calibration-session/read/preview/confirm/save/rollback
endpoints, and backup export/preview/restore endpoints. These routes depend on
application ports/services only. They accept bounded DTOs or uploaded backup bytes—never
a server filesystem path, SDK object, arbitrary Servo/register address, or executable
sample. Default device calls report blockers without constructing a bus.

Final pre-merge hardening adds only the narrow staged-commissioning surface: status,
motion-test session/arm/start/heartbeat/Stop, plus Kinematics status/draft/measurement/
commit. The historical field-acceptance compatibility read returns a derived summary;
confirmation-only global `PASSED` creation has no authorization semantics. The complete
current route/caller/service/scope disposition is maintained in `api-audit.md`; no route
was deleted merely for lacking a current UI caller.

One `SecurityService` protects normal REST, control, priority Stop, Vision, and
WebSocket surfaces. LAN browsers exchange a long-term Bearer once for a short-lived
HttpOnly `SameSite=Strict` cookie. The LAN policy permits only exact allowlisted HTTP
Origins on the API bind host (the UI port may differ); wildcard, public, cross-host,
HTTPS, and opaque Origins fail closed. Established Robot WebSockets and Vision streams
reauthorize each bounded publish/frame so expiry or revoke terminates the connection.
Control principals and sessions have hard capacity/rate bounds; priority Stop remains
authenticated but is not blocked by the ordinary command bucket.

`StructuredRequestAuditMiddleware` assigns a bounded request ID and records safe source,
principal, outcome, duration, status, and error code. Motion submissions/Jog start also
publish their command ID, `primary` robot, Dry Run mode, and preflight state. Recursive
redaction removes credentials, URLs, POSIX/Windows/file paths, and masks device identity
before the bounded memory or bounded rotating JSONL sink.

The Synthetic stream uses `multipart/x-mixed-replace`, `Cache-Control: no-store`, and
already encoded bounded PNG frames. Each slow consumer observes one latest-value slot
instead of accumulating a queue. The service permits 4 clients by default and at most
16, retains at most 64 frames subject to 32 MiB encoded content, and releases client
ownership on disconnect. Frame/tracking/Follow metadata remains available through REST.

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

The Stage 7 Vision workspace renders the Synthetic stream, exact frame identity/age,
manual pointer ROI, detections, tracking box/confidence/state, center and EMA errors,
dead-zone overlay/tuning, Provider Capability, Robot/Follow/lease state, Stop, and the
Real Follow block reason. Pointer-down captures frame identity so a late drag cannot
select a newer frame accidentally. Late Follow-start responses are compensated after
priority Stop, disconnect, or unmount. The checked 1440×960 and 390×844 real-app flows
passed Synthetic Select/Detect/Follow/Stop and responsive bounds with console
warnings/errors `[]`.

Settings displays release and masked identity evidence, `robot_unit_id`, the three
purposes, staged progress, per-joint commissioning controls, Kinematics pending state,
and structured capability blockers. Commissioning Motion is visually isolated from the
normal Control page and exposes press-and-hold only. `RealSessionContext` reads one
backend session summary and matrix for Control, Library, Studio, and Vision. It retains
no raw operator token; authority is in the HttpOnly cookie. Default data remains blocked,
and Fake completion cannot remove Feetech, physical Stop, or physical Kinematics gates.

The Stage 8 responsive results remain historical evidence. Final three-purpose browser
results are recorded separately only after the current Fake flow is executed.

## Configuration and persistence

Safe default loading uses typed defaults, tracked `config/default.yaml`, then `MOMO_*`
environment values. It does **not** probe or read ignored `config/local.yaml`. A caller
may opt in to one specific local file only by explicitly passing `local_config_path` to
the settings loader; that explicit file is then merged before environment overrides.
The tracked Stage 8 release defaults remain:

```text
control_mode: DRY_RUN
commissioning_motion_test_enabled: false
real_motion_enabled: false
hardware_access_policy: DISABLED
robot_unit_id: ""
camera_access_policy: SYNTHETIC_ONLY
field_acceptance_checklist_version: "1"
lan_enabled: false
```

The settings/config surface has no writable `field_acceptance_status`; the release
context initializes its backward/internal scalar as pending and derives capabilities
only from resolved staged evidence.

Capability-bearing values may be loaded only through one explicitly selected ignored
local file or environment overrides, but no single value creates authority. The
authorization matrix evaluates the complete set and the default release composition
still supplies no Real bus factory. The serial-port field is inert until a separately
reviewed field composition holds a complete grant. Kinematics models are reviewed
repository inputs, not local hardware configuration.

Vision defaults to the in-memory source at 12 fps and 640×360, with configuration caps
of 30 fps and 1280×720. `LIVE_CAMERA_ALLOWED` changes composition only when the selected
ignored local file also contains the explicit device ID and local opt-in. That
composition is closed: it performs no OpenCV import or device access at startup. A
confirmed operator open request lazy-loads the optional `camera` dependency and calls
`VideoCapture` for only that ID. The source is latest-value, JPEG, bounded, no-store,
and read-only; Close or shutdown releases it. No code enumerates devices.

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

Stage 8 Real Calibration revisions live under the fixed ignored `data/calibration`
root, one current file per variant plus fixed private backup directories. A forward save
validates a complete non-template document, writes the previous bytes to a durable
revision/fingerprint backup, then atomically replaces current bytes. Explicit rollback
uses an old backup as new content with a fresh identity and monotonic revision.

Backup restore uses the same process-wide `RepositoryMaintenanceGate` as ordinary
Pose/Motion/Draft repository work. Before the first exact create it durably publishes a
bounded transaction in `data/restore/restore-transaction.json`. Success or complete
compensation clears the journal durably. Application lifespan recovers any surviving
intent before yielding/serving requests; failure blocks startup. This supplies
process-crash atomic restore for the supported single-process, server-owned repository
configuration. Multiple backend writers and unsupported filesystems remain outside the
contract.

## Repository structure

- `backend/src/momo/domain/kinematics` — model/fingerprint and FK/IK result contracts.
- `backend/src/momo/ports/kinematics.py` — SI adapter protocol and named unit boundaries.
- `backend/src/momo/adapters/kinematics` — mesh-free FK/IK implementation.
- `backend/src/momo/application/services` — lifecycle, kinematics, gateway, executor
  coordination, command status, Jog lease, Library, trajectory, playback, bounded
  Studio/Vision use cases, and Stage 8 authorization/device/Calibration/security/backup
  services.
- `backend/src/momo/adapters/playback` — bounded latest-value playback observation.
- `backend/src/momo/adapters/vision` — Synthetic/disabled/latest-value adapters and a
  policy-first lazy-import optional OpenCV camera shell.
- `backend/src/momo/api` — versioned REST/read-only WebSocket transport, security
  middleware/dependencies, and optional safe SPA hosting; no raw driver surface.
- `backend/src/momo/adapters/hardware` — Dry Run/Fake bus plus a default-denied lazy
  Feetech shell whose adapter verification and writes remain pending.
- `backend/src/momo/adapters/storage` — Profile/example Calibration/runtime state,
  atomic UUID Pose/Motion/MotionDraft, revisioned Real Calibration, and durable restore
  journal adapters.
- `backend/src/momo/adapters/motion/real_motion_executor.py` — exact-prepared Fake-Bus-
  exercised Real execution path; not injected by the committed default composition.
- `kinematics_models` — V1/V2 provisional mesh-free documents.
- `frontend/src` — typed transport, shared runtime state, responsive pages/components,
  composed Studio Draft/Motion/Pose/navigation hooks, and Vision selection/Follow state.

Stage 3 design decisions are recorded in ADR 0009 and ADR 0010. Stage 4 persistence and
schema compatibility are recorded in ADR 0011; importer operation is documented in
`legacy-action-import.md`. Stage 5 compiled identity and scheduling are recorded in ADR
0012 and `trajectory-semantics.md`. Stage 6 draft, edge, recovery, and compiler decisions
are recorded in ADR 0013 and `studio-user-workflow.md`. Executed evidence and known
limitations are in each Stage report; the Stage 6 report explicitly separates green
implementation evidence from its now-recorded containing commit. Stage 7 camera access,
frame identity, provider honesty, and Follow lease decisions are in ADR 0014 and
`vision-provider-capabilities.md`; its dedicated commit is pushed. Stage 8 authorization,
network/audit, and release/field decisions are ADRs 0015–0017. The Stage 8 report records
green combined/browser/audit evidence plus its pushed commit and open Draft PR.
