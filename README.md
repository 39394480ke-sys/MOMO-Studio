# MOMO Studio

MOMO Studio is a local photography motion workstation for MOMO V1 and V2 robot arms. The intended workflow is to connect one active robot, find camera positions with joint or Cartesian control, capture poses and keyframes, arrange a motion on a timeline, save it to a library, preflight it, and play it back safely. Stage 8 hardens the release boundary around that Dry Run/Synthetic product: Real hardware remains multi-factor and field-acceptance gated.

This repository is the new web-first system. The legacy [`MOMO_RobotARM`](https://github.com/39394480ke-sys/MOMO_RobotARM) V2 branch is read-only migration evidence; MOMO Studio does not copy its hardware implementation wholesale. The pinned source point is recorded in the migration documents and Stage reports.

## Current status

Stage 3 is complete on top of the completed Stage 2 robot core. Its dedicated commit is
`133318e9437dff133a4c25bf01aec09cce5ae6e3` and is pushed to
`origin/codex/v1-autonomous-completion`. It adds
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

Stage 4 is complete and GREEN. Its dedicated scope introduces independent
Pose/Motion schema `2.0.0` contracts, UUID-named atomic file repositories with optimistic
revisions and corrupt-file isolation, coherent Pose Capture, Dry Run Goto through the
existing gateway, a bounded Library API/UI, and an explicit default-dry-run Legacy action
importer. The final gate passed 273 backend tests, 71 frontend tests across 8 files,
dependency checks, a 65-test route/import/hardware suite, and full desktop/mobile browser
acceptance. The independent audit passes P1=0/P2=0. The containing commit uses subject
`feat: add pose and motion library workflows`; its exact self-SHA/remote state is recorded
by the next Stage rather than fabricated inside its own report.

See the [Stage 4 report](docs/stage-reports/stage-04-library.md),
[atomic repository decision](docs/adr/0011-atomic-entity-repositories.md), and
[Legacy import guide](docs/legacy-action-import.md).

Stage 5 is complete and GREEN. It adds deterministic Joint/Cartesian-linear/hold
compilation, whole-plan preflight, immutable prepared trajectories with semantic
SHA-256 identity, bounded preview, and monotonic Dry Run playback with pause, resume,
Stop, rate, closed-loop, progress, and read-only WebSocket status. Playback revalidates
the exact prepared object through the existing Motion Safety Gateway and shares the one
motion slot. The final gate passed 352 backend tests, 85 frontend tests, a 128-test
focused isolation/integration suite, dependency/schema/build checks, and desktop/mobile
browser acceptance with zero console warnings/errors. Real playback remains blocked.

See the [Stage 5 report](docs/stage-reports/stage-05-trajectory-and-playback.md),
[compiled trajectory decision](docs/adr/0012-compiled-trajectory-and-digest.md), and
[trajectory semantics](docs/trajectory-semantics.md).

Stage 6 implementation gates pass: 393 backend tests, an independently rerun 36-test
Stage 6 domain/repository/coordinator/actions/API selection, 174 frontend tests across
12 files, and a focused 89-test Studio selection pass. Ruff and Ruff format pass across
141 files, strict mypy passes across 141 source files, ESLint/TypeScript/build and
isolated desktop/mobile browser acceptance pass, and the final independent integrated
audit closes at P1=0/P2=0. The backend is split into a bounded Draft/compile facade,
formal-save coordinator, and robot-actions collaborator; the frontend composes separate
Draft, Motion, Pose, and dirty-navigation sessions around the pure reducer. The implementation keeps incomplete work in a separate strict
`MotionDraft` schema, preserves explicit directed-edge/default semantics, reconciles
cross-repository formal saves with a fail-closed write-ahead intent and exact operator
release, compiles non-executable previews only on the backend, and routes
persisted-keyframe Goto through the existing Dry Run Motion Safety Gateway. Conflict
Save As uses an authoritative, provenance-preserving Draft fork without overwriting the
original Draft or Motion.

Lock and npm vulnerability gates also pass. Stage 6 is complete in commit
`37783bdf8c01146d3a312980dbe4a25716e5468c`, pushed to
`origin/codex/v1-autonomous-completion`. See the
[Stage 6 report](docs/stage-reports/stage-06-studio-timeline.md),
[MotionDraft decision](docs/adr/0013-motion-draft-and-timeline-editor.md), and
[Studio workflow](docs/studio-user-workflow.md).

Stage 7 implementation and static gates are green: 432 backend tests (including 34
focused Vision core/Follow/API tests), 190 frontend tests across 14 files (including 16
focused Vision client/page tests), backend/frontend lint/type/format/build, deterministic
schema generation, lock, and npm-audit checks pass. The Vision workspace provides a
deterministic Synthetic stream, frame-bound manual ROI, honest person/face/tracker
capabilities, tracking overlays, controller metrics, and one heartbeat-renewed Dry Run
Follow lease. Stale/lost/low-confidence/disconnect/fault/conflict/expiry/Stop events stop
ownership and cancel Vision commands through the normal motion application path.

Camera access defaults to `SYNTHETIC_ONLY`. OpenCV was not added as a dependency; its
optional camera shell imports lazily only after a complete explicit live grant, and
Stage 7 startup neither opens nor enumerates a camera. Synthetic detectors and the
tracker are deterministic fixtures, not general models. Real Follow remains blocked.
Desktop/mobile browser acceptance and final independent audit pass P1=0/P2=0. The Stage
7 dedicated commit is `dedbdabb9a35aefea01df05f0652214428305a93` and is pushed to
`origin/codex/v1-autonomous-completion`. See the
[Stage 7 report](docs/stage-reports/stage-07-vision-following.md),
[provider capabilities](docs/vision-provider-capabilities.md), and
[Vision access/Follow lease decision](docs/adr/0014-vision-access-policy-and-follow-lease.md).

Stage 8 software implementation and Dry Run release-candidate verification are complete
for `0.1.0-rc1` with `FIELD_ACCEPTANCE_REQUIRED`; the dedicated Stage commit/push and PR
disposition remain pending. It adds the minimal explicit-ID `ServoBus` port and Fake
Bus coverage, a multi-factor Real authorization matrix, short-lived Operator Sessions,
explicit-connect/read-only diagnostics, a protected current-angle Calibration workflow,
and a Fake-Bus-verified Real trajectory executor with truthful Stop uncertainty. The
default composition still supplies no Real bus factory and cannot open hardware.

The release boundary also includes exact-Origin local/LAN authentication, bounded
HttpOnly browser sessions, ongoing WebSocket/Vision stream reauthorization, structured
redacted audit, deterministic config-free backup, one-use preview grants, exact-revision
restore, and a durable write-ahead restore journal recovered before application traffic.
The built SPA can be hosted by the same backend from relative local assets; interactive
CDN-backed API documentation is disabled and no runtime CDN is required.

Feetech remains **Pending Adapter Verification**: the optional shell performs no import
until a complete grant is supplied, goal writes stay disabled, and unverified Stop
returns `SAFETY_STATE_UNCERTAIN`. Both committed kinematics models remain
`PROVISIONAL_DRY_RUN`, field acceptance is still `PENDING`, and every item in the Real
field checklist remains unchecked.

The final software gate passes 563 backend tests with one existing Starlette/httpx
deprecation warning and 201 frontend tests across 17 files. Ruff, format, strict mypy,
ESLint, TypeScript, schema determinism, lock/dependency compatibility, the 52-test
hardware/camera isolation suite, secret scan, npm audit, and the 1,642-module Vite build
all pass. Desktop 1440×960, mobile 390×844, and 850/830 breakpoint acceptance complete
the V2 Dry Run Control→Library→Studio→Playback→Synthetic Vision workflow with no
horizontal overflow and console warnings/errors `[]`. The final independent audit closes
P1=0/P2=0 after 74 focused tests. Exact evidence and remaining delivery/field gates are
in the [Stage 8 report](docs/stage-reports/stage-08-release-hardening.md).

## Develop locally

Requirements: Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), and a current Node.js/npm release. `make install` consumes both committed lockfiles.

