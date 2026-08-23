# Legacy migration map

## Source and evidence boundary

- Legacy repository: `https://github.com/39394480ke-sys/MOMO_RobotARM.git`
- Reference branch: `V2`
- Audited commit: `ff8bbda0c2222cb57951c7913f7f12f5777b98fa`
- Static audit begun: 2026-08-23; Stage 2 characterization updated: 2026-08-24
- All Legacy paths and observations refer to that immutable commit.
- The Legacy checkout is read-only. No Legacy program or hardware dependency was run, and no serial discovery, Servo operation, Calibration operation, motion command, or camera access was performed.
- Local/untracked Calibration, serial configuration, runtime files, backups, logs, secrets, and media are excluded. The contents of the tracked backup artifact noted below were deliberately not read.

Dispositions used by the Stage 2 audit are decisions, not permission to run or copy code:

- `ADAPT`: retain a characterized rule or contract but express it through the new domain/application/ports/adapters boundaries.
- `ADAPT_AS_PROVENANCE_ONLY`: record selected evidence/source revision without treating the Legacy data as a product or hardware authority.
- `REWRITE_WITH_CHARACTERIZATION`: independently implement pure behavior from an observed contract and pin it with synthetic golden tests.
- `REWRITE`: implement the product behavior afresh because the Legacy implementation boundary is unsuitable.
- `DEFER`: record evidence but add no product implementation in this Stage.
- `DEFER_TO_STAGE_3`: reconsider only inside the reviewed Stage 3 scope.
- `RETIRE_FOR_STAGE_2`: deliberately omit the Legacy capability now; later reconsideration still requires a new decision.
- `RETIRE_AS_ARCHITECTURE`: do not migrate the class/module shape; only separately characterized rules may survive elsewhere.
- `OUT_OF_SCOPE`: do not migrate the product capability.

## Stage 2 robot-core decisions

