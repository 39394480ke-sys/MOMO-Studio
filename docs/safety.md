# Safety

## Stage 8 release safety boundary

Stages 3–7 are complete and pushed. Stage 8 implements future Real-hardware software
seams while preserving a deny-by-default release configuration:

- tracked defaults are `DRY_RUN`, hardware `DISABLED`, real motion/startup/local opt-ins
  false, camera `SYNTHETIC_ONLY`, LAN false, and field acceptance `PENDING`;
- the default composition injects in-memory Dry Run motion and Synthetic Vision and gives
  the device service no Real bus factory;
- committed Profiles/Calibration are templates and Kinematics are
  `PROVISIONAL_DRY_RUN`; none can satisfy Real authorization;
- the Feetech shell is `PENDING_ADAPTER_VERIFICATION`, lazy, never instantiated by the
  autonomous release path, disables goal writes, and reports uncertain Stop;
- startup does not connect, enumerate, scan, Home, torque, move, calibrate, import a
  Servo SDK, open a serial port, or open/enumerate a camera;
- Robot status/FK/Dry Run command/playback/Vision evidence remains
  `hardware_accessed=false`; Fake Bus is the only autonomous Real-executor test adapter;
- API routes depend on application services and never import a concrete driver;
- no raw Servo, arbitrary register, arbitrary file, arbitrary Python, or driver-selection
  endpoint exists.

The software authorization, diagnostic, Calibration, and executor paths do not imply
physical readiness. Every item in `real-hardware-acceptance.md` remains unchecked.
Final Stage 8 combined software and browser gates pass, and the independent audit closes
P1=0/P2=0; the dedicated commit is pushed and Draft PR #1 is open. Nothing in this
document authorizes live-camera access, Real motion, Real Follow, or a physical Stop claim.

## Provisional kinematics are not Real authority

The V1 and V2 mesh-free models are `PROVISIONAL_DRY_RUN`. V1 is exactly `j11`-`j15`
with no rail; V2 is `j10`-`j15`, with J10 prismatic. Model fingerprints establish exact
software compatibility only.

The field-verification request accepts only a label and measured TCP. The backend must
obtain the corresponding fresh joint state from a server-owned, session/device-bound
snapshot provider and compute FK/residuals itself. `0.1.0-rc1` intentionally wires no
physical provider and does not reload persisted Kinematics evidence as authorization;
files remain audit history and verification must be repeated after restart.

Physical link geometry, frames, axes, signs, zero references, TCP, joint limits,
workspace, speed, acceleration, FK reference points, IK tolerances, and Cartesian path
accuracy remain unverified. Therefore provisional models categorically block:

- Real Cartesian Jog or Move Pose;
- Real playback containing Cartesian segments;
- Real vision follow;
- any claim that successful Dry Run IK is physically reachable.

UI/domain values remain `mm`/`deg`; adapter values are `m`/`rad`. Only named boundary
functions may convert them. Unit conversion cannot depend on the name `j10`.

## Commissioning and Real Motion authorization

Real hardware has three disjoint Operator Session purposes:

| Purpose | Narrow authority |
|---|---|
| `COMMISSIONING_READ_ONLY` | Exact-device diagnostics and Calibration capture; no write capability |
| `COMMISSIONING_MOTION_TEST` | One separately armed, bounded, relative single-joint test under a backend deadman |
| `REAL_MOTION` | Only the production capabilities supported by current capability evidence |

Purpose and scopes are immutable. Moving to another purpose requires a new session ID,
expiry, operator confirmation, and evidence snapshot. Completion of Calibration, a test,
acceptance, or Kinematics verification cannot upgrade an existing session.

Read-only commissioning retains its capability-narrowed `ReadOnlyServoBus`: explicit
open/close, exact-ID ping, and typed present-position/mode/torque reads. It has no goal,
Stop/Hold, torque-write, arbitrary-register, scan, enumeration, Home, Jog, Playback, or
Follow method. Partial open/ping/read failure closes the bus, revokes authorization, and
cannot report Connected.

Restricted commissioning motion has a separate default-false
`commissioning_motion_test_enabled` gate and never reuses `real_motion_enabled`. It also
requires Real mode, `FULL` policy, both hardware opt-ins, a non-empty local
`robot_unit_id`, verified non-template Profile, complete matching Calibration, exact
Device identity, current pre-motion-check evidence, and explicit operator/E-stop/
workspace confirmations. It deliberately does not require final Field Acceptance or
verified Kinematics.

