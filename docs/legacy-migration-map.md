# Legacy migration map

## Source and evidence boundary

- Legacy repository: `https://github.com/39394480ke-sys/MOMO_RobotARM.git`
- Reference branch: `V2`
- Audited commit: `ff8bbda0c2222cb57951c7913f7f12f5777b98fa`
- Static audit begun: 2026-08-23; Stage 2 and completed Stage 3 characterization
  updated: 2026-08-24
- All Legacy paths and observations refer to that immutable commit.
- The Legacy checkout is read-only. No Legacy program or hardware dependency was run, and no serial discovery, Servo operation, Calibration operation, motion command, or camera access was performed.
- Local/untracked Calibration, serial configuration, runtime files, backups, logs, secrets, and media are excluded. The contents of the tracked backup artifact noted below were deliberately not read.

Dispositions used by the audits are decisions, not permission to run or copy code:

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

## Stage 3 kinematics and control decisions

Stage 3 re-opened only the pinned tracked kinematics/control evidence needed for its
approved Dry Run scope. The detailed evidence and numeric transcription are in
`kinematics-model-audit.md` and `legacy-kinematics-characterization.md`. No Legacy
program, simulator, mesh, driver, serial dependency, local Calibration, runtime file, or
untracked file was opened or executed.

| Legacy path/area | Observed contract/risk | Disposition | Stage 3 result / contract | Remaining gate |
|---|---|---|---|---|
| `URDF运动学仿真/` V1 URDF | Contains a prismatic J10 and six movable joints, contradicting the rail-less V1 product contract; mesh/asset provenance is unresolved. | `REWRITE_WITH_CHARACTERIZATION` | A mesh-free provisional V1 serial chain contains exactly J11-J15. The zero-position base-to-arm transform is folded into the rail-less chain rather than retaining a phantom degree of freedom. No URDF/STL is copied into runtime. | Independently measure V1 geometry, frames, signs, zeros, limits, TCP, FK references, and IK tolerance before any Real capability. |
| `URDF运动学仿真/` V2 URDF | Provides candidate J10-J15 axes/origins, but J10 units/limits are mixed elsewhere and physical authority/provenance is incomplete. | `REWRITE_WITH_CHARACTERIZATION` | A mesh-free provisional V2 chain records J10 as prismatic and uses explicit SI geometry. It is fingerprinted and `PROVISIONAL_DRY_RUN`. | Verify rail stroke/axis/origin, all link geometry, frames/TCP, limits and physical reference poses. |
| Legacy PyBullet FK/IK modules | Fixed six-value order, URDF/mesh coupling, PyBullet process state, J10 name-based conversion, and configurable approximate IK acceptance. | `REWRITE` | Deterministic serial-chain FK and bounded numerical DLS IK are independent of meshes and GUI state. Results report best solution, residuals, iterations and termination reason; approximation is not silently accepted. | Stage 3 characterization, command, and browser evidence passed; physical accuracy remains unverified. |
| `Web控制台/backend/controller_bridge.py` and `service.py` | Large facade combines lifecycle, kinematics, storage, motion, diagnostics and driver dispatch; routes can become coupled to concrete behavior. | `RETIRE_AS_ARCHITECTURE` | Kinematics, gateway, executor, Jog lease and transport are separate contracts/services. Every motion route enters the Motion Safety Gateway. | Route-isolation and dependency-direction tests pass; later sources must preserve this boundary. |
| `真实舵机控制/连续关节流_continuous_joint_stream.py` | Contains useful regular-update/cancellation intent but mutable worker state, sleep-driven timing, hardware coupling and no product Jog ownership/lease contract. | `REWRITE_WITH_CHARACTERIZATION` | Dry Run execution uses injected monotonic time and absolute deadlines. Hold Jog is owned by a renewable backend lease; expiry, Stop, disconnect, fault or network loss ends it. | Fake Clock/no-drift, TTL, cancellation, conflict and duplicate-Stop tests pass; Real execution remains deferred. |
| `真实舵机控制/安全检查_safety_checker.py` | Central limit intent is useful, but fixed dictionaries and hardware-oriented values are not complete command authorization. | `ADAPT` | Gateway preflight combines explicit Profile/Kinematics identity, exact joints/units, finite/logical/provisional dynamic/workspace checks, FK/IK, freshness, idempotency, conflict and cancellation. Raw-derived limits apply only with an exactly compatible Calibration; absence records a Dry Run logical-only fallback, while incompatibility rejects. | Provisional values remain Dry Run only; Real requires new verified evidence and Stage 8 gates. |
| Legacy Base/Tool Cartesian behavior | Base delta is applied in Base; Tool translation follows current TCP orientation and Tool rotation composes locally. | `REWRITE_WITH_CHARACTERIZATION` | Retained as separate pure composition rules using normalized XYZW quaternions and explicit mm/deg↔m/rad boundaries. | Deterministic unit/composition tests pass; no physical validation claim. |
| Legacy WebSocket/status loops | Per-client delivery lacks a product-level maximum rate and bounded queue contract. | `REWRITE` | Stage 3 is read-only status/progress/fault delivery with a fixed 10 Hz cap, no application queue, a one-second send timeout, disconnect cleanup, a silent-socket watchdog, and REST fallback. It cannot receive motion or raw control. | Slow-client/rate/terminal/disconnect/watchdog tests and live browser fallback/recovery evidence pass. |
| Legacy V1/V2 Profiles | V1 may fabricate J10; V2 J10 appears in angle-shaped ranges; joint-name branching obscures units. | Prior Stage 2 `REWRITE`; Stage 3 `ADAPT_AS_PROVENANCE_ONLY` | Kinematics membership is validated against explicit Profile `enabled_joints`; port helpers convert from declared type/unit rather than joint spelling. | Physical Profile and Kinematics must be independently cross-verified. |

