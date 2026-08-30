# API audit

Audit refreshed: 2026-08-30. Branch: `codex/9da6853-system-audit-fixes`. Starting commit:
`9da68536d26eb2d37c4f9acbed8f30dee57843e4`.

This is a static inventory of the versioned HTTP/WebSocket surface, its product caller,
application owner, authorization boundary, Stage provenance, and disposition. It does
not claim physical verification. The count and tables must be regenerated after the
final route wiring and before the final report is marked complete.

The current generated OpenAPI contains **128 HTTP operations over 113 unique `/api/v1`
paths**, plus one read-only Robot WebSocket. The earlier Stage 8 baseline was 93
operations over 79 paths; later additions include commissioning, Kinematics verification,
staged acceptance, camera-preview, and supervised runtime-mode operations.

## Authorization legend

| Code | Boundary |
|---|---|
| R | `authorize_rest_request`; local policy or authenticated LAN browser session |
| C | `authorize_control_request`; R plus bounded control-rate admission |
| P | `authorize_priority_stop_request`; authenticated Stop path not blocked by the normal control bucket |
| V | `authorize_vision_request`; Vision surface authentication |
| WS | `authorize_websocket`, with ongoing publish-time reauthorization |
| O-RO | HttpOnly/legacy-header Operator Session with `COMMISSIONING_READ_ONLY` purpose and required read/Calibration scope |
| O-CM | Operator Session with `COMMISSIONING_MOTION_TEST` and `COMMISSIONING_SINGLE_JOINT_TEST` scope |
| O-RJ / O-RC / O-RP / O-RV | `REAL_MOTION` session with Joint, Cartesian, Playback, or Vision scope respectively |

R/C/P/V/WS protect the transport/deployment surface. Operator purpose/scope is a second,
independent hardware-authority check in the application service. Dry Run operations do
not manufacture a Real Operator Session.

## Stage 1–3 inventory

| Route(s) | Frontend caller | Service | Auth / scope | Stage | Status |
|---|---|---|---|---:|---|
| `GET /health` | `getBootstrapData` → `RuntimeStatusProvider` | Settings projection | R | 1 | Retain; active bootstrap |
| `GET /meta` | `getBootstrapData` → `RuntimeStatusProvider` | Settings/release projection | R | 1 | Retain; active bootstrap |
| `GET /meta/product-scope` | None in product UI | Settings product-scope projection | R | 1 | Retain; documented/tested external metadata |
| `GET /runtime/mode`, `POST /runtime/mode` | Settings runtime selector | local mode supervisor | R; POST is loopback-only and disconnected-only, REAL also requires physical E-stop/workspace confirmations | 8 | Retain; persists only the ignored mode selection and gracefully rebuilds the composition; never connects or moves hardware |
| `GET /robot`, `GET /robot/profile`, `GET /robot/diagnostics` | `getBootstrapData` → `RuntimeStatusProvider` | `RobotApplicationService` | R | 2 | Retain; active bootstrap/status |
| `POST /robot/connect`, `POST /robot/disconnect` | `RuntimeStatusProvider` | `RobotApplicationService` / motion lifecycle | R+C | 2 | Retain; Dry Run lifecycle, not Device commissioning |
| `POST /robot/stop` | `RuntimeStatusProvider` | motion lifecycle Stop | R+P | 2 | Retain; global Robot lifecycle Stop |
| `PUT /robot/variant` | `RuntimeStatusProvider` | `RobotApplicationService` | R+C | 2 | Retain; disconnected-only variant change |
| `GET /calibration/status` | `getBootstrapData` → `RuntimeStatusProvider` | Calibration diagnostics service | R | 2 | Retain; active bootstrap, never writes Calibration |
| `GET /robot/fk` | `useForwardKinematics` | `KinematicsApplicationService` | R | 3 | Retain; diagnostic computation |
| `POST /kinematics/ik` | `useInverseKinematics` | `KinematicsApplicationService` | R | 3 | Retain; diagnostic solution only |
| `POST /motion/joints`, `POST /motion/jog-step`, `POST /motion/home` | `ControlPage` / `useMotionCommands` | `MotionApplicationService` → `MotionSafetyGateway` | R+C; REAL adds O-RJ | 3 | Retain; reviewed high-level gateway |
| `POST /motion/cartesian-jog`, `POST /motion/pose` | `useMotionCommands` | `MotionApplicationService` → `MotionSafetyGateway` | R+C; REAL adds O-RC | 3 | Retain; no raw target or driver access |
| `POST /motion/jog/start`, `POST /motion/jog/{session_id}/heartbeat` | `useDeadmanJog` | `JogApplicationService` → gateway | R+C; REAL adds O-RJ | 3 | Retain; renewable backend Jog lease |
| `POST /motion/jog/{session_id}/stop` | `useDeadmanJog` | `JogApplicationService` | R+P | 3 | Retain; idempotent lease Stop |
| `GET /motion/commands/{command_id}` | Control/Studio motion hooks | `MotionApplicationService` | R | 3 | Retain; bounded status polling |
| `POST /motion/stop` | Control/Studio motion hooks | `MotionApplicationService` | R+P | 3 | Retain; ordinary motion-slot Stop |
| `WS /api/v1/ws/robot` | `RuntimeStatusProvider` | Robot/Kinematics/motion/playback observers | WS | 3 | Retain; canonical versioned server-to-client read-only path, no command frames |

