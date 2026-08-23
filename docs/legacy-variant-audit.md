# Legacy V1/V2 variant audit

## Audit identity and method

- Legacy repository: `https://github.com/39394480ke-sys/MOMO_RobotARM.git`
- Branch: `V2`
- Audited commit: `ff8bbda0c2222cb57951c7913f7f12f5777b98fa`
- All evidence references below are relative to that immutable commit.
- Inspection was static and read only. No Legacy Python code or dependency was run. No serial device, calibration operation, actuator command, camera or real robot was accessed.
- Local/runtime calibration contents were excluded. Only tracked example-file structure and Git-index presence were inspected; no calibration number was transcribed.

## Product contract (authoritative for MOMO Studio)

The product contract is not inferred from Legacy file names, array lengths, URDF contents or physical assumptions. It is explicit:

| Variant | `has_linear_rail` | `enabled_joints` | Required joint semantics |
|---|---:|---|---|
| V1 | `false` | `j11`, `j12`, `j13`, `j14`, `j15` | Five enabled revolute joints, each with an explicit angular unit such as `deg`; J10 is not enabled. |
| V2 | `true` | `j10`, `j11`, `j12`, `j13`, `j14`, `j15` | J10 is prismatic with an explicit linear unit such as `mm`; J11-J15 are revolute with explicit angular units such as `deg`. |

Consequences fixed in Stage 1:

- Variant names describe physical product models, not software versions.
- `RobotProfile.enabled_joints` is authoritative. No domain/API/storage code may assume `j10-j15`, six joints, or all-angle units.
- Stage 1 profile values are safe examples, not production calibration. Legacy limits, scales, homes and hardware mappings remain unverified.
- UI boundaries use mm/deg; a later kinematics adapter uses m/rad. Conversion must be explicit and tested at that boundary.

## Evidence matrix

