# Robot profile examples

These files encode the MOMO Studio product contract, not verified hardware calibration.

- V1 enables `j11` through `j15` and has no linear rail.
- V2 enables `j10` through `j15`; `j10` is the linear rail.

Stage 2 records explicit units, servo IDs, transmission scales, operating modes, raw bounds, source revision, and verification status so pure mapping behavior can be characterized. Logical limits and J10 millimetre data remain synthetic, and Legacy-derived transmission references are not verified for real hardware.

Each loaded profile receives a deterministic SHA-256 fingerprint over motion- and safety-relevant canonical fields. Display name, description, and other UI metadata do not affect it. Both committed profiles are `template: true` and cannot authorize Real mode. Local verified profiles and calibration must not be committed.
