# Changelog

All notable changes to MOMO Studio are recorded here. The project has not selected a
distribution license; a release tag does not itself grant redistribution rights.

## 0.1.0-rc1 - 2026-08-24

Release status: `FIELD_ACCEPTANCE_REQUIRED`.

### Added

- V1/V2 Profile, Calibration, mesh-free kinematics, FK/IK, and one reviewed Motion
  Safety Gateway with cancellable Dry Run execution and deadman Jog.
- Atomic UUID-based Pose, Motion, and MotionDraft repositories; Library, deterministic
  trajectory preflight/preview/playback, and Studio timeline authoring.
- Synthetic Vision source, ROI/detector/tracker fixtures, bounded streaming, and
  lease-bound Dry Run Follow with target-lost and stale-frame Stop behavior.
- Minimal explicit-ID `ServoBus` port, Fake Bus verification, lazy optional Feetech
  adapter shell, full Real-readiness matrix, short-lived memory-only Operator Session,
  explicit connect, gated read-only diagnostics, protected Calibration revisions, and
  Fake-Bus Real executor verification.
- Localhost-by-default security, opt-in token-authenticated LAN policy, bounded request
  and control rates, structured redacted audit records, deterministic config-free
  backup/import preview/migration/atomic restore, static SPA hosting, and CI isolation
  gates.

### Safety status

- Dry Run and Synthetic workflows are validated.
- Committed Profiles and Calibration are examples; kinematics remain provisional for
  physical use.
- No field-acceptance item was executed during autonomous development.
- Real hardware, Real Cartesian, Real Playback, and Real Vision Follow remain blocked
  until their complete capability gates and physical acceptance pass.