## Stage 4–7 inventory

| Route(s) | Frontend caller | Service | Auth / scope | Stage | Status |
|---|---|---|---|---:|---|
| `GET /poses`, `GET /poses/{pose_id}` | `LibraryPage`, Studio pose hooks | `LibraryApplicationService` | R | 4 | Retain; active bounded reads |
| `POST /poses/capture` | `LibraryPage` | `LibraryApplicationService` | R | 4 | Retain; coherent capture, no device path |
| `POST /poses` | API client only; no product caller | `LibraryApplicationService` | R | 4 | Retain; documented explicit-snapshot creation and tests |
| `PATCH /poses/{pose_id}` | API client only; no product caller | `LibraryApplicationService` | R | 4 | Retain; documented revision-CAS edit and tests |
| `DELETE /poses/{pose_id}`, `POST /poses/{pose_id}/duplicate` | `LibraryPage` | `LibraryApplicationService` | R | 4 | Retain; active persistence operations |
| `POST /poses/{pose_id}/goto` | `LibraryPage` | Library → motion service → gateway | R+C; REAL adds O-RJ | 4 | Retain; persisted-snapshot Goto |
| `GET /motions`, `GET /motions/{motion_id}`, `POST /motions` | `LibraryPage`, Studio hooks | `LibraryApplicationService` | R | 4 | Retain; active bounded entity flow |
| `PATCH /motions/{motion_id}` | API client only; no product caller | `LibraryApplicationService` | R | 4 | Retain; documented revision-CAS external edit and conflict tests |
| `DELETE /motions/{motion_id}`, `POST /motions/{motion_id}/duplicate` | `LibraryPage` | `LibraryApplicationService` | R | 4 | Retain; active persistence operations |
| `POST /motions/{motion_id}/preflight` | Library/Studio motion hooks | `TrajectoryApplicationService` | R | 5 | Retain; produces reviewed prepared plan, does not execute |
| `POST /motions/{motion_id}/play` | Library/Studio motion hooks | `TrajectoryApplicationService` → gateway/playback | R+C; REAL requires O-RP and Cartesian plans additionally O-RC | 5 | Retain; digest/revision-bound execution |
| `GET /playback` | Library/Studio motion hooks | `TrajectoryApplicationService` | R | 5 | Retain; bounded status |
| `POST /playback/pause`, `POST /playback/resume`, `PUT /playback/rate`, `PUT /playback/loop` | Library/Studio motion hooks | `PlaybackService` | R+C; REAL adds O-RP | 5 | Retain; active playback ownership |
| `POST /playback/stop` | Library/Studio motion hooks | `PlaybackService` | R+P | 5 | Retain; playback-owner Stop |
| `GET /trajectory/{digest}/preview` | `LibraryPage` | `TrajectoryApplicationService` | R | 5 | Retain; bounded non-executable transport preview |
| `GET /studio/drafts`, `POST /studio/drafts`, `POST /studio/drafts/from-motion/{motion_id}` | Studio draft hook | `StudioApplicationService` | R | 6 | Retain; active Draft entry flow |
| `GET /studio/drafts/{draft_id}`, `PUT /studio/drafts/{draft_id}`, `POST /studio/drafts/{draft_id}/fork` | Studio draft hook | `StudioApplicationService` | R | 6 | Retain; active UUID/revision-CAS Draft flow |
| `DELETE /studio/drafts/{draft_id}` | API client only; no product caller | `StudioApplicationService` | R | 6 | Retain; documented Draft cleanup and tests |
| `POST /studio/drafts/{draft_id}/save-intent/abandon` | Studio draft hook | `StudioApplicationService` | R | 6 | Retain; exact recovery release |
| `POST /studio/drafts/{draft_id}/validate`, `POST /studio/drafts/{draft_id}/compile` | Studio draft hook | `StudioApplicationService` | R | 6 | Retain; compile is explicitly non-executable |
| `POST /studio/drafts/{draft_id}/save`, `POST /studio/drafts/{draft_id}/save-as` | Studio draft hook | `StudioFormalSaveCoordinator` | R | 6 | Retain; active transactional persistence |
| `POST /studio/capture` | Studio workspace hook | `StudioRobotActions` | R | 6 | Retain; coherent snapshot only |
| `POST /studio/drafts/{draft_id}/keyframes/{keyframe_id}/goto` | Studio motion hook | `StudioRobotActions` → motion gateway | R+C; REAL adds O-RJ | 6 | Retain; persisted-keyframe Goto |
| `GET /vision/capabilities`, `GET /vision/status` | Vision workspace hook | `VisionApplicationService` | V | 7 | Retain; active metadata/status |
| `GET /vision/stream` | `VisionCanvas` image stream | `VisionApplicationService` | V, ongoing frame reauth | 7 | Retain; active latest-value no-store stream |
| `GET /vision/frame` | URL exported, no rendered product caller | `VisionApplicationService` | V | 7 | Retain; documented exact-frame fallback and tests |
| `POST /vision/camera/open`, `POST /vision/camera/close` | Vision workspace hook | `VisionApplicationService` | C / P | post-RC read-only camera | Retain; explicit configured-ID acquisition and priority device release; no device ID in request |
| `POST /vision/selection`, `DELETE /vision/selection`, `POST /vision/detect/{detector}`, `POST /vision/tracking/reset` | Vision workspace hook | `VisionApplicationService` | V | 7 | Retain; active bounded Synthetic workflow |
| `POST /vision/follow/start`, `POST /vision/follow/{lease_id}/heartbeat` | Vision workspace hook | `VisionFollowService` → motion gateway | V+C; REAL adds O-RV | 7 | Retain; renewable Follow ownership |
| `POST /vision/follow/{lease_id}/stop` | Vision workspace hook | `VisionFollowService` | V+P | 7 | Retain; Follow-owner priority Stop |