The commissioning-motion backend permits only `RELATIVE_SINGLE_JOINT_TEST`. The immutable
hard envelope caps active joints at 1, command duration at 2 seconds, session duration at
300 seconds, revolute/prismatic delta at 2 degrees/1 millimetre, speed at 2 degrees per
second/1 millimetre per second, acceleration at 4 degrees per second squared/2 millimetres
per second squared, deadman lease at 400 milliseconds, and commands per session at 24.
Local configuration may only narrow these values. A narrowed
`CommissioningMotionServoBus` can read the selected joint, write one prepared goal, and
request the available typed Stop/Hold behavior; it has no production-motion, multi-joint,
raw-register, mode, torque, scan, enumeration, or arbitrary-ID capability.

Every test is separately armed and heartbeat-renewed. Pointer release/cancel, blur,
hidden visibility, route teardown, network loss, session expiry, backend shutdown,
operator Stop, Global Stop, or backend lease timeout requests Stop/fault. The backend
owns the deadline; UI behavior is not the safety boundary. Every pass or failure records
unit/fingerprint-bound immutable evidence after direction, raw/logical readback,
freshness, limits, and divergence verification.

A separate `REAL_MOTION` session requires `real_motion_enabled` and current evidence for
the requested production capability. Joint, Cartesian, Playback, and Vision Follow are
derived independently. Cartesian and Cartesian-containing Playback additionally require
valid multi-point Kinematics evidence plus Cartesian acceptance. No global writable
`PASSED` record or legacy status value can unlock them.

Here, “valid” means evidence applied by the current live reviewed workflow. Persisted
Kinematics JSON is not bootstrap authority in this release candidate.

Browser authority uses an HttpOnly, SameSite=Strict, API-path cookie, Secure when served
over HTTPS. Raw tokens are absent from React state, browser storage, URLs, logs, and audit
events. The global frontend context holds only the backend session summary, expiry,
capability readiness, and blocked reasons. Refresh re-reads the summary; restart
invalidates the grant and never issues another automatically.

The current-angle Calibration workflow is selected-joint and read-only at the Servo
boundary. With no stored Calibration it creates an incomplete Profile-bound draft whose
uncaptured values remain `None`, then reads one configured present raw value and accepts
the operator's logical value, direction, phase, and bounds. It previews round-trip
evidence and requires every enabled joint explicitly confirmed before the normal domain
validator and atomic repository path save Revision 1. Recalibration starts from Revision
N and saves Revision N+1. Neither path can write a Servo, change mode/torque, move, or
scan. After a persistence attempt begins, the coordinator revokes/closes commissioning
authorization in `finally`, including on filesystem durability failure. Rollback is
explicit and creates a new forward revision. A template/example can never be promoted.

Completing Calibration grants no motion capability. The local ignored
`FieldAcceptanceBundle` contains independent pre-motion, Joint, Cartesian, Playback, and
Vision Follow evidence bound to `robot_unit_id`, variant, Profile, Calibration, Device,
applicable Kinematics, checklist version, operator, and software commit. Evidence without
unit identity or capability—including historical schema-v1/global evidence—is retained
as `STALE_LEGACY_EVIDENCE` and grants nothing. Any binding change stales the affected
derived capabilities and invalidates sessions rather than upgrading them.

The Real executor accepts only the already-preflighted immutable trajectory/digest and
rechecks authorization/context/sequence/continuity. It maps samples through verified
Profile/Calibration, validates every raw goal, uses monotonic deadlines, reads back, and
fails on divergence, partial write, timeout, bus fault, disconnect, expiry, or
cancellation. It never recompiles browser samples. The software path is tested only with
Fake Bus and remains absent from default route composition. Fake success proves
software-path behavior only. Feetech goal write, software/physical Stop, physical
E-stop, and physical Kinematics remain field-verification gates.

## Unified Motion Safety Gateway

There is one reviewed application admission point for every movement source. Joint
Move, single/continuous Joint Jog, Home, Cartesian Jog, Move Pose, Library Goto,
Playback, Studio Goto, and Vision Follow may not call an executor or
driver directly.

The gateway owns one atomic admission coordinator for ordinary motion, trajectory
preflight, and playback. Each final safety recheck and owner claim stays inside that
coordinator. Playback additionally rechecks the exact prepared-object identity and
latest preflight generation after every asynchronous boundary and after claiming its
runner; superseded or evicted prepared work fails closed.

That same coordinator owns a lifecycle epoch/count fence. Work beginning during Stop,
Disconnect, or Shutdown is rejected, and work captured before the transition cannot
publish or dispatch afterward. Playback Stop completion is owned by one shielded task;
canceling an HTTP/lifecycle caller cannot cancel cleanup, and a repeated Stop joins the
same task until terminal state publication releases motion ownership.

Ordinary executor submission rechecks that lifecycle epoch after its awaited claim. If
Stop began in that window, the exact command is canceled before conflict is returned and
no idempotency acceptance is published. Global Stop itself also has one shielded
completion owner, so cancellation of its first caller cannot interrupt Jog, trajectory,
or executor hook iteration; repeated Stop joins the same operation.

