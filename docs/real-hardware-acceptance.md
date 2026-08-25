# Real-hardware field acceptance

Status: **NOT EXECUTED — REQUIRED FOR `0.1.0-rc1`**.

This is a field procedure for qualified personnel, not an autonomous test script. Apply
it to one exact V1/V2 unit. Record the operator, independent reviewer, date, software
commit, local `robot_unit_id`, masked hardware identity, Profile/Calibration/Device/
Kinematics fingerprints, measurements, evidence IDs, and every deviation outside Git.
A result for one unit or variant never qualifies another.

The order below is mandatory. Do not create a global `PASSED` record before testing.
Each later capability is derived only from current evidence produced by earlier phases.
An unchecked item is a no-go for that phase and everything downstream.

## Phase 0 — Physical preparation

- [ ] A stable `robot_unit_id` for the exact arm is assigned in ignored local
  configuration; it was not derived from a port, hostname, protocol, or Servo IDs.
- [ ] A tested physical E-stop is present, reachable, and independently halts/removes
  actuation as intended.
- [ ] The arm is unloaded or carries only the approved payload; the guarded workspace is
  clear and cannot be entered during actuation.
- [ ] Power supply, grounding, current limits, cables, strain relief, fixtures, and
  mechanical condition are reviewed.
- [ ] The exact Feetech SDK/package/version/source/API/license and transitive artifacts
  are approved; import and adapter construction have no device side effects.
- [ ] Correct explicit serial device, protocol, and ordered Servo IDs are independently
  verified. No scan or enumeration is permitted.
- [ ] Correct software commit and clean offline build are installed; no secret, port,
  Calibration, local evidence, or unit identity is committed to Git.
- [ ] Initial delta, speed, acceleration, duration, and playback rate are reduced to the
  approved field values, never above compiled commissioning hard caps.
- [ ] Two-person stop/go review is complete.

Use the physical E-stop immediately on unexpected motion, noise, current, heat,
communication loss, divergence, or an uncertain software Stop result.

## Phase 1 — Read-only commissioning

- [ ] Real mode, `READ_ONLY` hardware policy, explicit startup/local opt-ins, verified
  non-template Profile, exact Device identity, and `COMMISSIONING_READ_ONLY` confirmation
  were reviewed.
- [ ] Explicit connect opened only the configured device and pinged only configured IDs.
- [ ] Connection performed no scan, enumeration, Home, mode write, torque write, goal
  write, or movement.
- [ ] Operating mode, torque state, and present position were read for every explicit
  Profile joint; partial failure closed the bus and invalidated the session.
- [ ] The read-only token was rejected by Commissioning Motion, Joint, Home, Cartesian,
  Playback, Studio, Library Goto, and Vision Follow operations.
- [ ] Backend restart, expiry, revoke, context drift, and disconnect invalidated the
  session; refresh did not issue a replacement automatically.

## Phase 2 — Calibration

- [ ] A fresh unit progressed from no Calibration to a complete Revision 1; missing
  values remained absent and no fabricated zero was used.
- [ ] Each enabled joint was selected explicitly; capture read only that configured
  joint and performed no write or movement.
- [ ] Direction, Home raw/logical value, phase/multi-turn behavior, raw bounds, logical
  bounds/unit, scale, operating mode, mapping round trip, and fingerprint were reviewed.
- [ ] The saved Calibration binds the exact `robot_unit_id`, variant, Profile
  fingerprint, enabled-joint set, and Device context.
- [ ] Revision N → N+1 recalibration, backup, fingerprint change, and explicit
  forward-only rollback were reviewed.
- [ ] Calibration completion granted no motion and did not upgrade the read-only token.

## Phase 3 — Pre-motion safety checks

- [ ] The physical E-stop was retested immediately before motion.
- [ ] Workspace-clear, payload, fixture, cable, power, and two-person confirmations are
  current.
- [ ] Unit, variant, Profile, Calibration, Device, ordered joints/IDs, units, modes,
  logical/raw limits, and adapter identity match exactly.