## Stage 8 and final-hardening inventory

| Route(s) | Frontend caller | Service | Auth / scope | Stage | Status |
|---|---|---|---|---:|---|
| `POST /security/session`, `DELETE /security/session` | `LanSecuritySessionPanel` | `SecurityService` | Explicit long-term Bearer exchange / bounded cookie revoke | 8 | Retain; deployment authentication, not hardware authority |
| `GET /device/readiness` | `RealSessionProvider` | `DeviceDiagnosticsService` + `RealHardwareAuthorization` | R | 8/final | Retain; one backend capability matrix and blocked reasons |
| `POST /device/operator-session` | `RealSessionProvider` | `OperatorSessionService` | R + exact purpose confirmation; sets HttpOnly operator cookie | 8/final | Retain; no raw token in JSON |
| `DELETE /device/operator-session` | `RealSessionProvider` | `OperatorSessionService` | R + current Operator cookie/header | 8/final | Retain; revoke and clear cookie |
| `GET /device/field-acceptance` | `RealHardwarePanel` | `FieldAcceptanceService.status` | R | 8/final | Retain as read-only compatibility/derived summary |
| `GET /device/field-acceptance/progress` | `CommissioningMotionPanel` | `FieldAcceptanceService.progress` | R | final | Retain; derived per-capability/per-joint progress, no client authority |
| `POST /device/field-acceptance/pre-motion-checks` | `CommissioningMotionPanel` | `FieldAcceptanceService.complete_pre_motion_checks` | R+C + O-RO | final | Retain; embeds typed exact-ID diagnostics that bootstrap semantically revalidates |
| `POST /device/field-acceptance/joint-motion` | `CommissioningMotionPanel` | `FieldAcceptanceService.accept_joint_motion` | R+C + O-CM | final | Retain; requires both directions for every enabled joint |
| `POST /device/field-acceptance` | No product caller | `FieldAcceptanceService.accept` | R+C + O-RO; always raises `FIELD_ACCEPTANCE_MANUAL_PASS_FORBIDDEN` | final compatibility | OpenAPI-deprecated; retain temporarily as explicit fail-closed legacy contract; no authorization effect |
| `POST /device/connect` | `RealHardwarePanel` | `DeviceDiagnosticsService` | R+C + O-RO | 8 | Retain; explicit exact-ID read-only connect |
| `POST /device/diagnostics` | `RealHardwarePanel` | `DeviceDiagnosticsService` | R + O-RO | 8 | Retain; typed bounded reads only |
| `POST /device/disconnect` | `RealHardwarePanel` | `DeviceDiagnosticsService` | R+C + current O-RO | 8 | Retain; explicit cleanup/revoke |
| `POST /device/stop` | `RealHardwarePanel` | `DeviceDiagnosticsService` | R+P; token-independent safety action | 8 | Retain; typed result, never claims E-stop equivalence |
| `POST /device/calibration/sessions` | `CalibrationWizard` | `CalibrationWorkflowCoordinator` | R+C + O-RO | 8 | Retain; first Revision 1/recalibration entry |
| `GET /device/calibration/sessions/{session_id}` | API/test only; no product caller | `CalibrationWorkflowCoordinator` | R+C + O-RO | 8 | Retain; documented recovery/status |
| `POST /device/calibration/sessions/{session_id}/read`, `/preview`, `/confirm`, `/complete` | `CalibrationWizard` | `CalibrationWorkflowCoordinator` | R+C + O-RO | 8 | Retain; read-only capture then atomic persistence |
| `DELETE /device/calibration/sessions/{session_id}` | `CalibrationWizard` | `CalibrationWorkflowCoordinator` | R+C + O-RO | 8 | Retain; explicit session cleanup |
| `POST /device/calibration/rollback` | API/test only; no product caller | `CalibrationWorkflowCoordinator` | R+C + O-RO | 8 | Retain; documented forward-only rollback |
| `POST /backup/export`, `POST /backup/import/preview` | No product UI | `BackupApplicationService` | R | 8 | Retain; documented operator/external recovery workflow and tests |
| `POST /backup/import/restore` | No product UI | `BackupApplicationService` | C + digest/confirmation/one-use grant | 8 | Retain; documented recovery workflow and tests |
| `GET /device/commissioning/status` | `CommissioningMotionPanel` | `CommissioningMotionTestService` | R | final | Retain; token-free safe status |
| `POST /device/commissioning/session`, `POST /device/commissioning/joints/{joint_id}/arm` | `CommissioningMotionPanel` | `CommissioningMotionTestService` | R+C + O-CM | final | Retain; runtime session/explicit ARM, not Operator issuance |
| `POST /device/commissioning/joints/{joint_id}/tests/start` | `CommissioningMotionPanel` | `CommissioningMotionTestService` → narrowed bus | R+C + O-CM | final | Retain; only prepared relative one-joint test |
| `POST /device/commissioning/tests/heartbeat` | `CommissioningMotionPanel` | `CommissioningMotionTestService` | R+C + O-CM | final | Retain; renews only the current backend lease |
| `POST /device/commissioning/tests/stop` | `CommissioningMotionPanel` | `CommissioningMotionTestService.priority_stop` | R+P; token-independent | final | Retain; loss/expiry of operator cookie cannot block Stop |
| `GET /kinematics-verification` | `KinematicsVerificationPanel` | `KinematicsVerificationService` | R | final | Retain; active Settings field workflow |
| `POST /kinematics-verification/draft`, `POST /kinematics-verification/draft/{draft_id}/measurement`, `POST /kinematics-verification/draft/{draft_id}/commit` | `KinematicsVerificationPanel` | `KinematicsVerificationService` | R+C + O-RJ | final | Retain; measurement accepts only label/measured TCP and requires a fresh server-owned session/device-bound joint-state snapshot |

