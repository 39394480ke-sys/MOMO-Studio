# Final pre-merge Real commissioning hardening

- Date: 2026-08-25
- Release: `0.1.0-rc1`
- Branch: `codex/v1-autonomous-completion`
- Starting commit: `eb90d516dcc1cb7c09d75fc7c5894e9f619116a6`
- Implementation commit: `b0d5f076e32e33d86687751cb1a0c61049555dce` —
  `fix: add staged field acceptance and commissioning motion tests`
- Final docs/delivery head: recorded in PR #1 and the final task response after the docs
  commit is created and pushed; this file cannot contain its own Git object ID
- New commits: implementation commit above plus the final docs commit recorded in that
  external handoff
- Draft PR: [#1](https://github.com/39394480ke-sys/MOMO-Studio/pull/1), must remain Draft
- Base: `main` at `32d0163431e229cb3c2e01a285e7e851124ce9c1`, must remain untouched

This report separates implemented software design from verification outcomes. A gate is
not PASS until its final command or CI run is recorded below. Historical Stage 8 and
first commissioning-fix results are baselines only.

## Second Field Acceptance deadlock

The first fix made read-only diagnostics and initial Calibration reachable without Real
Motion authority. A second cycle remained:

```text
production Real motion requires global Field Acceptance PASSED
  -> field checklist requires physical joint/Cartesian/Playback/Vision motion
  -> that motion cannot run before PASSED
```

Creating `PASSED` first would invert the evidence order. This hardening adds a separate,
severely bounded commissioning-motion purpose and replaces one writable pass with staged
capability evidence.

## Three immutable Session purposes

| Purpose | Authority | Explicit exclusions |
|---|---|---|
| `COMMISSIONING_READ_ONLY` | Exact-device diagnostics and Calibration capture | Every write and motion operation |
| `COMMISSIONING_MOTION_TEST` | One separately armed relative single-joint test under the frozen envelope/deadman | Production Joint, Home, Cartesian, Playback, Library/Studio, Vision, multi-joint and raw operations |
| `REAL_MOTION` | Only production capabilities backed by current capability evidence | Any capability lacking its own current evidence |

Purpose never upgrades. A purpose change requires a new session ID, raw token, expiry,
confirmation, and evidence snapshot. The independent default-false
`commissioning_motion_test_enabled` switch is not `real_motion_enabled`.

## Commissioning safety envelope

The backend immutable hard maxima are:

| Limit | Maximum |
|---|---:|
| Active joints | 1 |
| Command duration | 2.0 s |
| Session duration | 300.0 s |
| Revolute / prismatic delta | 2.0 deg / 1.0 mm |
| Revolute / prismatic speed | 2.0 deg/s / 1.0 mm/s |
| Revolute / prismatic acceleration | 4.0 deg/s² / 2.0 mm/s² |
| Deadman lease | 400 ms |
| Commands per session | 24 |

Local configuration may only narrow these maxima. The client cannot submit an envelope,
and active sessions retain their frozen snapshot.

## Backend deadman

Each attempt must be ARMED and heartbeat-renewed. Frontend release/cancel, blur, hidden
visibility, route teardown, component unmount, and request/network failure request Stop.
The backend independently owns expiry; loss of heartbeat, session expiry, authorization
drift, shutdown, operator Stop, or Global Stop ends/faults the attempt even if the browser
cannot deliver a final request. A lease is bound to the current attempt and cannot be
reused.

## ServoBus capability narrowing

Read-only commissioning receives `ReadOnlyServoBus`. Restricted motion receives only
`CommissioningMotionServoBus`: selected-joint readback, one explicitly prepared goal,
and the typed Stop/Hold request supported by the adapter contract. It receives neither
the production executor nor multi-Servo, raw-register, arbitrary-ID, scan, enumeration,
mode, torque, Home, Cartesian, Playback, or Vision capability.

The physical Feetech adapter remains `PENDING_ADAPTER_VERIFICATION`. Goal-write and
physical/software Stop behavior are not promoted by Fake tests, and the production
factory remains closed until independent field evidence exists.

Focused regression fixtures include a `ProductionMotionBomb`, which fails if restricted
commissioning reaches Home/multi-joint/Cartesian/Playback/Vision production motion, and
a `CommissioningEnvelopeBomb`, which fails if a command beyond the frozen envelope
reaches the adapter. The Fake V2 backend flow assigns a unit, completes read-only
commissioning/Revision 1/pre-motion checks, records `j10`–`j15` positive and negative
tests, and derives Joint evidence while retaining physical production blockers.

## Test-move data flow

```text
ARM + live lease
  -> authorize exact motion-test session/unit/joint
  -> read fresh present value
  -> target = readback + bounded signed delta
  -> Profile logical limits + Calibration-derived raw limits
  -> exact mapping and preflight
  -> immutable prepared one-joint command
  -> narrowed bus write
  -> fresh raw/logical readback
  -> direction/delta/freshness/limits/divergence verification
  -> typed Stop/Hold when required
  -> atomic immutable pass/failure evidence + redacted audit
```

## Commissioning evidence

`CommissioningTestEvidence` binds UUID/schema/revision, `robot_unit_id`, variant,
Profile/Calibration/Device fingerprints, session/request/operator/software commit,
joint/unit, start/request/target/final logical and raw values, requested speed, expected/
observed direction, divergence, Stop behavior, timestamps, result, and bounded optional
failure reason. Passing evidence additionally embeds the complete prepared command and
frozen envelope required by the acceptance resolver. The server owns UUID paths; records
are local, ignored, immutable, and atomic. Audit records contain bounded operational
facts and never a session token.

## Physical unit identity and Device fingerprint

`robot_unit_id` comes from ignored local configuration and is empty in tracked examples.
It is not inferred from a serial path, hostname, protocol, or Servo IDs. It enters Device
identity/fingerprint, Real Calibration binding, session/test/acceptance/Kinematics/
production evidence, and audit. It is intentionally excluded from
`RobotProfile.fingerprint`, which identifies a variant contract rather than a specimen.

Evidence without unit identity or with a different unit is stale and cannot be upgraded.
The Device fingerprint is the canonical SHA-256 of the stable `robot_unit_id`, explicit
serial port, protocol, and ordered Servo-ID allowlist. It therefore changes when the
physical-unit label or connection identity changes; Profile fingerprinting remains
unit-independent.

## Staged Field Acceptance

`FieldAcceptanceBundle` contains independent `PRE_MOTION_CHECKS`, `JOINT_MOTION`,
`CARTESIAN`, `PLAYBACK`, and `VISION_FOLLOW` evidence. `accepted_by` is required; records
either embed the typed pre-motion snapshot or reference server-generated supporting
tests, and readiness is recalculated against current fingerprints/checklist. There is no
Accept All, Mark Robot Ready, or writable full-completion pass.

Persisted bundle files are non-authoritative on deserialization. Before authorization,
the service semantically resolves embedded/referenced evidence and publishes a transient
validated bundle. Pre-motion embeds session/time and exact per-joint Servo ping, mode,
raw/logical value, bounds, and torque-off data; bootstrap recomputes mapping/bounds and
coverage so it can survive READ_ONLY → FULL restart without trusting fingerprints alone.
Joint records resolve every UUID and require each embedded prepared command's frozen
envelope to equal the exact current commissioning envelope.

PRE_MOTION/JOINT acceptance is a discrete linearized commit under the Device guard: the
same token/session/operator and current context are reauthorized, the resolved record is
durably saved, the old session/connection is invalidated, and the live bundle is
published before unlocking. If concurrent revoke wins first, no pass record is saved.
Kinematics is audit-first and reauthorizes before live publication; a losing race may
leave an audit file, but it grants neither live nor post-restart authority.

Joint acceptance requires positive, negative, limit-safe, and fresh logical/raw evidence
for every Profile-enabled joint: V1 `j11`–`j15`, V2 `j10`–`j15`. One joint or one
direction is insufficient.

| Capability | Required current evidence |
|---|---|
| Real Joint | Joint Motion |
| Real Cartesian | Joint + Kinematics + Cartesian |
| Joint-only Playback | Joint + Playback |
| Cartesian Playback | Joint + Kinematics + Cartesian + Playback |
| Real Vision Follow | Joint + Vision Follow + Kinematics when required by the controller |

All rows also retain independent startup/config/Profile/Calibration/Device/adapter/Stop/
operator/session gates.

Only PRE_MOTION and JOINT have acceptance transitions/resolvers in `0.1.0-rc1`.
CARTESIAN, PLAYBACK, and VISION_FOLLOW records remain audit-only until later typed field-
test repositories and semantic resolvers exist; the capability matrix is a required gate,
not a claim that those physical workflows are already accepted.

## Legacy global PASSED disposition

The compatibility GET may report a derived summary. The OpenAPI-deprecated legacy POST
fails with `FIELD_ACCEPTANCE_MANUAL_PASS_FORBIDDEN`; it cannot create acceptance.
Schema-v1/global evidence and evidence without `robot_unit_id` or capability remain
readable audit data as `STALE_LEGACY_EVIDENCE`. The writable
`field_acceptance_status` Settings/default-config surface is removed; release context
starts the remaining backward/internal scalar as pending. No migration promotes old
evidence.

## Kinematics Verification Evidence

The V1/V2 tracked YAML remains `PROVISIONAL_DRY_RUN`. A local ignored overlay binds the
exact unit, Profile, Calibration, Device, Kinematics fingerprint/schema, checklist,
thresholds, operator, commit, and at least three predicted/measured TCP points with
server-owned state/session/sequence/time provenance and position/orientation residuals.
Defaults are 5 mm / 5 degrees; software rejects thresholds looser than 25 mm / 15
degrees. Unit/Profile/Calibration/Device/model/schema/checklist/commit drift makes the
record stale. Only a current record derives effective Real Kinematics; it never rewrites
the tracked model.

The measurement request accepts only a label and independently measured TCP. The backend
must capture a fresh server-owned joint state bound to the current unit, Device, and
Operator Session, then compute FK and residuals itself. The `0.1.0-rc1` release
composition intentionally supplies no physical snapshot provider and does not promote
persisted Kinematics JSON during bootstrap. Those files are audit history after restart;
a reviewed field adapter and fresh verification are required before Real Kinematics can
become effective.

## Global frontend capability state

Operator authority is set in an HttpOnly, SameSite=Strict `/api/v1` cookie, Secure when
served over HTTPS. React state, LocalStorage, SessionStorage, URLs, logs, and audit never
hold the raw token. `RealSessionContext` stores only the backend session summary, purpose,
expiry, capability details, and blocked reasons. Refresh restores the summary without
issuing authority; backend restart invalidates it.

Control Joint/Home/Cartesian, Library Goto/Play, Studio Goto/Preview/Play, and Vision
Follow consume the same backend-derived capability matrix. This creates the positive
software path without making unavailable physical evidence appear ready.

## API changes and audit

The narrow hardening surface is summarized in [`../api-audit.md`](../api-audit.md).
The post-wiring snapshot contains 106 HTTP operations over 92 versioned paths plus the
one read-only Robot WebSocket.
Commissioning status/session/arm/start/heartbeat/Stop and Kinematics status/draft/
measurement/commit are added. Staged Field Acceptance adds derived progress plus
pre-motion and Joint-evidence transitions. Commissioning and Kinematics mutations use
control authentication, while Commissioning Stop uses priority authentication and a
token-independent service Stop so an expired/lost operator cookie cannot block it. Final
React callers are present in the Commissioning and Kinematics Settings panels and send
credentials through the shared HttpOnly-cookie request path. Their final component/route
tests match the audited contracts. No endpoint was deleted merely because the React
product currently lacks a caller.

## Documentation

New normative/audit documents are ADR 0019, the Commissioning Motion Test contract, the
staged Field Acceptance model, the Kinematics field-verification procedure, the API
audit, and this report. README, Safety, Operator Guide, Real Hardware Acceptance,
Architecture, Domain Model, Release Checklist, Roadmap, and the Stage 8/autonomous
completion reports now distinguish the historical global-PASSED/two-purpose baseline
from the current three-purpose, exact-unit, capability-evidence model. ADR 0018 and the
first commissioning-fix report carry explicit partial-supersession notes; their old prose
is retained only as historical evidence.

## Verification results

| Gate | Final result |
|---|---|
| `make test` / backend pytest count | **PASS — backend 629 passed; one existing Starlette/httpx deprecation warning** |
| Frontend Vitest count/files | **PASS — 230 tests across 19 files** |
| Focused session/envelope/deadman/evidence/Bomb tests | **PASS — included in the final 140-test safe isolation selection** |
| Security + backup focused tests | **PASS — 34 passed; same deprecation warning** |
| Ruff / format / strict mypy | **PASS — Ruff, format check, and mypy clean across the 234-file scope** |
| ESLint / TypeScript / Vite | **PASS — 1,646 modules; existing >500 kB chunk-size warning only** |
| Schema determinism | **PASS — fresh temporary generation matches `docs/schemas`** |
| `uv lock --check` / `uv pip check` | **PASS** |
| `pip-audit` | **PASS — no known vulnerabilities; local non-PyPI package skipped** |
| `npm audit --audit-level=high` | **PASS — 0 vulnerabilities** |
| Hardware isolation | **PASS — final 13-file hardware/camera/commissioning/Kinematics selection, 140 passed** |
| Camera isolation | **PASS — included in the same final 140-test selection** |
| Secret scan / `git diff --check` | **PASS — local high-confidence scan and full diff check clean** |
| Browser Fake commissioning E2E / console | **PASS — all 12 V2 directions, Joint acceptance, persisted reload, console warning/error `[]`** |
| Pre-merge architecture audit P1/P2/P3 | **PASS — P1=0, P2=0, P3=1; 38 focused tests plus Ruff/mypy pass** |
| Push CI | **PENDING FOR FINAL HEAD** |
| Pull-request CI | **PENDING FOR FINAL HEAD** |

At the starting commit, PR #1 was open as Draft and the baseline CI was green. Those facts
do not establish the final-head result. The baseline
[push run](https://github.com/39394480ke-sys/MOMO-Studio/actions/runs/32756517593)
and [pull-request run](https://github.com/39394480ke-sys/MOMO-Studio/actions/runs/32756521770)
both passed at `eb90d516`; record final commit, checks, links, and PR head only after push
and both required workflow triggers finish.

The browser harness bound only to `127.0.0.1` and was stopped after the run. It exercised
genuine held `-`/`+` controls for `j10`–`j15`, derived Joint acceptance, reloaded persisted
Fake evidence, and still reported `KINEMATICS_VERIFICATION_PENDING`, physical Stop
`PENDING`, and production Joint/Cartesian/Playback/Vision blocked. Fake browser evidence
does not qualify a physical unit.

## Architecture audit checklist

Final review must record evidence for each item:

- Route → Driver and Vision → Driver imports;
- bypass around the reviewed safety gateway;
- read-only write path or Commissioning → production bypass;
- manual Field Acceptance or stale-evidence authorization;
- frontend-only permission assumption;
- raw Servo/register/path/Python/hidden override surface;
- module-global robot, `arm_a`, fleet behavior, or Stage 8 God Object;
- token logging or secret browser storage.

P1/P2 findings must be fixed before completion. Supported P3 findings remain documented.

The audit found and integration corrected persisted `JOINT_MOTION`, pre-motion, and
Kinematics evidence-chain bypasses. File-loaded Field bundles are non-authoritative until
startup semantically resolves the typed pre-motion snapshot or current all-joint/
both-direction UUIDs, embedded prepared commands, and exact current envelope into a
transient validated bundle. Kinematics measurement accepts no client joint state and
requires a fresh server-owned snapshot. Release bootstrap does not promote persisted
Kinematics evidence, so it requires fresh field verification after restart. Final
re-audit closes P1=0/P2=0 after 38 focused tests. There is no unsafe or module-global God
Object. One supported P3 service concentration remains: `DeviceDiagnosticsService` is a
974-line app-scoped, guard-locked coordinator spanning sessions/readiness,
connection/diagnostics, Calibration/Profile invalidation, Field/Kinematics publication,
Stop, and shutdown. It remains fail-closed behind typed ports with no bypass, but should
be decomposed after merge without changing this release's authorization semantics.

## Known limitations

- Feetech exact goal write, cancellation, readback timing, and Stop/Hold behavior are not
  physically verified.
- Physical Stop and physical E-stop behavior are pending.
- V1/V2 geometry, backlash, flex, rail alignment, TCP measurement, and Real Kinematics
  are pending.
- Camera latency and Real Vision Follow gains are pending.
- Cartesian, Playback, and Vision Follow acceptance-write workflows/typed resolvers are
  not implemented in `0.1.0-rc1`; their records remain audit-only.
- Fake capability evidence is software evidence only and cannot qualify a physical unit.
- Every Phase 0–10 field item remains unchecked.

Known user-acknowledged untracked files were left untouched.

## Safety statement

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

All commissioning-motion verification used Fake, Bomb, or isolated adapters.

COMMISSIONING_MOTION_TEST does not grant production REAL_MOTION authority.

Fake field-acceptance evidence does not constitute physical field acceptance.

Feetech goal-write behavior remains field-verification-gated unless independently proven otherwise.

Physical Stop behavior remains field-verification-gated unless independently proven otherwise.

Real Kinematics remain field-verification-gated.

Real-hardware field acceptance remains required.
```