### Stage 3 contracts derived from characterization

| Contract | New authority | Enforcement target |
|---|---|---|
| V1 has no kinematic rail | Product variant contract plus V1 provisional model | Exact ordered model/profile validation; J10 input rejects. |
| V2 J10 is prismatic | V2 Profile/model type and named unit boundary | Domain mm, adapter m; no angle/name heuristic. |
| Geometry identity is explicit | Deterministic Kinematics fingerprint | Command/FK/IK/preflight compatibility checks. |
| Provisional is not Real verified | `KinematicsVerificationStatus.PROVISIONAL_DRY_RUN` | Real Cartesian, Cartesian playback and Real Vision remain blocked. |
| Approximate IK is not reachability | Typed IK residuals and termination reason | Gateway dispatches only a successful within-tolerance result. |
| All motion has one owner | Motion Safety Gateway and command coordinator | One Active Motion/Jog; conflict/idempotency/Stop are observable. |
| Hold Jog needs a backend deadman | Renewable Jog lease | TTL expiry stops even when the browser loses the network. |
| Status streaming is not a control path | Read-only bounded WebSocket | No motion/raw request schema; REST remains fallback. |

## Stage 4 Library and action-import decisions

Stage 4 read only pinned tracked Git objects via `git show`: V1/V2 sample action JSON
shapes, their README, and action-library/recorder/common-alias source text. It did not
inspect a Legacy worktree's ignored/untracked/local data, operator exports, local
Calibration, runtime state, backup contents, serial configuration, or media, and it
executed nothing from Legacy. No tracked sample numeric motion/raw value was copied into
the product or tests; the converter and fixtures are independently written.