- [ ] `commissioning_motion_test_enabled` is explicitly enabled locally;
  `real_motion_enabled` remains an independent production gate.
- [ ] Feetech goal-write and Stop semantics have measured adapter evidence; otherwise
  this phase remains blocked and no physical test session is issued.
- [ ] Immutable `PRE_MOTION_CHECKS` capability evidence was committed with required
  operator identity, read-only session/timestamp, and exact per-joint Servo ping, mode,
  present raw/logical value, bounds, and torque-off snapshot.
- [ ] After the required READ_ONLY → FULL restart, startup semantically revalidated exact
  joint/Servo coverage, Calibration mapping/mode/bounds, torque-off evidence, timing, and
  current bindings; fingerprints alone were not treated as authority.

## Phase 4 — Restricted joint motion test

Request a new `COMMISSIONING_MOTION_TEST` session. It cannot be derived from the
read-only token and it does not grant production `REAL_MOTION`.

- [ ] The UI displays `REAL HARDWARE — LOW-SPEED SINGLE-JOINT TEST ONLY`, the physical
  E-stop reminder, exact unit/fingerprints, current/raw values, and hard caps.
- [ ] Each attempt requires explicit ARM plus press-and-hold; pointer release/cancel,
  blur, hidden visibility, route change, network loss, expiry, Stop, or 400 ms backend
  deadman timeout ends/faults it.
- [ ] The backend rejects more than one active joint, absolute targets, multi-joint work,
  Home, Cartesian, Playback, Library/Studio motion, Vision motion, loops, arbitrary IDs,
  raw registers, mode writes, and torque writes.
- [ ] The active envelope does not exceed: one joint, 2 s command, 300 s session,
  2 deg/1 mm delta, 2 deg/s or 1 mm/s, 4 deg/s² or 2 mm/s², and 24 commands.
- [ ] Target calculation used the latest fresh readback, Profile logical bounds,
  Calibration-derived raw bounds, exact mapping, immutable prepared command, and one
  explicitly authorized Servo ID.
- [ ] Readback verified expected/observed direction, requested/actual logical and raw
  change, freshness, limit compliance, divergence, and Stop behavior.
- [ ] Successful and failed attempts produced immutable local evidence and bounded audit
  records without a session token or client-selected path.

Complete this table for every Profile-enabled joint. V1 is `j11`–`j15`; V2 is
`j10`–`j15`, with prismatic `j10` in millimetres.

| Check | J10 if enabled | J11 | J12 | J13 | J14 | J15 |
|---|---|---|---|---|---|---|
| Positive direction | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Negative direction | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Logical/raw readback | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Limit-safe target | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Divergence behavior | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Software Stop result | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| Physical E-stop result | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |

Fake Stop success may be recorded only as `SOFTWARE_PATH_VERIFIED`. It cannot set
`physical_stop_verified`; physical behavior remains `PENDING` until measured here.

## Phase 5 — Joint motion acceptance

- [ ] Every enabled joint has current positive, negative, limit-safe, and fresh
  logical/raw readback evidence; one joint is insufficient.
- [ ] Failed direction, divergence, stale readback, Stop failure, wrong unit, missing
  joint/direction, or fingerprint mismatch blocks acceptance.
- [ ] The backend created `JOINT_MOTION` acceptance only from server-validated test
  evidence; no confirmation-only/global-PASSED endpoint or Accept All action was used.
- [ ] Joint capability becomes software-ready only for the exact evidence binding.
- [ ] A new production session is still required, and unverified Feetech/physical Stop
  gates continue to block physical production motion.

## Phase 6 — Kinematics verification

- [ ] Joint Motion acceptance is current before measurement begins.
- [ ] V1 rail-less and V2 rail models are measured separately; base, Tool, TCP, axes,
  signs, zero references, and V2 J10 `mm`↔`m` / revolute `deg`↔`rad` boundaries are
  reviewed.
