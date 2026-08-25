# MOMO Studio roadmap

This roadmap starts at the `0.1.0-rc1` software candidate. It does not authorize Real
hardware, expand the accepted first-version scope, or turn future ideas into current
product commitments. V1 and V2 are robot variants, not software versions.

## v0.1.0-rc1 — COMPLETE: software candidate

The candidate includes the web-first local application, V1/V2 Dry Run Control, FK/IK,
Pose/Motion Library, trajectory compiler and Playback, Studio timeline, Synthetic Vision
Follow, and the fail-closed commissioning/Real-hardware software boundary.

Software evidence is complete for user acceptance. Fake/Bomb/isolated commissioning
evidence is not physical acceptance. Feetech goal write, Physical Stop/E-stop, Real
Kinematics, and all capability-specific Real operation remain field gated.

## Phase A — User software acceptance

- Run the [software user-acceptance checklist](user-acceptance-checklist.md).
- Record `ACCEPT`, `ACCEPT WITH ISSUES`, or `REJECT`.
- Keep PR #1 Draft until the user decides.
- Resolve only focused acceptance issues; do not reopen the architecture broadly.

## Phase B — Feetech adapter verification

- Pin and review the exact SDK artifact, provenance, license, API, and supported platform.
- Verify explicit-ID read/write mapping without scan or arbitrary register access.
- Validate cancellation and typed Stop/Hold semantics on an isolated bench setup.
- Keep the production write-capable factory closed until reviewed evidence exists.

## Phase C — Physical commissioning

- Assign a stable local `robot_unit_id` for the exact robot.
- Complete physical preparation and read-only commissioning.
- Create and review Calibration Revision 1 for each physical unit.
- Preserve explicit operator intent, physical E-stop readiness, and workspace controls.

## Phase D — Joint field acceptance

- Run bounded positive and negative tests for every enabled joint.
- Verify raw/logical mapping, direction, limits, readback, divergence, and Stop behavior.
- Accept Joint Motion only from complete, current, exact-unit evidence.

## Phase E — Kinematics field verification

- Add and review the physical joint-state snapshot provider.
- Measure at least three independent TCP points for each unit/model.
- Compare server-computed FK with physical TCP measurements and accepted thresholds.
- Keep tracked Kinematics YAML `PROVISIONAL_DRY_RUN`; use exact-unit local evidence.

## Phase F — Cartesian and Playback acceptance

- Complete Cartesian field tests only after Joint and Kinematics acceptance.
- Accept Cartesian independently from Joint Motion.
- Validate Joint-only and Cartesian Playback against their distinct evidence sets.
- Keep unavailable capabilities blocked with structured reasons.

## Phase G — Vision field tuning

- Review the exact live-camera provider, device policy, provenance, and latency.
- Characterize tracking loss, end-to-end latency, dead zone, filtering, and gains.
- Complete Vision Follow evidence only after its Joint/Kinematics prerequisites.
- Retain automatic Stop on stale/lost/low-confidence targets and lease loss.

## Phase H — Desktop packaging / Tauri

- Follow the [Tauri packaging plan](tauri-packaging-plan.md).
- Establish reproducible, signed build and update procedures.
- Complete dependency-license collection and choose a repository license before
  distribution.
- Preserve loopback, authentication, storage, backup, and safety boundaries.

## Phase I — Future multi-arm research

- Treat this as a future product decision, not a first-version deliverable.
- Preserve one active robot and explicit identity in the current product.
- Do not add a global robot singleton, `arm_a` assumptions, or fleet-facing controls.
- Require a new architecture/safety review before any multi-arm implementation.

## Field procedure

Physical work follows [Real-hardware field acceptance](real-hardware-acceptance.md) in
Phase 0–10 order. No roadmap entry may be marked complete from Fake evidence alone.
