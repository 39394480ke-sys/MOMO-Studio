# MOMO Studio 0.1.0-rc1 release candidate

## Candidate identity

- Version: `0.1.0-rc1`
- Branch: `codex/v1-autonomous-completion`
- Source baseline for this repository-cleanup pass:
  `eafa4af0bb6c2ab30c5955d63c72028b51b98eb2`
- Candidate commit: the commit containing this document; the canonical immutable value
  is the head of [Draft PR #1](https://github.com/39394480ke-sys/MOMO-Studio/pull/1)
- Base: `main` at `32d0163431e229cb3c2e01a285e7e851124ce9c1`
- Candidate state: software user acceptance pending

A Git commit cannot embed its own object ID. The final handoff response and PR head are
the authoritative exact candidate SHA.

## Status

```text
Dry Run validated.

Commissioning software workflow validated with Fake/Bomb/isolated adapters.

Real hardware field acceptance pending.

No production Real capability is physically verified yet.
```

## Software scope

MOMO Studio is a local motion-production workstation for one active MOMO V1 or V2 camera
robot. The candidate contains the web application, backend, domain contracts, local file
repositories, deterministic Dry Run runtime, safety gateways, and the fail-closed
commissioning/Real-hardware boundary.

V1 uses `j11`–`j15`. V2 uses `j10`–`j15`, where `j10` is a prismatic rail in millimetres
and `j11`–`j15` are revolute joints in degrees.

## Completed software capabilities

- Dry Run lifecycle and responsive Joint/Cartesian Control.
- Deterministic FK/IK for provisional mesh-free V1/V2 models.
- Pose capture and Pose/Motion Library workflows.
- Joint, hold, and Cartesian-linear trajectory compilation and whole-plan preflight.
- Playback with pause, resume, rate, loop, progress, and priority Stop.
- Studio timeline authoring, Undo/Redo, Save, Save As, and conflict handling.
- Synthetic Vision, ROI/tracking, and lease-bound Dry Run Follow.
- Versioned REST/read-only WebSocket APIs under `/api/v1`.
- Read-only commissioning, initial Calibration, restricted commissioning-motion test,
  staged capability evidence, and Kinematics field-verification workflow.
- Local/LAN security boundary, redacted audit, backup/restore, static hosting, and CI.

## Dry Run validation

The V1/V2 software model, Joint/Cartesian controls, Library, trajectory compiler,
Playback, Studio, and Synthetic Vision/Follow are validated in Dry Run. The default
configuration sets:

```text
control_mode = DRY_RUN
hardware_access = DISABLED
real_motion_enabled = false
commissioning_motion_test_enabled = false
camera_access_policy = SYNTHETIC_ONLY
```

Running that configuration cannot control a real robot.

## Commissioning validation

Fake, Bomb, Temp Repository, Fake Clock, and isolated adapters validate the software
workflow from explicit unit identity and read-only diagnostics through Calibration,
pre-motion checks, bounded positive/negative tests for every enabled V2 joint, and Joint
Acceptance derivation. This does not validate a physical Feetech write, Stop, E-stop,
Servo timing, Calibration, robot geometry, or Kinematics.

The three session purposes remain independent:

| Purpose | Authority |
|---|---|
| `COMMISSIONING_READ_ONLY` | Explicit-device diagnostics and Calibration capture; no writes |
| `COMMISSIONING_MOTION_TEST` | One separately armed, bounded relative joint test under a backend deadman |
| `REAL_MOTION` | Only production capabilities supported by current evidence |

No purpose upgrades into another, and no manual global Field Acceptance `PASSED` can
grant authority.

## Real-hardware blocked capabilities

- Feetech goal write and the production write-capable bus factory.
- Physical Stop and E-stop behavior.
- Real Servo timing and device-specific motion semantics.
- Real Kinematics and physical V1/V2 geometry/TCP.
- Real Cartesian motion.
- Real Playback where required capability evidence is incomplete.
- Real Vision Follow and live-camera tuning.

The complete physical process is the separate
[Real-hardware field acceptance](real-hardware-acceptance.md) procedure.

## Known limitations

- Mechanical backlash and flex are not characterized.
- Camera latency is not characterized; Vision gains are not field tuned.
- The committed Kinematics models remain `PROVISIONAL_DRY_RUN`.
- The release composition has no physical Kinematics snapshot provider and does not
  promote persisted Kinematics evidence after restart.
- Tauri/desktop packaging is not implemented.
- The repository license decision is pending; Legacy redistribution rights are not
  established.
- `DeviceDiagnosticsService` retains one recorded P3 service-concentration debt; it is
  not a release-candidate safety bypass.

## Test results

The final software implementation gate before repository presentation cleanup passed:

| Gate | Result |
|---|---|
| Backend | 629 passed; one existing Starlette/httpx deprecation warning |
| Frontend | 230 passed across 19 files |
| Hardware/camera/commissioning isolation | 140 passed |
| Security and backup focused tests | 34 passed |
| Architecture-focused tests | 38 passed |
| Ruff / Ruff format / strict mypy | Passed |
| ESLint / TypeScript | Passed |
| Vite production build | Passed |
| Schema determinism / `uv lock --check` / `uv pip check` | Passed |
| `pip-audit` | No known vulnerabilities |
| `npm audit --audit-level=high` | 0 vulnerabilities |

The repository-cleanup pass changes documentation only and repeated the full gate with
the same counts and outcomes. A lightweight browser smoke also passed: the actual
Control, Studio, Library, Vision, and Settings pages loaded; V2 Dry Run connected and
updated status; Synthetic Vision streamed; Real hardware remained blocked; and browser
warnings/errors were `[]`.

## CI results

The implementation head `eafa4af0bb6c2ab30c5955d63c72028b51b98eb2` passed both
[push CI](https://github.com/39394480ke-sys/MOMO-Studio/actions/runs/32820730671) and
[pull-request CI](https://github.com/39394480ke-sys/MOMO-Studio/actions/runs/32820734167).

The candidate is handed off only after the live push and pull-request checks for the
document-containing PR head are also GREEN. The PR checks are the authoritative final CI
record because this file cannot embed the CI run created by its own commit.

## Acceptance requirements

Software product experience is reviewed with the
[user-acceptance checklist](user-acceptance-checklist.md). All checks use Dry Run and
Synthetic Vision. The user records one of `ACCEPT`, `ACCEPT WITH ISSUES`, or `REJECT`.

Real-hardware acceptance is not part of software acceptance. No physical checklist item
is checked or inferred by this release candidate.

## Pull request

[Draft PR #1 — MOMO Studio v0.1.0-rc1 autonomous completion](https://github.com/39394480ke-sys/MOMO-Studio/pull/1)
must remain Draft until the user completes software acceptance.
