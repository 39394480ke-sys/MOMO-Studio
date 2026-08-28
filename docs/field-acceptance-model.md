# Staged Field Acceptance model

Field Acceptance is a bundle of independent, immutable capability evidence. It is not a
single writable boolean and there is no endpoint or button that marks the robot ready.

## Progress model

The UI may present the following derived progression:

```text
NOT_STARTED
READ_ONLY_COMMISSIONING_COMPLETE
CALIBRATION_COMPLETE
PRE_MOTION_CHECKS_COMPLETE
JOINT_MOTION_TESTING
JOINT_MOTION_ACCEPTED
KINEMATICS_VERIFICATION_PENDING
CARTESIAN_ACCEPTED
PLAYBACK_ACCEPTED
VISION_FOLLOW_ACCEPTED
FULL_ACCEPTANCE_COMPLETE
```

These labels summarize records; they are not mutable authority. Independent capability
evidence remains the source from which readiness is derived.

## Evidence capabilities

`FieldAcceptanceBundle` contains `FieldAcceptanceEvidence` for:

- `PRE_MOTION_CHECKS`;
- `JOINT_MOTION`;
- `CARTESIAN`;
- `PLAYBACK`;
- `VISION_FOLLOW`.

Each schema-v2 record contains an evidence UUID, `robot_unit_id`, variant, Profile,
Calibration and Device fingerprints, optional Kinematics fingerprint, capability,
checklist version, supporting test-evidence UUIDs, acceptance time, required
`accepted_by`, optional reviewer, and software commit. It is immutable, saved atomically
under its UUID, and interpreted against the current context on every authorization.

Persisted records deserialize into a non-authoritative bundle whose
`valid_capabilities` is empty. The application must semantically resolve their embedded
or referenced evidence and construct a transient validated bundle before authorization.
For Joint Motion, the resolver requires current passing positive and negative tests for
every enabled joint, exact unit/Profile/Calibration/Device/software bindings, each
embedded prepared command, and the exact current `CommissioningSafetyEnvelope`. A
hand-authored capability JSON, arbitrary test UUID, or evidence from a different
envelope therefore cannot grant authority.

`PRE_MOTION_CHECKS` embeds a typed read-only diagnostic snapshot: Operator Session ID,
capture time, and one exact joint/Servo record for every enabled joint containing ping,
mode, present raw/logical value, raw bounds, and torque confirmed off. At startup the
resolver checks capture-to-acceptance timing, exact joint/Servo coverage, current
Calibration mode/bounds/mapping, mapped logical value, and current context fingerprints.
This permits the required READ_ONLY → FULL restart without trusting fingerprints alone.

## Joint Motion acceptance

Every joint in the active Profile's explicit `enabled_joints` must have current evidence
for positive direction, negative direction, limit-safe motion, and fresh logical/raw
readback. A checklist may additionally require a Stop attempt. One joint is never
sufficient.

- V1 requires exactly `j11` through `j15`.
- V2 requires exactly `j10` through `j15`; `j10` is prismatic in millimetres.

The acceptance service selects evidence by the Profile contract. It does not infer six
joints or special-case the name `j10`. Failed direction, divergence, stale readback,
wrong unit, wrong unit identity, or missing direction evidence blocks acceptance.

Physical Stop remains separately pending even when every software-path joint test passes.

## Capability matrix

| Product capability | Required acceptance/evidence |
|---|---|
| Real Joint Motion | current Joint Motion acceptance |
| Real Cartesian | Joint Motion + valid Kinematics verification + Cartesian acceptance |
| Joint-only Playback | Joint Motion + Playback acceptance |
| Cartesian Playback | Joint Motion + valid Kinematics verification + Cartesian + Playback acceptance |
| Real Vision Follow | Joint Motion + Vision Follow acceptance, plus valid Kinematics evidence when used by the controller |