Motion update/delete and execution validation share one process-local revision lease.
The lease stays held through fresh repository read, gateway checks, and the `PLAYING`
claim. A mutation therefore commits before that claim and invalidates the prepared
revision, or commits only after the immutable reviewed plan is already executing.

Before producing prepared Dry Run work, the gateway must fail closed unless it verifies:

1. active Robot identity and connected state;
2. Dry Run mode, disabled hardware access, and false real-motion release gate;
3. expected `state_sequence` and monotonic observation freshness;
4. exact Profile and Kinematics fingerprints;
5. exact Profile `enabled_joints` and explicit unit map;
6. finite values and logical limits, plus raw-derived reachability only when a
   Calibration is configured and exactly compatible;
7. target delta plus provisional velocity/acceleration/duration limits;
8. workspace bounds and finite FK;
9. IK success and residual thresholds for Cartesian commands;
10. command source, idempotency, ownership, conflict, and cancellation state.

When no Calibration is configured, preflight records raw-derived validation as
`not_applicable` and uses logical Profile limits only for Dry Run. A configured but
incompatible Calibration is a rejection, not a silent fallback. Matching template
Calibration may narrow Dry Run bounds, but neither its presence nor its absence can
authorize Real motion.

Provisional dynamic/workspace values may support bounded Dry Run behavior only. They
must be named and reported as provisional and never promoted to Real verification.

Freshness is the monotonic age of the last successful high-level Dry Run driver
observation. UTC `updated_at` is used for display and persistence only. A stale state
gets one high-level read attempt bounded to 0.25 seconds; read failure or timeout leaves
the state stale, regardless of wall-clock movement.

A failed preflight returns a typed rejection and dispatches nothing. The gateway must
not catch an exception and report success, silently crop joints, zero-fill missing data,
coerce NaN/infinity, accept an approximate IK candidate as reachable, or substitute a
default Profile/Kinematics model.

Stage 4 permits only a `LIBRARY`-source `MOVE_JOINTS` Goto command. Before gateway
submission, the Library service must match the entity revision, active variant, exact
joint/unit membership, Profile fingerprint, Kinematics fingerprint, and validated joint
state. The repository has no driver/executor dependency and cannot dispatch motion.
Motion CRUD and the Legacy importer never imply playback.

Stage 5 extends the same gateway for `PreparedTrajectory` execution. Successful
compilation is not permission to run later: immediately before dispatch the gateway
must revalidate the exact cached object, digest, Motion revision, active variant,
Profile/Kinematics fingerprints, start-state sequence, freshness, connection, Stop
capability, Dry Run/disabled-hardware policy, and single motion slot. Any changed fact
requires new preflight. API routes cannot provide samples or select an executor.

Whole-path preflight checks every Joint/Cartesian/hold sample, logical and applicable
raw-derived limits, provisional velocity/acceleration, workspace, FK/IK residual, and
Cartesian continuity before returning a digest. Cartesian failure rejects the plan; it
never degrades to Joint interpolation. Compilation, cache, samples, segments, duration,
preview, rate, and loop count are all bounded. Playback uses monotonic absolute
deadlines, skips overdue samples instead of bursting, and keeps Stop cancellable during
validation, sleep, pause, state application, or looping.

Stage 6 Draft compile uses the same Stage 5 compiler semantics but returns
`executable=false`, never inserts a prepared plan into the playback cache, and never
dispatches work. A Draft must become a formal Motion, pass the normal revision-bound
preflight, and identify the exact prepared digest before Dry Run playback.

Studio Goto accepts no browser-owned Joint target. The service reloads the requested
keyframe from an expected persisted Draft revision, verifies the active variant, exact
enabled-joint/unit set, Profile/Kinematics fingerprints, and snapshot validity, then
submits `STUDIO` + `MOVE_JOINTS` through the ordinary motion service and this gateway.
The Studio mutation lock remains held from Draft recovery through revision/keyframe
checks and command submission, preventing an autosave from replacing the target in that
interval.
Stale, missing, incompatible, disconnected, busy, or policy-blocked state dispatches
nothing.

## Vision access and Follow deadman

Camera policy is independent from hardware policy. `SYNTHETIC_ONLY` is the safe default;
`DISABLED` composes a fail-closed source. `LIVE_CAMERA_ALLOWED` is vocabulary, not an
implicit open. The optional OpenCV factory requires explicit local enablement, one
explicit bounded device ID, and operator action before its lazy import. Source
construction still performs no device I/O, application startup always selects Synthetic,
and Stage 7 exposes no live-open/enumeration route. OpenCV is absent from the manifest
and lock. Frames are `no-store`, never recorded, and subject to bounded retention.

