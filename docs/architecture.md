# Architecture

## Context

MOMO Studio is web-first and local-first. React supplies one UI that can run in a browser today and be wrapped by Tauri later. FastAPI owns transport concerns and delegates to application services. Domain code expresses invariants without importing the web framework or hardware packages.

```text
React frontend
  └─ REST now / WebSocket later
      └─ FastAPI routes and schemas
          └─ Application services
              ├─ Domain models and policies
              └─ Ports
                  ├─ Robot driver / registry
                  ├─ Kinematics
                  ├─ Pose and Motion storage
                  └─ Vision provider
                      └─ Adapters (later Stages)
```

Dependencies point inward. Adapters implement ports; domain modules never import adapters. An API route may import an application service or port-bound dependency, but never a raw servo driver.

## Stage 1 runtime

The backend app factory creates routes without opening devices, reading calibration, or starting background threads. Only these endpoints exist:

- `GET /api/v1/health`
- `GET /api/v1/meta`
- `GET /api/v1/meta/product-scope`

The frontend calls health and metadata through a single API client. A failed health request is an offline state, not simulated success. There are no motion, serial, arbitrary-file, raw-servo, or code-execution endpoints.

## Configuration

Configuration precedence is:

1. typed safe defaults;
2. repository `config/default.yaml`;
3. optional uncommitted `config/local.yaml`;
4. environment variables prefixed `MOMO_`.

Stage 1 validates configuration and rejects any attempt to set `real_motion_enabled=true`. `serial_port` is an inert string and is never opened. Relative repository paths are resolved from module location/settings, never the process working directory.

## Persistence boundary

No database is planned for the first version. Future file adapters will store `data/poses/<uuid>.json` and `data/motions/<uuid>.json`; display names never become filenames. Writes must serialize a versioned model to a temporary sibling, flush it as appropriate, then atomically replace the target. Runtime data is ignored; only reviewed examples are committed.

## Multi-robot boundary

The UI operates one active robot. Domain/port APIs use `RobotId` and a manager/registry boundary instead of a process-global driver or names such as `arm_a`. This preserves identity and testability without introducing Fleet, coordination, or multi-arm APIs.

## Unit boundary

Canonical product/domain values use millimetres and degrees for profile and joint data. TCP positions use millimetres and normalized `xyzw` quaternions. A kinematics adapter will use metres and radians internally. Conversion occurs only in named boundary functions; values never cross implicitly.

## Repository structure

- `backend/src/momo/api` — app factory, API schemas, route composition.
- `backend/src/momo/application` — use-case orchestration when introduced.
- `backend/src/momo/domain` — enums, models, validation, errors.
- `backend/src/momo/ports` — typed protocols for external capability.
- `backend/src/momo/adapters` — created only when a concrete implementation exists.
- `frontend/src/api` — transport client and response types.
- `frontend/src/app`, `layouts`, `components`, `pages` — composition, chrome, reusable UI, routes.