| Source | V1 fact at Legacy SHA | V2 fact at Legacy SHA | Contract status | Required migration treatment |
|---|---|---|---|---|
| `Web控制台/Web配置.yaml:94-121` | Explicit device is `variant: V1`, enables J11-J15 and sets `linear_rail: false`. | Explicit device is `variant: V2`, enables J10-J15 and sets `linear_rail: true`. | Matches | Preserve this explicit set/capability relationship as domain data, not Web-only configuration. Do not migrate the dual-arm device setup itself. |
| `Web控制台/README_Web控制台.md:55-71` | Documents V1 as rail-less J11-J15 and states hardware access will not scan/read/write J10. | Documents V2 as rail-equipped J10-J15. | Matches | Preserve as a safety expectation and test it at the driver boundary. |
| `Web控制台/测试脚本_test/test_多机械臂协同.py:115-136` | Test proves runtime V1 `joint_order` and driver keys exclude J10. | Not the focus of this test; paired fixtures use J10-J15 for V2 at `:193-194`. | Matches in explicit Web runtime | Recreate as single-active-robot profile/driver contract tests; retire multi-arm coordination behavior. |
| `配置/robot_v1.yaml:1-30` | Declares V1, but its name contains `with_linear_rail`; kinematics scales, hardware scales and limits all contain J10-J15. | N/A | Contradicts | Never load as a canonical MOMO Studio V1 profile. Retain only as historical evidence pending physical V1 verification. |
| `配置/robot_v2.yaml:1-33` | N/A | Declares V2 and contains J10-J15; target frame is `Link_7`; J12/J13 are marked raw-reachable. | Joint set matches; typing/ranges incomplete | Re-enter only verified facts into a typed profile. The generic `[-360, 360]` J10 range must not become a linear-mm production limit. |
| `机器人配置_profile_loader.py:12-39,69-113` | Global `JOINT_NAMES` is J10-J15 and validation requires every kinematics scale, hardware scale and limit map to contain that complete set for either variant. | Same forced set. | V1 contradicts; V2 set matches | Replace with validation against each profile's explicit `enabled_joints` and per-joint definitions. |
| `机器人配置_profile_loader.py:148-165` | `enabled_joints` is optional; absent values fall back to `joint_order` or the six-joint global. | Same. | Unsafe default for V1 | Require `enabled_joints`; no implicit six-joint fallback. |
| `配置/测试脚本_test/test_robot_profiles.py:41-67,425-434` | Legacy profile tests deliberately encode V1 as J10-J15 and expect six-joint V1 action/kinematics behavior. | Encodes V2 as J10-J15. | V1 test oracle contradicts product contract | Do not port these assertions. Replace them with Stage 1 contract tests: V1 J11-J15 only, V2 J10-J15. |
| `控制桥接_common.py:21-22,69-80` | Global order/multi-turn sets contain J10-J15; aliases map older five-axis names onto J11-J15. | Same globals happen to match V2 membership. | V1 contradicts; global design invalid | Remove global joint-set authority. Alias handling, if retained, belongs only in an explicit Legacy importer. |
| `URDF运动学仿真/urdf/v1/soarmoce_urdf.urdf:101-141` | Contains prismatic J10 followed by revolute J11-J15 and terminates at `Link_6`. | N/A | Contradicts V1 rail-less contract | Do not copy or reference it as the production V1 model. Obtain/build/verify a true no-rail V1 URDF and TCP mapping later. |
| `URDF运动学仿真/urdf/v2/soarmoce_urdf.urdf:101-141` | N/A | Contains prismatic J10 followed by revolute J11-J15 and terminates at `Link_7`. | Structurally matches | Still requires provenance/license clearance and physical FK/axis/limit verification before reuse. |
| `URDF运动学仿真/运动学模型_kinematics_model.py:53-71,211-249` | SDK joint list is globally fixed at six; units correctly distinguish J10 mm from J11-J15 deg, but a V1 selection still receives the six-joint SDK list. | Six-joint/unit shape matches V2. | V1 contradicts; useful unit evidence | Make the adapter consume `RobotProfile.enabled_joints` and definitions. Keep conversion functions explicit; never use array position as joint identity. |
| `URDF运动学仿真/正运动学_fk.py:12-18,39-44` and `逆运动学_ik.py:12-20,73-80` | CLI requires exactly six values regardless of selected profile. | Six inputs match V2 membership. | V1 contradicts | New FK/IK port accepts a joint-ID map validated against the active profile. |
| `真实舵机控制/真实配置.yaml:19-121` | No canonical V1 instance is defined here. | Canonical real config declares V2, `dof: 6`, J10-J15 and all six as multi-turn. J10's annotation calls its UI/Web unit mm. | V2 membership/units match, values unverified | Treat as Legacy implementation evidence only. No port, calibration or protocol value is copied during Stage 1. |
| `真实舵机控制/标定/v1.example.json:2-10,18-58` | `_meta.robot_variant` is V1, yet the top-level template contains J10-J15 and a gripper entry. | N/A | Contradicts V1; gripper retired | Do not silently drop J10 or copy values. A later importer must quarantine this shape or require an explicit, audited conversion. Create a new V1 template from the new profile only after hardware verification. |
| `真实舵机控制/标定/v2.example.json:2-10,18-58` | N/A | `_meta.robot_variant` is V2 and the template contains J10-J15 plus gripper. | Main joint set matches; gripper retired | Import structure only after schema/provenance review; omit no field silently. Production calibration remains local and fingerprinted. |
| `真实舵机控制/标定说明.md:8-17,29-50` | Says real calibration is local and variant must match, but its V2 discussion refers to retaining a prior V1 J10 calibration at `:38`, reinforcing a historical rail-equipped V1 concept. | Requires V2 J10 and exact calibration variant match. | Historical V1 contradiction; safety rule useful | Preserve exact-variant/template rejection; do not infer today's V1 mechanics from historical calibration prose. |
| `动作录制与回放增强/动作库/V1演示.json:2-13` | Current example declares V1 and J11-J15. | N/A | Matches | Eligible only as an importer fixture after removing values/raw/gripper; not production sample data. |
| `动作录制与回放增强/动作库/v2 演示.json:2-14` | N/A | Declares V2 and J10-J15. | Matches membership | Same: use structural fixtures only after explicit conversion; never copy recorded hardware snapshots blindly. |
| `动作录制与回放增强/动作库_示例备份_不要真实运行/示例_录制动作.json:2-13` | Declares V1 but uses `shoulder_pan`, `shoulder_lift`, `elbow_flex`, `wrist_flex`, `wrist_roll` rather than canonical IDs. Alias map in `运动学配置.yaml:14-25` maps them to J11-J15. | N/A | Semantically five-axis but noncanonical | Legacy importer may map aliases only with a visible conversion report; domain/storage always uses canonical joint IDs. |
| `Web控制台/backend/fleet.py:1004-1038` | If explicit devices are absent, fallback declares `variant: V1` with full `JOINT_ORDER` and `linear_rail: true`; explicit-device validation does correctly enforce rail iff J10 is enabled. | Explicit device configuration is coherent. | Fallback contradicts; validator useful | Eliminate fallback. Variant selection must resolve to an explicit validated profile. |
| `Web控制台/backend/schemas.py:146-158,232-250` | Map-shaped Move Joints is profile-capable, but FK requires at least six list entries and mode includes `sim`. | Six-entry FK happens to fit V2. | V1/schema semantics contradict | Domain uses joint-ID maps; `SIM` is not a product control mode. UI units are explicit and kinematics conversion is at the adapter boundary. |
| `硬件与装配资料/舵机ID与关节对应表.md:3-20` | Delegates V1 authority to `robot_v1.yaml`, so it inherits that file's unresolved contradiction. | Documents J10 as linear mm and J11-J15 as angular deg, with J10-J15 main chain. | V1 unresolved; V2 matches membership/units | Treat as a verification checklist, not canonical profile data. |
| `THIRD_PARTY_NOTICES.md:5-15` and `URDF运动学仿真/README_URDF运动学仿真.md:14-41` | V1 URDF/meshes are identified as third-party SOARM MOCE material. | Same for V2. | Provenance unresolved | No URDF/STL copied. Verify original source, license, attribution and redistribution/modification rights first. |

