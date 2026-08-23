# MOMO Studio

MOMO Studio is a local photography motion workstation for MOMO V1 and V2 robot arms. The intended workflow is to connect one active robot, find camera positions with joint or Cartesian control, capture poses and keyframes, arrange a motion on a timeline, save it to a library, preflight it, and play it back safely. Vision will later support target selection and following.

This repository is the new web-first system. The legacy [`MOMO_RobotARM`](https://github.com/39394480ke-sys/MOMO_RobotARM) V2 branch is read-only migration evidence; MOMO Studio does not copy its hardware implementation wholesale. The pinned source point is recorded in the migration documents and Stage reports.

## Current status

Stage 3 is complete on top of the completed Stage 2 robot core. It adds
mesh-free V1/V2 kinematics models, deterministic FK/IK, Base/Tool Cartesian composition,
one Motion Safety Gateway, cancellable interpolated Dry Run execution, a renewable Jog
deadman lease, a bounded read-only robot-status WebSocket, and the complete responsive
Control workspace. The final evidence is 226 passing backend tests and 54 passing
frontend tests, green lint/type/format/build/schema/lock/audit checks, desktop/mobile and
breakpoint browser acceptance, an empty final browser console, and focused
hardware/camera isolation. See the
[Stage 3 report](docs/stage-reports/stage-03-kinematics-and-control.md).

Both kinematics models are `PROVISIONAL_DRY_RUN`. V1 is rail-less and contains exactly
`j11`-`j15`; V2 contains `j10`-`j15`, with prismatic J10 converted between UI/domain
millimetres and adapter metres only at a named boundary. Provisional geometry, limits,
workspace, velocity, and acceleration values are software characterization inputs, not
physical authority.

The product remains locked to `DRY_RUN`, hardware access remains `DISABLED`, and
`real_motion_enabled` remains false. Stage 3 imports or instantiates no serial or Feetech
adapter, reads no real Calibration, opens no camera, and commands no physical hardware.
Every movement source passes through the same reviewed application gateway; there is no
raw-servo or direct-driver API.

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
- `frontend/` — React/Vite application, REST fallback, lifecycle/motion controls, diagnostics, and tests.
- `kinematics_models/` — mesh-free, fingerprinted V1/V2 provisional Dry Run serial chains.
- `config/default.yaml` — safe repository defaults; Real mode and non-disabled hardware access remain rejected.
- `robot_profiles/` — fingerprinted product-contract examples, never device-ready profiles.
- `calibration/examples/` — synthetic template calibrations, never real-device calibration.
- `data/examples/` — reviewed schema examples; runtime data is ignored.
- `docs/` — product, architecture, safety, domain, ADR, audit, and Stage evidence.

## First-version scope

Included later: connection, Dry Run/Real modes, joint and Cartesian control, FK/IK, poses, keyframes, motions, library/playback, camera-fed vision following, device diagnostics, and safety checks for one active robot.

Explicitly excluded: PyQt or another standalone GUI, AI/voice/natural-language control, gesture control, cinematic director/subject-lock directing, photography or video recording, grippers, teach mode, PyBullet product windows, community features, Camera Hub media management, and multi-arm product workflows.

See [product scope](docs/product-scope.md), [architecture](docs/architecture.md),
[safety](docs/safety.md), the [Stage 2 report](docs/stage-reports/stage-02-robot-core.md),
and the complete [Stage 3 report](docs/stage-reports/stage-03-kinematics-and-control.md).

## Later stages

Stage 4 begins after the dedicated green Stage 3 commit. Pose/Motion Library,
trajectory/playback, Studio, Vision, and the Real hardware boundary remain later Stage
work. Every later motion source must reuse the Stage 3 Motion Safety Gateway rather than
introducing a route-to-driver shortcut. Real hardware remains field-acceptance gated.

No open-source license has been selected. See `THIRD_PARTY_NOTICES.md` for provenance tracking; license selection remains a project decision.
