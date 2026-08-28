# Stage 8: Real boundary and release hardening

- Date: 2026-08-24
- Branch: `codex/v1-autonomous-completion`
- Baseline: `dedbdabb9a35aefea01df05f0652214428305a93`
- Target version: `0.1.0-rc1`
- Release status: `FIELD_ACCEPTANCE_REQUIRED`
- Stage commit: `4f7a75606aacb3fc93128445d7487ff196ce9efb`

> Historical Stage report: the results below describe the original Stage 8 commit. ADR
> 0018 then fixed first-Calibration authorization. Final pre-merge hardening later found
> the second global-acceptance deadlock and partially superseded the two-purpose/single-
> PASSED model with ADR 0019. Historical counts remain valid for their commits but are not
> evidence for the final-hardening worktree.

## Outcome

Stage 8 implements the software boundary required for a release candidate without
claiming physical readiness. The tracked/default application remains loopback-only,
Dry Run, hardware Disabled, real motion/startup/local opt-ins false, Synthetic camera,
and field acceptance Pending. The default composition supplies no Real bus factory and
cannot construct or open a hardware adapter.

The release UI identifies itself as:

```text
MOMO Studio 0.1.0-rc1
Dry Run validated
Real hardware field acceptance pending
```

The first line is software identity, the second reports the evidence-backed Dry Run
product, and the third is a mandatory unresolved physical release gate. V1 and V2 are
hardware variants, never software versions.

