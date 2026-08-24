# Release candidate checklist

Status: Stage 8 software gates, complete Dry Run browser acceptance, and final independent
audit pass. The dedicated commit, push, clean-worktree check, and Draft PR disposition are
**pending root-task Git delivery**. Checkboxes are evidence gates, not implementation
claims.
Every field item in `real-hardware-acceptance.md` must remain unchecked during autonomous
work.

## Source and identity

- [x] Branch is `codex/v1-autonomous-completion`; `main` was not merged or modified.
- [ ] Stage 3–8 commits exist in order and the worktree is clean.
- [x] Version is `0.1.0-rc1` in Python, frontend, lockfiles, defaults, API metadata, and UI.
- [x] Release status is `FIELD_ACCEPTANCE_REQUIRED`; UI says Dry Run validated and Real
  hardware field acceptance pending.
- [x] Generated schemas and lockfiles match inputs deterministically.

## Automated gates

- [x] `make test` — backend 563 passed; frontend 201 passed across 17 files.
- [x] `make lint`
- [x] `make format-check`
- [x] `make build` — 1,642 modules; JS 465.73 kB / 131.20 kB gzip.
- [x] Two fresh schema generations are byte-identical and match the tracked tree.
- [x] `git diff --check`
- [x] `uv lock --project backend --check`
- [x] `uv pip check` — 42 installed packages compatible.
- [x] `npm audit --omit=dev --audit-level=moderate` — 0 vulnerabilities.
- [x] Hardware and camera isolation suites — 52 passed.
- [x] Secret/basic provenance scan
- [x] CI workflow contains no hardware, camera, Real config, or network model download.
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
- [x] Stop uncertainty is represented truthfully and requires the physical E-stop.
- [x] `real-hardware-acceptance.md` remains entirely unchecked for this autonomous build.
- [x] Release notes state that Real field acceptance is required.

## Final evidence handoff

- Backend pytest exact result: 563 passed; one existing Starlette/httpx deprecation warning.
- Ruff / format / strict mypy exact result: PASS; 210 files clean.
- Schema/lock/dependency/isolation/secret-scan exact result: PASS; two deterministic
  generations equal tracked schemas, lock clean, 42 packages compatible, 52 isolation
  tests, secret scan and diff check pass.
- Frontend test/lint/type/build exact result: PASS; 201 tests/17 files, ESLint and
  TypeScript clean, 1,642-module build, JS 465.73 kB/131.20 kB gzip, npm audit 0.
- Desktop/mobile/breakpoint browser workflow and console result: PASS at 1440×960,
  390×844, 850, and 830; no horizontal overflow; console warning/error `[]`.
- Final independent audit P1/P2 result: PASS; P1=0/P2=0 after 74 focused tests.
- Stage 8 commit/push/PR result: `PENDING_ROOT_GIT`