## Staged Field Acceptance route wiring

`FieldAcceptanceService` owns three non-forgeable application operations:

- derived capability/per-joint `progress()`;
- `complete_pre_motion_checks(...)` after current exact-ID read-only diagnostics;
- `accept_joint_motion(...)` only after current positive/negative evidence for every
  Profile-enabled joint.

The backend exposes those as `GET /device/field-acceptance/progress`,
`POST /device/field-acceptance/pre-motion-checks`, and
`POST /device/field-acceptance/joint-motion`. Transitions use C plus the appropriate
O-RO/O-CM purpose. `CommissioningMotionPanel` reads progress and calls both evidence-
derived transitions; it never sends a global pass.

There is intentionally no CARTESIAN, PLAYBACK, or VISION_FOLLOW acceptance-write route
in this release candidate. Those capabilities require later typed field-test repositories
and semantic resolvers; file records alone remain audit-only and cannot authorize them.

## Callerless-route disposition

No route is removed in this audit. The explicit deletion rule requires all four facts:
no frontend caller, no documented external purpose, no test dependency, and duplication
with an existing route. None satisfies all four.

| Callerless route/group | Documented/test purpose | Duplicate? | Decision |
|---|---|---|---|
| Product scope metadata | Machine-readable scope/release inspection | No | Retain |
| Explicit Pose create/Pose patch/Motion patch | External entity authoring, CAS/conflict contracts | No | Retain |
| Draft delete | Explicit cleanup/recovery contract | No | Retain |
| Vision exact frame | Snapshot/fallback/testing distinct from multipart stream | No | Retain |
| Calibration session status/rollback | Recovery and forward-only rollback | No | Retain |
| Backup routes | Documented disaster-recovery surface | No | Retain |
| Legacy Field Acceptance POST | Stable explicit denial of the removed manual bypass | Semantically superseded | OpenAPI-deprecated/retain temporarily; never authorize |

