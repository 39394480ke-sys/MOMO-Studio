# Release candidate checklist

Status: Stage 8 software gates, complete Dry Run browser acceptance, final independent
audit, dedicated commit/push, and Draft PR creation pass. Checkboxes are evidence gates,
not implementation claims.
Every field item in `real-hardware-acceptance.md` must remain unchecked during autonomous
work.

The checked items below describe the earlier Stage 8/commissioning-fix baseline. Final
pre-merge hardening has its own pending gate section and must not inherit a PASS from
those historical results.

## Source and identity

- [x] Branch is `codex/v1-autonomous-completion`; `main` was not merged or modified.
- [x] Stage 3–8 commits exist in order; all task-owned changes are committed at delivery.
  Three externally created iCloud duplicate files remain excluded and untouched.
- [x] Version is `0.1.0-rc1` in Python, frontend, lockfiles, defaults, API metadata, and UI.
- [x] Release status is `FIELD_ACCEPTANCE_REQUIRED`; UI says Dry Run validated and Real
  hardware field acceptance pending.
- [x] Generated schemas and lockfiles match inputs deterministically.

## Automated gates

- [x] `make test` — backend 591 passed; frontend 215 passed across 18 files.
- [x] `make lint`
- [x] `make format-check`
- [x] `make build` — 1,642 modules; JS 480.15 kB / 135.88 kB gzip.
- [x] Two fresh schema generations are byte-identical and match the tracked tree.
- [x] `git diff --check`
- [x] `uv lock --project backend --check`
- [x] `uv pip check` — 66 installed packages compatible.
- [x] `pip-audit` is a locked dev dependency and a fail-closed CI gate; the direct
  vulnerable pytest 8.x dependency was upgraded to a fixed pytest 9.x release.
- [x] `npm audit --audit-level=high` — 0 vulnerabilities.
- [x] Hardware and camera isolation suites — 102 passed under explicit safe startup gates.
- [x] Secret/basic provenance scan
- [x] CI workflow contains no hardware, camera, Real config, or network model download.
- [x] Every JavaScript GitHub Action uses its official Node 24 runtime major.
- [x] Static release test proves relative local assets, `/docs` and `/redoc` disabled,
  OpenAPI free of CDN URLs, SPA refresh success, and missing API/assets remaining 404

## Product acceptance

- [x] Desktop 1440×960, mobile 390×844, and 850/830 widths around the primary breakpoint;
  no page horizontal overflow.
- [x] Complete V2 Dry Run workflow through Control, Pose/Library, Studio, Playback, Vision
  Synthetic Follow/target lost, Stop, and Disconnect.
- [x] Browser acceptance observes offline/stale, unreachable IK, target lost, Real blocked,
  template Calibration, and field-pending states; regression suites retain limit,
  revision-conflict, corrupt-Draft, Vision-stale, invalid-Calibration, and session-expiry
  coverage.
- [x] Browser console warning/error entries are `[]`.
- [x] Default Settings displays `Hardware access disabled` and never probes a device.
- [x] Safe fixture acceptance distinguishes Hardware Disabled, Commissioning `READ ONLY`,
  and Real Motion; commissioning exposes diagnostics/Calibration but no motion controls.
- [x] API/WebSocket/schema inventories and resource bounds match documentation.

## Security and recovery

- [x] Default bind is loopback; opt-in LAN token and exact same-host/same-scheme HTTP
  Origin tests pass with no wildcard/public bind.
- [x] REST, WebSocket, and Vision auth plus command rate limiting fail closed.
- [x] Established WebSocket/Vision streams terminate on session expiry/revoke and stale
  cookies can be replaced only by a valid long-term Bearer exchange.
- [x] Structured audit includes request/command/robot/source/mode/preflight/outcome/
  duration/error evidence where available, with token/session/URL/path/serial redaction.
- [x] Backup export, one-use preview, migration, collision policy, digest confirmation,
  exact-revision import, WAL compensation, and startup process-crash recovery pass;
  default backup contains no secret/device/runtime/log/camera/Calibration.