| Legacy path/area | Observed contract/risk | Disposition | Stage 4 result / contract | Remaining gate |
|---|---|---|---|---|
| `动作录制与回放增强/` action documents | Useful action/frame shape and canonical/short Joint aliases coexist with fixed-order arrays, `*_deg` naming, raw/multi-turn state, gripper fields, mutable files, and incomplete unit/provenance evidence. Tracked samples use `source` labels that are not reliable hardware variants. | `REWRITE_WITH_CHARACTERIZATION` for explicit import; recording/playback architecture remains retired/deferred | Offline `momo.tools.import_legacy_actions` accepts only one explicit JSON file/directory, defaults to report-only dry run, requires `arm_replay_sequence_v1` plus explicit V1/V2 `robot_variant`/`variant`, top-level exact `joint_order`, and `pose_count`; normalizes a closed Joint alias table; validates matching primary/replay targets and characterized timing fallbacks; requires exact Profile units; recomputes TCP; embeds schema `2.0.0` snapshots; and uses fresh UUIDs. `source` is safe-label provenance only; raw/gripper/TCP fields are reported but never silently repurposed. Global byte/action/keyframe/report budgets fail closed before conversion. | Final importer/root gates and independent audit pass; Stage 4 is GREEN. Unknown/ambiguous/incomplete formats remain report-quarantined; physical accuracy and playback remain unavailable. |
| `Web控制台/backend/action_composer.py` | Composition around mutable action/Pose references can make a saved Motion change when source data changes; monolithic service/filesystem coupling risks direct dispatch. | Formal entity rules `REWRITE`; architecture `RETIRE_AS_ARCHITECTURE` | Formal Motion still requires at least two keyframes and embeds full immutable snapshots. `source_pose_id` is provenance only; deleting/editing a Pose cannot alter a Motion. Stage 4 repositories cannot dispatch. | Incomplete authoring uses a separate Stage 6 `MotionDraft`; compiler/playback is Stage 5. |
| `Web控制台/backend/controller_bridge.py`, `service.py`, and storage endpoints | Client paths, display-name filenames, broad controller methods, and direct storage/driver access would violate new boundaries. | `RETIRE_AS_ARCHITECTURE`; bounded CRUD `REWRITE` | UUID-only server roots, four-MiB/schema/Pydantic validation, expected-revision CAS, atomic replace, corrupt quarantine/list continuation, and bounded root-file/entry/aggregate scans with structured capacity errors. Only compatible Library Goto submits `LIBRARY` + `MOVE_JOINTS` through the existing gateway. | Single backend writer process only; backup/restore and LAN authorization remain later gates. |
| Legacy recorded/user/local action data | May contain user motion, device-specific raw positions, identifiers, Calibration, secrets, or unsupported gripper state. | `EXCLUDE` | Only pinned tracked sample shapes/source text were characterized; no worktree ignored/untracked/local/runtime/user data or sample numeric motion/raw value was opened or copied. Tests use synthetic fixtures; importer provenance stores only basename, digest, bounded Legacy ID/source, and warnings. | Operator must explicitly select and review each import source; operational output remains ignored and outside Git. |

### Stage 4 contracts derived from characterization

| Contract | New authority | Enforcement target |
|---|---|---|
| Display names are not storage identity | Pose/Motion UUID | UUID filename/document equality; duplicate names allowed. |
| Old snapshots lack required compatibility evidence | Independent Pose/Motion schema `2.0.0` | Schema `1.0.0` is rejected/quarantined; no invented fingerprint/sequence/unit. |
| Saved Motion owns its playback data | Embedded `PoseSnapshot` values | Pose update/delete cannot cascade into a Motion. |
| Import is deliberate and offline | Explicit CLI `--source`; default dry run | No scan, browser path, Legacy code execution, or write without `--write`. |
| Aliases stop at the import boundary | Closed alias table then canonical Profile validation | V1 exactly J11-J15; V2 exactly J10-J15; collisions/missing/extra reject. |
| Misleading units are reported, not guessed | Profile domain units for characterized `*_deg`; explicit units for generic targets | V2 J10 remains mm; unknown units reject. |
| Repository is not a motion source | Storage ports plus Library application service | Only Goto constructs a command; gateway remains sole admission point. |

## Stage 5 trajectory and playback decisions

Stage 5 read only the three pinned tracked Legacy playback/interpolation modules listed
in its Stage report. It did not execute a player, load a Legacy Motion file, import a
controller, or inspect local runtime/Calibration/raw state.

| Legacy path/area | Observed risk | Disposition | Stage 5 result |
|---|---|---|---|
| `仿真控制系统/动作播放器_action_player.py` | Synchronous wall-clock sleeps and direct controller calls couple scheduling to hardware behavior. | `RETIRE_AS_ARCHITECTURE` | New playback uses an injected monotonic Clock, absolute deadlines, one high-level state sink, cancellation, and fresh shared-gateway validation. |
| `动作录制与回放增强/动作回放器_sequence_player.py` | Mutable pause/stop flags, file/controller ownership, ordered arrays, and raw/multi-turn replay do not preserve prepared-plan identity. | `REWRITE` | Motion revision compiles once to immutable unit-bearing samples and semantic digest; preview/play require the exact cached plan. Raw state is excluded. |
| `动作录制与回放增强/动作插值器_motion_interpolator.py` | Joint-array interpolation and J10 unit guessing cannot establish product Joint membership or true TCP-linear meaning. | `REWRITE_WITH_CHARACTERIZATION` | Profile-driven Joint maps support three easing functions; Cartesian-linear uses position interpolation, shortest quaternion SLERP, prior-seeded IK, and full intermediate checks. |
| Legacy unbounded/replay loop semantics | Drift, backlog bursts, endpoint jumps, or indefinite ownership could make Stop unreliable. | `RETIRE` | Absolute deadlines skip overdue samples; loops require closed trajectories, skip the duplicate boundary, cap at 100, and remain Stop-cancellable. |