Final combined automated gates, desktop/mobile/breakpoint browser acceptance, and the
independent audit are complete and recorded below. The dedicated Stage commit is pushed,
and Draft PR [#1](https://github.com/39394480ke-sys/MOMO-Studio/pull/1) is open.

## Commissioning and Real Motion authorization boundary

Stage 8 adds:

- a full bounded `ServoBus` port plus a capability-narrowed `ReadOnlyServoBus` for
  commissioning, exposing only explicit open/close, exact-ID ping, and bounded
  present-position/mode/torque reads;
- no scan, arbitrary register, torque-enable, Home, raw SDK, filesystem, or Python API;
- a deterministic Fake Bus for all autonomous hardware-boundary tests;
- a pure purpose-aware `RealHardwareAuthorization` matrix with independent commissioning
  diagnostics, Calibration capture, Joint, Cartesian, Playback, and Follow readiness;
- immutable `COMMISSIONING_READ_ONLY` and `REAL_MOTION` Operator Session purposes with
  exact scopes, evidence, confirmation, expiry, and no upgrade path;
- explicit device/protocol/ordered Servo IDs with masked public diagnostics;
- explicit Connect and read-only diagnostics with cleanup on partial failure;
- backend-owned session-expiry cleanup so an abandoned frontend cannot leave the bus
  open indefinitely;
- truthful typed Stop outcomes, including `SAFETY_STATE_UNCERTAIN`.

Commissioning requires Real mode, `READ_ONLY` policy, startup/local opt-ins, verified
non-template Profile, identified available adapter, explicit device/protocol/exact
Profile Servo IDs, and a current commissioning-purpose session. It deliberately does
not require `real_motion_enabled`, Calibration, acceptance, or Kinematics and cannot
grant any write or motion scope.

Real Joint Motion separately requires `FULL` policy, all motion opt-ins, complete
matching Calibration, current fingerprint-bound Field Acceptance Evidence, the same
exact device, and a newly confirmed motion-purpose session. Cartesian, Cartesian
Playback, and Follow additionally require matching `VERIFIED_FOR_REAL` Kinematics. No
environment value, local file value, frontend action, or old commissioning token bypasses
another gate.

Committed example Profiles/Calibration and both provisional Kinematics models fail this
matrix. The shipped/default application therefore reports blockers rather than Ready.

## Feetech adapter status

The repository contains an independently written lazy optional Feetech adapter shell.
It is deliberately reported as **Pending Adapter Verification**:

- no third-party SDK source was vendored or copied;
- no optional Feetech package is required by the default install;
- module import and adapter construction do not open a port;
- optional SDK import occurs only inside a factory holding a complete grant;
- the factory refuses use until exact package/module/API/license approval is supplied;
- goal writes remain disabled pending bounded cancellation/field verification;
- physical Stop semantics are not guessed and return `SAFETY_STATE_UNCERTAIN`.

The tracked Legacy dependency declaration and public package record are provenance
candidates only. Distribution and physical use require the exact package/version/source,
license files, API behavior, binary/transitive provenance, cancellation behavior, and
field Stop semantics to be independently approved.

## Protected Calibration workflow

The current-angle workflow is explicit, selected-joint, and commissioning-read-only:

```text
commissioning session
  -> explicit read-only connection
  -> create an incomplete Profile-bound draft (no stored Calibration is allowed)
  -> choose one enabled joint
  -> read that configured Servo's present raw value
  -> enter observed logical value
  -> preview direction/Home/phase/raw bounds/round-trip/fingerprint
  -> confirm the joint
  -> repeat for every Profile-enabled joint
  -> validate the complete proposed Calibration
  -> atomically save Revision 1, or Revision N+1 for recalibration
  -> close/revoke device authorization in final cleanup
```

Missing draft fields remain absent and are never replaced by zero. The workflow cannot
scan, move, write a goal/register, change mode, toggle torque, or promote an example.
Saving Revision 1 does not enable motion; Field Acceptance Evidence and a new
`REAL_MOTION` session remain mandatory. The Real Calibration repository keeps one current file per variant under a
fixed ignored root. A forward save preserves prior exact bytes in a private
revision/fingerprint backup and atomically replaces current bytes. Rollback restores old
content as a new UUID/new forward revision; it never rewinds history. Persistence and
cleanup reach a terminal result despite repeated caller cancellation. Once a save or
rollback persistence attempt starts, device authorization is invalidated in `finally`,
including after replace-then-directory-fsync failure.

## Field Acceptance Evidence

A local ignored evidence document binds an acceptance pass to schema and checklist
versions, robot variant, Profile fingerprint, Calibration fingerprint, optional
Kinematics fingerprint, device fingerprint, acceptance time, and optional operator
identity. A settings value of `PASSED` is display/compatibility input only and cannot
authorize motion. Profile, Calibration, device, Kinematics, variant, or checklist drift
makes the evidence stale and returns motion readiness to blocked until acceptance is
explicitly repeated. See ADR 0018.

## Final pre-merge hardening addendum

The current model resolves the second deadlock without weakening production motion:

- `COMMISSIONING_READ_ONLY`, `COMMISSIONING_MOTION_TEST`, and `REAL_MOTION` are separate,
  non-upgradeable purposes with new confirmation/evidence for every transition;
- stable local `robot_unit_id` binds Device fingerprint, Real Calibration, sessions,
  commissioning evidence, Field Acceptance, Kinematics evidence, production evidence,
  and audit, but is excluded from the generic Profile fingerprint;
- restricted commissioning permits only a separately armed relative single-joint test,
  with backend hard caps, fresh readback/mapping/limits, one prepared command, a 400 ms
  backend deadman, and immutable pass/failure evidence;
- the commissioning service receives a narrowed bus rather than the production executor;
- Field Acceptance contains independent pre-motion, Joint, Cartesian, Playback, and
  Vision Follow evidence; global/schema-v1 `PASSED` records remain
  `STALE_LEGACY_EVIDENCE` and cannot grant authority; the writable
  `field_acceptance_status` Settings/default-config surface is removed and the remaining
  backward/internal scalar starts pending;
- bootstrap grants no authority from deserialization/fingerprints alone: it semantically
  revalidates the embedded typed pre-motion diagnostic snapshot and resolves every Joint
  test UUID, prepared command, direction, enabled joint, and exact current envelope;
- current Joint evidence requires both directions and readback for every explicit
  enabled joint; later capabilities add Kinematics and their own acceptance records;
- tracked Kinematics YAML remains `PROVISIONAL_DRY_RUN`; only an exact-unit, multi-point
  live evidence overlay produced from server-owned joint snapshots can derive effective
  Real verification; `0.1.0-rc1` has no physical snapshot provider and treats persisted
  Kinematics JSON as audit-only after restart;
- an HttpOnly operator cookie carries authority while the global frontend context stores
  only the backend summary, capability matrix, expiry, and blocked reasons used by
  Control, Library, Studio, and Vision.

The field checklist now follows Phases 0–10 from physical preparation through final
review. Feetech goal write, software/physical Stop, physical E-stop, physical Kinematics,
and all Real capability acceptance remain pending. Final local hardening evidence passes
629 backend tests, 230 frontend tests across 19 files, the exact 140-test CI isolation
selection, all requested static/build/schema/dependency gates, and the Fake 12-direction
browser flow with console warning/error `[]`. The re-audit closes P1=0/P2=0 and records
one P3 `DeviceDiagnosticsService` decomposition debt. Final commit IDs and push/PR CI are
recorded in `final-pre-merge-hardening.md` only after they exist.

## Real executor software path

`RealMotionExecutor` accepts only the exact immutable `PreparedTrajectory` and expected
digest. It maps logical samples through the verified Profile/Calibration, checks raw
bounds, schedules monotonic deadlines, writes only the exact Servo-ID map, reads back,
checks divergence, and updates high-level state through an observer. It revalidates
authorization, purpose, artifact identity, state sequence, and position continuity at
safety boundaries.

Partial write, timeout, bus fault, disconnect, readback mismatch, divergence, session
expiry, cancellation, and Stop enter typed terminal/fault states. The executor does not
compile browser samples, scan a device, or open a bus. Autonomous execution uses only
Fake Bus; default API composition does not expose this executor.

## Local/LAN security and audit

The default bind is `127.0.0.1`. LAN requires explicit enablement, a concrete private
address, a strong long-term token, authentication, and at least one exact allowlisted
Origin. The Stage 8 server is HTTP-only: LAN browser Origins must use the same HTTP
scheme and exact API bind host; the UI port may differ. Wildcard, public, cross-host,
opaque, and HTTPS Origins fail closed. The server does not trust proxy headers, bind a
wildcard, create a tunnel, configure UPnP, or provide TLS termination.

REST, control, WebSocket, and Vision use one verifier. The browser exchanges the
long-term Bearer once for a bounded short-lived HttpOnly `SameSite=Strict` cookie and
retains only expiry metadata. No credential enters a URL or browser storage. An
established Robot WebSocket and Vision stream reauthorize before every bounded
publish/frame, so expiry or revoke terminates them. Priority Stop remains authenticated
but bypasses the ordinary control-command rate bucket.

Every HTTP request receives a bounded structured audit event. Motion submission/Jog
start populate exact command ID, `primary` robot, `DRY_RUN` mode, and preflight state in
addition to request/principal/source/outcome/duration/error evidence. Recursive
redaction removes credentials, sessions, HTTP URLs, file URIs, POSIX/Windows/embedded
absolute paths, and masks serial identity. Sinks are bounded memory or a fixed private,
symlink-resistant, size/rotation-bounded JSONL file.

## Backup, migration, and process-crash recovery

Backup export is deterministic canonical JSON for Pose, Motion, and MotionDraft.
Calibration is excluded unless explicitly selected. Secrets, serial/device/runtime/log/
camera/local-path data are rejected. Import accepts uploaded bytes, never a server path,
and performs bounded syntax/digest/schema/domain/safety/migration/collision validation.
Only `reject` and `skip` collision policies exist; restore never overwrites.

A valid preview records one bounded five-minute, one-use server grant bound to the exact
bundle digest, collision policy, and Calibration choice. Restore consumes that grant,
reparses/revalidates under the shared repository maintenance gate, then writes exact
final entity revisions instead of replaying revision history.

Before the first create, restore durably publishes a bounded write-ahead transaction
containing exact entity kind/UUID/revision and absent Calibration variant/UUID targets.
Create/delete/Calibration workers survive repeated caller cancellation to a known
terminal filesystem result. A post-replace directory-fsync failure is treated as a
committed create and compensated. The journal is cleared only after complete commit or
proven compensation.

Application lifespan runs pending-restore recovery before serving traffic. A surviving
WAL causes exact target compensation and durable journal removal; invalid or incomplete
recovery blocks startup. This supplies process-crash atomic restore for the supported
single-backend, server-owned repository configuration. Multiple writers, external
manual edits, unsupported/network filesystems, media corruption, and disk loss remain
outside that guarantee.

## App and release preparation

- the frontend API base and Vite asset base are relative/configurable;
- one FastAPI backend can serve the built React SPA with safe extensionless refresh;
- missing API and asset paths remain 404; `index.html` is `no-store`;
- framework `/docs` and `/redoc` are disabled to remove CDN-backed interactive docs;
- `/openapi.json` remains local JSON with no CDN dependency;
- the release UI uses no runtime CDN or Internet model/asset download;
- Tauri remains a later packaging adapter; no second GUI or native project was added;
- GitHub Actions cover backend/frontend/static/schema/isolation/secret gates without
  hardware, camera, Real configuration, or network model download.

Repository-license selection, exact third-party license collection, packaged binary
reproducibility/signing/notarization, and any native update mechanism remain release
distribution gates.

## Verification status

| Gate | Final Stage 8 result |
|---|---|
| Full backend pytest | PASS — 563 passed; one existing Starlette `TestClient`/httpx deprecation warning |
| Ruff / Ruff format / strict mypy | PASS — 210 files clean |
| Deterministic schemas / tracked diff / lock | PASS — two fresh generations byte-identical and equal to tracked schemas; `uv lock --check` clean |
| Dependency / isolation / secret / diff gates | PASS — `uv pip check` reports 42 compatible packages; 52 isolation tests; high-confidence secret scan and `git diff --check` pass |
| Full frontend tests / ESLint / TypeScript / build / npm audit | PASS — 201 tests across 17 files; static gates pass; 1,642 modules; JS 465.73 kB / 131.20 kB gzip; 0 vulnerabilities |
| Desktop 1440×960 workflow | PASS — complete V2 Dry Run Control→Library→Studio→Playback→Synthetic Vision→Disconnect flow |
| Mobile 390×844 workflow | PASS — responsive navigation/content, no page horizontal overflow |
| Breakpoint/error/offline/console acceptance | PASS — 850/830 widths, offline/stale and fail-closed Real/Calibration states observed; warning/error console `[]` |
| Final independent integrated audit | PASS — P1=0/P2=0; 74 focused tests |
| Stage 8 commit and push | PASS — `4f7a75606aacb3fc93128445d7487ff196ce9efb` on `origin/codex/v1-autonomous-completion` |
| Draft PR | PASS — [#1](https://github.com/39394480ke-sys/MOMO-Studio/pull/1), open as Draft against `main` |

The desktop workflow selected V2, connected only the Dry Run robot, exercised Joint jog,
Move Joints, FK, Cartesian jog, unreachable and reachable IK, Move Pose, and captured Pose
A/B. It created a Motion, edited a Studio transition with hold `0.2`, duration `2.5`,
`ease-in-out`, and `JOINT`, then completed preflight, Play/Pause/Resume/Stop. It changed
the transition to `CARTESIAN_LINEAR`, completed preflight, used Save As, and replayed the
saved Library Motion to 100%. Synthetic Vision selected an ROI, entered Follow `ACTIVE`,
then used a deterministic edge ROI to produce `TARGET_LOST` and automatic Stop. The robot
was disconnected. Offline/stale behavior and the blocked Real/template-Calibration/
field-pending states remained explicit. No browser step entered a Real path.

## Autonomous safety statement

```text
No serial port was opened.
No serial device enumeration was performed.
No servo scan was performed.
No servo register was read.
No servo register was written.
No torque command was sent.
No real Home command was sent.
No real motion command was sent.
No real calibration was read or modified.
No physical robot was moved.
No real camera was opened.
No camera enumeration was performed.
No microphone was opened.
All autonomous motion verification used Dry Run or Fake adapters.
Real-hardware field acceptance remains required.
```

## Known limitations and mandatory next gates

- Every item in `docs/real-hardware-acceptance.md` is intentionally unchecked.
- Feetech adapter, goal-write cancellation, operating modes, readback, and physical Stop
  semantics are pending adapter/field verification.
- V1/V2 geometry, frames, TCP, limits, direction, Home, workspace, FK/IK, dynamics, and
  Cartesian accuracy are not physically verified.
- Live camera/OpenCV/provider behavior is not part of autonomous acceptance.
- Stage 8's built-in LAN server is HTTP-only and suitable only for a trusted private
  network; TLS/reverse-proxy support needs separate review.
- A repository license and exact third-party distribution notices remain unresolved.
- Tauri/native packaging and packaged-app acceptance are deferred.

```text
Software implementation complete.
Dry Run validated.
Real-hardware field acceptance required.
```
