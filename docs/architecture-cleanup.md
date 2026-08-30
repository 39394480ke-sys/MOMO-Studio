# Architecture cleanup ledger

This ledger records the product-architecture cleanup started on 2026-08-29.  It is a
current engineering guide, not historical Stage evidence and not authorization for Real
hardware.

## Target shape

MOMO Studio has one UI, API, domain model, safety gateway, and persistence model.  The
only intended execution variation is behind application-owned ports:

```text
MOMO Studio product flow
  -> MotionSafetyGateway
      -> MotionExecutor
          -> DRY_RUN adapter
          -> reviewed REAL adapter (explicit field-only composition)
```

## Keep

| Area | Reason |
|---|---|
| React Control/Library/Studio/Vision/Settings application | One operator product and one shared state vocabulary |
| Versioned `/api/v1` high-level routes | Stable transport boundary; routes do not own drivers |
| Domain/application/ports/adapters layering | Correct dependency direction and testable hardware seam |
| Motion Safety Gateway | One admission point for every product motion source |
| Dry Run driver and executor | Validated simulation backend |
| Device commissioning services | Narrow read-only, Raw-direction, and single-joint field workflows |
| Profile/Calibration/Kinematics/evidence contracts | Explicit robot identity, units, limits, and authorization inputs |

## Refactor

| Item | Current action | Completion condition |
|---|---|---|
| Generic bootstrap names | Renamed to explicit simulation builders and service bundle | No caller can mistake the current product graph for production REAL execution |
| Layer rules documented only in prose | Added executable AST dependency tests | API/application/domain/ports cannot import concrete adapters or Legacy controllers |
| DRY_RUN/REAL product relationship | Recorded ADR 0022 and authorization clarification ADR 0023 | Both modes share product logic and differ only at reviewed outer adapters; every REAL capability still has its own evidence grant |
| Production REAL composition | Implemented in a separate `real_bootstrap.py` outer composition | REAL supplies lifecycle, command, and playback ports; an unavailable or incoherent field configuration fails closed and never falls back to DRY_RUN |
| Control workspace UI | Extracted one `ControlWorkspaceView` and shared product control panel | DRY RUN, production REAL, and restricted commissioning reuse the same view; controller adapters provide commands and state without replacing the page |

## Reviewed Legacy mapping

| Legacy capability | Allowed migration | Not allowed |
|---|---|---|
| Explicit serial lifecycle | `FtServoProductionBus` behind `ServoBus`, exact configured device fingerprint and ID allowlist | Scan, auto-connect, startup connect, or arbitrary device selection |
| Joint state readback | `RealRobotDriver` converts raw readback into Profile-bound `JointState` with explicit units | Raw dictionaries or fixed six-joint assumptions |
| Joint goal/Stop behavior | `RealMotionExecutor` receives immutable prepared trajectories; software Stop reads present positions and requests Hold while reporting physical safety as uncertain | Raw-servo HTTP, direct frontend calls, or success on uncertain Stop |
| Mapping and direction knowledge | Existing named Profile/Calibration boundary conversions plus exact fingerprint checks | Copying Legacy Calibration/runtime files or `arm_a` assumptions |

## Remove or reject

- A second “old UI” or “real UI”.
- Duplicated `/real/*` motion APIs.
- API routes importing drivers, SDKs, serial modules, or Legacy controllers.
- Application services selecting concrete adapters.
- Global robot singletons, fleet controls, implicit V1/V2 joint sets, and display-name
  persistence.
- Automatic scan, Home, Calibration mutation, torque enable, or motion at startup.
- Silent fallback from requested REAL execution to DRY_RUN.

## First cleanup increment

- [x] Simulation composition is explicit in builder and service-bundle names.
- [x] Product and commissioning compositions remain separate.
- [x] Architecture dependency tests cover domain, ports, application, API routes,
  concrete adapter construction, simulation composition, and Legacy imports.
- [x] ADR 0022 defines the only supported future REAL integration shape.
- [x] Characterized pinned Legacy commit `ff8bbda0` and migrated only explicit-ID
  lifecycle, readback, bounded goal writes, stream setup, torque-on-before-write, Hold,
  and torque-off-on-close behavior.
- [x] Adapted the existing `RealMotionExecutor` behind the product `MotionExecutor` and
  playback ports with purpose-bound authorization and per-sample context revalidation.
- [x] Added a fail-closed production REAL composition selected only by an explicitly
  supplied local field configuration and complete acceptance evidence.
- [x] Added synthetic-SDK tests proving construction is inert and writes cannot escape
  the authorized exact joint/Servo-ID set.
- [x] Removed the separate Legacy-style REAL control page. The modern Control workspace
  is now the only view; DRY RUN uses the product simulation controller, production REAL
  uses the reviewed product gateway, and restricted field testing uses a purpose-bound
  commissioning controller adapter behind the same UI components.
- [x] Reduced the commissioning controller to its characterized single-joint workflow.
  Group move, Home, and Cartesian product actions are disabled there; the obsolete public
  multi-joint commissioning write route and its bus capabilities were removed. Product
  multi-joint and Cartesian commands enter only through `MotionSafetyGateway -> MotionExecutor`.
- [x] Product Cartesian commands are prepared as immutable, time-stamped TCP-path IK
  samples. Both executors consume those reviewed samples instead of relabelling a joint
  interpolation as Cartesian motion.
- [x] Cartesian hold uses the same backend-owned 250–500 ms deadman lease pattern as
  joint hold. The browser sends one start, renewable heartbeats, and one Stop; it never
  loops finite motion commands.
- [x] The product motion service emits one 25 Hz software trajectory and the production
  STS3215 adapter applies each sample as one synchronized multi-axis goal frame. The
  adapter no longer starts a second per-sample Servo Profile interpolation. Readback is
  checked against a bounded following window and the final goal receives a bounded
  settle check.
- [x] REAL has one product control surface and one runtime, but not one undifferentiated
  grant. Joint/Home/Pose Goto require current Joint Motion acceptance. Cartesian also
  requires current Kinematics verification and Cartesian acceptance. Studio/Library
  Playback requires Playback acceptance and additionally requires the Cartesian gates
  when its exact prepared trajectory contains any `CARTESIAN_LINEAR` segment. Vision
  Follow retains its independent acceptance and Kinematics gates. These production
  commands cannot be used to create their own acceptance evidence; the only implemented
  pre-production write workflow remains bounded `COMMISSIONING_MOTION_TEST`.
- [x] Settings no longer owns `/device/connect` or `/device/disconnect`; product lifecycle
  is exclusively `/robot/connect`, `/robot/disconnect`, and `/robot/stop`. The old
  Commissioning control, raw-direction, and hardware panels were removed from the product
  frontend. Commissioning backend services remain isolated maintenance capabilities.

## Scope boundary

The code-side composition is complete, but the repository defaults remain DRY_RUN,
hardware `DISABLED`, and production adapter disabled. This work does not constitute
physical acceptance. A field operator must explicitly select a device-local REAL
configuration, confirm the physical E-stop, issue a short-lived `REAL_MOTION` session,
and connect the exact configured serial identity before any production motion. A
`REAL_MOTION` session contains only the scopes backed by current capability-specific
evidence and freezes the evidence UUIDs used for each scope; it is never upgraded in
place. All sources share the reviewed execution path, while Joint, Cartesian, Playback,
and Vision remain separately gated as defined by ADR 0019 and ADR 0023. REAL pause, rate
changes, and looping remain deliberately unavailable; software Hold never claims a
physical stop.
