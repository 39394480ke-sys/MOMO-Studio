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
          -> future reviewed REAL adapter
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
| DRY_RUN/REAL product relationship | Recorded ADR 0022 | Both modes share product logic and differ only at reviewed outer adapters |
| Production REAL composition | Deferred, not hidden in the simulation bootstrap | A later reviewed composition supplies both lifecycle and motion ports and fails closed |

## Migrate later

| Legacy capability | Allowed migration | Not allowed |
|---|---|---|
| Explicit serial lifecycle | Adapter behind a port with exact configured device identity | Scan, auto-connect, startup connect, or arbitrary device selection |
| Joint state readback | Typed Profile-bound `JointState` with explicit units | Raw dictionaries or fixed six-joint assumptions |
| Joint goal/Stop behavior | Prepared command execution with bounded cancellation and truthful uncertainty | Raw-servo HTTP, direct frontend calls, or success on uncertain Stop |
| Mapping and direction knowledge | Reviewed tests/evidence tied to exact Profile and Calibration | Copying Legacy Calibration/runtime files or `arm_a` assumptions |

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
- [ ] Characterize and map the pinned Legacy controller into candidate port operations.
- [ ] Decide whether the existing `RealMotionExecutor` fully satisfies the production
  port before adding any Legacy adapter.
- [ ] Add a fail-closed production REAL composition only after the adapter and field
  evidence are reviewed.

## Scope boundary

This increment changes names, documentation, and architecture enforcement only.  It does
not change HTTP schemas, persisted schemas, UI behavior, settings gates, hardware
configuration, Calibration, field evidence, or motion capability.
