# Safety

## Stage 1 safety case

Stage 1 is structurally incapable of commanding the robot:

- configuration defaults to `DRY_RUN`, rejects `real_motion_enabled=true`, and is frozen after validation;
- the FastAPI route table exposes only health and metadata reads;
- there is no hardware adapter, serial package, startup hook, motion service, or background device worker;
- the frontend has no motion controls and cannot enable Real mode;
- tests inspect the route surface and safe defaults.

The `serial_port` setting is recorded for future configuration shape only. It is never opened, scanned, or probed.

## Non-negotiable restrictions

Do not scan or write servos, auto-home, read/overwrite real calibration, import legacy hardware dependencies merely to test motion, expose raw device access, or add a developer bypass. Never commit port names, secrets, calibration, raw/multi-turn runtime state, or captured production poses/motions.

## Future real-motion gate

A future Stage may enable real motion only behind a single reviewed application safety entry point. Before dispatch it must establish at least:

1. explicit operator intent and Real-mode authorization;
2. active `RobotId` and matching V1/V2 product profile;
3. connected device identity and calibration fingerprint match;
4. complete keyed joints with finite values and correct units/ranges;
5. raw and multi-turn constraints derived from reviewed device data;
6. FK/IK reachability, residual/error, and model compatibility checks;
7. trajectory sampling, speed/acceleration/timing and workspace checks;
8. stop/emergency-stop behavior, target-loss stop for Vision, and observable execution state.

No API route or UI component may route around this entry point.

## Data trust

Legacy YAML, URDF, action, and calibration files are inputs to an audit, not automatically trusted profiles. The Stage 1 example limits and hardware mappings are unverified placeholders. Real-mode work is blocked until discrepancies in `legacy-variant-audit.md` are resolved with the exact hardware and calibration artifacts.

## Vision safety

Future target following must use a bounded command path, EMA/dead-zone policy, reachability and joint-limit checks, and an immediate stop-on-target-loss rule. A camera stream is perception input only; it does not authorize image/video capture or recording.