- [x] No web endpoint accepts a server filesystem path or arbitrary register operation.

## Provenance and distribution

- [ ] Exact lockfile dependency/license report and required license files are collected.
- [x] Optional Feetech/OpenCV packages remain absent unless exact package, version,
  canonical source, license, binary provenance, and field behavior are approved.
- [x] Feetech capability remains `PENDING_ADAPTER_VERIFICATION`, goal writes remain
  disabled, and unverified Stop returns `SAFETY_STATE_UNCERTAIN`.
- [x] No Legacy code, Calibration, local setting, runtime motion, ignored data, model,
  mesh, or unknown asset was copied.
- [ ] Repository license decision is resolved before public binary/source distribution.

## Safety sign-off

- [x] Default is Dry Run, hardware Disabled, real motion false, camera Synthetic.
- [x] Every motion source uses the reviewed Motion Safety Gateway; API routes import no
  raw driver and expose no raw register/filesystem/Python escape hatch.
- [x] Commissioning uses an immutable read-only session purpose and `ReadOnlyServoBus`;
  its token cannot call or become a motion session.
- [x] Initial Calibration Revision 1 and recalibration N+1 share complete validation;
  Calibration completion alone never enables motion.
- [x] Field acceptance is local fingerprint-bound evidence; a stale or bare status value
  cannot authorize motion.
- [x] Stop uncertainty is represented truthfully and requires the physical E-stop.
- [x] `real-hardware-acceptance.md` remains entirely unchecked for this autonomous build.
- [x] Release notes state that Real field acceptance is required.

## Commissioning-fix re-verification

- Backend pytest exact result: 591 passed; one existing Starlette/httpx deprecation warning.
- Ruff / format / strict mypy exact result: PASS; 214 files clean.
- Schema/lock/dependency/isolation/secret-scan exact result: PASS; two deterministic
  generations equal tracked schemas, lock clean, 66 packages compatible, 102 isolation
  tests, secret scan and diff check pass.
- Frontend test/lint/type/build exact result: PASS; 215 tests/18 files, ESLint and
  TypeScript clean, 1,642-module build, JS 480.15 kB/135.88 kB gzip, npm audit 0.
- Focused commissioning and safe-gate isolation results: PASS; 88 commissioning tests
  and 102 hardware/camera isolation tests.
- Browser result: prior desktop/mobile/breakpoint acceptance remains covered by the full
  regression; the isolated READ_ONLY flow completed diagnostics and Revision 1 with
  motion blocked and console warning/error `[]`.
- Independent commissioning safety audit: PASS; no P1/P2 safety bypass remains.

## Final pre-merge hardening gates

- [x] Three immutable session purposes are verified; read-only cannot write,
  commissioning motion cannot call production motion, and no token upgrades.
- [x] The compiled/default commissioning envelope is backend enforced; local config can
  only narrow it and one ARM/lease can affect one enabled joint.
- [x] Backend deadman stops/faults on lease, network, route/browser, session, and shutdown
  loss; Fake Stop is not represented as physical verification.
- [x] Stable local `robot_unit_id` binds Device fingerprint, Calibration, sessions,
  commissioning evidence, Field Acceptance, Kinematics evidence, production evidence,
  and audit while remaining outside Profile fingerprinting.
- [x] Legacy/global PASSED evidence is audit-only stale; the writable
  `field_acceptance_status` config surface is absent, and no confirmation-only endpoint
  or UI action can forge full acceptance.
- [x] All enabled joints and both directions are required for Joint acceptance; every
  later capability uses its independent evidence prerequisites.
- [x] Kinematics commit requires multiple measured points, accepts no client joint state,
  uses a fresh server-owned session/device-bound snapshot, enforces thresholds/bindings,
  and leaves tracked provisional YAML unchanged.
- [x] Release bootstrap does not promote persisted Kinematics JSON; without a reviewed
  physical snapshot provider, Kinematics measurement and geometry-dependent Real
  capabilities fail closed and field verification must be repeated after restart.
