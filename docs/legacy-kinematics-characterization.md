# Legacy kinematics characterization

## Source

- Repository: `MOMO_RobotARM`
- Commit: `ff8bbda0c2222cb57951c7913f7f12f5777b98fa`
- Reviewed tracked areas: `URDF运动学仿真/`, the Web controller bridge/service,
  continuous joint streaming, safety checker, and the two tracked Robot Profiles.

The review was static. No Legacy application, simulator GUI, driver, serial SDK,
camera, or device operation ran.

## Characterized behavior

| Behavior | Observation | MOMO Studio disposition |
|---|---|---|
| Joint membership | Global six-joint `j10`-`j15` assumptions occur even for V1. | Reject. Membership always comes from explicit `enabled_joints`. |
| Units | Several paths branch on the string `j10` for mm/m while treating all other values as deg/rad. | Rewrite. Conversion follows declared joint type/unit at named boundaries. |
| FK | PyBullet-backed, fixed-order and mesh/URDF-coupled. | Rewrite as a mesh-free serial chain with deterministic matrix math. |
| IK | Fixed-order PyBullet solve with configurable approximate residual acceptance. | Rewrite as typed DLS results with best solution, residuals and a failure reason. |
| Base delta | Translation is interpreted in the base frame. | Retain as a pure composition rule. |
| Tool delta | Translation is rotated by current TCP orientation; tool rotation post-multiplies current orientation. | Retain as a pure composition rule and test separately from base motion. |
| Continuous stream | Attempts regular scheduling and cancellation but uses mutable worker state and sleep-driven timing. | Retain the absolute-deadline/no-drift intent; rewrite using an injected monotonic clock and explicit cancellation. |
| Stop | Mixed with controller/driver ownership and cannot express uncertain physical state. | Rewrite behind one application gateway; Stage 3 is Dry Run only. |
| WebSocket | Per-client sends have no product-level bounded queue/rate contract. | Rewrite as read-only bounded-rate status delivery; never expose raw control. |
| Controller bridge | Lifecycle, kinematics, filesystem, motion and other product areas are combined. | Retire as architecture. API routes call small application services only. |

## Stage 3 characterization tests

New tests use only provisional model files, synthetic joint maps, deterministic targets,
a Fake Clock, and the in-memory Dry Run driver. They pin V1/V2 membership, SI boundary
conversion, FK determinism, IK round trips and failures, base/tool composition, limit and
fingerprint checks, cancellation, lease expiry, Stop priority, idempotency, and hardware
isolation. WebSocket coverage also pins its read-only payload, 10 Hz timing,
slow-client timeout, terminal delivery, silent-socket watchdog, REST fallback, and
disconnect cleanup. The complete Stage 3 suite passed without hardware or camera access.

## Non-migrated evidence

Meshes, local calibration, serial/device settings, runtime poses/actions, ignored or
untracked files, controller classes, PyBullet GUI behavior, and any third-party SDK or
binary remain excluded. Numeric parameters are provisional characterization values and
must not be promoted to Real verification.