A manual selection or provider result is usable only when its complete frame ID,
source, aware capture time, and dimensions match a retained unexpired frame. A new
Follow frame ID must advance its capture time strictly; equal/older timestamps stop as
stale. Same-frame loss or confidence corrections remain actionable so they cancel the
old direction instead of being discarded as duplicates.

Follow requires explicit confirmed Dry Run intent, one short backend lease, and a
Profile-bound mapping marked `VERIFIED_FOR_DRY_RUN`. Both mapped joints must be distinct
members of explicit `enabled_joints` and `REVOLUTE`/`deg`; the prismatic V2 rail and
unknown/disabled joints fail closed. The controller bounds error/EMA/dead-zone/gain,
increment, and rate. Its coordinator has only the high-level motion application surface,
so every command passes through the shared gateway and motion slot.

Target loss or low confidence immediately suspends/cancels the active Vision command,
then begins the bounded lost-target interval; it never continues the last direction.
Frame staleness, camera/browser disconnect, tracker fault, Robot disconnect/fault/stale
state, motion conflict/rejection, lease expiry, operator Stop, Global Stop, and backend
shutdown all end ownership. Centered frames and active commands still trigger a fresh
Robot snapshot, so a heartbeat cannot conceal a lifecycle fault.

Start is lifecycle-epoch fenced around its awaited Robot snapshot. Global Stop can
therefore invalidate an idle-but-starting Follow without re-entering motion cancellation
from the registered hook. Backend shutdown uses the same barrier, performs normal Vision
command cancellation, permanently closes the service, and prevents a late or later
start from installing a lease.

## Dry Run executor

The `DryRunMotionExecutor` is required to be deterministic, cancellable, bounded, and
hardware-free:

- inject a monotonic Clock and use absolute deadlines;
- run at a fixed maximum update rate without accumulating sleep drift;
- interpolate a single move instead of teleporting to its target;
- allow only one Active Motion;
- bound duration and sample count; allow no waiting command queue, one active task, and
  no retry loop;
- update the in-memory runtime and `state_sequence` monotonically;
- persist only compatible logical Dry Run runtime state;
- cancel on Stop, disconnect, conflict, lease expiry, shutdown, or fault;
- enter `FAULTED` on executor errors and never fabricate target-as-actual state.

Tests use a Fake Clock and do not depend on real sleeping. Stage 3 execution must never
perform logical-to-raw writes or instantiate hardware.

## Stop and conflict priority

Stop is always visible and has priority over ordinary admission. It sets the active
cancellation event and invalidates a Jog lease before asking the Dry Run runtime to stop.
It must remain callable while another command is active. Duplicate Stop is stable.

Dry Run `STOPPED` means only that in-memory Stage 3 execution stopped at its last
accepted sample. It is not a physical emergency-stop claim. Stage 8 Real Stop uses the
typed outcomes `STOPPED_AND_VERIFIED`, `HOLD_REQUESTED`,
`TORQUE_DISABLE_REQUESTED`, `NOT_CONNECTED`, `FAILED`, and
`SAFETY_STATE_UNCERTAIN`. Only complete verified evidence may return the first. The
pending Feetech shell cannot establish that evidence and therefore instructs use of the
physical E-stop.

Only one Active Motion/Jog owner exists. Conflicting commands are rejected with a
structured conflict; they are never silently queued without a documented finite bound.
Idempotent replay returns the original command status, while an identity reused for
different intent is rejected.

## Continuous Jog deadman

Hold-to-Jog is protected by a short renewable backend lease, not by `pointerup` alone.

- Start returns an opaque `jog_session_id` and expiry.
- Heartbeat renews only the matching active lease within a bounded TTL.
- Explicit Stop cancels immediately.
- Pointer release/cancel, blur, visibility change, route teardown, and component unmount
  request Stop.
- Network loss is handled by server-side expiry.
- Disconnect, fault, backend shutdown, command conflict, or Global Stop cancels the
  lease.

Expiry must stop producing increments; it cannot reuse a previous direction. Session IDs
are runtime identifiers, not persistent secrets, and must not enter saved robot state.

## Read-only WebSocket

The robot WebSocket publishes RobotStatus (including its safe last-error summary), TCP
pose/FK, the latest command status/progress/error, state sequence, and top-level
`hardware_accessed=false`; it has no separate fault-list field. Its current source loop
is capped at 10 Hz, has no application queue, and gives each send a one-second timeout.
A slow client can block only its own sender; timeout or disconnect exits that client
handler. Dedicated timing, slow-client, terminal-delivery, silent-socket watchdog, REST
fallback, and disconnect tests pass. After 1.5 seconds or 15 missed 10 Hz frames, the
frontend clears a silent socket snapshot, closes it, and enters bounded REST/reconnect;
only a valid complete frame resets that timer.

