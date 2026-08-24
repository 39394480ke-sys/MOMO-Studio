# Real-hardware field acceptance

Status: **NOT EXECUTED — REQUIRED FOR `0.1.0-rc1`**.

This is a field procedure, not autonomous test instructions. It must be approved and
performed by qualified personnel with the exact V1/V2 unit. Record operator, reviewer,
date, hardware identifiers outside Git, software commit, Profile/Calibration/Kinematics
fingerprints, power configuration, results, measurements, evidence, and every deviation.
One passing variant or unit does not qualify another.

## Environment and go/no-go

- [ ] Tested physical E-stop is present, reachable, and independently removes/halts
  actuation as intended.
- [ ] Arm is unloaded; no camera payload, gripper, or unapproved attachment is fitted.
- [ ] Guarded workspace is clear and no person can enter it during actuation.
- [ ] Initial limits, velocity, acceleration, and playback rate are reduced to the
  approved low-speed acceptance values.
- [ ] Power supply, grounding, cables, strain relief, and current limits are adequate.
- [ ] Correct explicit serial device, protocol, and ordered explicit Servo IDs are
  independently verified; no scan is allowed.
- [ ] Correct commit and clean build are installed offline; no local secret, Calibration,
  or hardware identifier is placed in Git or evidence screenshots.
- [ ] V1/V2 Profile, Calibration, and Kinematics fingerprints match the intended unit.
- [ ] Two-person stop/go review is complete before enabling any torque or motion.

Any unchecked item is a no-go. Use the physical E-stop on unexpected motion, noise,
current, heat, communication loss, divergence, or uncertain software Stop result.

## Dependency, connection, and isolation

- [ ] Exact Feetech SDK package, version, canonical source, API compatibility, license,
  bundled notices, and transitive native artifacts are approved.
- [ ] Import and adapter construction have no device side effects.
- [ ] Explicit connect opens only the reviewed device and pings only the reviewed IDs.
- [ ] Partial ping/read/mode failure closes the port, invalidates the session, and never
  reports Connected.
- [ ] Connect performs no scan, Home, mode write, torque enable, goal write, or movement.
- [ ] Backend restart, token expiry, context drift, disconnect, and power interruption
  revoke authorization and fail closed.

## Per-joint record

Complete the following for every joint in the active Profile's `enabled_joints`; do not
assume six joints or J10. V1 is exactly J11–J15. V2 is J10–J15, with J10 in millimetres.

| Check | J10 if enabled | J11 | J12 | J13 | J14 | J15 |
|---|---|---|---|---|---|---|
| Explicit Servo ID | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Operating Mode | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Direction | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Home raw/logical | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Phase/multi-turn | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Raw bounds | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Logical bounds/unit | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Low-speed positive move | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Low-speed negative move | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Readback/tolerance | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Divergence trip | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Software Stop result | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Physical E-stop result | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |

- [ ] Direction and Home were established independently, not inferred from Legacy data.
- [ ] Raw and logical bounds reject both sides before any bus write.
- [ ] Calibration capture read only the selected joint and performed no movement/write.
- [ ] New Calibration revision, fingerprint, backup, and explicit rollback were verified.

## Kinematics and Cartesian acceptance

- [ ] V1 rail-less chain and V2 rail chain are tested separately.
- [ ] Multiple measured FK reference points cover the workspace and joint extremes.
- [ ] Base and Tool frames and the configured TCP transform are measured and signed off.
- [ ] V2 J10 `mm` ↔ `m` boundary is correct; revolute `deg` ↔ `rad` boundaries are correct.
- [ ] IK reachability, convergence, limits, and best-result rejection are verified.
- [ ] Push In / Pull Out and signed Base/Tool Cartesian jog directions are correct.
- [ ] Cartesian lines remain within approved path/tolerance/workspace bounds.
- [ ] Collision/singularity/load constraints not modeled by software are documented.

Until every applicable item passes, Real Cartesian, Cartesian Playback, and Real Vision
Follow remain blocked even if Real Joint motion is accepted.

## Playback acceptance

- [ ] Two-keyframe Joint Motion at minimum approved speed.
- [ ] Two-keyframe Cartesian Motion only after Kinematics acceptance.
- [ ] Duration, hold, easing, rate, and exact prepared digest behave as reviewed.
- [ ] Pause, Resume, Stop, and loop termination are verified.
- [ ] Power interruption produces a known safe recovery procedure.
- [ ] Network interruption expires ownership and does not continue unbounded motion.
- [ ] Readback divergence, partial write, bus fault, and disconnect enter a truthful
  fault/uncertain state with an audit event.

## Vision acceptance

- [ ] Exact camera/device/provenance and offline provider are approved.
- [ ] ROI and target identity stay bound to the exact frame/source.
- [ ] Target lost, stale frame, low confidence, Follow Stop, lease expiry, disconnect,
  and conflict stop motion.
- [ ] Pan/tilt direction, dead zone, EMA, gain, max step, and max speed are verified at
  low speed with the physical E-stop held ready.
- [ ] Real Vision capability stays blocked if Kinematics or any upstream gate is not
  verified for Real.

## Release sign-off

- [ ] All failures and deviations are resolved or explicitly release-blocking.
- [ ] Software Stop semantics—including Feetech hold/torque behavior—are documented from
  measured results. No uncertain outcome is labeled success.
- [ ] Security, backup/restore, audit redaction, and recovery were exercised in the
  intended deployment topology.
- [ ] Field Acceptance record is approved by operator and independent reviewer.
- [ ] Only after approval, ignored local configuration may set field acceptance to
  `PASSED`; committed defaults remain `PENDING`.