No Legacy timing constant, sample, Servo value, controller call, file layout, or raw
mapping is product authority. Stage 5 synthetic tests establish software behavior only.

## Deferred Legacy areas

| Legacy area | Disposition | Reason and gate |
|---|---|---|
| Physical/asset reuse from `URDF运动学仿真/` | Stage 3 software behavior `REWRITE_WITH_CHARACTERIZATION`; physical/asset authority remains `DEFER` | Mesh-free provisional chains are sufficient only for Dry Run. URDF/STL redistribution and physical V1/V2 correctness remain blocked on provenance, measurement and field acceptance. |
| `动作录制与回放增强/` | Import slice `REWRITE_WITH_CHARACTERIZATION`; recording retired; playback architecture `REWRITE` | Stage 4 imports only validated explicit action JSON. Stage 5 independently compiles formal Motions into immutable digest-bound plans and provides bounded Dry Run scheduling; no Legacy player/raw state is reused. |
| `Web控制台/backend/service.py` | `RETIRE_AS_ARCHITECTURE` | More than one product area and multiple side effects are combined. Future capabilities become bounded application services with isolated construction and tests. |
| `Web控制台/backend/action_composer.py` | Formal Motion rules `REWRITE`; interactive composition `DEFER_TO_STAGE_6` | Stage 4 creates only valid formal Motions with embedded snapshots. Draft/timeline authoring cannot weaken that invariant. |
| `Web控制台/backend/app.py` and `schemas.py` | `REWRITE` by approved Stage | The new FastAPI app factory exposes approved lifecycle/diagnostic, Stage 3 motion, bounded Stage 4 Library, and digest-bound Stage 5 playback routes. Legacy AI, multi-arm, gripper, recording, arbitrary-path, client-sample, and raw schemas remain absent. |
| `视觉识别与跟随/` | `DEFER` | Vision is absent. A later provider must establish source freshness, target-loss inhibition, finite geometry, smoothing/dead-zone behavior, and model provenance without adding capture/recording. |
| `硬件与装配资料/` | `ADAPT` as review evidence | Treat mapping, wiring, and maintenance notes as verification checklists, never canonical data. Do not copy operator records, serials, images, or Calibration. |
| `THIRD_PARTY_NOTICES.md` and binary assets | `DEFER` pending provenance | Original source, exact license, attribution, modification, and redistribution rights must be recorded before any code/model/mesh/binary enters the new repository. |

## Data conversion rules

| Legacy input | Decision |
|---|---|
| V1 with exact canonical J11-J15 | Structurally compatible only; validate units, finiteness, ranges, provenance, and explicit Profile before conversion. |
| V1 with five known semantic aliases | Stage 4 importer maps `SHOULDER_PAN`, `SHOULDER_LIFT`, `ELBOW_FLEX`, `WRIST_FLEX`, and `WRIST_ROLL` to J11-J15 with a visible report/provenance boundary; aliases never persist as Joint IDs. |
| V1 with J10 | Reject or quarantine. Never crop J10, relabel as V2, or change the declared variant silently. |
| V2 with exact canonical J10-J15 | Structurally compatible only; importer requires J10 mm and J11-J15 deg through Profile-declared units. Characterized `*_deg` fields use those product units and emit a warning rather than treating J10 as an angle. |
| Missing, unknown, duplicate, non-finite, or ambiguous-unit joints | Reject; never zero-fill or ignore. |
| Legacy Calibration template | Non-production evidence only. Do not crop or copy numeric values; Stage 2 templates are newly constructed synthetic documents tied to new Profile Fingerprints. |
| Local Calibration, backup, serial settings, runtime state, logs, secrets, or media | Excluded. Do not read, copy, summarize, log, or commit. |
| Action with gripper or raw/multi-turn snapshot | Stage 4 reports ignored fields and never reinterprets them as a logical arm target. A valid exact logical Joint target is still required; raw-only input is rejected. |
| Action with Legacy TCP/Cartesian fields | Ignore with an explicit warning and recompute TCP from typed Joint state using the selected provisional MOMO model; never trust a mismatched source TCP. |
| Imported observation sequence | Store `state_sequence=null` because a coherent MOMO runtime observation cannot be established from offline Legacy data; never fabricate a live sequence. |
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
