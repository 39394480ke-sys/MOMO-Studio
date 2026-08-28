# MOMO Studio

MOMO Studio is a local motion-production workstation for MOMO V1/V2 camera robots.
It supports robot positioning, keyframe capture, pose and motion libraries,
timeline-based trajectory authoring, trajectory playback, and vision following.

## Current status

| Area | Status |
|---|---|
| Version | `0.1.0-rc1` |
| Dry Run | **VALIDATED** |
| V1/V2 software model | **VALIDATED** |
| Joint / Cartesian software control | **VALIDATED IN DRY RUN** |
| Pose / Motion Library | **VALIDATED** |
| Trajectory / Playback | **VALIDATED IN DRY RUN** |
| Studio Timeline | **VALIDATED** |
| Synthetic Vision / Follow | **VALIDATED IN DRY RUN** |
| Read-only live camera preview | **IMPLEMENTED; EXPLICIT LOCAL OPT-IN REQUIRED** |
| Commissioning software workflow | **VALIDATED WITH FAKE/BOMB/ISOLATED ADAPTERS** |
| Real Feetech hardware | **FIELD VERIFICATION REQUIRED** |
| Physical Stop | **FIELD VERIFICATION REQUIRED** |
| Real Kinematics | **FIELD VERIFICATION REQUIRED** |
| Real Cartesian / Playback / Vision | **BLOCKED UNTIL FIELD ACCEPTANCE** |

This is a software user-acceptance candidate. Automated commissioning evidence proves
the software path only; it is not physical field acceptance.

## What MOMO Studio does

- Positions one active MOMO camera robot through Joint or Cartesian controls.
- Captures immutable Pose snapshots and reusable Motion keyframes.
- Authors Joint and Cartesian-linear transitions on a Studio timeline.
- Preflights, previews, and plays trajectories through one Motion Safety Gateway.
- Provides deterministic Synthetic Vision, tracking, and safe Dry Run Follow.
- Provides an optional explicit-ID live-camera preview that is read-only: no selection,
  detection, tracking, recording, or Follow.
- Provides read-only commissioning, initial Calibration, staged field evidence, and
  explainable Real-capability gates without silently enabling hardware.

## Product workflow

```text
CONTROL
    ↓
Find camera position
    ↓
Capture Pose / Keyframe
    ↓

STUDIO
    ↓
Arrange keyframes
    ↓
Configure Joint / Cartesian transitions
    ↓
Preflight
    ↓

LIBRARY
    ↓
Save / Reuse Motion
    ↓

PLAYBACK
```

Vision is a separate workflow:

```text
VISION
    ↓
Select subject
    ↓
Track
    ↓
Safe Follow
```

## Supported robots

| Robot | Enabled joints | Rail | Units |
|---|---|---|---|
| MOMO V1 | `j11`–`j15` | None | `deg` |
| MOMO V2 | `j10`–`j15` | `j10` is prismatic | `j10`: `mm`; `j11`–`j15`: `deg` |

V1 never contains `j10`. V1 and V2 are hardware variants, not software versions. Both
committed Kinematics models remain `PROVISIONAL_DRY_RUN`.

## Core features

- Responsive Control workspace with lifecycle, Joint Jog, continuous Jog, FK/IK,
  Cartesian Jog, Move Pose, Home, and priority Stop in Dry Run.
- UUID-backed Pose and Motion Library with revisions, compatibility checks, search,
  tags, duplicate, and safe deletion.
- Deterministic Joint, hold, and Cartesian-linear trajectory compilation and whole-plan
  preflight.
- Playback with pause, resume, Stop, rate, loop, progress, and one active-motion slot.
- Timeline Studio with capture, reorder, duration, hold, easing, Undo/Redo, Save, and
  Save As.
- Synthetic Vision with ROI selection, tracking overlays, filtering, a renewable Follow
  lease, and automatic Stop on stale/lost targets.
- Backend-derived capability explanations shared by Control, Library, Studio, Vision,
  and Settings.

## Quick start

Requirements: Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), and a current
Node.js/npm release.

```bash
git clone https://github.com/39394480ke-sys/MOMO-Studio.git
cd MOMO-Studio
make install
cp config/default.yaml config/local.yaml
make dev-backend LOCAL_CONFIG=config/local.yaml
```

In a second terminal:

```bash
make dev-frontend
```

Open the Vite URL printed by the frontend command. The copied configuration remains
`DRY_RUN`, hardware access is disabled, Real and commissioning motion are disabled, and
Vision is Synthetic-only.

