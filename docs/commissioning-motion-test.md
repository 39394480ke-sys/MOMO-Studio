# Commissioning Motion Test

Status: software workflow for `0.1.0-rc1`; physical execution and adapter behavior remain
field-verification gated.

This workflow exists only to collect the first bounded joint-direction/readback evidence.
It is not normal robot operation and is not a reduced version of production control.

## Entry gates

The backend requires all of the following before it may issue a
`COMMISSIONING_MOTION_TEST` session:

- `control_mode == REAL`;
- `hardware_access_policy == FULL`;
- explicit startup hardware opt-in and ignored local hardware config;
- `commissioning_motion_test_enabled == true`;
- non-empty local `robot_unit_id` matching Device and Calibration;
- non-template `VERIFIED_FOR_REAL` Profile matching the selected variant;
- complete non-template Calibration with matching unit, variant, Profile fingerprint,
  enabled-joint set, mapping, Home, mode, and raw bounds;
- explicit device/protocol and the exact ordered Profile Servo IDs;
- an available adapter whose identity has been reviewed;
- current pre-motion-check evidence;
- exact commissioning-motion confirmation, physical E-stop readiness, workspace-clear
  confirmation, and bounded operator identity.

It does not require final Field Acceptance, Joint/Cartesian/Playback/Vision acceptance,
`real_motion_enabled`, or Real Kinematics verification.

The tracked release does not satisfy these gates. The optional Feetech adapter remains
`PENDING_ADAPTER_VERIFICATION`, so the production factory must not create a write-capable
physical bus.

## Backend hard envelope

The immutable default hard caps are:

| Limit | Hard maximum |
|---|---:|
| Active joints | 1 |
| Command duration | 2.0 s |
| Session duration | 300.0 s |
| Revolute delta | 2.0 deg |
| Prismatic delta | 1.0 mm |
| Revolute speed | 2.0 deg/s |
| Prismatic speed | 1.0 mm/s |
| Revolute acceleration | 4.0 deg/s² |
| Prismatic acceleration | 2.0 mm/s² |
| Deadman lease | 400 ms |
| Commands per session | 24 |

Local configuration may only reduce these values. The frontend cannot supply or enlarge
the envelope. The backend snapshots it into session evidence; changing configuration
does not mutate an active session.

## State machine

```text
IDLE
  -> AUTHORIZED       separate session issued
  -> ARMED            selected joint explicitly armed
  -> MOVING           prepared write is active while the lease is live
  -> VERIFYING        final fresh readback and direction/divergence checks
  -> STOPPING         bounded Stop/Hold request when required
  -> COMPLETED        immutable evidence saved

Any state -> FAILED   validation, write, readback, direction, divergence, or Stop failure
Any live state -> EXPIRED  session or deadman expiry
```

`AUTHORIZED` never starts motion. Every attempt needs a new ARM action and a live lease.

## Permitted command

The only permitted intent is a relative test for exactly one Profile-enabled joint:

```text
joint_id
signed_delta        # deg or mm from the Profile joint type
requested_speed
requested_acceleration
command_duration
```

The API never accepts an absolute raw target, arbitrary Servo ID, register address,
multi-joint mapping, executable samples, adapter selection, or filesystem path.

## Test-move data flow

```text
operator holds direction control
  -> backend validates motion-test session, ARM, lease, command count, and envelope
  -> read selected joint through CommissioningMotionServoBus
  -> reject stale/non-finite/wrong-unit/wrong-identity readback
  -> target = latest logical readback + signed bounded delta
  -> enforce logical Profile limits and Calibration-derived raw limits
  -> map logical target through exact Profile + Calibration
  -> build immutable PreparedCommissioningTestCommand
  -> write the one explicitly authorized Servo goal
  -> read selected joint again
  -> verify raw/logical direction, delta, freshness, limits, and divergence
  -> request Stop/Hold when required
  -> atomically persist pass or failure evidence
```

Only the prepared command crosses the write boundary. Production Home, Cartesian,
Playback, Library, Studio, Vision, multi-joint, raw-register, scan, enumeration,
mode-write, and torque-write capabilities are absent from the commissioning bus type.

## Backend deadman

Pointer release is only one Stop source. The frontend begins heartbeats on
press-and-hold and requests Stop on pointer up, pointer cancel, window blur, hidden
visibility, route change, component unmount, or network failure. The backend independently
owns the deadline and stops/faults when heartbeats cease, the session expires, the
connection changes, shutdown begins, or current authorization/evidence no longer matches.

Network loss is therefore safe even if the browser cannot deliver its Stop request.
Heartbeats renew only the current attempt; a previous direction or lease cannot be reused.

## Evidence and audit

Every completed or failed attempt produces immutable local `CommissioningTestEvidence`
with schema/revision and UUID filename identity. It records:

- unit/variant and Profile, Calibration, and Device fingerprints;
- joint/unit, start/requested/target/final logical values, start/final raw values, and
  prepared raw target;
- requested speed, observed direction and result, divergence, and Stop behavior;
- request/session IDs, start/completion time, software commit, operator, result, and
  bounded failure reason.

A passed record must also embed its complete immutable prepared command and frozen
envelope; pre-preparation failures may have no prepared command. Joint acceptance accepts
only passing records whose embedded envelope exactly equals the current configured
envelope.

Audit events record the same bounded operational facts but never the session token.
Evidence paths are server-owned and ignored; a web client cannot name a destination.

## Stop truthfulness

Fake-adapter Stop success proves only `SOFTWARE_PATH_VERIFIED`. It cannot set
`physical_stop_verified`. Until measured on the exact Feetech hardware, the UI and
evidence must state `PHYSICAL_BEHAVIOR_PENDING` and remind the operator that the physical
E-stop is the independent safety control.

## API surface

The final API inventory is maintained in `api-audit.md`. The intended narrow endpoints
are one status/session entry, one per-joint ARM/start flow, one heartbeat, and one
idempotent Stop. Existing production motion endpoints reject a motion-test session by
scope, and the commissioning endpoints reject read-only and production sessions.

## Structured failure contract

Readiness uses stable blocker values such as `COMMISSIONING_MOTION_NOT_ENABLED`,
`COMMISSIONING_MOTION_SESSION_REQUIRED`, `ROBOT_UNIT_ID_REQUIRED`,
`ROBOT_UNIT_MISMATCH`, and `PHYSICAL_STOP_NOT_VERIFIED`. Service/API failures retain
typed codes including `COMMISSIONING_MOTION_SESSION_REQUIRED`,
`COMMISSIONING_ENVELOPE_EXCEEDED`, `MULTI_JOINT_TEST_FORBIDDEN`, `DEADMAN_EXPIRED`,
`COMMISSIONING_READBACK_INVALID`, and `COMMISSIONING_EVIDENCE_STORAGE_FAILED`.
Operator-session failures separately distinguish unauthorizable, unauthorized, invalid
confirmation, and insufficient scope. UI prose is not the error contract.

## Verification boundary

Automated tests use Fake buses, Write/Production/Envelope Bombs, fake clocks, temporary
repositories, and safe configuration. They may validate state transitions, bounds,
deadman expiry, evidence, and forbidden-call isolation. They do not validate Feetech
register behavior, physical Stop/E-stop response, timing, backlash, flex, geometry, or
motion of a physical robot.