The socket accepts no motion command, raw value, Python expression, file path, or Servo
operation. REST remains a status fallback. A disconnected socket does not implicitly
leave a continuous Jog safe; the independent Jog lease expires and stops it.
In LAN mode the server reauthorizes before every bounded publish. Session expiry,
explicit revoke, or backend restart closes the established socket instead of granting
authorization for its original connection lifetime. Vision streaming applies the same
per-frame rule.

## Lifecycle, Profile, Calibration, and runtime trust

Only the active Profile's explicit `enabled_joints` determines membership. V1 never
contains J10; V2 requires it in `mm`. Fixed six-joint arrays, dictionary-order chains,
`arm_a`, and joint-name unit branches are prohibited.

Committed Profiles, Calibration documents, and kinematics models are templates or
provisional Dry Run data. They do not authorize Real use. Calibration compatibility
still requires exact variant, Profile fingerprint, joint set, Servo IDs/modes, raw
bounds/Home, direction, and completeness. Stage 8's separately protected Real workflow
may produce ignored non-template forward revisions only after complete authorization;
committed examples remain read-only and cannot be upgraded.

Runtime state remains path-confined ignored data. Atomic restore fails closed on corrupt
JSON, wrong schema/identity/variant/Profile, wrong joint/unit set, non-finite or
out-of-range values. A saved connection never reconnects a device. Motion command
admission separately checks current state sequence and Kinematics fingerprint.

## Pose, Motion, MotionDraft, and import safety

Pose/Motion persistence accepts UUID identities, not display-name paths. The server owns
both repository roots and their quarantine directories. Documents are capped at four
MiB, validated by generated JSON Schema plus domain validation, and must match their UUID
filename. Writes use a temporary sibling, flush, file `fsync`, atomic replace, and
directory `fsync`; stale updates/deletes fail with an expected-revision conflict. A
corrupt entry is omitted from lists and quarantined when the filesystem permits.
Repository work fails closed above 5,000 root JSON entities, 10,000 scanned root entries,
or 64 MiB aggregate regular-entity bytes. The current lock is
repository-instance-local; multiple backend writer processes are not a supported
configuration. Quarantine is best effort and has no automatic retention/pruning policy.

MotionDraft uses an independent UUID root and a recursively strict persisted schema.
Every serialized field—including nested keyframe UUIDs, directed default-edge identity,
server-owned source metadata/Legacy trust, and formal-save intent identity—is required
during recovery; defaults are not used to invent omitted past state. All configured
runtime/Profile/Calibration/Kinematics/Pose/
Motion/Draft roots must be pairwise disjoint before repository construction under
resolved/ancestor relationships, existing filesystem identity, NFC Unicode
normalization, and case folding. Stage 8 extends that check to Real Calibration,
restore-journal, and audit roots. A Draft repository therefore cannot mistake a formal
Motion or an operational recovery/audit document for corrupt Draft data and quarantine
it.

Save/Save As spans Draft and Motion repositories only through a write-ahead intent. The
Draft marker is CAS-persisted before the Motion write; the formal candidate is persisted
through the same Library mutation/revision lease used to fence Stage 5 playback; a
second Draft CAS binds the exact source and clears the marker. Caller cancellation
cannot cancel an in-flight intent-backed commit. Restart reconciliation verifies target
identity and complete semantic content, never auto-creates a duplicate, and preserves a
stale intended revision only for a known-source Save when a later writer has advanced,
so the next Save conflicts. An advanced fresh/Save-As target, mismatched creation
identity, or mismatched semantic content—including typed source metadata—retains the
marker and fails closed. Exact-match recovery binds once without creating a duplicate.

Imported null-sequence snapshots are admitted only when their full canonical SHA-256
identity is present in the bounded server-owned Draft trust registry seeded from the
source Motion. Sorted-key JSON ignores mapping insertion order but not field content;
altered or fabricated snapshots remain rejected. Autosave, recovery, rebind, abandon,
and provenance-preserving forks retain the registry without accepting it from clients.

A retained formal-save marker can be abandoned only by an operator request bound to
the exact Draft revision and operation UUID plus a fixed confirmation literal. That raw
CAS clears only the marker; it never mutates a Motion. Studio conflicts identify only
`MotionDraft` or `Motion`; missing/unknown scope and active formal-save recovery remain
generic and fail closed. Conflict Save As captures local content before loading the
authoritative Draft, forks that Draft at an exact revision, reapplies the captured local
document, and saves a new Motion without overwriting the original Draft or Motion.

Schema `1.0.0` Pose/Motion documents are not considered compatible with Stage 4
`2.0.0`. Missing Profile/Kinematics fingerprints, units, variants, or observation
evidence must never be guessed. Live Capture reads only the active high-level Dry Run
state and retries a bounded three times if the sequence/Profile/joints change around FK.
It does not read Calibration or hardware.