## Intentional overlaps

- `/robot/connect` is the product lifecycle: DRY_RUN uses the in-memory driver; REAL
  first obtains and binds an authorized production bus. `/device/connect` remains the
  separate commissioning diagnostics connection. They are not aliases.
- Robot, motion, Jog, Playback, Vision, Device, and Commissioning Stop endpoints stop
  different owners/scopes. All use priority authentication where applicable and converge
  on bounded service Stop handling; collapsing them would weaken ownership semantics.
- `jog-step` is a discrete command; the Jog session endpoints own a renewable lease.
- `/motion/pose`, persisted Pose Goto, and Studio keyframe Goto accept different
  high-level provenance and all enter the same gateway.
- Motion preflight creates an executable digest-bound prepared plan; Studio compile is a
  non-executable Draft preview.
- `/security/session` is LAN/deployment authentication. `/device/operator-session`
  grants one purpose-bound hardware authority. `/device/commissioning/session` starts the
  already-authorized test runtime. They are deliberately distinct.

## Bypass and scope findings

- Route → concrete driver import: **none found**.
- Vision → driver/executor import: **none found**; Follow uses the motion application
  coordinator/gateway.
- Raw Servo/register, scan/enumeration, arbitrary command/path/Python endpoint: **none**.
- Read-only write path: **none exposed by `ReadOnlyServoBus`**.
- Commissioning → production executor bypass: **none; narrowed prepared-command port**.
- Manual global PASSED bypass: **removed; compatibility POST fails explicitly**.
- Stale/legacy evidence authorization: legacy schema-v1 is rejected. The audit found and
  integration corrected the persisted `JOINT_MOTION` chain gap by making file-loaded
  bundles non-authoritative until every referenced UUID/current all-joint-direction test,
  embedded prepared command, and exact current commissioning envelope are semantically
  resolved into a transient validated bundle, including at startup. Pre-motion evidence
  embeds the read-only session/timestamp plus exact joint/Servo ping, mode, raw/logical,
  bounds, and torque-off snapshot; bootstrap recomputes mapping/bounds and exact enabled-
  joint/device coverage before restoring that capability. Matching fingerprints alone
  remain insufficient.
