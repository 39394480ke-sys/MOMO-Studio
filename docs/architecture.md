# Architecture

## Context and current Stage

MOMO Studio is web-first and local-first. React supplies one operator UI that can run
in a browser now and may be wrapped by Tauri later. FastAPI owns transport concerns and
delegates use cases to application services. Domain code expresses product, kinematics,
and safety invariants without importing the web framework or a hardware SDK.

Stage 2 established one Active Robot, Profile/Calibration diagnostics, an in-memory Dry
Run driver, and atomic runtime state. Stage 3 is complete and adds only Dry Run
kinematics and control. Real hardware, Pose/Motion persistence, trajectory playback,
Studio authoring, and Vision remain outside the Stage 3 boundary.

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

Every movement source—Joint Move, Joint Jog, Home, Cartesian Jog, Move Pose, and all
later Goto/Playback/Studio/Vision sources—must submit an immutable command to the same
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

Frontend component tests and desktop/mobile/breakpoint browser acceptance pass. The
checked widths have no horizontal overflow and the final browser console is empty.

## Configuration and persistence

Safe default loading uses typed defaults, tracked `config/default.yaml`, then `MOMO_*`
environment values. It does **not** probe or read ignored `config/local.yaml`. A caller
may opt in to one specific local file only by explicitly passing `local_config_path` to
the settings loader; that explicit file is then merged before environment overrides.
Throughout Stage 3:

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
kinematics fingerprints and stale state sequences. Pose and Motion repositories remain
future adapters.

## Repository structure

- `backend/src/momo/domain/kinematics` — model/fingerprint and FK/IK result contracts.
- `backend/src/momo/ports/kinematics.py` — SI adapter protocol and named unit boundaries.
- `backend/src/momo/adapters/kinematics` — mesh-free FK/IK implementation.
- `backend/src/momo/application/services` — lifecycle, kinematics, gateway, executor
  coordination, command status, and Jog lease use cases.
- `backend/src/momo/api` — versioned REST/read-only WebSocket transport only.
- `backend/src/momo/adapters/hardware` — Dry Run adapter only in Stage 3.
- `backend/src/momo/adapters/storage` — Profile, example Calibration, and runtime state.
- `kinematics_models` — V1/V2 provisional mesh-free documents.
- `frontend/src` — typed transport, shared runtime state, responsive pages/components.

Stage 3 design decisions are recorded in ADR 0009 and ADR 0010. Completion evidence,
tests, browser verification, and known limitations are tracked in the Stage 3 report.