Legacy action import is an offline CLI only. It requires one operator-supplied source
path and defaults to a conversion report without writes. It does not scan a Legacy
checkout, user directory, serial device, or browser-selected server path. Hardware
variant must be explicit V1/V2; a Legacy `source` label is provenance and never a variant
alias. The top-level Joint order and Pose count must exactly match normalized content.
Only recognized tracked-format Joint aliases and explicit units may be converted;
unknown units, incomplete joint sets, non-finite values, invalid transitions, raw-only
values, and incompatible variants are rejected/report-quarantined. Gripper/raw fields
are reported but not silently repurposed. A successful write receives a fresh UUID
filename and preserves only a safe identifier-like `source` label, basename, digest, and
bounded metadata; path-like source provenance is rejected. One invocation is capped at
2,000 scanned directory entries, 1,000 selected JSON files, 32 MiB input, 2,000 actions,
20,000 keyframes, and 2,000 report entries.

The importer validates scope and converts in separate bounded passes. A hostile local
writer could mutate an explicitly selected source between those passes; this is outside
the intended local single-operator threat model. Operators must import only a preserved,
reviewed export.

## Network, audit, and backup safety

The default server is loopback-only. LAN requires explicit enablement, a concrete private
bind, a strong token, authentication on REST/control/WebSocket/Vision, bounded control
rate/session tables, and an exact allowlist. Stage 8 LAN browser Origins must use HTTP
and the exact API bind host (the UI port may differ); wildcard, public, cross-host,
opaque, and HTTPS Origins fail closed. The built-in server provides no TLS termination,
proxy trust, discovery, UPnP, or tunnel and must be used only on a trusted private network
until a separate deployment review exists.

Long-term credentials are accepted only from the Bearer header and exchanged for a
short-lived HttpOnly `SameSite=Strict` cookie; they never enter a URL or browser storage.
Established Robot WebSocket and Vision streams reauthorize every publish/frame. Priority
Stop stays authenticated but is not delayed by the ordinary control rate bucket.
Structured audit is bounded and records request/command/robot/source/mode/preflight/
outcome/duration/error evidence where available. Tokens/sessions, HTTP URLs, file URIs,
POSIX/Windows paths, and full serial identity are redacted before any sink.

Backup export excludes secrets, device/serial/runtime/log/camera/local-path data and
Calibration by default. Import accepts bytes only, validates canonical digests and
explicit migrations, and allows `reject` or `skip` collisions—never overwrite. A valid
preview produces one five-minute, one-use grant bound to digest/options. Calibration
requires explicit export/preview/restore opt-in.

Restore shares the repository maintenance gate and durably publishes a bounded WAL
transaction before the first exact-revision create. Failure/cancellation removes only
the transaction's exact revisions/absent Calibration identities. A post-replace fsync
error is treated as committed and compensated. The journal is cleared only after full
commit or proven rollback. Application startup recovers any surviving intent before
serving traffic; invalid/incomplete recovery blocks startup. This is process-crash atomic
for one supported backend writer over server-owned repositories, not a guarantee for
manual edits, multiple writers, disk loss, or unsupported filesystems.

The release SPA uses local relative assets. Missing API/assets remain 404, extensionless
non-API refresh may fall back to no-store `index.html`, and CDN-backed `/docs`/`/redoc`
are disabled. Offline/static UI must never cache or fabricate Robot status, control API,
WebSocket, Vision stream, or online safety state.

## Non-negotiable restrictions

The committed/default/autonomous path must not scan/read/write Servos, enumerate devices,
open a serial port, auto-connect, auto-Home, change torque, read or overwrite real
Calibration, or introduce a debug bypass. Future field diagnostics/Calibration/motion
may perform only the explicitly authorized bounded operations above and only after the
complete matrix passes. Do not expose raw-device access, arbitrary Python execution,
arbitrary file access, or raw-servo HTTP/WebSocket endpoints. Do not commit ports,
secrets, local Calibration, multi-turn runtime data, production Poses/Motions/Drafts,
restore/Draft save-intent recovery data, import quarantine data, audit logs, or captured
media.

No API route may import a concrete hardware bus or driver. No later Stage may add a
parallel motion path around the Stage 3 gateway.

## Legacy and evidence boundary

Legacy commit `ff8bbda0c2222cb57951c7913f7f12f5777b98fa` is read-only evidence. Its
V1 URDF incorrectly contains J10; its fixed-order kinematics, name-based unit conversion,
large controller bridge, mutable continuous stream, and unbounded WebSocket behavior are
not product architecture. No mesh, Legacy controller, local Calibration, serial setting,
runtime data, backup, untracked file, SDK, or binary was copied or executed.

