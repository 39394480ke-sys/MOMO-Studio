# ADR 0008: Dry Run runtime state

- Status: Accepted
- Date: 2026-08-24

## Context

Dry Run should preserve the last validated logical state across backend restarts without confusing stale data for a physical connection. The state is operational and replaceable, not a user-authored Pose, Motion, Calibration, or source artifact. A partial write, incompatible Profile, corrupt JSON, or path supplied by a client must not crash startup or fabricate joint values.

## Decision

Persist one schema-versioned JSON document per safe `RobotId` under a server-configured directory. The default active path is:

```text
data/runtime/robots/primary.json
```

The document contains only:

- schema version and robot ID;
- variant and exact Profile Fingerprint;
- exact logical positions and explicit units;
- the last recorded connection state;
- timezone-aware update timestamp and non-negative `state_sequence`.

It contains no serial port, secret, hardware identifier, raw Servo position, multi-turn device state, real Calibration, or arbitrary filesystem path. Runtime files and quarantine files are ignored by Git.

Robot IDs must match a restricted filename pattern. The resolved target's parent must be the configured runtime directory, and clients cannot choose either the directory or robot ID. API diagnostics expose only a safe repository-relative description and an optional quarantine filename, never the configured absolute host path.

Writes serialize deterministic JSON to a temporary sibling in the target directory, flush and `fsync` the file, then replace the destination atomically. Temporary files are removed if replacement fails.

On load, JSON and the Pydantic schema are validated first. Application restore then requires:

- `robot_id=primary`;
- exact active variant and Profile Fingerprint;
- positions and units whose keys exactly equal `enabled_joints`;
- units exactly equal the Profile's per-joint units;
- finite values inside logical Profile limits.

Corrupt or incompatible state is renamed to `primary.quarantine-<UTC timestamp>.json`, recorded as a safe diagnostic, and ignored. The restore candidate falls back to the active Profile's Home positions and sequence zero rather than trying to repair or partially merge data. Initial startup uses that zero; a variant switch advances from the current runtime sequence as described below.

A compatible file restores positions, units, and sequence. It never restores connection authority: every process constructs a fresh in-memory driver and starts `DISCONNECTED`, regardless of the saved connection-state field. Connect remains an explicit operator action.

Connect, Disconnect, Stop, and variant switch persist stable Dry Run state through the application service. One command lock serializes those operations. Variant switching is disconnected-only; it checks the candidate variant's saved file against that candidate Profile and otherwise uses its Home state. The next sequence is greater than both the current runtime and any accepted restored sequence.

## Alternatives

- Do not persist Dry Run state: rejected because deterministic restart behavior and state diagnostics are useful without adding physical risk.
- Reuse Pose or Motion storage: rejected because runtime state is replaceable operational data, while Pose/Motion are immutable/revisioned user entities with different compatibility and retention rules.
- Restore a saved `CONNECTED` state: rejected because process history cannot prove a current connection, even for Dry Run, and must never become a precedent for hardware reconnection.
- Merge partial/mismatched joint maps with Home values: rejected because it can hide Profile changes, fabricate missing joints, or retain V2 J10 in V1.
- Overwrite invalid files silently: rejected because quarantine preserves diagnostic evidence without blocking a safe Home fallback.
- Use display names or client paths as filenames: rejected because names are mutable and unsafe as storage identity.

## Consequences

Dry Run restarts are deterministic when state is compatible and safely recoverable when it is not. Profile changes intentionally invalidate state. Operators can see whether restore succeeded or quarantine occurred without exposing host paths.

Runtime state is not a physical-state record, motion history, or authorization artifact. A later real-hardware Stage must define a separate device-state and reconnection policy; it must not reuse this Dry Run restore behavior to infer that hardware is connected or safe.
