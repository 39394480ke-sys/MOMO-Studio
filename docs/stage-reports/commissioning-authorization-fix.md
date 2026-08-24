# Commissioning authorization deadlock fix

- Date: 2026-08-25
- Release: `0.1.0-rc1`
- Branch: `codex/v1-autonomous-completion`
- Start commit: `4f2ea9ea90a4fca302fdc68ca047da6cbfa1265a`
- Draft PR: [#1](https://github.com/39394480ke-sys/MOMO-Studio/pull/1)
- Delivery commits: listed in the Git history and final handoff; a commit cannot embed
  its own final object ID.

## Problem and root cause

### Why the deadlock existed

The original Stage 8 `DIAGNOSTICS` purpose reused the Real Joint Motion readiness gate.
That gate required `FULL` policy, `real_motion_enabled`, a complete Calibration, field
acceptance, and a motion-capable Operator Session. The Calibration workflow simultaneously
required a current Calibration revision before it could start. A fresh robot therefore
could not obtain the read-only present-position data needed to create its first
Calibration. Hardware read access and hardware motion authority were incorrectly modeled
as one capability.

## Old authorization flow

```text
No Calibration / Field Acceptance PENDING
  -> real_joint_motion_ready = false
  -> no Operator Session / DIAGNOSTICS grant
  -> no explicit read-only connection or present-position capture
  -> no Calibration Revision 1
  -> field acceptance can never complete
```

## New authorization flow and state machine

```text
DRY RUN
    |
    `-- normal software operation

REAL / Hardware Disabled
    |
    `-- no hardware access

REAL / READ_ONLY
    |
    |-- COMMISSIONING_READ_ONLY session
    |-- explicit device connect
    |-- exact-ID read diagnostics
    |-- Calibration Revision 1 or N+1
    `-- Field Acceptance evidence collection
        `-- NO MOTION

REAL / FULL
    |
    |-- verified Profile
    |-- complete matching Calibration
    |-- current Field Acceptance Evidence
    |-- exact verified device
    |-- new REAL_MOTION session
    `-- Joint Motion

Cartesian / Cartesian Playback / Follow
    `-- additional VERIFIED_FOR_REAL Kinematics required
```

The model has no `READ_ONLY -> write`, `commissioning token -> motion`, `Calibration
complete -> automatic motion`, or `stale acceptance -> motion` transition.

## Commissioning readiness

`commissioning_diagnostics_ready` and `calibration_capture_ready` are independent of
motion readiness. They require Real control mode, `READ_ONLY` hardware policy, startup
and ignored-local hardware opt-ins, a verified non-template Profile, a valid Profile
fingerprint, exact serial/protocol/Servo-ID device configuration, and an available
verified adapter. They do not require `real_motion_enabled`, Calibration, field
acceptance, or verified Kinematics.

## Motion readiness

Real Joint Motion retains `FULL` policy, `real_motion_enabled`, both hardware opt-ins,
verified Profile, complete matching non-template Calibration, current matching Field
Acceptance Evidence, exact device identity, available adapter, and an active
motion-purpose Operator Session. Cartesian, Cartesian-containing Playback, and Vision
Follow additionally require matching `VERIFIED_FOR_REAL` Kinematics. Completing
Calibration while acceptance is pending leaves every motion capability false.

## Operator Session purposes and evidence

`OperatorSessionPurpose` is immutable:

- `COMMISSIONING_READ_ONLY` has exactly `DIAGNOSTICS_READ` and
  `CALIBRATION_CAPTURE` scopes. Evidence binds new session/token identity, issue/expiry,
  robot/variant, Profile fingerprint, device fingerprint, exact Servo IDs, and operator
  confirmation. Calibration and Kinematics fingerprints are absent.
- `REAL_MOTION` has only explicitly available motion scopes and binds Profile,
  Calibration, device, acceptance context, and, for geometry scopes, Kinematics evidence.

Session purpose is never mutated. After Calibration/acceptance, the operator must perform
a new confirmation and receive a new motion session ID, token, expiry, and fingerprints.
Expiry uses an injected/testable clock and fails closed for diagnostics, capture, and
motion.

## ReadOnly ServoBus boundary

Commissioning services depend on `ReadOnlyServoBus` through a narrowing facade. Its
public capability is limited to explicit open/close, exact-ID ping, operating-mode read,
torque-state read, and present-position read. It exposes no goal-position write,
Stop/Hold write, torque command, raw-register read/write, scan, enumeration, Home, Jog,
Playback, Cartesian, or Follow method. Fake and Write-Bomb tests are the only adapters
used for this fix.

## Initial Calibration Revision 1

When the repository is empty, the workflow creates a `CalibrationDraft` from the active
Profile. It binds variant, Profile fingerprint, ordered enabled joints, creation time,
and absent base revision. Joint present raw, logical value, direction, phase, bounds,
and operating mode remain absent until captured or explicitly entered; zero is never an
incomplete sentinel. Every enabled joint must be read, previewed, validated, and
explicitly confirmed. The normal complete Calibration validator and atomic repository
path then save Revision 1.

Existing Revision N recalibration remains compatible and saves Revision N+1 with the
same conflict, backup, fingerprint, atomic-write, and rollback guarantees.

### Recalibration behavior

A successful initial save, recalibration, or rollback first persists through the
repository and then refreshes the live authorization context from the exact
`CalibrationDocument` returned by that persistence operation. The commissioning session
is revoked and its owned read-only connection is closed, so the operator must explicitly
authorize and connect again. The refreshed readiness state can therefore report the
persisted Calibration as configured while Field Acceptance remains pending; it does not
grant motion. If persistence fails, the live Calibration context is cleared and readiness
fails closed instead of retaining an uncommitted draft or an assumed revision.

## Field Acceptance Evidence and invalidation

`FieldAcceptanceEvidence` stores schema version, Passed status, robot variant, Profile
fingerprint, Calibration fingerprint, optional Kinematics fingerprint, device
fingerprint, checklist version, acceptance time, and optional operator identity in a
local ignored repository. A settings `PASSED` string alone grants no authority. Variant,
Profile, Calibration, device, Kinematics, or checklist mismatch reports the evidence as
stale and returns motion readiness to fail-closed pending/blocked state.

Evidence creation requires a current commissioning session, the exact current evidence,
checklist version, explicit confirmation, and current device identity. It is not an
unguarded one-click pass endpoint.

### Evidence invalidation

A variant or Profile switch revokes every active Operator Session, closes any owned bus,
and clears the Profile-derived Calibration, Kinematics, expected-device, and authorization
context before the robot Profile is changed. Previously stored Field Acceptance Evidence
is retained as an auditable local record, but the new context evaluates it as stale; no
commissioning or motion grant carries across the switch. Calibration, device,
Kinematics, or checklist fingerprint changes likewise make existing evidence stale and
return motion readiness to a fail-closed pending/blocked state.

## Capability matrix

| Capability | `DISABLED` | `READ_ONLY` commissioning session | `FULL` motion session |
|---|---:|---:|---:|
| Explicit exact-ID diagnostics | No | Yes | No |
| Calibration capture | No | Yes | No |
| Hardware writes | No | No | Only reviewed motion path |
| Joint Motion | No | No | Complete motion evidence required |
| Cartesian / Cartesian Playback / Follow | No | No | Plus verified Kinematics |

## API changes

- `POST /api/v1/device/operator-session` now requires an explicit immutable `purpose`
  and returns that purpose plus exact scopes.
- `GET /api/v1/device/readiness` returns commissioning and motion authorizability and
  six independent capability flags. Its authoritative `calibration_configured` boolean
  lets the UI distinguish an existing persisted Calibration from a fresh robot without
  disclosing a Calibration fingerprint in commissioning-session evidence.
- device connect, diagnostics, and Calibration routes require a commissioning-purpose
  token; Calibration uses the dedicated capture scope.
- `GET /api/v1/device/field-acceptance` reports missing/valid/stale evidence, and the
  guarded `POST` requires an active connected commissioning session, current artifacts,
  checklist version, and exact confirmation before atomic local persistence.
- Real-mode Joint/Jog/Home/Goto, Cartesian, Playback, Studio Goto, and Vision Follow
  routes require their matching motion scope. A valid commissioning token fails with
  `403 OPERATOR_SESSION_SCOPE_INSUFFICIENT`. Priority Stop routes remain available for
  safety but cannot issue a write through a commissioning connection.

## Frontend changes

Settings distinguishes Hardware Disabled, Commissioning/Read-only, and Real Motion.
Commissioning displays a prominent `READ ONLY / No motion commands are permitted`
banner and only exposes read-only connect, diagnostics, and Calibration controls while
showing Calibration Not configured, Draft, configured/field-pending, and acceptance
evidence status. Control, Library Goto/Playback, Studio Goto/Playback, and Vision Follow
remain disabled in commissioning and never reuse Dry Run APIs for Real operation. The
default Hardware Disabled and normal Dry Run workspaces retain their existing behavior.
The Settings panel reconciles its page-local token with the authoritative active session
reported by readiness and clears local controls after server-side revocation or context
invalidation.

## Tests added

The repository now collects 42 more automated tests than the pre-fix release head:
28 backend tests and 14 frontend tests. The dedicated six-file commissioning selection
contains 88 tests. It includes fresh/recalibration behavior, Field Acceptance negative
authorization cases, no-op/rejected/successful variant switches, server-side session
invalidation reconciliation, and existing-Calibration display without putting its
fingerprint into commissioning evidence.

The focused matrix covers fresh-robot readiness, commissioning issuance without
Calibration, read-only diagnostics, type/capability write exclusion, API scope rejection,
Revision 1 creation, Revision 2 compatibility, post-Calibration motion block, token
non-upgrade, full motion evidence, all fingerprint invalidations, session expiry, no
scan/enumeration, and the complete Write-Bomb commissioning flow.

## Regression results

| Gate | Result |
|---|---|
| Focused commissioning tests | PASS — 88 |
| Full backend pytest | PASS — 591; one existing Starlette/httpx deprecation warning |
| Full frontend Vitest | PASS — 215 tests across 18 files |
| Ruff / format / mypy | PASS — 214 files |
| ESLint / TypeScript / Vite build | PASS — 1,642 modules; JS 480.15/135.88 gzip kB |
| Schema determinism | PASS — two fresh generations match each other and the tracked tree |
| `uv lock --check` / `uv pip check` | PASS — 68 packages resolved; 66 installed packages compatible |
| `pip-audit` | PASS — no known vulnerabilities; local non-PyPI project skipped |
| `npm audit` | PASS — 0 vulnerabilities at `high` threshold |
| Hardware isolation | PASS — combined safe-gate isolation selection: 102 |
| Camera isolation | PASS — same 102-test selection, Synthetic-only camera policy |
| Browser safe-fixture acceptance | PASS — READ ONLY diagnostics, Revision 1, post-save motion block; warning/error `[]` |
| Final GitHub CI | External final-head gate; exact run and result are recorded in the final handoff |

## CI release hardening

The workflow upgrades every JavaScript action to an official Node 24 runtime release.
`pip-audit` is a locked dev dependency and a fail-closed backend CI gate. Its first scan
identified direct dependency `pytest 8.4.2` as vulnerable (`PYSEC-2026-1845`); the direct
constraint and lock were upgraded to a fixed pytest 9.x release before regression.

## Hardware isolation evidence

No physical adapter is instantiated by the default composition. All commissioning tests
use Fake or Write-Bomb buses, fake devices, fake clocks, and temporary repositories.
The final 102-test isolation selection ran with Dry Run, hardware Disabled, startup and
local hardware opt-ins false, an empty serial/Servo configuration, Synthetic-only camera
policy, empty camera ID, loopback serving, offline model flags, and blocked outbound
proxies. It passed without instantiating a physical adapter or camera source.

## Known limitations

- Feetech adapter package/API/license/physical Stop behavior remains Pending Adapter
  Verification and its goal writes remain disabled.
- V1/V2 physical geometry, limits, Calibration, Kinematics, and motion behavior remain
  unverified until the field checklist is performed on each exact unit.
- Both committed Kinematics models remain `PROVISIONAL_DRY_RUN`; Real Cartesian,
  Cartesian Playback, and Follow remain blocked.
- Live camera behavior is outside this commissioning fix and remains physically
  unverified.
- In this release, the `REAL_MOTION` token remains local to `RealHardwarePanel`; Control,
  Library, Studio, and Vision do not yet receive or send it. Their positive Real-motion UI
  path is therefore not usable yet, and those surfaces remain safely blocked even after a
  `FULL` motion session is issued in Settings.
- The built-in LAN server remains HTTP-only for a trusted private network.
- The three externally created iCloud duplicate files observed during this task were
  excluded and left untouched.

## Real hardware acceptance still required

This fix proves the authorization separation and first-Calibration workflow only with
Fake, Write-Bomb, and isolated adapters. It does not establish physical behavior for a
V1 or V2 unit. Before any Real motion is authorized, an operator must complete the
documented field checklist against the exact robot variant, Profile, persisted
Calibration, device identity, and applicable Kinematics evidence. Until that matching
local evidence is current, all Real motion readiness remains blocked.

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
All commissioning verification used Fake or isolated adapters.
Commissioning read-only access does not grant motion authority.
Real-hardware field acceptance remains required.
```