| Legacy Path | Observed contract/risk | Disposition | Stage 2 result | Verification / remaining gate |
|---|---|---|---|---|
| `真实舵机控制/舵机驱动_servo_driver.py` | Feetech bus lifecycle and a Dry Run/fake boundary are mixed near hardware operations. Import/use could reach serial, ping/read/write, torque, or scan. | Feetech: `DEFER`; Dry Run behavior: `REWRITE` | Added only `adapters/hardware/dry_run_robot_driver.py`: in-memory state, no SDK/serial import, idempotent disconnect/Stop, no target-position method. | Hardware isolation tests must prove app creation, Connect, Stop, variant switch, and Calibration diagnostics never call a hardware spy. A real bus requires a separate approved Stage and optional dependency. |
| `真实舵机控制/角度映射_angle_mapper.py` | Preserves Home-relative multi-turn mapping and raw/logical round trips, but degree-shaped naming and fixed-joint assumptions cannot represent V2 J10 safely. | `REWRITE_WITH_CHARACTERIZATION` | `domain/hardware_mapping.py` uses `logical_value`, explicit Profile scale/resolution, Calibration direction/Home, intersected raw bounds, dynamic logical limits, and no joint-name unit branch. | Synthetic golden tests cover zero/Home, positive/negative direction, mm/deg, round trips, bounds, invalid inputs, and dynamic limits. Physical scale/sign/Home verification remains required. |
| `真实舵机控制/安全检查_safety_checker.py` | Central logical limits, raw-reachable limits, absolute raw bounds, and Calibration completeness are valuable; Legacy dictionaries and fixed constants are not. | `ADAPT` | Rules are split between immutable Profile/Calibration validation, `domain/safety.py`, mapping bounds, and application readiness diagnostics. | Stage 2 calculations are not command authorization. A future motion gateway must invoke complete Profile/Calibration/reachability/rate checks before dispatch. |
| `真实舵机控制/标定管理_calibration_manager.py` | Exact variant/template rejection and complete multi-turn reference data are useful; write/current-angle flows and local device data are unsafe for this Stage. | `ADAPT` | Added versioned `CalibrationDocument`, per-joint mode/direction/Home/phase/raw bounds, a read-only fixed-name repository, structured variant/Profile/joint/mapping status, and synthetic templates. Mapping status verifies Profile-matching Servo IDs/modes and overlapping raw bounds/Home. No write API exists. | Production Calibration lifecycle, device identity, independent review, and Real acceptance remain deferred. Stage 2 always blocks Real readiness. |
| `真实舵机控制/真实机械臂控制器_real_arm_controller.py` | Large controller combines connection, Calibration, mapping, safety, state, Home, movement, and hardware I/O. | `RETIRE_AS_ARCHITECTURE` | No class or direct replacement was copied. Lifecycle is a small application service over a driver port; pure rules live in the domain. | Real integration must be a new adapter behind one reviewed safety entry point and cannot revive a route-to-controller path. |
| `真实舵机控制/连续关节流_continuous_joint_stream.py` | Continuous scheduling, timeout, command coalescing, and Stop behavior are motion concerns. | `DEFER_TO_STAGE_3` | No stream, scheduler, worker, thread, Jog API, or UI control exists. | Stage 3 must decide rate limits, watchdog, cancellation, ownership, and Stop semantics before implementation. |
| `真实配置加载_real_config_loader.py` | Separates real configuration/Calibration concerns but carries device-local paths and Legacy policy. | `RETIRE_FOR_STAGE_2`; real configuration `DEFER` | New typed settings independently separate `ControlMode` from `HardwareAccessPolicy`; Stage 2 rejects Real and all non-disabled access. Profile, Calibration, and runtime directories have distinct server-owned repositories. | Never import Legacy local paths, port names, runtime data, or Calibration. Future Real configuration needs secret/local hygiene and operator authorization. |
| `机器人配置_profile_loader.py` | Global J10-J15 constants and missing-`enabled_joints` fallback fabricate J10 for V1. | `REWRITE` | Fixed-name YAML repository plus `RobotProfile` validation requires explicit ordered joints, exact definitions, types/units, unique Servo IDs, provenance, and variant contract. No six-joint fallback exists. | V1 must remain J11-J15; V2 J10-J15; malformed/unknown Profiles fail closed. Physical numbers remain unverified. |
| `控制桥接_common.py` | Contains unit/multi-turn constants and old five-axis aliases, but also a global J10-J15 order used across variants. | `RETIRE_AS_ARCHITECTURE`; isolated contracts `REWRITE` | Mapping names/units are explicit and Profile-driven. No alias map or global joint order entered the runtime domain. | Known aliases may exist only in a future audited Legacy importer with a visible conversion report. |
| `Web控制台/backend/controller_bridge.py` | Monolithic facade owns simulation/real lifecycle, FK/IK, poses, actions, diagnostics, filesystem behavior, and motion; it falls back to global joint order. | `RETIRE_AS_ARCHITECTURE` | Replaced only the Stage 2 slice with small Profile, Calibration, and Robot services. Routes receive those services and expose no movement. | Future use cases stay separate and must prove an API route cannot bypass the application safety boundary. |
| `Web控制台/backend/fleet.py` | Useful identity, per-runtime lock, exact variant/joint compatibility; unsafe fallback declares V1 with J10/rail. Coordination, recording, and exactly-two-arm workflows are entangled. | Single-runtime concept: `REWRITE`; Fleet product capability: `OUT_OF_SCOPE` | One `primary` runtime is owned by `RobotManager`; one async command lock serializes lifecycle and variant commands. No Fleet route, page, or `arm_a` naming exists. | Any future multi-robot product work requires a new product/safety decision; it is not implied by identity-aware interfaces. |
| `配置/robot_v1.yaml` | Declares V1 but contains J10, rail-oriented naming, and angle-shaped limits. | `ADAPT_AS_PROVENANCE_ONLY` | New V1 template is rail-less and exactly J11-J15. Source revision is recorded; numeric mapping inputs are synthetic/unverified Dry Run characterization, not production truth. | Obtain independent physical V1 Servo mapping, signs, limits, Home, and a true rail-less kinematics model. V1+J10 inputs fail closed. |
| `配置/robot_v2.yaml` | J10-J15 membership agrees with V2, but J10 is placed in a degree-shaped `[-360, 360]` map and physical values are not authoritative. | `ADAPT_AS_PROVENANCE_ONLY` | New V2 template types J10 as `PRISMATIC`/`mm` and J11-J15 as `REVOLUTE`/`deg`. The J10 range is synthetic and explicitly not Real-verified. | Verify physical rail stroke, scale, direction, Home/raw bounds, joint limits, TCP, and model before any Real use. |

The detailed mapping/safety behavior matrix and its intentional changes are recorded in `legacy-robot-core-characterization.md`. No Legacy controller, bridge, Feetech SDK source, local Calibration, serial setting, or runtime file was copied into Stage 2.

## Stage 2 product contracts derived from the audit

| Contract | New authority | Stage 2 enforcement |
|---|---|---|
| V1 is rail-less J11-J15 | `VARIANT_PRODUCT_CONTRACTS` and `RobotProfile` | Profile load, runtime status, Calibration joint-set match, UI ordering, and tests reject J10. |
| V2 is rail-equipped J10-J15 | Same | Profile requires J10 and its exact position in the enabled order. |
| J10 is linear mm; J11-J15 angular deg | Per-joint `JointDefinition` | Model validation, status units, frontend types, and mapping tests. |
| No implicit default Profile | Explicit Profile validation context and repository lookup | Pose/Motion validation never reads a global Profile; lifecycle resolves the configured variant through `ProfileService`. |
| Exact Profile identity matters | Deterministic Profile Fingerprint | Calibration compatibility and runtime restore require exact match. |
| Calibration templates are non-production | `template` plus structured readiness | Examples can support Dry Run diagnostics, including explicit mapping compatibility, but never Real readiness. |
| Stop remains reachable without fabricating physical success | `StopResponse` result contract | Dry Run returns `STOPPED` or `NOT_CONNECTED`; all responses state no hardware access. |
| Runtime history never reconnects a device | Runtime restore policy | Positions/sequence may restore; in-memory connection always starts disconnected. |

