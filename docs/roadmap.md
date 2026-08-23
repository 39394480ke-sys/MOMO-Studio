# Roadmap

This roadmap describes sequencing constraints, not work already started.

## Stage 1 — Foundation (current)

Independent repository, product/safety boundary, domain models, ports, schemas, health/meta APIs, frontend routes, Legacy audit, tests, and reproducible developer commands. No robot capability.

## Later prerequisites and increments

1. **Storage and safe application services:** atomic file repositories, revisions, CRUD/use cases, conflict and corruption tests. Still Dry Run.
2. **Kinematics and robot-state simulation:** explicit unit converters, reviewed V1/V2 URDF mapping, FK/IK reachability/error contracts, fake driver and deterministic state flow.
3. **Reviewed hardware integration:** one model at a time, verified profiles/calibration identities, unified safety gate, connection/diagnostics/Stop before any motion, operator-only Real enablement.
4. **Control and pose workflow:** joint/Cartesian controls, snapshot capture, Goto with preflight, error recovery.
5. **Studio and Library:** keyframes, interpolation/sampling, timeline editing, atomic persistence, compatibility and playback safety.
6. **Vision following:** camera provider, target selection/detection, smoothing/dead zone, bounded tracking and target-loss stop.

Each increment gets its own scoped Stage, evidence, tests, safety review, and commit. Out-of-scope product features remain excluded unless the product definition is explicitly revised.

## Decisions awaiting evidence

- verified joint limits, homes, servo mappings, gear/sign conventions, and multi-turn representation for each physical variant;
- authoritative V1/V2 URDF and TCP link mapping;
- calibration file identity/version contract;
- later desktop packaging and local network authentication model;
- licensing choice and approval of each migrated third-party asset.