## Joint-set summary

| Evidence Layer | V1 observed set | V2 observed set | Interpretation |
|---|---|---|---|
| MOMO Studio product contract | J11-J15 | J10-J15 | Authoritative. |
| Explicit Legacy Web devices | J11-J15 | J10-J15 | Agrees with the product contract. |
| Legacy root profiles and profile loader | J10-J15 | J10-J15 | Root cause of the V1 contradiction. |
| Legacy URDF files | J10-J15, including prismatic J10 | J10-J15, including prismatic J10 | V1 model is not a rail-less product model. |
| Legacy calibration templates | J10-J15 plus gripper | J10-J15 plus gripper | V1 conflict; gripper is outside the first-version scope for both. |
| Current Legacy action examples | J11-J15 | J10-J15 | Membership agrees, but schemas/raw/gripper data do not. |
| Older Legacy V1 action examples | Five aliases mapping to J11-J15 | N/A | Requires an importer; never becomes a domain naming convention. |
| Legacy fixed global constants | J10-J15 | J10-J15 | Cannot be the new domain authority. |

## Contradictions and migration decisions

### VA-01 — V1 rail membership has two competing Legacy truths

The explicit Web device contract says V1 is rail-less J11-J15, while the root V1 profile, loader tests, global constants and V1 URDF include J10. MOMO Studio resolves this in favor of the stated product contract: V1 enables only J11-J15 and `has_linear_rail` is false.

No Legacy file is edited to create the appearance of consistency. A later V1 adapter must fail closed if a profile, action or calibration declares V1 with J10 until an explicit migration decision is recorded.

### VA-02 — The V1 profile name itself claims a rail

`配置/robot_v1.yaml:2-6` uses the name `soarmmoce_with_linear_rail` and a V1 URDF that contains J10. The name is historical evidence, not a new display name or hardware fact. It must not leak into MOMO Studio branding or identifiers.

### VA-03 — The V1 URDF is not compatible with the new V1 contract

The V1 URDF contains a prismatic J10. Simply hiding J10 in the UI would leave a different kinematic chain and frame topology. MOMO Studio therefore records only an `urdf_reference` placeholder in Stage 1; a real no-rail model, axes and TCP must be obtained or built and verified later.

### VA-04 — V1 calibration examples contain a J10 entry

The V1 example is marked as a template and includes J10-J15. Values were not read into this audit. Do not crop it to J11-J15 and call the result valid: calibration is physical-device state, and silent cropping would destroy provenance. A future conversion must either reject/quarantine it or require an operator-reviewed mapping and produce a new calibration fingerprint.

### VA-05 — Fixed six-joint code can silently fabricate V1 data

Global `JOINT_ORDER`, list normalization and six-value FK/IK can fill or assume J10. The new domain rejects missing enabled joints and unknown joints based on the selected profile. Compatibility inference from an array length is allowed only inside a narrowly scoped Legacy importer and must report that it inferred rather than observed the variant.

### VA-06 — J10 type/unit/range are conflated in Legacy configuration

The kinematics layer identifies J10 as mm and converts it to meters, and URDF identifies it as prismatic. Yet both root profiles put J10 in an angle-shaped `joint_limits` map with `[-360, 360]`. MOMO Studio models joint type and `domain_unit` explicitly. No static J10 limit, home, scale or stroke becomes production data until verified against the physical V2 and its calibration/raw constraints.

### VA-07 — Action history spans two joint namespaces and retired fields

Current actions use canonical J IDs; older V1 actions use five semantic aliases. Audited action JSON also carries gripper and hardware snapshot fields. The new importer must:

1. accept canonical V1 only when the exact set is J11-J15;
2. accept canonical V2 only when the exact set is J10-J15;
3. map the known five V1 aliases to J11-J15 only in an explicit conversion report;
4. reject/quarantine V1+J10 rather than silently dropping J10;
5. reject missing/duplicate/non-finite joints and ambiguous units;
6. embed complete Pose Snapshots into Motion keyframes;
7. handle retired gripper data explicitly and never migrate it into the first-version domain;
8. preserve safety-relevant multi-turn data only in a typed optional hardware snapshot after separate review.

