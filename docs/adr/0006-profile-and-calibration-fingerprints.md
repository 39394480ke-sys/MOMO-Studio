# ADR 0006: Profile fingerprint and Calibration binding

- Status: Accepted
- Date: 2026-08-24

## Context

Calibration and saved Dry Run state are meaningful only for the exact Profile that defined joint identity, units, limits, and hardware mapping. Comparing a filename, display name, timestamp, or variant alone would allow a safety-relevant Profile edit to reuse stale data silently. Conversely, changing UI copy must not invalidate compatible state.

Stage 2 also needs to distinguish configuration compatibility from real-hardware trust. A deterministic hash can identify content, but it cannot prove that the content was measured or approved on a physical robot.

## Decision

Compute `RobotProfile.fingerprint` as lowercase SHA-256 over deterministic JSON:

- keys are sorted;
- separators are compact and fixed;
- ASCII escaping is deterministic;
- NaN and Infinity are forbidden;
- enabled joints and joint definitions preserve their validated order.

The canonical payload includes:

- variant and ordered `enabled_joints`;
- per-joint ID, type, domain unit, and Servo ID;
- motor degrees per domain unit and raw counts per motor revolution;
- operating mode and direction;
- logical minimum, maximum, and Home;
- Home present raw, raw bounds, and `raw_reachable`.

It excludes display name, description, template and verification state, source metadata, timestamps, schema version, URDF/TCP display references, and the deprecated placeholder mapping. `has_linear_rail` is not duplicated because the included variant and validated product contract determine it.

Every `CalibrationDocument` stores the exact `profile_fingerprint` it was authored against. Calibration compatibility requires exact variant, exact Profile Fingerprint, exact enabled-joint set, Profile-matching Servo IDs/modes/raw bounds, and complete valid joint entries. Every persisted Dry Run runtime state also stores the Profile Fingerprint; a mismatch causes quarantine and Profile-Home fallback rather than partial restore.

Stage 2 does not compute a separate Calibration-content fingerprint. The immutable Calibration document's UUID is its document identity, while `profile_fingerprint` is its compatibility binding. The existing optional Calibration fingerprint field in Pose provenance remains unused until a later Stage defines a canonical Calibration digest and migration policy. Adding such a field is a persisted-schema change and requires an ADR, compatibility analysis, round-trip tests, and regenerated schemas.

Fingerprint equality never grants Real readiness. Template state and `verification_status` are checked separately, and Stage 2 always blocks Real hardware by policy.

## Alternatives

- Hash the complete serialized Profile: rejected because display/provenance edits would invalidate Calibration and runtime state without changing motion or safety behavior.
- Match only variant or enabled joints: rejected because limits, direction, Servo mapping, Home, raw bounds, and mode could change silently.
- Use a random Profile UUID: rejected because equal reviewed content would not have a reproducible identity and edited content could retain the same ID.
- Add a Calibration digest immediately: deferred because no Stage 2 workflow captures, revises, selects, or replays production Calibration. Defining a digest without that lifecycle would create a misleading contract.

## Consequences

A motion/safety Profile edit invalidates associated Calibration compatibility and saved runtime restoration deterministically. Display-only edits do not. Runtime mismatches are recoverable through quarantine and Home fallback, while Calibration mismatches remain visible diagnostics.

Canonical-field changes now require deliberate compatibility review because they change every dependent fingerprint. Hashes remain identity evidence only; provenance, template state, physical verification, operator intent, and hardware policy are independent gates.