- [ ] At least three materially distinct known joint poses cover the applicable
  workspace; the backend captures each fresh session/device-bound joint state and its
  sequence/time, computes predicted TCP, and records the independently measured TCP,
  residuals, and measurement time. The browser never supplies joint state.
- [ ] Every point passes frozen field thresholds no looser than the software hard bounds
  of 25 mm and 15 degrees; stricter approved thresholds are recorded.
- [ ] Immutable local `KinematicsVerificationEvidence` binds unit, Profile,
  Calibration, Device, model fingerprint/schema, checklist, operator, and software
  commit.
- [ ] The committed provisional YAML remains `PROVISIONAL_DRY_RUN`; effective Real
  verification is derived only from the current evidence overlay.
- [ ] Unit/Profile/Calibration/Device/model/checklist/software-commit change makes the
  evidence stale and blocks geometry-dependent capabilities.
- [ ] A reviewed physical snapshot adapter is wired. `0.1.0-rc1` supplies none and does
  not restore persisted Kinematics evidence as authorization after restart; repeat this
  phase after every restart before relying on effective Real Kinematics.

## Phase 7 — Cartesian acceptance

- [ ] Joint and Kinematics evidence are current and a new authorized production path is
  used; Commissioning Motion cannot call Cartesian operations.
- [ ] FK reference positions/orientations, IK reachability/convergence/limits/residual
  rejection, Base/Tool signed directions, workspace bounds, and Cartesian path
  tolerances were measured.
- [ ] Singularity, collision, load, backlash, flex, and constraints not modeled by
  software are documented.
- [ ] Cartesian acceptance evidence references the supporting unit-bound tests and
  required independent reviewer.

## Phase 8 — Playback acceptance

- [ ] Two-keyframe Joint Motion runs at the minimum approved speed only after Joint
  acceptance.
- [ ] Cartesian Motion runs only after current Kinematics and Cartesian acceptance.
- [ ] Exact prepared digest, duration, hold, easing, rate, Pause/Resume/Stop, loop
  termination, and state/readback continuity behave as reviewed.
- [ ] Network/power interruption, partial write, divergence, bus fault, disconnect, and
  expiry end in a truthful bounded fault/uncertain state.
- [ ] Playback acceptance evidence distinguishes Joint-only from Cartesian-dependent
  prerequisites.

## Phase 9 — Vision Follow acceptance

- [ ] Exact camera/device/provider provenance and offline deployment are approved.
- [ ] ROI/target remains bound to the exact frame/source; lost target, stale/non-advancing
  frame, low confidence, lease expiry, disconnect, conflict, Stop, and shutdown end
  motion.
- [ ] Pan/tilt directions, dead zone, EMA, gain, maximum step/speed, camera latency, and
  physical response are measured at approved low speed.
- [ ] Current Joint evidence, Vision Follow evidence, and Kinematics evidence whenever
  the controller requires it are present.

## Phase 10 — Final review

- [ ] Operator and independent reviewer reconciled every evidence ID, audit event,
  failure, deviation, fingerprint, checklist version, and software commit.
- [ ] Security, HttpOnly operator-session renewal/revoke, LAN deployment, backup/restore,
  redaction, restart invalidation, and recovery were exercised in the intended topology.
- [ ] Changing `robot_unit_id`, Profile, Calibration, Device, Kinematics, model schema,
  checklist version, software commit, or commissioning envelope stales or fails
  semantic resolution for the appropriate evidence and removes capability readiness.
- [ ] Old schema-v1/global evidence remains audit-only `STALE_LEGACY_EVIDENCE`, and the
  removed writable `field_acceptance_status` config key is absent; neither has any
  authorization effect.
- [ ] `FULL_ACCEPTANCE_COMPLETE`, if displayed, is derived from all required current
  capability records and is not a persisted writable pass.
- [ ] Feetech goal-write behavior, software/physical Stop, and physical E-stop claims are
  supported by measured evidence; otherwise release remains blocked.
- [ ] The final sign-off states which capabilities passed. No capability is inferred from
  another and one unit's evidence is never reused for another unit.
