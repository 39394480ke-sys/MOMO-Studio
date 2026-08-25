# Kinematics field verification

The committed V1 and V2 Kinematics models remain `PROVISIONAL_DRY_RUN`. Their
fingerprints identify exact software geometry; they do not prove physical correctness.
Real verification is represented by a separate ignored local evidence overlay.

## Preconditions

Kinematics measurement begins only after the exact robot unit has current Joint Motion
acceptance. The operator uses a tested physical E-stop, guarded clear workspace, approved
low speed, exact Profile/Calibration/Device identity, and a newly authorized production
or specifically reviewed field-measurement flow.

The Kinematics-verification API records calculations and measurements. It does not accept
arbitrary motion samples or bypass the normal motion gateway. Moving to a test pose uses
the already-authorized bounded motion path.

## Workflow

```text
Joint Motion accepted
  -> create a verification draft bound to current fingerprints
  -> select a reviewed known joint test pose
  -> move at the approved low speed through normal authorization
  -> backend captures a fresh server-owned joint state
  -> compute FK with the exact provisional model
  -> operator enters independently measured TCP position/orientation
  -> calculate position and orientation residuals
  -> repeat across multiple distinct workspace points
  -> require every point within the frozen thresholds
  -> commit immutable KinematicsVerificationEvidence
```

At least three distinct test points are required. One point cannot pass the workflow.
The checklist should cover materially different joint configurations and the applicable
workspace, frames, rail travel, and TCP transform rather than repeating one pose.

## Evidence contract

`KinematicsVerificationEvidence` contains:

- schema/revision and UUID;
- `robot_unit_id` and variant;
- Profile, Calibration, Device, and Kinematics fingerprints;
- Kinematics model schema and verification checklist versions;
- at least three test points, each with joint state, capture sequence/time and session,
  predicted TCP, measured TCP, position/orientation residuals, label, and measurement
  time;
- frozen position/orientation thresholds;
- acceptance time, required operator identity, and software commit.

The current software hard bounds permit configured acceptance thresholds no looser than
25 mm position and 15 degrees orientation; the default evidence thresholds are 5 mm and
5 degrees. Field procedures may require smaller values. Every point must pass both frozen
thresholds before evidence can be committed.

The request contains only the operator's label and measured TCP; extra fields, including
a client-selected joint state, are rejected. Measured TCP values are operator
measurements, not browser claims of model correctness. The backend captures a fresh
server-owned state bound to the current unit, Profile, Calibration, Device, and Operator
Session, reauthorizes after capture, computes FK, and validates the residuals.

## Effective verification

A valid evidence record applied by the live reviewed workflow derives:

```text
effective_kinematics_verification = VERIFIED_FOR_REAL
```

for that exact context only. The tracked YAML remains unchanged and continues to say
`PROVISIONAL_DRY_RUN`. The overlay can unlock only the capabilities whose independent
acceptance records are also current.

`0.1.0-rc1` deliberately does not restore persisted Kinematics evidence into the
authorization context at bootstrap. A local JSON file remains audit history after a
restart and cannot regain authority by matching fingerprints. The release composition
also provides no physical joint-state snapshot adapter, so the field measurement step
fails closed until that adapter is reviewed and wired. After either process restart or
adapter installation, perform a fresh field verification before relying on effective
Real Kinematics.

## Automatic staleness

Evidence becomes stale when any of these changes:

- `robot_unit_id` or variant;
- Profile fingerprint;
- Calibration fingerprint;
- Device fingerprint;
- Kinematics fingerprint or model schema version;
- verification checklist version;
- software commit;
- required measurement/threshold contract.

Stale evidence remains local audit history but cannot authorize Cartesian, Cartesian
Playback, or Kinematics-dependent Vision Follow. A session bound to the earlier evidence
is invalidated.

## API and storage

The intended narrow sequence is draft, measurement, and commit. Draft IDs and evidence
IDs are server-issued. The API accepts structured TCP measurements and labels, never a
joint state, server path, arbitrary Python, model replacement, or a client assertion that
thresholds passed. Evidence is atomically saved under a UUID in ignored local storage;
that persistence is audit retention, not restart authority in this release candidate.

Kinematics deliberately differs from Field Acceptance publication. Commit saves the
immutable record as audit evidence, then reauthorizes the same Real Motion session and
checks the current context under the Device guard before live publication. If revoke or
context drift wins during persistence, the saved record remains audit-only and is not
published; success invalidates the old session and closes its owned connection. Because
bootstrap never promotes these files, an orphaned or tampered record cannot regain
authority after restart.

Structured workflow failures distinguish `KINEMATICS_VERIFICATION_PENDING`,
`KINEMATICS_VERIFICATION_DRAFT_INVALID`, and
`KINEMATICS_VERIFICATION_THRESHOLD_FAILED`. Readiness separately reports
`KINEMATICS_VERIFICATION_PENDING` or `KINEMATICS_EVIDENCE_STALE`.

## Fake verification boundary

Automated tests may use calculated Fake measured TCP values to prove pass/fail thresholds,
multi-point enforcement, fingerprint binding, persistence, and staleness. Such evidence
does not validate V1/V2 geometry, backlash, flex, TCP measurement, rail alignment, or any
physical robot. Default runtime has no real evidence, so Real geometry-dependent
capabilities remain blocked.
