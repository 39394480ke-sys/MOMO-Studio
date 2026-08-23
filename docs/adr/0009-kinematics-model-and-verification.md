# ADR 0009: Kinematics model and verification

- Status: Accepted
- Date: 2026-08-24

## Context

Dry Run control needs reproducible FK, IK, and Cartesian target composition for two
hardware variants. The Legacy V1 URDF contradicts the product by including J10, while
the Legacy implementation assumes six ordered values and a name-based unit branch.
Neither is a safe product contract.

## Decision

Use versioned, mesh-free serial-chain model documents with explicit variant, frames,
joint identity/type/axis/origin, SI limits, provenance, verification status, and a
deterministic geometry fingerprint. V1 contains `j11`-`j15`; V2 contains `j10`-`j15`
with a prismatic J10. Domain/UI values remain mm/deg and are converted to m/rad only
through named port helpers.

The initial persisted contract is schema `1.0.0`, represented by
`docs/schemas/kinematics-model.schema.json`. Each YAML document declares its
`kinematics_fingerprint`; model validation recomputes the canonical digest and rejects a
missing or mismatched value. The digest identifies an exact software model only and is
not evidence of physical accuracy, provenance clearance, or permission to redistribute
Legacy-derived material.

Implement FK with deterministic homogeneous transforms and IK with damped least
squares, joint-limit projection, deterministic seeds, bounded iterations, explicit
position/orientation residuals, best-solution reporting, and typed termination reasons.
Quaternions use normalized XYZW order. Base and Tool increments are distinct pure
operations.

Both initial model documents are `PROVISIONAL_DRY_RUN`. Their values can support Dry
Run but categorically block every Real Cartesian-derived capability.

## Consequences

V1 can no longer inherit a phantom rail, dictionary order cannot change results, and
model compatibility can be checked independently from the Robot Profile. NumPy is the
only new runtime math dependency. Physical model accuracy remains unverified and is a
field-acceptance item.
