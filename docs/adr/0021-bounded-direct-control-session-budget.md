# ADR 0021: Bounded direct-control session command budget

- Status: Accepted
- Date: 2026-08-27

## Context

The first V2 field-control session limited the commissioning envelope to 24
single-joint commands. Repeated operator checks near a logical limit consumed
the budget before J13 positive, J14, or J15 could be exercised. The session was
still bounded to five minutes, one active joint, fixed low-speed steps, explicit
logical and Raw limits, deadman heartbeats, and Stop/Hold.

Field evidence also showed normal loaded settling 13–28 Raw counts short of the
prepared target. The previous 16-count verification threshold reported these
same-direction movements as failed even though the requested physical movement
occurred.

## Decision

Increase `CommissioningSafetyEnvelope.max_commands_per_session` from 24 to 120.
This is a validation relaxation only: the field remains an integer with the same
name and meaning, and all previously persisted values remain valid. No schema
version bump or migration is required.

Use a 32-count divergence tolerance when composing the physical V2
commissioning adapter. Direction verification remains mandatory, so the wider
endpoint tolerance cannot turn a stationary or opposite-direction readback into
a pass. The five-minute session deadline, one-joint invariant, fixed delta and
speed caps, profile and Raw limits, deadman lease, explicit operator session,
and priority Stop remain unchanged.

Regenerate the committed JSON Schema and retain round-trip coverage for both the
legacy value 24 and the new maximum 120.

## Compatibility analysis

- Existing commissioning evidence containing 24 remains valid and round-trips.
- New evidence may contain values through 120 and is rejected by older binaries;
  operators must not downgrade a live field-control workspace while retaining a
  new active session.
- Calibration, Profile, motion, pose, runtime, and field-acceptance schemas are
  unchanged.
- The change grants no production-motion authority and does not alter the
  `real_motion_enabled` gate.

## Consequences

An operator can complete a six-axis direction comparison without restarting the
session after incidental retries. The maximum remains finite and time-bounded.
Loaded small steps are reported according to observed direction and a realistic
endpoint band instead of an overly tight bench threshold.
