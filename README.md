# MOMO Studio

MOMO Studio is a local photography motion workstation for MOMO V1 and V2 robot arms. The intended workflow is to connect one active robot, find camera positions with joint or Cartesian control, capture poses and keyframes, arrange a motion on a timeline, save it to a library, preflight it, and play it back safely. Vision will later support target selection and following.

This repository is the new web-first system. The legacy [`MOMO_RobotARM`](https://github.com/39394480ke-sys/MOMO_RobotARM) V2 branch is read-only migration evidence; MOMO Studio does not copy its hardware implementation wholesale. The pinned source point is recorded in the migration documents and Stage reports.

## Current status

Stage 2 adds an explicit V1/V2 Profile repository, Profile Fingerprints, Calibration compatibility diagnostics, a single Active Robot, an in-memory Dry Run driver, serialized Connect/Disconnect/Stop lifecycle commands, atomic runtime-state persistence, read-only robot APIs, and backend-backed Control and Settings pages.

The product mode remains `DRY_RUN`, `hardware_access` is locked to `DISABLED`, and `real_motion_enabled` is locked to false. There is no motion, Jog, Home, kinematics, serial, servo, or calibration-write endpoint. Running Stage 2 cannot move a real robot.

## Develop locally

Requirements: Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), and a current Node.js/npm release. `make install` consumes both committed lockfiles.

```bash
make install
make dev-backend
```

In another terminal:

```bash
make dev-frontend
```

The frontend development server proxies `/api` to the local FastAPI server. Direct route refreshes are handled by Vite's SPA fallback.

## Test and build

```bash
make test
make lint
make format-check
make build
make schemas
```

Backend commands use `backend/.venv`; frontend commands run through npm in `frontend/`.

## Repository map

- `backend/` — FastAPI factory, application services, domain models, ports/adapters, schema generator, tests.
- `frontend/` — React/Vite application, REST polling, lifecycle controls, diagnostics, and tests.
- `config/default.yaml` — safe repository defaults; Stage 2 rejects real mode or non-disabled hardware policy from every settings source.
- `robot_profiles/` — fingerprinted product-contract examples, never device-ready profiles.
- `calibration/examples/` — synthetic template calibrations, never real-device calibration.
- `data/examples/` — reviewed schema examples; runtime data is ignored.
- `docs/` — product, architecture, safety, domain, ADR, audit, and Stage evidence.

## First-version scope

Included later: connection, Dry Run/Real modes, joint and Cartesian control, FK/IK, poses, keyframes, motions, library/playback, camera-fed vision following, device diagnostics, and safety checks for one active robot.

Explicitly excluded: PyQt or another standalone GUI, AI/voice/natural-language control, gesture control, cinematic director/subject-lock directing, photography or video recording, grippers, teach mode, PyBullet product windows, community features, Camera Hub media management, and multi-arm product workflows.

See [product scope](docs/product-scope.md), [architecture](docs/architecture.md), [safety](docs/safety.md), and the [Stage 2 report](docs/stage-reports/stage-02-robot-core.md).

## Later stages

Stage 3 may add only its separately reviewed scope, such as kinematics and movement commands routed through one safety entry point. Real hardware, motion playback, Studio/Library workflows, and Vision remain later work. Every capability requires its own scoped migration, tests, safety review, and Stage report.

No open-source license has been selected. See `THIRD_PARTY_NOTICES.md` for provenance tracking; license selection remains a project decision.
