# ADR 0019: Staged field acceptance and restricted commissioning motion

Status: Accepted for `0.1.0-rc1` final pre-merge hardening.

## Context

ADR 0018 separated read-only commissioning from production motion. That removed the
first commissioning deadlock: an operator can identify a configured device and capture
the first Calibration without already having motion authority.

A second deadlock remained. Production motion required one global Field Acceptance
`PASSED` record, while that checklist itself required positive/negative joint motion,
readback, divergence, Stop, Cartesian, Playback, and Vision Follow tests. Requiring the
global pass before those tests made them impossible; allowing an operator to declare the
pass first made the evidence meaningless.

The earlier model also treated a serial path, protocol, and Servo-ID set as sufficient
physical identity. Two robots of the same variant can have identical Servo IDs, and a
serial path can change. Finally, the browser kept an operator token only in the Settings
panel, leaving Control, Library, Studio, and Vision without one backend-derived Real
capability context.

## Decision

MOMO Studio uses three immutable Operator Session purposes:

1. `COMMISSIONING_READ_ONLY` permits only explicit-device read-only diagnostics and
   Calibration capture.
2. `COMMISSIONING_MOTION_TEST` permits only a backend-prepared, bounded, relative,
   single-joint test under a renewable backend deadman lease.
3. `REAL_MOTION` permits only the production capabilities supported by current,
   capability-specific acceptance evidence.

No purpose can be upgraded. A different purpose always requires a new session ID, token,
expiry, evidence snapshot, and operator confirmation. Completing Calibration, a joint
test, an acceptance record, or Kinematics verification never adds scope to an existing
session.

The commissioning-motion switch is independent:

```text
commissioning_motion_test_enabled = false  # tracked/default
real_motion_enabled = false                # tracked/default
```

Enabling one never enables the other.

## Restricted commissioning motion

The only first-version commissioning write intent is
`RELATIVE_SINGLE_JOINT_TEST`. The application service reads the latest selected-joint
position, calculates and validates a bounded target, maps it through the exact Profile
and Calibration, and produces an immutable prepared command. The adapter receives no
arbitrary target, raw register, Servo-ID set, multi-joint plan, Home, Cartesian,
Playback, Library, Studio, or Vision command.

The backend snapshots a `CommissioningSafetyEnvelope` into the session. Compile-time
hard caps cannot be expanded by local configuration or a client. Every test is separately
armed and requires a renewable backend deadman lease. Expiry, disconnect, network loss,
session invalidation, shutdown, Stop, stale readback, direction mismatch, divergence, or
write/readback failure stops or faults the attempt.

The production Real executor is not handed to the commissioning service. A narrowed
`CommissioningMotionServoBus` exposes only selected-joint readback, one prepared goal
write, and the verified Stop/Hold request supported by the adapter contract.

## Physical unit identity

Every physical robot receives a stable `robot_unit_id` from ignored local configuration.
It is not derived from the serial path, hostname, protocol, or Servo IDs. It binds Device
identity/fingerprint, Real Calibration, commissioning sessions and test evidence, staged
Field Acceptance, Kinematics verification, production-session evidence, and audit data.

`robot_unit_id` is intentionally excluded from `RobotProfile.fingerprint`: a Profile
describes a hardware variant contract, while a unit ID identifies one physical specimen.
Tracked examples use an empty value and cannot authorize commissioning or Real motion.

## Staged Field Acceptance

One global writable `PASSED` record is removed as an authorization concept. A
`FieldAcceptanceBundle` contains independent evidence for:

- pre-motion checks;
- Joint Motion;
- Cartesian;
- Playback;
- Vision Follow.

Capability readiness is derived from current evidence and fingerprints. There is no
Accept All or Mark Robot Ready command. Full acceptance, when displayed, is a read-only
derived summary.

Persisted records are not authoritative merely because they deserialize. Pre-motion
embeds a typed read-only session/time and exact per-joint Servo diagnostic snapshot that
bootstrap semantically revalidates against current mapping, bounds, mode, torque-off
state, and identity. Joint test evidence embeds its prepared command and frozen envelope;
startup resolves every UUID, both directions, every enabled joint, and equality with the
current commissioning envelope before constructing a transient validated bundle.

Legacy schema-v1/global evidence remains readable for audit but is
`STALE_LEGACY_EVIDENCE`. Evidence without `robot_unit_id`, an explicit capability,
the required typed snapshot/supporting test evidence, `accepted_by`, or the current
binding cannot authorize motion.

## Kinematics verification overlay

Tracked V1/V2 Kinematics YAML remains `PROVISIONAL_DRY_RUN`. Field verification produces
ignored local `KinematicsVerificationEvidence` bound to the unit, Profile, Calibration,
Device, model fingerprint/schema, checklist version, multiple measured points,
server-owned joint-state capture provenance, thresholds, operator, and software commit.
The client supplies only a label and measured TCP. A current record applied by the live
workflow derives effective Real Kinematics readiness; it does not edit or promote the
tracked YAML. `0.1.0-rc1` treats persisted files as audit-only after restart, ships no
physical snapshot adapter, and therefore requires a reviewed adapter plus fresh
verification before Real Kinematics can become effective.

## Capability derivation

| Capability | Required current evidence |
|---|---|
| Restricted commissioning test | pre-motion checks, valid unit/Profile/Calibration/Device, separate motion-test session |
| Real Joint Motion | Joint Motion acceptance and a new `REAL_MOTION` session |
| Real Cartesian | Joint acceptance, valid Kinematics evidence, Cartesian acceptance |
| Joint-only Playback | Joint acceptance and Playback acceptance |
| Cartesian Playback | Joint acceptance, valid Kinematics evidence, Cartesian acceptance, Playback acceptance |
| Real Vision Follow | Joint acceptance, valid Kinematics evidence when the controller uses it, Vision Follow acceptance |

Every row remains subject to the independent startup, local-config, Profile,
Calibration, adapter, Stop, device, freshness, and operator gates.

## Browser session transport

Backend authorization remains the only source of truth. Operator authority is delivered
in a Secure-when-HTTPS, HttpOnly, SameSite=Strict, API-path cookie. Raw operator tokens
are not placed in React state, LocalStorage, SessionStorage, a URL, logs, or audit events.
The global `RealSessionContext` stores only the backend session summary, expiry,
capability details, and blocked reasons. Refresh re-reads that summary; it never creates
a session. Backend restart invalidates the in-memory grant.

## Compatibility and supersession

This ADR partially supersedes ADR 0018. ADR 0018 remains authoritative for the separation
of read-only commissioning from production motion and for non-upgradeable sessions. Its
two-purpose model and global Field Acceptance flow are replaced by this three-purpose,
capability-evidence decision.

Persisted-data changes require round-trip tests, compatibility analysis, deterministic
schema generation, and retained stale legacy records. No migration may silently upgrade
legacy evidence.

## Consequences

- The second acceptance deadlock is resolved without granting normal robot control.
- Backend limits, deadman, evidence, and capability derivation are testable with Fake and
  Bomb adapters without accessing hardware.
- More local evidence types and explicit operator steps are required.
- Feetech goal write, software/physical Stop behavior, physical E-stop behavior, Real
  Kinematics, and all physical field acceptance remain pending until measured on the
  exact unit. Fake success cannot satisfy those gates.
