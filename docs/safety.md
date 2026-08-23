# Safety

## Stage 3 safety boundary

Stage 3 is complete and remains Dry Run only. It adds FK, IK, Joint Move/Jog, Home,
Cartesian Jog, Move Pose, command status, and a read-only status WebSocket while
remaining structurally unable to command physical hardware:

- settings require `control_mode=DRY_RUN`, `real_motion_enabled=false`, and
  `hardware_access_policy=DISABLED`;
- the composition root may inject only in-memory Dry Run motion implementations;
- no serial or Feetech adapter/dependency is available through the product path;
- no startup, Connect, route, WebSocket, executor, or kinematics operation may enumerate,
  scan, read, write, Home, torque, calibrate, or move a device;
- Robot status, FK, command-status, Stop, diagnostics, lifecycle, and WebSocket contracts
  that carry hardware-access evidence report `hardware_accessed=false`; accepted-motion,
  IK, and Jog-lease DTOs do not claim a field they do not define, while their execution
  remains structurally hardware-free;
- API routes depend on application services and never import a concrete driver;
- no raw Servo, arbitrary register, arbitrary file, arbitrary Python, or driver-selection
  endpoint exists.

Focused route/import isolation tests, the complete test/build gates, and browser
acceptance passed. The Stage 3 report records the executed evidence; design documentation
alone remains insufficient proof for any later capability.

## Provisional kinematics are not Real authority

The V1 and V2 mesh-free models are `PROVISIONAL_DRY_RUN`. V1 is exactly `j11`-`j15`
with no rail; V2 is `j10`-`j15`, with J10 prismatic. Model fingerprints establish exact
software compatibility only.

Physical link geometry, frames, axes, signs, zero references, TCP, joint limits,
workspace, speed, acceleration, FK reference points, IK tolerances, and Cartesian path
accuracy remain unverified. Therefore provisional models categorically block:

- Real Cartesian Jog or Move Pose;
- Real playback containing Cartesian segments;
- Real vision follow;
- any claim that successful Dry Run IK is physically reachable.

UI/domain values remain `mm`/`deg`; adapter values are `m`/`rad`. Only named boundary
functions may convert them. Unit conversion cannot depend on the name `j10`.

## Unified Motion Safety Gateway

There is one reviewed application admission point for every movement source. Joint
Move, single/continuous Joint Jog, Home, Cartesian Jog, Move Pose, and later Goto,
Playback, Studio, and Vision commands may not call an executor or driver directly.

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
accepted sample. It is not a physical emergency-stop claim. A later Real Stage must use
verified outcomes, expose uncertainty, and remind the operator to use a physical E-stop.

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

## Lifecycle, Profile, Calibration, and runtime trust

Only the active Profile's explicit `enabled_joints` determines membership. V1 never
contains J10; V2 requires it in `mm`. Fixed six-joint arrays, dictionary-order chains,
`arm_a`, and joint-name unit branches are prohibited.

Committed Profiles, Calibration documents, and kinematics models are templates or
provisional Dry Run data. They do not authorize Real use. Calibration compatibility
still requires exact variant, Profile fingerprint, joint set, Servo IDs/modes, raw
bounds/Home, direction, and completeness, but Stage 3 performs no calibration write or
device read.

Runtime state remains path-confined ignored data. Atomic restore fails closed on corrupt
JSON, wrong schema/identity/variant/Profile, wrong joint/unit set, non-finite or
out-of-range values. A saved connection never reconnects a device. Stage 3 command
admission separately checks current state sequence and Kinematics fingerprint.

## Non-negotiable restrictions

Do not scan/read/write Servos, enumerate devices, open a serial port, auto-connect,
auto-Home, change torque, read or overwrite real Calibration, or introduce a debug
bypass. Do not expose raw-device access, arbitrary Python execution, arbitrary file
access, or raw-servo HTTP/WebSocket endpoints. Do not commit ports, secrets, local
Calibration, multi-turn runtime data, production Poses/Motions, or captured media.

No API route may import a concrete hardware bus or driver. No later Stage may add a
parallel motion path around the Stage 3 gateway.

## Legacy and evidence boundary

Legacy commit `ff8bbda0c2222cb57951c7913f7f12f5777b98fa` is read-only evidence. Its
V1 URDF incorrectly contains J10; its fixed-order kinematics, name-based unit conversion,
large controller bridge, mutable continuous stream, and unbounded WebSocket behavior are
not product architecture. No mesh, Legacy controller, local Calibration, serial setting,
runtime data, backup, untracked file, SDK, or binary was copied or executed.

The provisional model transcription and retained Base/Tool behavior are documented in
the kinematics audit and characterization. Numeric values remain field-verification
items.

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
