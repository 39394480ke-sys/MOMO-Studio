# MOMO Studio

MOMO Studio is a local photography motion workstation for MOMO V1 and V2 robot arms. The intended workflow is to connect one active robot, find camera positions with joint or Cartesian control, capture poses and keyframes, arrange a motion on a timeline, save it to a library, preflight it, and play it back safely. Vision will later support target selection and following.

This repository is the new web-first system. The legacy [`MOMO_RobotARM`](https://github.com/39394480ke-sys/MOMO_RobotARM) V2 branch is read-only migration evidence; Stage 1 does not copy its hardware implementation wholesale. The audited source point is recorded in the migration documents and Stage report.

## Current status

Stage 1 establishes the architecture, domain contracts, ports, health/meta APIs, JSON Schemas, and a five-route frontend shell. It does **not** connect to a serial port, read servos, enable real motion, run kinematics, control hardware, record media, or implement vision tracking.

The product mode defaults to `DRY_RUN`. In Stage 1, `real_motion_enabled` is permanently false and there is no motion endpoint. Running this repository cannot move a real robot.

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

- `backend/` — FastAPI factory, domain models, ports, settings, schema generator, tests.
- `frontend/` — React/Vite application shell, API client, routes, components, tests.
- `config/default.yaml` — safe repository defaults; environment variables may override supported settings, but Stage 1 rejects real-motion enablement.
- `robot_profiles/` — uncalibrated product-contract examples, never device-ready profiles.
- `data/examples/` — reviewed schema examples; runtime data is ignored.
- `docs/` — product, architecture, safety, domain, ADR, audit, and Stage evidence.

## First-version scope

Included later: connection, Dry Run/Real modes, joint and Cartesian control, FK/IK, poses, keyframes, motions, library/playback, camera-fed vision following, device diagnostics, and safety checks for one active robot.

Explicitly excluded: PyQt or another standalone GUI, AI/voice/natural-language control, gesture control, cinematic director/subject-lock directing, photography or video recording, grippers, teach mode, PyBullet product windows, community features, Camera Hub media management, and multi-arm product workflows.

See [product scope](docs/product-scope.md), [architecture](docs/architecture.md), [safety](docs/safety.md), and the [Stage 1 report](docs/stage-reports/stage-01-foundation.md).

## Later stages

Later stages may add file repositories, simulation-safe application services, kinematics adapters, reviewed hardware integration, Studio/Library workflows, and Vision. Each requires its own scoped migration, tests, safety review, and Stage report. Stage 2 has not started.

No open-source license has been selected. See `THIRD_PARTY_NOTICES.md` for provenance tracking; license selection remains a project decision.
