# Safety

## Stage 2 safety case

Stage 2 can manage only an in-memory Dry Run robot. It is structurally unable to command a physical robot through the product path:

- settings require `control_mode=DRY_RUN`, `real_motion_enabled=false`, and `hardware_access_policy=DISABLED`;
- `READ_ONLY`, `FULL`, `REAL`, or enabled real motion causes startup validation to fail before a robot adapter is built;
- the only concrete robot adapter is `DryRunRobotDriver`, which imports no serial or Servo SDK and has no target-position method;
- the application factory performs no connect, scan, Home, calibration, torque, register I/O, or background-thread action;
- Connect accepts no request body, query string, or mode, and every command response states `hardware_accessed=false`;
- API routes depend on the lifecycle application service and never import a raw driver;
- the route inventory contains status, Profile/Calibration diagnostics, Dry Run connect/disconnect/Stop, and disconnected-only variant selection, but no motion endpoint;
- the frontend verifies the safe backend policy and provides no Jog, Home, Move, slider, Real switch, or fabricated telemetry.

`ControlMode.REAL` and `HardwareAccessPolicy.READ_ONLY/FULL` remain domain vocabulary for later reviewed work. Their existence is not current permission. Stage 2's deny-by-default settings gate is a Stage policy, not a claim that Real mode can never exist.

## Lifecycle safety

One `asyncio.Lock` serializes Connect, Disconnect, Stop, status/diagnostic reads, and variant changes. This prevents overlapping command transitions and prevents multiple drivers from being created by concurrent Connect calls.

- Connect is allowed only from `DISCONNECTED`; a duplicate is a structured conflict.
- Disconnect is idempotent when already disconnected and can recover a `FAULTED` Dry Run runtime to `DISCONNECTED`.
- Variant selection is allowed only while disconnected, creates a fresh in-memory driver, and never auto-connects.
- Dry Run Stop is callable while disconnected and returns `NOT_CONNECTED`; while connected it returns `STOPPED` without changing position.
- Driver failures enter `FAULTED`, preserve an operator-visible safe error summary, and do not leak a Python traceback.

The Stop result vocabulary also reserves `FAILED` and `SAFETY_STATE_UNCERTAIN`. A later real Stop must never report ordinary success when physical safety cannot be established. Stage 2 Stop makes no claim about a physical robot.

## Profile and Calibration trust

Only the active Profile's explicit `enabled_joints` determines membership. V1 is exactly `j11`-`j15`; V2 is exactly `j10`-`j15`, with `j10` in millimetres and the remaining joints in degrees. Fixed six-joint arrays and `arm_a` assumptions are prohibited.

Committed Profiles and Calibration documents are templates for Dry Run and diagnostics. `VERIFIED_FOR_DRY_RUN` means their shape is accepted by this software; it does not verify limits, scales, directions, raw bounds, Home, phase, Servo IDs, URDF, or physical reachability. A template Profile cannot claim `VERIFIED_FOR_REAL`, and a template Calibration cannot authorize Real use.

Calibration status requires exact variant, Profile Fingerprint, enabled-joint set, unique and Profile-matching Servo IDs, matching operating modes, valid/overlapping raw bounds and Home, valid direction/raw fields, and complete multi-turn Home/phase data before it can be structurally valid. Mapping compatibility is reported separately. Even a complete non-template document is reported with `real_readiness=BLOCKED_BY_STAGE_POLICY` in Stage 2. Missing Calibration does not prevent Dry Run startup.

## Mapping safety

Logical/raw mapping is pure, unit-neutral calculation. It uses the Profile's explicit unit/scale/resolution/mode/bounds and Calibration's direction/Home/bounds. It does not infer a conversion from `joint_id`. Inputs must be finite; scale and count resolution must be positive; directions must be `-1` or `1`; modes must match; raw bounds must be valid and overlap.

Effective logical reachability is the intersection of Profile logical limits and the raw interval reachable from calibrated Home. Both positive and negative direction are supported. Mapping utilities are not connected to an API command or driver write in Stage 2; characterization results are not authorization to move hardware.

## Runtime-state safety

Dry Run runtime state is untracked operational data. The configured directory is server-owned and cannot be selected by a client. Robot IDs are filename-constrained, path resolution must stay inside that directory, and atomic writes use a same-directory temporary file plus `fsync` and replace.

Restore fails closed on corrupt JSON, wrong schema, robot/variant/Profile mismatch, wrong joint or unit set, non-finite values, or out-of-range values. Rejected files are renamed to a timestamped quarantine filename and the robot returns to Profile Home in `DISCONNECTED`. A saved `CONNECTED` marker is diagnostic history only and never reconnects after restart.

Runtime documents contain logical Dry Run values and units only. They must never contain a serial port, secret, real calibration, device-local multi-turn state, or a claim about physical connection.

## Non-negotiable restrictions

Do not scan/read/write Servos, open a serial port, auto-connect, auto-Home, change torque, read or overwrite real Calibration, or introduce a debug bypass. Do not expose raw-device access, arbitrary Python execution, arbitrary file access, or a raw-servo HTTP/WebSocket endpoint. Do not commit ports, secrets, local Calibration, runtime state, captured production Poses/Motions, or captured media.

No API route may ever import a concrete hardware bus or driver. Future physical operations must pass through one reviewed application safety entry point; lifecycle diagnostics alone are not such an entry point.

## Future motion gate

Stage 3 is future work. Before any Dry Run FK, IK, Joint Jog, Cartesian Jog, Move Pose, Home, or motion workflow is exposed, that Stage must define command intent, keyed joint/unit validation, reachability/error contracts, cancellation and Stop semantics, rate/timing limits, and tests proving routes cannot bypass its application boundary. None of these operations exists in Stage 2.

A later Real-motion Stage has additional gates:

1. explicit operator intent and separate Real authorization;
2. an active `RobotId` and physically verified non-template Profile;
3. positively identified device plus exact variant/Profile/Calibration match;
4. complete keyed targets with finite values and correct units;
5. reviewed Servo mapping, logical/raw/multi-turn limits, and current state;
6. FK/IK model compatibility, reachability, and residual/error checks;
7. sampled trajectory, speed, acceleration, timing, and workspace checks;
8. observable execution, cancellation, and verified Stop/emergency behavior;
9. for Vision only, freshness validation and immediate target-loss motion inhibition.

No route, UI control, script, or adapter may bypass that future entry point.

## Legacy and evidence boundary

Legacy commit `ff8bbda0c2222cb57951c7913f7f12f5777b98fa` is read-only evidence. Its local Calibration, serial settings, runtime files, backups, and untracked data are excluded. Numeric examples in MOMO Studio are synthetic characterization data and remain unverified for physical use. Legacy URDF/STL and third-party vision assets remain excluded until provenance, license, and hardware-model verification are recorded.

Stage 2 safety evidence must truthfully support all of these statements:

```text
No serial port was opened.
No servo scan was performed.
No servo register was read.
No servo register was written.
No torque command was sent.
No real calibration was read or modified.
No motion command was exposed.
No physical robot was moved.
```
