# 9da6853 system audit fixes

- Date: 2026-08-30
- Baseline branch: `codex/frontend-figma-redesign`
- Starting commit: `9da68536d26eb2d37c4f9acbed8f30dee57843e4`
- Delivery branch: `codex/9da6853-system-audit-fixes`
- Final commit: recorded in the Draft PR and final handoff after this report's own commit
- Draft PR: [#2](https://github.com/39394480ke-sys/MOMO-Studio/pull/2)
- Base branch: `codex/frontend-figma-redesign`; `main` is not modified

This report is the current evidence ledger for the system-level repair. It separates
software verification from physical acceptance. No software result in this report is
evidence that a physical robot, Stop circuit, torque transition, Feetech timing, camera,
or cancellation deadline has passed field verification.

## Executive result

Final local verification is green. The implementation restores capability-specific
production authorization, binds every issued scope to immutable evidence, moves exact
trajectory compilation ahead of final preflight, fences stale production-bus writes,
and makes torque an explicit executor-owned lifecycle. It also splits hardware and
browser Session TTLs, keeps the versioned Robot WebSocket canonical, adds structured
Studio compatibility recovery, and suspends inactive Viewer rendering.

## Reproduced baseline failures

The exact `9da6853` baseline was checked in an isolated detached worktree after locked
Python 3.11 and npm installation. Backend collection contained 690 tests: 686 passed and
the four authorization/TTL tests below failed. The WebSocket test passed on the actual
baseline because the public URL was already `/api/v1/ws/robot`; its assertion and audit
documentation nevertheless inspected the unprefixed router path and were corrected to
the public canonical contract.

| Audit case | Baseline result | Repair disposition |
|---|---|---|
| public Robot WebSocket path | PASS on actual baseline | Test now resolves the mounted public URL; docs use `/api/v1/ws/robot` |
| Calibration Revision 1 without acceptance | FAIL: production Session authorizable | Fixed in implementation; final full-suite result below |
| bare `field_acceptance_status=PASSED` without evidence | FAIL: production Session authorizable | Fixed in implementation; final full-suite result below |
| default LAN browser exchange | FAIL: shared one-year TTL rejected | Split TTLs; final full-suite result below |
| stale LAN cookie replacement after restart | FAIL: shared one-year TTL rejected | Split TTLs and retained explicit Bearer replacement; final full-suite result below |

## Root cause and final capability matrix

`RealHardwareAuthorizationService` built a strict `production_base` but Joint,
Cartesian, and Playback readiness used the weaker manual/pre-motion base. That bypassed
verified-Profile, Joint-acceptance, Physical-Stop, and capability-specific evidence
requirements when REAL configuration was otherwise enabled. Separately,
`OperatorSessionEvidence` carried only a single Joint-oriented compatibility field, so
it could not prove why Cartesian, Playback, Vision, or Kinematics scopes had been issued.

All production rows now share the startup opt-in, explicit local opt-in, REAL/FULL mode,
exact unit/device/Servo allowlist, reviewed dependency, verified Profile, complete
unit-bound Calibration, current Joint acceptance, physical Stop verification, and a new
short-lived `REAL_MOTION` Session. Additional requirements are:

| Scope / executable content | Additional current bindings |
|---|---|
| `REAL_JOINT_MOTION` | Joint Motion acceptance UUID |
| `REAL_CARTESIAN_MOTION` | Cartesian acceptance UUID plus current Kinematics verification UUID/fingerprint |
| `REAL_PLAYBACK`, Joint/Hold only | Playback acceptance UUID |
| `REAL_PLAYBACK` containing `CARTESIAN_LINEAR` | Playback and Cartesian acceptance UUIDs plus current Kinematics verification UUID/fingerprint |
| `REAL_VISION_FOLLOW` | Vision Follow acceptance UUID plus controller-required Kinematics verification UUID/fingerprint |

`capability_evidence_ids` is the immutable capability-to-UUID map.
`kinematics_verification_evidence_id` and `kinematics_fingerprint` are separate immutable
geometry bindings. The old `field_acceptance_evidence_id` is accepted only as the Joint
Motion compatibility alias. Context or evidence drift invalidates the Session; new
evidence never upgrades an existing Session in place. A REAL Session is not issued when
no production scope is currently backed by evidence.

Physical Stop remains an independent production gate. Fake Hold proves only a software
Hold path, returns `safety_state_known=false`, and never creates
`VERIFIED_FOR_UNIT` evidence.

## Exact executable trajectory

The former command adapter generated smoothstep samples after the Motion Safety Gateway
and constructed its own accepted trajectory report. The new boundary is:

```text
intent -> exact samples -> every-sample validation -> immutable digest/report
       -> PreparedTrajectory -> purpose-bound executor -> explicit raw mapping
```

Joint, Home, Goto, Cartesian, and bounded continuous commands now receive one exact,
digest-bound `PreparedTrajectory` from the gateway. The final validation covers the
complete joint/unit set, Profile and raw-derived limits, FK/workspace, Cartesian TCP/FK
agreement, speed, and acceleration. The command adapter refuses a missing or stale
artifact and passes the identical digest/report to status and audit; it does not
interpolate or manufacture `accepted=True`. Sample mutation invalidates the digest.

Continuous Jog still uses a bounded precompiled envelope, but its lease/deadman and
execution authorization are rechecked before every possible bus write. Stop/lifecycle
epochs reject work prepared before or during a transition.

## Stop fence, blocking SDK, and torque lifecycle

The production bus uses a monotonic write generation. Stop, Close, cleanup, and torque
disarm advance/fence the generation before waiting for serialized SDK ownership. A
queued old write cannot begin after the fence and an in-flight old call cannot report
success after the fence. Stop/Close do not report completion while a controlled blocking
SDK thread still owns the transport. Because the third-party call is not hard-cancellable,
an in-flight physical call may finish before the serialized Hold/Close can run; that
condition remains `SAFETY_STATE_UNCERTAIN` and field-verification-gated rather than being
described as a hard real-time deadline.

Torque is no longer a hidden first-goal side effect. The executor explicitly arms the
exact authorized Servo set after its last context check, records per-Servo results,
best-effort rolls back partial enable, and explicitly disarms on completion, Stop,
fault, and close. Cleanup attempts every Servo even after an earlier error. Any partial
transition or close error remains safety-uncertain. There is no API/UI torque switch and
startup never enables torque.

## Lifecycle and Session TTLs

REAL connection binds one current Session/device bus rather than treating a Joint grant
as Cartesian/Playback authority; each execution still carries and revalidates its own
purpose-specific authorization. Authenticated user Disconnect and trusted backend
cleanup are separate paths. Expiry, revoke, shutdown, and cleanup can always fence
writes, Stop, unbind, best-effort disarm/close, invalidate the Session, and release the
port without relying on a still-valid motion cookie.

Hardware operator authority defaults to 300 seconds and is constrained to 30–900
seconds. LAN browser security authority defaults to 1,800 seconds and is constrained to
30–43,200 seconds. The browser exchange alone drives HttpOnly cookie `Max-Age`/`Expires`;
cookies remain `SameSite=Strict`, become `Secure` on HTTPS, and the raw token is never
returned in JSON. A valid long-term Bearer can replace a stale cookie after restart.

## WebSocket, Studio, and Legacy compatibility

The single canonical read-only Robot socket is `/api/v1/ws/robot`. No duplicate alias
was added.

Studio contract failures retain Fail Closed behavior and return bounded structured
diagnostics: draft/active variant, keyframe ID/index/name/source Pose, checks, expected
and actual joints/units/Profile/Kinematics fingerprints, missing/extra joints, TCP
mismatch, state-sequence issue, and provenance issue. The Chinese product surface
explains that simulation/playback is blocked, identifies affected keyframes, and exposes
only explicit replacement, capture, delete, safe variant switch, compatible-copy (when
deterministic), or abandon actions. It never fills missing joints, changes units, swaps
fingerprints, or edits imported originals silently. Default keyframe labels prefer the
source Pose name, then `关键帧 N`; J10 values remain secondary metadata.

Library compatibility is evaluated before execution. Imported originals remain immutable
audit records; incompatible assets are marked/warned and require an explicit repaired
copy before use.

## Viewer and assets

The Viewer runtime is render-on-demand while static. Joint changes and Orbit interaction
invalidate one frame; active playback alone requests continuous frames. Hidden,
offscreen, and reduced-motion states suspend unnecessary work. Unmount removes listeners
and observers, cancels animation frames, disposes controls/resources, and loses the
WebGL context exactly once.

Three/URDF code stays dynamically loaded, and V1/V2 asset manifests are separate lazy
chunks so selecting one variant does not request the other. Full robot meshes are not
used as repeated Library-card thumbnails. Exact upstream license texts are tracked for
Three.js 0.171.0 (MIT) and `urdf-loader` 0.13.1 (Apache-2.0); MOMO/Legacy asset provenance
remains separate and is not relicensed.

## Architecture audit

The final audit traces Control Joint, continuous Joint Jog, Cartesian step/hold, Home,
Move Pose, Pose Goto, Library Playback, Studio Goto/Playback, Vision Follow,
Commissioning Motion Test, and Raw Direction Test. The required production shape is
route -> application service -> Motion Safety Gateway -> exact prepared artifact ->
purpose authorization -> executor -> narrowed bus.

- P1: **0 open**. The independently discovered Raw Direction adapter lock held across
  its complete settle loop, so priority Stop/deadman cleanup could not interrupt it.
  The adapter now uses short serialized SDK stages plus a monotonic generation fence;
  Stop/session reset/Close revoke an in-flight step before waiting, and the service
  preserves `OPERATOR_STOP`/expiry as terminal state.
- P2: **0 open**. Vision Follow start/heartbeat had their transport rate budgets reversed;
  start now uses normal control admission and heartbeat uses keepalive admission. The
  lifecycle's session-neutral binding/trusted cleanup paths and the public WebSocket
  path assertion were also corrected during the audit.
- P3: the existing large API client/pages/hooks/styles remain bounded maintenance debt;
  this safety repair performs only local decomposition and does not start a broad UI
  rewrite.

No route imports a concrete driver. No raw/register, scan/enumeration, arbitrary
filesystem/Python, hidden REAL override, frontend-only authorization, token-storage, or
REAL-to-DRY_RUN fallback surface is introduced.

## Verification ledger

| Gate | Final result |
|---|---|
| Backend `pytest` | PASS — 728 passed; one known Starlette/httpx deprecation warning |
| Frontend Vitest | PASS — 295 passed across 31 files |
| Ruff / Ruff format / strict mypy | PASS — 261 files in strict mypy; 261 formatted files |
| ESLint / TypeScript | PASS |
| Vite production build and bundle report | PASS — 1,679 modules; main 510.32 kB/150.96 kB gzip; Viewer 585.40 kB/149.57 kB gzip; variant manifests are separate ~1 kB lazy chunks |
| `pip-audit` / `npm audit --audit-level=high` | PASS — no known vulnerabilities; local non-PyPI package skipped; npm 0 vulnerabilities |
| Hardware/camera/commissioning/production Bomb isolation | PASS — 187 tests |
| deterministic JSON Schemas | PASS — two temporary generations byte-identical to each other and tracked schemas |
| `uv lock --check` / `uv pip check` | PASS — 71 packages resolved; 66 installed packages compatible |
| `make test`, `make lint`, `make format-check`, `make build`, `make schemas` | PASS on the final documented worktree |
| `git diff --check` | PASS |
| Browser QA at 1440x960, 1280x800, 390x844 | PASS for isolated DRY RUN product flow and responsive overflow; console warning/error `[]` |
| Pull-request CI | PASS — Backend/static/isolation, Frontend/lint/types/build/audit, and secret scan |

## Browser acceptance

Browser QA used an isolated loopback backend with DRY_RUN, hardware disabled, temporary
repositories, a Synthetic camera, and the in-app browser. Control covered connect,
disconnected state, Joint command, route-change cancellation, Home/Cartesian control
availability, priority Stop, and disconnect. Studio captured two default-named keyframes,
loaded the V2 Viewer, played/paused simulation, and never treated scrub as hardware.
Library and Settings loaded at all three requested viewports without horizontal overflow;
Settings showed DRY RUN and `SYNTHETIC_ONLY`. The clean acceptance tab's warning/error
console was `[]`.

Structured incompatible-Draft recovery, Legacy Pose/Motion warnings, continuous-Jog
lease loss, LAN cookie renewal/restart, and Viewer hidden/offscreen scheduling are covered
by deterministic backend/component integration tests rather than fabricated browser data.

## Commits, repository state, CI, and limitations

| Commit | Summary |
|---|---|
| `a8fc3ad` | restore capability authorization, immutable Session evidence, TTL split, lifecycle cleanup |
| `141a742` | exact trajectory boundary, generation fences, explicit torque, Raw Direction Stop |
| `2059b07` | Studio/Library recovery, canonical socket regression, Viewer scheduling, exact licenses |
| final documentation commit | reconcile reports and final evidence |

- Final `git status --short`: clean after the final documentation commit.
- Push/Draft PR URL: [Draft PR #2](https://github.com/39394480ke-sys/MOMO-Studio/pull/2), base `codex/frontend-figma-redesign`.
- CI link/result: PASS on [GitHub Actions run 33297675264](https://github.com/39394480ke-sys/MOMO-Studio/actions/runs/33297675264) (PR event); the duplicate push-event run also passed.
- `main`: not checked out, merged, rebased, or modified by this task.

Known limitations:

1. Physical Stop, torque transitions, SDK scheduling, Feetech timing, and in-flight
   third-party-call cancellation cannot be proven by software Fakes.
2. Production adapter enablement and every unresolved capability acceptance remain Fail
   Closed until exact-unit field verification.
3. Real Vision Follow remains unavailable until its typed provider/mapping/acceptance
   workflow is complete; Synthetic Follow remains the validated product workflow.
4. Large frontend modules and full-resolution meshes remain bounded P3/performance debt;
   the selected variant is lazy, but Vite still emits the tracked static assets.
5. The repository distribution license decision remains pending. MOMO asset ownership
   and third-party library license texts do not grant rights to unrelated Legacy assets.

## Safety and isolation declaration

- No serial port was opened.
- No serial device enumeration was performed.
- No servo scan was performed.
- No servo ping was performed.
- No servo register was read.
- No servo register was written.
- No torque command was sent.
- No real Home command was sent.
- No real Joint command was sent.
- No real Cartesian command was sent.
- No real Playback command was sent.
- No real calibration was read or modified.
- No physical robot was moved.
- No real camera was opened.
- No camera enumeration was performed.

All REAL-path verification used Fake, Bomb, blocking fake SDK, temporary repositories,
or isolated adapters.

Passing software tests does not constitute physical field acceptance.

Physical Stop, Torque lifecycle, Feetech timing, and stale-write cancellation remain
field-verification-gated until independently measured on the exact robot unit.