For the separately gated read-only camera preview, install the optional local dependency
with `make install-camera`, then follow the exact ignored-local-config procedure in the
[operator guide](docs/operator-guide.md#read-only-live-camera-preview). The default
installation and configuration never open a camera.

> Running the default development configuration cannot control a real robot.

## Development

```bash
make test
make lint
make format-check
make build
make schemas
make audit
```

The REST and read-only WebSocket surfaces are versioned under `/api/v1`. Backend commands
use `backend/.venv`; frontend commands run through npm in `frontend/`.

## Project structure

- `backend/` — FastAPI application, domain/application layers, ports/adapters, tests,
  and JSON Schema generation.
- `frontend/` — React/Vite Control, Library, Studio, Vision, Settings, and tests.
- `robot_profiles/` — V1/V2 product-contract examples, not device-ready profiles.
- `kinematics_models/` — mesh-free provisional Dry Run models.
- `calibration/examples/` — synthetic templates, never real-device Calibration.
- `data/examples/` — reviewed Pose/Motion examples; runtime and user data are ignored.
- `config/default.yaml` — deny-by-default repository configuration.
- `docs/` — product, architecture, safety, operation, acceptance, ADR, and historical
  Stage evidence.

## Safety model

- `DRY_RUN` and hardware access `DISABLED` are the defaults.
- Every motion source passes through the Motion Safety Gateway.
- `COMMISSIONING_READ_ONLY` has no write capability.
- `COMMISSIONING_MOTION_TEST` permits only a separately armed, bounded, relative
  single-joint test under a backend deadman.
- `REAL_MOTION` is a separate purpose and requires current capability evidence.
- Session purpose never upgrades; a new purpose requires a new confirmation and session.
- Field acceptance is staged. No writable global `PASSED` value can authorize motion.
- The normal release composition does not create a production write-capable Feetech bus.
- Camera access defaults to `SYNTHETIC_ONLY` and never auto-opens a real camera.
- Live preview requires an ignored local device ID plus an explicit button press; closing
  it releases the device and captured frames are never persisted by MOMO Studio.

See the [Safety model](docs/safety.md) and
[staged field-acceptance decision](docs/adr/0019-staged-field-acceptance.md).

## Real hardware status

Real hardware is intentionally unavailable in the release-candidate defaults. Feetech
goal write, physical Stop/E-stop behavior, servo timing, physical geometry, TCP,
Kinematics, Cartesian motion, Playback, and Vision Follow require evidence for the exact
physical robot. The field procedure is separate from software user acceptance.

See [Real-hardware field acceptance](docs/real-hardware-acceptance.md).

## Documentation

Start with the [documentation index](docs/README.md). Key entry points:

- [Release candidate summary](docs/release-candidate-0.1.0-rc1.md)
- [Software user-acceptance checklist](docs/user-acceptance-checklist.md)
- [Operator guide](docs/operator-guide.md)
- [Architecture](docs/architecture.md)
- [Safety](docs/safety.md)
- [Final user-acceptance handoff](docs/stage-reports/v0.1.0-rc1-user-acceptance-handoff.md)

## Test status

The latest candidate verification passes:

- Backend: 670 tests.
- Frontend: 296 tests across 31 files.
- Hardware/camera/commissioning isolation: 140 tests.
- Ruff, Ruff format, strict mypy, ESLint, TypeScript, Vite production build,
  deterministic schemas, lock/dependency checks, secret scan, `pip-audit`, and
  `npm audit`.

The historical release-candidate commit and CI runs are recorded in the Draft PR and final
handoff. The newer local Figma redesign and V1/V2 Viewer verification is recorded in the
[frontend redesign report](docs/stage-reports/frontend-figma-redesign.md) and remains
uncommitted.

## Known limitations

- Feetech goal-write and Physical Stop/E-stop behavior are not physically verified.
- Servo timing and V1/V2 physical geometry are not verified.
- Mechanical backlash/flex is not characterized; physical TCP calibration is incomplete.
- Kinematics remain provisional; Real Cartesian is blocked.
- Real Playback remains blocked where its required evidence is incomplete.
- Real Vision Follow is blocked; camera latency and Vision gains are not field tuned.
- Read-only live preview is intentionally not object detection, tracking, recording, or
  evidence that Real Vision Follow is ready.
- Desktop/Tauri packaging is not implemented.
- The project license decision remains pending. The user's direct ownership and use
  authorization for the V1/V2 robot models is recorded in `THIRD_PARTY_NOTICES.md`;
  rights for unrelated Legacy assets must not be assumed.

## Roadmap

The software candidate is complete. Remaining work is sequenced through user software
acceptance, physical adapter/commissioning evidence, capability-specific field
acceptance, Vision tuning, and optional desktop packaging. See the
[roadmap](docs/roadmap.md).

## License and third-party notice

No repository license has been selected. Project license decision pending. The V1/V2
robot-model permission basis is recorded, but do not assume rights for unrelated Legacy
assets. Dependency and provenance notes are recorded in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