The provisional model transcription, retained Base/Tool behavior, and Stage 4 importer
characterization use only the pinned tracked source. The importer tests use synthetic
fixtures; they do not inspect the actual Legacy checkout, ignored/local data, recorded
user motions, or Calibration. Numeric hardware values remain field-verification items.

## Stage 3 completion evidence

Stage 3 recorded 226 passing backend tests and 54 passing frontend tests, green
lint/type/format/build/schema/lock/dependency-audit gates, Fake Clock and Jog-expiry
coverage, bounded WebSocket behavior, desktop/mobile/breakpoint browser acceptance, an
empty final browser console, and focused route/import/hardware/camera isolation. The
executed evidence truthfully supports:

```text
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
All Stage 3 motion verification used Dry Run or Fake adapters.
```

No forbidden serial, OpenCV, RealSense, Feetech, `scservo`, or `pyaudio` module was
loaded. The pinned Legacy checkout and excluded ignored/local data remained untouched.

## Stage 4 evidence status

Stage 4 preserves the Dry Run/Fake-only boundary in executed checks. The root gate passes
273 backend tests and the final frontend suite passes 71 tests across 8 files; the focused
route/import/storage/hardware-isolation suite passes 65 tests, and its forbidden loaded
module inventory is `[]`. Locked-runtime and production dependency audits pass, desktop
1440 x 960 and exact 390 x 844 mobile browser QA used Dry Run only with no horizontal
overflow, and the final browser console warning/error list is `[]`. No
serial/Servo/camera/microphone path was loaded or used.

The initial independent audit identified P1 issues that implementation agents addressed.
Its first re-review found additional client-snapshot/error, importer, and aggregate-bound
issues. Fixes landed and the final independent re-review passes P1=0/P2=0. The combined
main post-fix gate also passes, so Stage 4 is GREEN and complete. Its containing commit's
exact SHA/remote state is recorded by Stage 5 because the commit cannot contain its own
SHA. The Stage 3 evidence above remains valid only for its committed scope.

## Stage 5 evidence status

Stage 5 remains Dry Run/Fake-only. The final root gate passes 352 backend tests and 85
frontend tests; the focused route/import/hardware/trajectory/playback suite passes 128
tests. Ruff, strict mypy, Ruff format, ESLint, TypeScript, Vite build, schema
determinism, lock checks, Python/npm vulnerability audits, and `git diff --check` pass.
Browser acceptance preflighted and played only isolated logical samples, reported
`hardware_accessed=false`, had no page-level horizontal overflow, and produced console
warnings/errors `[]`.

Independent review found and closed P2 issues in cooperative compiler cancellation,
preflight ownership, preview-cache event-loop affinity, public fault sanitization,
rate-change time continuity, cross-tab status freshness, durable command errors,
lifecycle-exact controls/priority Stop, atomic cross-source admission, and stale prepared
identity rejection, lifecycle epoch fencing, and cancellation-safe Stop finalization.
Lifecycle invalidation after preflight has claimed state also performs Stop before its
epoch conflict is returned, preserving `STOPPED` over generic `FAULTED`. Regression tests
also cover ordinary post-submit rollback and cancellation-safe global Stop hook
completion, plus API update/delete fencing at the execution claim. Final independent
review passes P1=0/P2=0. Stage 5
does not add a serial/camera dependency or persisted user schema, and cannot authorize
Real Playback.

## Stage 6 evidence status

The current gate passes 393 backend tests plus an independently rerun 36-test Stage 6
domain/repository/coordinator/actions/API selection, and 174 frontend tests across 12
files plus an independently rerun 89-test Studio selection. Ruff/format and strict mypy
pass across 141 backend files, ESLint/TypeScript/build pass, two fresh schema generations
are byte-identical and the final temporary schema tree matches tracked artifacts,
`uv lock --check` passes for 44 packages, and npm audit reports zero vulnerabilities.
The final independent integrated and code-quality re-review reports P1=0/P2=0.

Regressions cover strict nested persisted identity, corrupt Draft quarantine, disjoint
storage roots including case and Unicode aliases, default-edge recovery, canonical
Legacy trust and provenance preservation, fail-closed formal-save recovery and exact
abandon, structured conflict scope and local-preserving fork, cancellation-shielded
commit, source-revision/playback lease ordering, compile/save lock ordering, and
persisted-keyframe `STUDIO` Goto linearized against autosave. Bounded backend
formal-save/robot-action collaborators and composed frontend Draft/Motion/Pose/navigation
hooks close the God-Object findings. The final post-refactor isolated real-backend browser
run covers full Save, an external Motion conflict without overwrite, local-preserving
fork/Save As, null recovery markers, and a fresh 390 x 844 mobile drawer. Earlier exact
responsive measurements cover container-local Timeline overflow and focus restoration;
all desktop/mobile console warnings/errors are `[]`.

