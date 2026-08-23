# Architecture

## Context

MOMO Studio is web-first and local-first. React supplies one operator UI that can run in a browser now and may be wrapped by Tauri later. FastAPI owns transport concerns and delegates robot lifecycle work to application services. Domain code expresses product and safety invariants without importing the web framework or a hardware SDK.

Stage 2 adds a single-active-robot Dry Run core. It does not add motion, kinematics, real hardware, Fleet, or background device workers.

```text
React frontend (1 Hz REST polling)
  -> FastAPI routes and response schemas
      -> RobotApplicationService (one async command lock)
          -> RobotManager -> primary RobotRuntime
          -> ProfileService -> ProfileRepository -> reviewed YAML examples
          -> CalibrationService -> CalibrationRepository -> read-only JSON examples
          -> RuntimeStateRepository -> untracked atomic JSON
          -> RobotDriver port -> in-memory DryRunRobotDriver
```

Dependencies point toward domain and port contracts. The composition root builds the repositories and application services and explicitly injects a driver factory that constructs only `DryRunRobotDriver`; `RobotApplicationService` has no implicit concrete-driver fallback. API routes receive that application service through FastAPI dependencies and never import a raw servo driver. There is no Feetech adapter, serial dependency, hardware scan path, or module-level robot singleton.

## Stage 2 runtime

`create_app()` loads typed settings and builds a fresh service graph for that app instance. Construction may read reviewed Profile/Calibration examples and the configured untracked Dry Run runtime file; it does not connect, scan, home, calibrate, import a servo SDK, open a serial port, or start a thread. A saved runtime state is restored only when its robot ID, variant, Profile Fingerprint, exact joint set, units, finite values, and logical limits match. The in-memory runtime always starts `DISCONNECTED`, even if the persisted diagnostic record says it was previously connected.

The manager owns exactly one runtime:

```text
robot_id = primary
active variant = configured V1 or V2
driver = DryRunRobotDriver
```

This identity-aware boundary is extensible without exposing Fleet behavior. Variant changes replace the `primary` runtime and driver only while disconnected; they never connect automatically. Connect, disconnect, Stop, status reads, diagnostics, and variant changes share one `asyncio.Lock`, so lifecycle commands cannot overlap.

The Dry Run driver stores only a validated joint-value map in memory. Connect exposes the restored or Profile Home state, disconnect is idempotent, and Stop is idempotent without changing position. It offers no position-writing method. `hardware_accessed` is always `false`, and `raw_positions` is always `null` in Stage 2 status.

## HTTP surface

Stage 2 exposes:

- `GET /api/v1/health`
- `GET /api/v1/meta`
- `GET /api/v1/meta/product-scope`
- `GET /api/v1/robot`
- `GET /api/v1/robot/profile`
- `GET /api/v1/robot/diagnostics`
- `POST /api/v1/robot/connect`
- `POST /api/v1/robot/disconnect`
- `POST /api/v1/robot/stop`
- `PUT /api/v1/robot/variant`
- `GET /api/v1/calibration/status`

Connect accepts no body, query string, or mode selector, so a client cannot request Real behavior. API failures use the structured `code`, `message`, `details`, and optional `request_id` envelope; tracebacks are not returned. There are no FK, IK, Jog, Move, Home, Pose, Motion, playback, calibration-write, arbitrary-file, raw-servo, or code-execution endpoints.

## Frontend data flow

`RuntimeStatusProvider` fetches health, metadata, robot status, Profile, Calibration status, and diagnostics together, then polls once per second. It verifies the returned Stage 2 policy (`DRY_RUN`, hardware access `DISABLED`, real motion false, hardware not accessed) before accepting the payload. Network failure retains the last robot payload as stale data, marks the backend unavailable, and stops polling when the provider unmounts.

Control presents lifecycle commands and read-only joint state. Settings presents V1/V2 selection, Profile provenance/fingerprint, Calibration variant/Profile/joint/mapping compatibility, and safe diagnostics. Studio, Library, and Vision remain unavailable. No page contains a motion control or Real-mode switch.

## Configuration

Configuration precedence is:

1. typed safe defaults;
2. repository `config/default.yaml`;
3. optional uncommitted `config/local.yaml`;
4. environment variables prefixed `MOMO_`.

Stage 2 requires all three gates:

```text
control_mode: DRY_RUN
real_motion_enabled: false
hardware_access_policy: DISABLED
```

`ControlMode` and `HardwareAccessPolicy` are separate contracts. `REAL`, `READ_ONLY`, and `FULL` remain vocabulary for a later reviewed Stage, but selecting any of them now fails settings validation before an adapter can be created. `serial_port` is an inert compatibility field and is never opened. Repository-relative paths resolve from the source checkout, not the process working directory.

## Persistence boundaries

Profiles are loaded only from the fixed `v1.example.yaml` and `v2.example.yaml` names under the configured Profile directory. Calibration diagnostics are loaded only from the fixed example filenames under the configured Calibration directory; Stage 2 provides no calibration writes.

Dry Run runtime state is stored as schema-versioned JSON at `data/runtime/robots/primary.json` by default. Writes use a temporary sibling, flush and `fsync`, then `os.replace`. Robot IDs are filename-constrained and resolved paths must remain inside the configured directory. Invalid, incompatible, or corrupt state is quarantined and the runtime falls back to Profile Home. Runtime files remain untracked and contain no serial port, secret, or real calibration.

Pose and Motion repositories remain Stage 1 contracts only. Future persistent entities use UUID filenames rather than display names. Their schemas cannot change without compatibility analysis, round-trip tests, regenerated JSON Schema, and a Stage decision.

## Unit and safety boundaries

Product/UI joint values use explicit `mm` or `deg` units. Mapping helpers operate on the Profile's declared scale and the Calibration document's direction/Home; they never infer units from `joint_id`. A future kinematics adapter will convert at named boundaries to `m` and `rad`.

Stage 2 mapping and reachability functions are pure calculations and are not reachable from an HTTP motion command. Real motion remains blocked until a later Stage supplies verified non-template Profiles and Calibration, a real adapter, operator intent, and one reviewed application safety entry point.

## Repository structure

- `backend/src/momo/api` - app factory, dependencies, route composition, API schemas, and error translation.
- `backend/src/momo/application` - the single-active manager and lifecycle/Profile/Calibration services.
- `backend/src/momo/domain` - immutable models, fingerprints, runtime contracts, mapping, validation, and errors.
- `backend/src/momo/ports` - typed protocols for drivers and repositories.
- `backend/src/momo/adapters/hardware` - only the in-memory Dry Run driver in Stage 2.
- `backend/src/momo/adapters/storage` - Profile, read-only Calibration, and atomic runtime-state adapters.
- `frontend/src/api` - transport client and response types.
- `frontend/src/app`, `layouts`, `components`, `pages` - composition, shared runtime state, chrome, and routes.
