# ADR 0010: Unified motion safety gateway

- Status: Accepted
- Date: 2026-08-24

## Context

Joint moves, jog, Home, Cartesian moves, Library playback, Studio preview, and Vision
follow share safety requirements. Letting each route or feature dispatch directly would
duplicate checks, make Stop unreliable, and create future hardware bypasses.

## Decision

Every motion source submits an immutable `MotionCommand` through one application
`MotionSafetyGateway`. The gateway validates active identity, connection and freshness,
Dry Run policy, expected state sequence, Profile and Kinematics fingerprints, exact
joint/unit sets, finite values, logical/provisional dynamic/workspace limits, FK/IK
evidence, idempotency, conflicts, and cancellation before producing prepared work for
an injected executor.

Raw-derived validation is conditional. A configured Calibration must match the active
variant, Profile fingerprint, joint set, and mapping or admission is rejected. When no
Calibration is configured, preflight records a Dry Run-only logical-limit fallback;
that fallback cannot become Real authority.

Only one active motion is permitted. Stop bypasses ordinary command admission, sets the
active cancellation signal first, and then asks the robot motion port to stop. Continuous
jog uses a short renewable backend lease; expiry stops motion even if the browser cannot
send pointer release. Executors use injected monotonic time and absolute deadlines.

HTTP and read-only WebSocket routes depend on application services and never import a
driver. Long-running requests return a command ID. The current WebSocket source is
capped at 10 Hz, has no application queue, and bounds each send to one second; it does
not accept motion commands. Later Library, Studio, Playback, Vision, and Real paths must
reuse this gateway rather than add parallel dispatch surfaces.

## Consequences

Command ownership, conflicts, status, cancellation and Stop semantics are observable
and testable. Stage 3 execution changes only in-memory Dry Run state. This gateway is a
necessary boundary for later Real work but does not itself authorize hardware access.