Every capability also requires its own current backend authorization scope and the
independent Profile, Calibration, Device, adapter, startup, Stop, and operator gates.
Passing one row never unlocks another.

For `0.1.0-rc1`, “valid Kinematics” means evidence applied during the current process by
the reviewed field workflow using a fresh server-owned joint-state snapshot. Release
bootstrap does not promote persisted Kinematics JSON, and the production composition has
no physical snapshot provider, so geometry-dependent capabilities remain fail-closed
until a reviewed adapter is wired and verification is repeated after restart.

This hardening exposes evidence-derived transitions only for PRE_MOTION and JOINT.
CARTESIAN, PLAYBACK, and VISION_FOLLOW have no acceptance-write endpoint or typed field-
test resolver in `0.1.0-rc1`; any such persisted records remain audit-only. Their rows
define the future gate and do not claim those physical workflows are implemented or
accepted.

## No manual global pass

The historical `FieldAcceptanceService.accept()` behavior—confirmation text directly
creating global `PASSED` evidence—has no authorization role in this model. Compatibility
responses may expose a derived full-completion summary, but it is read-only and cannot
override missing capability evidence.

There is no `Accept All`, `Mark Robot Ready`, or product-wide `PASSED` request. An
acceptance command may only commit a named capability after the backend validates the
supporting server-generated evidence and checklist.

## Legacy evidence

Schema-v1/global records remain readable for audit and are not deleted. They lack at
least an explicit capability and `robot_unit_id`, so they are classified
`STALE_LEGACY_EVIDENCE` and never enter `valid_capabilities`.

The writable `field_acceptance_status` Settings/default-config surface has been removed.
Release context initializes the remaining backward/internal scalar as `PENDING`; it is
not user input and cannot create, upgrade, or substitute for evidence. No migration
silently promotes a legacy record.

## Staleness

A capability record is stale when any required binding changes, including:

- `robot_unit_id` or variant;
- Profile, Calibration, Device, or applicable Kinematics fingerprint;
- expected enabled-joint set;
- evidence/checklist schema or checklist version;
- software commit;
- commissioning safety envelope for Joint test evidence;
- referenced test evidence or its current validity.

Stale records are retained for audit, reported with structured stale fields, and grant no
authority. New acceptance requires new evidence; an active session is invalidated rather
than upgraded.

## Storage and backup boundary

Field evidence is operational local data, ignored by Git and saved by server-owned
repositories. The web API accepts identifiers and measurements, not file paths. Backup
policy must preserve the distinction between portable user Library data and
unit-specific safety evidence; importing evidence for another unit cannot authorize the
current unit.

PRE_MOTION and JOINT publication is one linearized command under the Device Diagnostics
guard. The service reauthorizes the same token/session/operator against the current
context, durably saves the already-resolved record, invalidates the session/closes its
bus, and publishes the live validated bundle before releasing the guard. If concurrent
revoke wins first, no passed record is saved or published. If acceptance wins first, its
legitimate durable/live commit completes and revoke runs afterward. A new purpose-
specific session is always required for the next phase.

Structured transition failures distinguish `FIELD_ACCEPTANCE_NOT_AUTHORIZABLE`,
`FIELD_ACCEPTANCE_MANUAL_PASS_FORBIDDEN`, `FIELD_ACCEPTANCE_INCOMPLETE`,
`JOINT_TEST_EVIDENCE_INCOMPLETE`, and `FIELD_ACCEPTANCE_STORAGE_FAILED`. Readiness uses
separate missing/stale capability blockers, including
`FIELD_ACCEPTANCE_EVIDENCE_STALE`; a generic disabled label is not authoritative.

## Full completion

`FULL_ACCEPTANCE_COMPLETE` may be shown only as a derived summary when every required
capability record is current. It is not itself a persisted pass, session scope, or API
write target. Physical field acceptance remains pending until qualified personnel have
completed and reviewed the Phase 0–10 procedure for the exact robot.