Create the ignored `config/local.yaml` with the explicit reviewed bind, for example
`server_host: 127.0.0.1` and `server_port: 8000`, then run:

```bash
make install
make dev-backend LOCAL_CONFIG=config/local.yaml
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
- `frontend/` — React/Vite application, REST fallback, lifecycle/motion controls,
  Pose/Motion Library and playback, Studio timeline authoring, Synthetic Vision/Follow,
  Real-readiness/Calibration diagnostics, release status, security session controls,
  and tests.
- `kinematics_models/` — mesh-free, fingerprinted V1/V2 provisional Dry Run serial chains.
- `config/default.yaml` — safe repository defaults: loopback, Dry Run, hardware Disabled,
  real motion false, Synthetic camera, and field acceptance Pending.
- `robot_profiles/` — fingerprinted product-contract examples, never device-ready profiles.
- `calibration/examples/` — synthetic template calibrations, never real-device calibration.
- `data/examples/` — reviewed schema examples; operational Pose/Motion/Draft/runtime and
  quarantine data is ignored.
- `docs/` — product, architecture, safety, domain, ADR, audit, and Stage evidence.

## First-version scope

First-version scope includes connection, Dry Run plus a field-gated Real software boundary, joint and Cartesian
control, FK/IK, poses, keyframes, motions, Studio authoring, library/playback,
camera-fed vision following, device diagnostics, and safety checks for one active
robot. Stages 1–7 are complete and pushed. Stage 8 software implementation, Dry Run
browser acceptance, and independent audit are evidence-backed; its dedicated Git
delivery and all physical field acceptance remain separate unresolved gates.

Explicitly excluded: PyQt or another standalone GUI, AI/voice/natural-language control, gesture control, cinematic director/subject-lock directing, photography or video recording, grippers, teach mode, PyBullet product windows, community features, Camera Hub media management, and multi-arm product workflows.

See [product scope](docs/product-scope.md), [architecture](docs/architecture.md),
[safety](docs/safety.md), the [Stage 2 report](docs/stage-reports/stage-02-robot-core.md),
and the complete [Stage 3 report](docs/stage-reports/stage-03-kinematics-and-control.md).

## Release boundary

Stages 3–8 are complete and GREEN. Stage 8 commit
`4f7a75606aacb3fc93128445d7487ff196ce9efb` is pushed, and Draft PR
[#1](https://github.com/39394480ke-sys/MOMO-Studio/pull/1) is open. Stage 8 owns the
separately gated Real hardware/release boundary. Every motion source
must reuse the Motion Safety Gateway rather than introducing a route-to-driver shortcut.
Real hardware, Real Cartesian/Playback/Follow, and any physical Stop claim remain
field-acceptance and adapter-verification gated.

No open-source license has been selected. See `THIRD_PARTY_NOTICES.md` for provenance tracking; license selection remains a project decision.
