# ADR 0022: Unified product motion runtime

- Status: Accepted
- Date: 2026-08-29

## Context

MOMO Studio now has one product UI and one set of Robot, Motion, Library, Studio, and
Vision APIs.  The repository also contains three distinct implementation concerns:

1. the validated in-memory DRY_RUN product runtime;
2. the narrowly scoped Real-device commissioning services; and
3. a production `RealMotionExecutor` whose outer product composition had not yet been
   connected when this decision was accepted.

Generic composition names made these concerns look interchangeable.  That ambiguity
would make it easy to connect the redesigned UI directly to a Legacy controller, add a
second Real-only API path, or hide a hardware adapter behind the existing simulation
bootstrap.  Any of those choices would duplicate product logic and bypass the single
Motion Safety Gateway.

## Decision

MOMO Studio is one product with one inward dependency chain:

```text
React UI
  -> versioned high-level API
      -> application services
          -> MotionSafetyGateway
              -> MotionExecutor port
                  -> DRY_RUN implementation or reviewed REAL implementation
```

DRY_RUN and REAL are execution backends, not separate products, frontends, route sets,
domain models, or persistence schemas.  V1 and V2 remain hardware variants.

The product compositions are named explicitly:

- `build_simulation_robot_service` constructs the in-memory robot lifecycle;
- `build_simulation_product_services` constructs the product services around
  `DryRunMotionExecutor`;
- `ProductServices` contains only shared application services and port-typed executors;
- `build_real_product_composition` supplies `RealRobotDriver`,
  `RealCommandMotionExecutor`, and `RealPlaybackService` from a separate outer module.

Real-device commissioning remains a separate outer composition in
`release_bootstrap.py`.  Its read-only, Raw-direction, and bounded single-joint ports are
not production motion executors and cannot be substituted for one.

The production REAL composition must:

- implement the existing `RobotDriver` and `MotionExecutor` ports, or a reviewed
  successor port introduced by a separate ADR;
- reuse the same application services, command contracts, Motion Safety Gateway,
  persistence contracts, and frontend;
- be selected only in an explicit outer composition after complete backend-derived
  authorization;
- preserve exact Profile `enabled_joints`, units, Calibration, limits, state sequence,
  Stop semantics, and capability-specific evidence;
- fail closed rather than falling back to DRY_RUN when REAL was requested.

Legacy MOMOarm/MOMO_RobotARM code remains read-only evidence pinned to the recorded
Legacy source commit.  Only reviewed low-level behavior may enter MOMO Studio through a
new adapter.  The product runtime must never import a Legacy controller, global robot
instance, local runtime state, Calibration, serial configuration, or raw-servo surface.

Executable architecture tests enforce the inward dependency rules and restrict adapter
construction to explicit outer compositions and migration tools.

## Consequences

- Repository defaults and ordinary development runtime behavior remain DRY_RUN; no Real
  motion is enabled by tracked configuration.
- REAL is available only through the explicit field composition after all local,
  evidence, device, operator-session, and purpose gates pass.
- REAL and DRY_RUN now share one integration seam instead of separate frontend/backend
  paths.
- Commissioning can continue to use its narrower purpose-built ports without becoming a
  hidden production executor.
- A future commit that imports a concrete adapter from API, application, domain, or ports
  fails the architecture test suite.

## Implementation note — 2026-08-29

The decision is now implemented. The production adapter is inert until an authorized
connect call, never scans, targets only the configured IDs, and reuses the existing
prepared-trajectory executor. Cancellation requests software Hold and reports
`SAFETY_STATE_UNCERTAIN`; it never represents that result as a physical E-stop. REAL
playback currently fixes rate at 1.0 and rejects pause, resume, and loop controls.

Authorization clarification (2026-08-30): ADR 0023 corrects the first implementation's
unsafe interpretation of “unified.” The shared runtime does not merge capability grants.
Joint, Cartesian, Playback, and Vision retain ADR 0019's capability-specific evidence,
and the REAL executor may consume only the exact trajectory and digest produced by final
preflight. Where this implementation note conflicts with ADR 0019 or ADR 0023, the later
capability-bound decision controls.

## Alternatives

- Let the UI call the Legacy controller directly: rejected because it duplicates state,
  authorization, error handling, and motion semantics.
- Add `/real/*` copies of existing motion routes: rejected because it creates two product
  APIs and invites behavioral drift.
- Put a `REAL` branch inside the DRY_RUN bootstrap: rejected because permissive
  configuration could silently construct hardware in the simulation composition.
- Copy the entire Legacy project into this repository: rejected because it imports
  incompatible architecture, device-local data, implicit assumptions, and unreviewed
  dependencies.
