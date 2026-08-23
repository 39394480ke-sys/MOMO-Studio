# Robot profile examples

These files encode the MOMO Studio product contract, not verified hardware calibration.

- V1 enables `j11` through `j15` and has no linear rail.
- V2 enables `j10` through `j15`; `j10` is the linear rail.

All limits, homes, TCP link names, hardware mappings, and URDF references in Stage 1 are placeholders. They must be reviewed against the exact robot, calibration, URDF, and mechanical limits before a later stage may use them for real motion. Local calibrated profiles must not be committed.