## Deferred Legacy areas

| Legacy area | Disposition | Reason and gate |
|---|---|---|
| `URDF运动学仿真/` | `DEFER_TO_STAGE_3` | Both Legacy models contain J10, so the V1 model contradicts the product. V2 remains a candidate only after source/license, axes, link/TCP, unit, reference FK, and IK residual verification. No URDF/STL was copied. |
| `动作录制与回放增强/` | `DEFER` | Stage 1 defined immutable embedded Pose Snapshot/Motion contracts, but Stage 2 adds no CRUD, trajectory, timeline, or playback. A future importer must use UUID identity, exact variant/joint/unit checks, explicit alias reports, and no silent gripper/raw loss. |
| `Web控制台/backend/service.py` | `RETIRE_AS_ARCHITECTURE` | More than one product area and multiple side effects are combined. Future capabilities become bounded application services with isolated construction and tests. |
| `Web控制台/backend/action_composer.py` | `DEFER` | Motion authoring is outside Stage 2. Future composition must embed full snapshots rather than dereference mutable source Pose files. |
| `Web控制台/backend/app.py` and `schemas.py` | `REWRITE` by approved Stage | The new FastAPI app factory and API schemas expose only approved Stage 2 lifecycle/diagnostic routes. Legacy AI, multi-arm, gripper, recording, motion, and raw schemas remain absent. |
| `视觉识别与跟随/` | `DEFER` | Vision is absent. A later provider must establish source freshness, target-loss inhibition, finite geometry, smoothing/dead-zone behavior, and model provenance without adding capture/recording. |
| `硬件与装配资料/` | `ADAPT` as review evidence | Treat mapping, wiring, and maintenance notes as verification checklists, never canonical data. Do not copy operator records, serials, images, or Calibration. |
| `THIRD_PARTY_NOTICES.md` and binary assets | `DEFER` pending provenance | Original source, exact license, attribution, modification, and redistribution rights must be recorded before any code/model/mesh/binary enters the new repository. |

## Data conversion rules

| Legacy input | Decision |
|---|---|
| V1 with exact canonical J11-J15 | Structurally compatible only; validate units, finiteness, ranges, provenance, and explicit Profile before conversion. |
| V1 with five known semantic aliases | Future importer may map to J11-J15 only with a visible inference/conversion report; aliases never persist in the domain. |
| V1 with J10 | Reject or quarantine. Never crop J10, relabel as V2, or change the declared variant silently. |
| V2 with exact canonical J10-J15 | Structurally compatible only; require J10 mm and J11-J15 deg, then Profile/Calibration checks. |
| Missing, unknown, duplicate, non-finite, or ambiguous-unit joints | Reject; never zero-fill or ignore. |
| Legacy Calibration template | Non-production evidence only. Do not crop or copy numeric values; Stage 2 templates are newly constructed synthetic documents tied to new Profile Fingerprints. |
| Local Calibration, backup, serial settings, runtime state, logs, secrets, or media | Excluded. Do not read, copy, summarize, log, or commit. |
| Action with gripper or raw/multi-turn snapshot | Future importer must report unsupported fields and route any retained safety data through a separately reviewed typed schema; never reinterpret raw as logical state. |
| URDF/STL or vision model | Blocked until provenance/license and technical verification are complete. |

The audited Git index contains a JSON artifact under `真实舵机控制/标定/标定备份_backups/` despite Legacy ignore/documentation intent. Its contents were not read. It has no target module and is permanently excluded from fixtures, excerpts, reports, and commits.

## First-version retirement register

The following remain `OUT_OF_SCOPE`: PyQt GUI, AI/natural-language/voice/STT control, gesture recognition, Cinematic Director, subject-lock direction, photo/video capture or recording, gripper, Teach Mode/torque-off drag teaching, PyBullet product UI, community, Camera Hub media management, and every multi-arm page/coordination/synchronization/recording workflow.

Identity-aware `RobotId` and `RobotManager` contracts do not weaken this retirement decision. Vision may later consume a live stream for target selection/following, but that does not create media-capture scope.

## Gates for any later migration

Every later migration change must include:

1. the pinned Legacy SHA and exact source path/function;
2. provenance/license clearance for every copied line or asset;
3. characterization tests using synthetic/offline data;
4. conversion into explicit `enabled_joints`, typed units, and versioned schemas;
5. deny-by-default review of variant, Profile/Calibration identity, logical/raw/multi-turn limits, non-finite data, timing, cancellation, and Stop;
6. proof that no serial port, local Calibration, runtime state, secret, captured media, or user-specific path entered Git;
7. confirmation that no retired or out-of-scope capability was introduced;
8. a scoped Stage decision, test/build/browser evidence, and updated safety documentation.
