# Kinematics model audit

## Evidence boundary

The only Legacy evidence reviewed for Stage 3 is tracked content at commit
`ff8bbda0c2222cb57951c7913f7f12f5777b98fa`. No Legacy program was executed, no
mesh was copied, and no local or ignored configuration, calibration, runtime data,
serial setting, or device was inspected.

Both tracked Legacy URDF files describe six movable joints and include a prismatic
`J10`. That contradicts the MOMO V1 product contract, which is exactly `j11` through
`j15` and has no rail. The Legacy V1 URDF therefore cannot be used directly.

## Provisional reconstruction

The Stage 3 models are mesh-free serial chains expressed in SI units. Joint axes and
origin transforms are transcribed as characterization evidence, not copied as an
authoritative hardware asset. The V2 model retains `j10` through `j15`. The V1 model
removes the `j10` degree of freedom and folds the Legacy zero-position base transform
into the fixed base-to-arm transform before `j11`.

This reconstruction is intentionally marked `PROVISIONAL_DRY_RUN`. It is suitable for
deterministic software tests and Dry Run UI behavior only. It does not authorize Real
Cartesian motion, Real playback containing Cartesian segments, or Real vision follow.

## Evidence extracted

| Variant | Joint | Type | Axis | Provisional model origin translation (m) |
|---|---|---|---|---|
| V1 | j11 | revolute | +Z | `[-0.00000505, -0.005287, 0.0922507]` (rail-free base transform folded in) |
| V1 | j12 | revolute | +Z | `[-0.031005, 0.00000003, -0.10690639]` |
| V1 | j13 | revolute | -Z | `[0.12501147, 0.043, 0.062]` |
| V1 | j14 | revolute | -Z | `[0.153, 0.000075, 0.011775]` |
| V1 | j15 | revolute | +Z | `[-0.067125, 0.00002501, -0.015925]` |
| V2 | j10 | prismatic | +Z | `[0.025, 0, 0]` |
| V2 | j11 | revolute | -Z | `[0.000145, 0.089, -0.02500505]` |
| V2 | j12 | revolute | +Z | `[0.02599998, 0, 0.06700005]` |
| V2 | j13 | revolute | +Z | `[0, 0.12999998, -0.00000005]` |
| V2 | j14 | revolute | +Z | `[0.14999991, 0.00000003, -0.063]` |
| V2 | j15 | revolute | +Z | `[0.06139999, -0.00440002, 0.03045014]` |

The persisted provisional YAML files are the implementation authority for Dry Run. They
use schema `1.0.0`; its generated artifact is
`docs/schemas/kinematics-model.schema.json`. Each file stores a declared
`kinematics_fingerprint`, and model loading recomputes the canonical digest over schema
version, variant, frames, and ordered joint identity/type/axis/origin/limits:

| Variant | Current schema 1.0.0 fingerprint |
|---|---|
| V1 | `9477f15fd2484ba393ee95eff15441d544e1a1aa904668b10c6b4e53f96e6e4e` |
| V2 | `84fdb19f6f7045856e68be8b54ae6192b26c27106756bef604e69817903eca13` |

A missing or mismatched declaration rejects model loading. Verification/provenance state
and human-readable prose are excluded so editorial changes cannot invalidate compatible
geometry. These hashes prove exact software-model identity only; they are not evidence
of physical accuracy, safety, ownership, license clearance, or redistribution rights.
Two consecutive schema-generation runs produced byte-identical artifacts; the Stage 3
report records the complete verification evidence.

## Conflicts and decisions

- Legacy Profile YAML gives V1 a rail and gives J10 angle-shaped limits. It is retained
  only as conflict evidence.
- Legacy FK/IK assumes a fixed six-value array and branches on the J10 name to convert
  units. MOMO Studio instead uses keyed joint maps and each joint's explicit type/unit.
- Legacy IK delegates to PyBullet and permits approximate outcomes under configuration.
  MOMO Studio uses deterministic damped least squares with explicit residuals and
  termination reasons; an approximate result is never silently treated as reachable.
- Legacy Cartesian movement solves only the endpoint. It is not evidence of a linear
  TCP path and is not reused for the Stage 5 Cartesian compiler.
- No STL, PyBullet GUI, Legacy controller, or third-party binary is part of the new
  kinematics runtime.

## Verification still required

Physical V1/V2 link geometry, base and TCP frames, signs, joint zero references,
workspace, limits, velocities, accelerations, FK reference points, IK tolerances, and
Cartesian path accuracy all require independent field measurement and acceptance.