Stage 6 is contained by pushed commit
`37783bdf8c01146d3a312980dbe4a25716e5468c`. Its Python runtime dependency audit was
not rerun because the Stage added no dependency and changed neither lockfile; no passing
result is inferred. None of this evidence authorizes Real preview, Real playback, or any
physical Studio Goto.

## Stage 7 evidence status

The current automated gate passes 432 backend tests with one known Starlette/httpx
deprecation warning, including 34 focused Vision core/Follow/API tests. It passes 190
frontend tests across 14 files, including 16 focused Vision client/page tests. Ruff,
Ruff format, and strict mypy pass across 168 backend files; ESLint, TypeScript, Vite
build, deterministic schema generation, the 44-package lock check, and npm audit with
zero reported vulnerabilities pass. No Python runtime vulnerability audit was rerun
because Stage 7 adds no package/lock change; no result is inferred.

Policy-first/lazy-import Spy coverage proves denied camera requests cannot import
OpenCV or call `VideoCapture`, and constructor/capability reads do not open a camera.
The full task opened/enumerated no camera and downloaded/recorded no frame, model, or
cascade. Synthetic detector/tracker tests state explicitly that these are fixtures, not
general models. Hardware remained Dry Run/Fake-only and all accepted Vision commands
used the high-level Motion Safety Gateway path.

The real application passed 1440×960 and 390×844 Synthetic manual selection (LOCKED
98%), person detection (LOCKED 98%), Follow ACTIVE with EMA/tuning lock, accepted
gateway preflight and completed command with `hardware_accessed=false`, operator Stop,
lease expiry after navigation/unmount, exact mobile width bounds, and console
warnings/errors `[]`. Final independent audit reports P1=0/P2=0. The dedicated Stage 7
commit `dedbdabb9a35aefea01df05f0652214428305a93` is pushed; Real Follow stays blocked.

## Stage 8 evidence status

The worktree contains the deny-by-default Real boundary, Fake Bus/Real executor,
protected Calibration workflow, security/audit, WAL backup/startup recovery,
same-backend/no-CDN hosting, CI, and release documentation described above. The final
software gate passes 563 backend and 201 frontend tests, static/schema/dependency gates,
52 isolation tests, and 1440×960/390×844/850/830 browser acceptance with console `[]`.
The independent audit closes P1=0/P2=0 after 74 focused tests. Stage 8 commit
`4f7a75606aacb3fc93128445d7487ff196ce9efb` is pushed; the Draft PR is recorded in the
Stage report. Every physical field
item, Feetech adapter verification, verified V1/V2 kinematics, live camera, and Real
motion result remains pending.

## Commissioning authorization fix evidence

The follow-up fix passes 591 backend tests, 215 frontend tests across 18 files, an
88-test focused commissioning selection, and a 102-test safe-gate hardware/camera
isolation selection. Ruff/format, strict mypy across 214 files, ESLint, TypeScript, the
1,642-module build, two fresh deterministic schema generations, lock compatibility,
`pip-audit`, `npm audit`, secret scan, and diff checks pass. The browser completed an
isolated Fake READ_ONLY flow from no Calibration through Revision 1, revoked the old
session after save, kept Field Acceptance pending and every motion control blocked, and
reported console warning/error `[]`. No physical adapter or camera source was used.

## Final pre-merge hardening evidence boundary

The earlier counts above are historical baselines. Results for the three-purpose staged
acceptance change are recorded only after the final worktree commands, focused safety
matrix, browser Fake workflow, isolation checks, and both CI triggers complete. Until
then they are pending, not inherited from the previous green baseline.

The final local software worktree passes 629 backend tests (one existing Starlette/httpx
deprecation warning), 230 frontend tests across 19 files, and the exact 13-file CI
hardware/camera/commissioning/Kinematics isolation selection with 140 tests. Ruff,
format check, strict mypy, ESLint, TypeScript, the 1,646-module Vite build, deterministic
schemas, lock/compatibility, and Python/npm vulnerability gates pass. The Fake browser
completed all 12 V2 joint directions and Joint acceptance with console warning/error
`[]`, while Kinematics, physical Stop, and production capabilities remained blocked.
The final re-audit closes P1=0/P2=0 after 38 focused tests and records one safe P3
`DeviceDiagnosticsService` concentration/decomposition debt. Final-head push/pull-request
CI remains a separate delivery-time gate.

Regardless of later software results, Fake commissioning evidence is not physical field
acceptance. Feetech goal-write/Stop behavior, the physical E-stop, physical joint timing,
Real V1/V2 Kinematics, backlash, flex, TCP measurement, camera latency, and Real Follow
gains remain field-verification required.