### VA-08 — Local calibration hygiene is inconsistent in the Legacy Git index

Legacy documentation and `.gitignore` say local calibration/backups must not be committed, but the audited tree tracks one JSON under `真实舵机控制/标定/标定备份_backups/`. Its contents were not read. This is a provenance/privacy warning: the artifact is retired and excluded from every copy, report excerpt, fixture and commit.

### VA-09 — Asset licensing is not established

The Legacy notice calls SOARM MOCE URDF/STL third-party and says licensing/attribution must be verified. The audited root contains no `LICENSE` or `COPYING` file, and bundled YuNet/MediaPipe model files have no source/license record in the notice. No such asset is present in MOMO Studio Stage 1.

## Explicit conversion rules

| Legacy input | Stage 1 classification | Later conversion rule |
|---|---|---|
| V1 + exact J11-J15 canonical IDs | Structurally compatible | Validate units, finiteness, ranges and provenance against an explicit V1 profile; convert to typed joint map. |
| V1 + five known semantic aliases | Legacy-compatible only | Map aliases to J11-J15 in a dedicated importer and emit a conversion report; never persist aliases in domain data. |
| V1 + J10 present | Quarantine | Reject by default. Do not silently crop, reinterpret as V2 or change the declared variant. Requires an operator-reviewed source/hardware decision. |
| V2 + exact J10-J15 | Structurally compatible | Validate J10 as linear mm at UI/domain boundary, J11-J15 as angular deg, then profile/range/calibration compatibility. |
| Any variant with missing/unknown/duplicate joints | Invalid | Reject; no zero fill or unknown-field ignore. |
| Calibration template | Non-production | Templates never authorize real motion. Production calibration remains local, exact-variant, device/profile matched and fingerprinted. |
| Action with gripper | First-version field retired | Report the unsupported field; do not add a gripper domain module. No silent loss in an automated migration. |
| Action containing raw/multi-turn snapshot | Safety-sensitive | Import only into a typed optional hardware snapshot after hardware schema and replay-safety review; never treat raw as logical joint state. |
| URDF/STL or vision model binary | Blocked on provenance | Do not copy until original source, license, attribution and redistribution/modification rights are recorded. |

## What is resolved and what remains open

| Topic | Stage 1 status | Later evidence required |
|---|---|---|
| Product joint membership | Resolved: V1 J11-J15; V2 J10-J15 | Driver and adapter conformance tests. |
| Rail capability | Resolved: V1 false; V2 true | Physical V2 stroke/home/range verification. |
| Joint identity representation | Resolved: joint-ID maps validated by `enabled_joints` | Import fixtures for every supported Legacy shape. |
| Joint type/unit | Resolved semantically: V2 J10 prismatic/mm; revolute joints deg at UI/domain boundary | Exact per-joint limits, signs, scales and homes. |
| V1 URDF and TCP | Unresolved; Legacy V1 asset conflicts | Verified no-rail V1 model, link chain, axes and TCP reference. |
| V2 URDF and TCP | Candidate only | Provenance/license plus physical FK reference poses and IK residual tests. |
| Calibration migration | Unresolved and intentionally deferred | Versioned calibration schema, profile/device fingerprint, local-only storage and hardware-approved validation. |
| Legacy motion migration | Unresolved and intentionally deferred | Versioned importer, snapshot semantics, unit/range checks, multi-turn replay policy and golden tests. |
| Third-party assets | Blocked | Original source/license/attribution/redistribution records. |

## Required regression tests for future stages

- V1 profile accepts exactly J11-J15 and rejects J10.
- V2 profile accepts exactly J10-J15; J10 is prismatic/mm and the other joints are revolute/deg.
- Every joint state rejects missing, unknown, duplicate and non-finite values using the selected profile.
- V1 driver discovery/read/write receives only J11-J15; it never scans J10.
- V2 J10 conversion is mm to m only at the kinematics boundary and round-trips within tolerance.
- A V1+J10 Legacy payload is rejected or quarantined, never silently cropped.
- Alias conversion is confined to the Legacy importer and produces canonical J11-J15 output plus an audit report.
- Calibration template, missing variant, variant mismatch and fingerprint mismatch all deny real motion.
- Motion import preserves immutable embedded snapshots and rejects incompatible variant/profile/joint sets.
- Lost, invalid, stale or repeated vision frames inhibit further motion immediately and transition the follow workflow to a safe hold/stop.