- Acceptance/revoke TOCTOU: **corrected**. PRE_MOTION/JOINT transitions reauthorize the
  same session/operator and linearize durable save plus live publication under the Device
  guard; revoke-first saves no pass. Kinematics persists audit evidence first, then
  reauthorizes under the Device guard; a losing race can leave audit history but cannot
  publish or bootstrap authority.
- Frontend-only security assumption: **none intended; backend purpose/scope and evidence
  are authoritative**.
- Raw operator token in browser state/storage/URL/log: **none in the current browser
  path**. Authority uses HttpOnly cookie; the bounded header is local-tool compatibility.
- Module-global robot, `arm_a`, Fleet API, hidden Real override: **none found**.
- Stage 8 God Object: **no unsafe/global object; P3 service concentration documented**.
  `DeviceDiagnosticsService` remains a 974-line app-scoped, guard-locked coordinator
  spanning sessions/readiness, connection/diagnostics, Calibration/Profile invalidation,
  Field/Kinematics publication, Stop, and shutdown. It stays behind typed boundaries and
  the audit found no bypass, but decomposition is post-merge refactor debt.

- Client-selected Kinematics state: **removed**. The request schema forbids extra fields
  and accepts only the operator's label and measured TCP. The service requires a fresh
  server-owned snapshot bound to the current unit, Profile, Calibration, Device, and
  Operator Session, reauthorizes after capture, and computes FK from that state.
- Persisted Kinematics promotion: **fail-closed in `0.1.0-rc1`**. The release bootstrap
  does not load local Kinematics JSON into authorization context, and the release service
  intentionally has no physical snapshot provider. Files remain audit history after
  restart; a reviewed field adapter and fresh verification are required before Real
  Kinematics can become effective. Device fingerprint and software commit are included
  in live evidence staleness checks.

The first snapshot found two scope inconsistencies: commissioning mutations inherited
only R and Kinematics mutations inherited only R. Integration corrected commissioning
session/arm/start/heartbeat to C, Commissioning Stop to P with token-independent
`priority_stop()`, and Kinematics draft/measurement/commit to C. Final route tests must
lock those dependencies.

## Static reproduction

The audit uses no hardware and does not run application lifespan:

```bash
PYTHONPATH=backend/src backend/.venv/bin/python -c \
  'from momo.api.app import create_app; print(create_app().openapi()["paths"])'

rg -n 'from momo\.adapters\.hardware|feetech|raw_register|scan|enumerat' \
  backend/src/momo/api backend/src/momo/application

rg -n '/device/commissioning|/kinematics-verification|/field-acceptance' \
  frontend/src backend/src/momo/api
```

Final verification must additionally cover generated route enumeration, per-route auth
tests, wrong-purpose/scope rejection, manual-PASS denial, stale evidence, and frontend
caller integration. Command/CI results belong in the final Stage report only after they
are actually run.

## CI and verification mapping

The repository has one `CI` workflow triggered by pull requests, pushes to `main` or
`codex/**`, and manual dispatch. Its three jobs are:

- backend: locked `uv` sync, `uv pip check`, `pip-audit`, Ruff lint/format, strict mypy,
  security/backup tests, full pytest, hardware/camera/commissioning/Kinematics isolation,
  deterministic schema diff, and `uv lock --check`;
- frontend: locked `npm ci`, high-severity npm audit, Vitest, ESLint, TypeScript, and Vite
  production build;
- secret scan: high-confidence private-key/provider-token patterns in tracked files.

The local aggregate commands are `make test`, `make lint`, `make format-check`,
`make build`, `make audit`, and `make schemas`, followed by `git diff --check`. Schema
determinism requires generating to a fresh temporary directory and diffing it against
`docs/schemas`; running `make schemas` alone updates the tracked output and is not the
comparison. Push and pull-request CI are independent required final-head observations.
