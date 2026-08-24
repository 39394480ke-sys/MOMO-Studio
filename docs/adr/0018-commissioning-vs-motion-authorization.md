# ADR 0018: Separate commissioning from motion authorization

Status: Accepted for `0.1.0-rc1`

## Context

First commissioning must read the present positions of explicitly configured servos in
order to create the first device-local Calibration. The original Stage 8 authorization
treated diagnostics as a Real Joint Motion capability. It therefore required a complete
Calibration, passed field acceptance, `real_motion_enabled`, and the other motion gates
before a read-only connection or Operator Session could exist. The Calibration workflow
also required an existing Calibration revision. Together those rules formed a cycle:

```text
no Calibration / acceptance pending
  -> no Real Joint Motion readiness
  -> no Operator Session or diagnostics
  -> no present-position capture
  -> no first Calibration
  -> acceptance cannot be completed
```

Reading identified hardware is not equivalent to granting authority to move it. The
boundary must express that distinction in the domain, session evidence, application
authorization, and ServoBus capability rather than relying on disabled UI controls.

## Decision

MOMO Studio has two immutable Operator Session purposes:

- `COMMISSIONING_READ_ONLY` is available only in `REAL` control mode with
  `READ_ONLY` hardware policy, both explicit hardware opt-ins, a verified non-template
  Profile, an explicit device/protocol/exact Servo ID allowlist, an available verified
  adapter, and an explicit operator confirmation. It does not require a Calibration,
  field-acceptance pass, verified Real kinematics, or `real_motion_enabled`.
- `REAL_MOTION` is available only with `FULL` hardware policy and retains every existing
  motion gate: `real_motion_enabled`, both hardware opt-ins, verified Profile, complete
  matching non-template Calibration, current matching Field Acceptance Evidence,
  explicit verified device, available adapter, and a new explicit operator confirmation.
  Cartesian, Cartesian-containing Playback, and Vision Follow additionally require
  matching `VERIFIED_FOR_REAL` Kinematics evidence.

Session purpose never changes. A commissioning session has a new token, ID, expiry,
Profile fingerprint, and device fingerprint. Its Calibration and Kinematics fingerprints
may be absent, and its scopes are restricted to `DIAGNOSTICS_READ` and
`CALIBRATION_CAPTURE`. A motion session binds the current Profile, Calibration, device,
acceptance, and, when needed, Kinematics evidence and has only the motion scopes supported
by that evidence. Completing Calibration or field acceptance cannot upgrade an existing
commissioning token; the operator must request and confirm a new `REAL_MOTION` session.

Commissioning application services receive a `ReadOnlyServoBus` capability. It exposes
only explicit open/close, exact-ID ping, operating-mode reads, torque-state reads, and
present-position reads. It has no goal-position, torque command, raw-register, scan, or
enumeration method. The narrowing is enforced by the port/facade type as well as runtime
session authorization.

The Calibration workflow can now create an incomplete `CalibrationDraft` from the active
Profile when no stored Calibration exists. Missing samples remain `None`; they are never
represented by invented zeroes. All enabled joints must be explicitly captured,
completed, previewed, validated, and confirmed before the normal atomic repository path
saves Revision 1. Recalibration still starts from Revision N and atomically saves Revision
N+1 through the same validation path.

A local, ignored `FieldAcceptanceEvidence` document binds a pass to robot variant,
Profile fingerprint, Calibration fingerprint, optional Kinematics fingerprint, device
fingerprint, checklist version, acceptance time, and optional operator identity. A
configured `PASSED` string alone grants nothing. Any binding or checklist change makes
the evidence stale and motion readiness fails closed until acceptance is repeated.

## Data and compatibility

`CalibrationDraft` and Operator Session evidence are runtime/API contracts and do not
rewrite existing Calibration documents or revision records. Revision N repositories keep
their forward-save and backup behavior; an empty repository is the new, explicit base
case for Revision 1.

`FieldAcceptanceEvidence` is a new persisted local contract with a generated JSON Schema
and round-trip repository tests. There is no legacy evidence file to migrate. Existing
`field_acceptance_status: PASSED` configuration is retained only as a compatibility/
display hint and intentionally becomes fail-closed `PENDING` until a matching evidence
document is created. Missing, unknown-version, corrupt, or mismatched evidence is never
upgraded or guessed.

## Authorization state machine

```text
DRY RUN
  -> normal software-only operation

REAL / DISABLED
  -> no hardware adapter instantiation or access

REAL / READ_ONLY
  -> new COMMISSIONING_READ_ONLY session
  -> explicit device connection
  -> exact-ID read-only diagnostics and Calibration capture
  -> Calibration Revision 1 or later recalibration
  -> field-acceptance evidence collection
  -> NO MOTION

REAL / FULL
  -> verified Profile + Calibration + current acceptance + exact device
  -> new REAL_MOTION session
  -> Joint Motion
  -> Cartesian / Cartesian Playback / Follow only with verified matching Kinematics
```

There is no `READ_ONLY -> write`, `commissioning token -> motion`, `Calibration complete
-> automatic motion`, or `stale acceptance -> motion` transition.

## Consequences

- A new physical robot has a reachable, read-only path to Calibration Revision 1.
- Diagnostics and Calibration capture no longer inherit motion prerequisites.
- The hardware capability boundary is narrower and safer for future maintenance.
- Two Operator Session purposes, separate readiness capabilities, and purpose-aware API
  errors must be maintained and tested.
- Initial Calibration and recalibration share the same domain validation and atomic
  persistence guarantees.
- Motion authorization is not weakened; completing Calibration only permits the operator
  to continue field acceptance.
- Real-hardware adapter verification and physical field acceptance remain external,
  mandatory release gates.