- [x] One backend session/capability summary drives Control, Library, Studio, and Vision;
  raw operator authority remains only in the HttpOnly cookie.
- [x] `docs/api-audit.md` matches final routes, callers, services, scopes, stages, and
  retained/deprecated disposition; no bypass/raw/register/path/Python route remains.
- [x] `make test`, `make lint`, `make format-check`, `make build`, `make schemas`, and
  `git diff --check` pass on the final worktree.
- [x] Focused session/envelope/deadman/evidence/staleness/Bomb/isolation matrices pass on
  final worktree — 140 passed across the exact 13-file CI selection.
- [x] `uv lock --check`, `uv pip check`, `pip-audit`, and `npm audit --audit-level=high`
  pass without reduced strictness; no known Python vulnerabilities (local package skipped
  as non-PyPI) and 0 npm vulnerabilities.
- [x] Browser Fake V2 Phase 0–5 workflow passes with zero unhandled console errors while
  Feetech, physical Stop, Kinematics, Cartesian, Playback, and Vision remain blocked.
- [x] Architecture audit closes P1=0/P2=0 and records one supported P3: post-merge
  decomposition debt in the fail-closed 974-line `DeviceDiagnosticsService` coordinator.
- [ ] Push and pull-request CI are green for the final PR head; PR #1 remains Draft and
  `main` remains untouched.
- [x] Known user-acknowledged untracked duplicate files remain untouched and excluded.

## Historical Stage 8 delivery

- Original Stage 8 gate: 563 backend tests, 201 frontend tests across 17 files,
  strict mypy across 210 files, 42 compatible installed packages, 52 isolation tests,
  and the 1,642-module build at JS 465.73 kB/131.20 kB gzip.
- Original desktop/mobile/breakpoint browser workflow: PASS at 1440×960, 390×844,
  850, and 830; no horizontal overflow; console warning/error `[]`.
- Original independent Stage 8 audit: PASS; P1=0/P2=0 after 74 focused tests.
- Stage 8 commit/push/PR result: PASS —
  `4f7a75606aacb3fc93128445d7487ff196ce9efb` pushed; Draft PR
  [#1](https://github.com/39394480ke-sys/MOMO-Studio/pull/1) open against `main`.

## 9da6853 system-audit repair

This is the current pre-merge evidence; older counts above remain historical snapshots.

- [x] Capability-specific Joint/Cartesian/Playback/Vision evidence is restored and
  immutable per Session; no scope upgrades in place.
- [x] REAL execution consumes only the exact digest-bound trajectory accepted by final
  gateway validation.
- [x] Production and Raw Direction buses use monotonic Stop/session/Close fences;
  blocking Fake tests prove no stale command can report success after the fence.
- [x] Torque arm/disarm is executor-owned, per-Servo, rollback-capable, and never runs at
  startup or through a product-facing bypass.
- [x] Hardware operator TTL is 300 seconds by default; browser transport TTL is an
  independent 1,800 seconds.
- [x] Full backend: 728 passed. Full frontend: 295 passed across 31 files.
- [x] Hardware/camera/commissioning/production-Bomb isolation: 187 passed.
- [x] Ruff, Ruff format, strict mypy, ESLint, TypeScript, Vite build, lock/dependency
  checks, `pip-audit`, npm audit, deterministic schemas, and `git diff --check` pass.
- [x] Isolated DRY RUN browser flow passes at 1440×960, 1280×800, and 390×844 with no
  horizontal overflow and clean acceptance-tab warning/error console.
- [x] Exact Three.js 0.171.0 MIT and `urdf-loader` 0.13.1 Apache-2.0 texts are tracked.
- [x] Draft PR #2 CI is green for Backend/static/isolation, Frontend/lint/types/build/audit,
  and secret scan; base remains `codex/frontend-figma-redesign` and `main` is untouched.
- [ ] Repository distribution license decision is resolved.
