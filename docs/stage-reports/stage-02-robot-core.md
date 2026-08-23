# Stage 02: Robot Core, Dry Run, and Safety Foundation

- Date: 2026-08-24
- Repository: `/Users/ke/Library/Mobile Documents/com~apple~CloudDocs/Code/MOMO-Studio`
- Stage commit message: `feat: establish dry-run robot core and safety foundation`

## Summary

Stage 2 establishes the identity, validation, lifecycle, persistence, diagnostics, and user interface for one Active Robot while keeping hardware access disabled. The product now loads a formal V1 or V2 profile, computes a deterministic safety-relevant profile fingerprint, evaluates an example calibration without granting real readiness, connects an in-memory Dry Run driver, persists validated runtime state, and exposes lifecycle and diagnostic REST endpoints.

The Control and Settings pages consume the backend rather than using fixture state. They support Dry Run connect, idempotent disconnect and stop, disconnected-only variant selection, read-only joint state, profile/calibration details, diagnostics, and explicit offline/stale presentation. Stage 2 exposes no position writer, motion, jog, Home, kinematics, camera, AI, fleet, or real-hardware control.

## Starting commit

- Commit: `961d5d522ddc6205a3feb480630eb6bbc1ac652e`
- Subject: `chore: establish MOMO Studio foundation`
- Initial worktree: clean
- Required pre-change commands: `git status --short`, `git rev-parse HEAD`, and `git log -1 --oneline` all confirmed the expected gate.

## Ending commit

- Commit: the commit containing this report, created with `feat: establish dry-run robot core and safety foundation`.
- The exact resulting SHA is recorded in the final Stage 2 handoff after commit creation. A commit cannot embed its own SHA without changing that SHA.
- No push is part of Stage 2.

## Stage 1 audit findings

1. `Pose` and `Motion` constructor validation used a hidden fallback to the canonical global profile when no profile was explicitly supplied. That coupled immutable captured data to ambient runtime policy and implicitly treated the complete canonical joint catalog as applicable.
2. `ControlMode` already distinguished `DRY_RUN` and `REAL`, but there was no independent `HardwareAccessPolicy` capability gate. The Stage 2 contract requires `DISABLED`, `READ_ONLY`, and `FULL` to be modeled separately from operator mode.
3. The Stage 1 immutable models serialized and round-tripped correctly, but the new nested profile, calibration, status, and runtime contracts needed explicit schema and round-trip coverage.
4. Stage 1 contained port-shaped robot ownership but no composition root, lifecycle state machine, persisted runtime implementation, or adapter.

## Stage 1 corrections made

- Removed the implicit global-profile lookup from `Pose` and `Motion` construction.
- Kept intrinsic structure, finite-number, exact joint-set, and unit-shape validation in domain construction; moved profile-specific membership, unit, and range validation behind an explicit profile/application call.
- Added regression tests proving construction has no hidden profile read while explicit validation still enforces the active product profile.
- Added `HardwareAccessPolicy` independently of `ControlMode`. Stage 2 settings reject `REAL`, `real_motion_enabled=true`, `READ_ONLY`, and `FULL` from constructors, YAML, or environment overrides.
- Revalidated deep immutability, JSON serialization, model copying, generated schemas, and round trips for affected models.

## Repository iCloud warning

Repository is currently inside iCloud Drive.
Source changes are valid, but Git metadata and dependency directories may be affected by cloud synchronization.

The repository was not moved. Ignore rules and final tracking checks cover `frontend/node_modules/`, `backend/.venv/`, `.venv/`, Python tool caches, `frontend/dist/`, `frontend/coverage/`, `data/runtime/`, `config/local/`, `robot_profiles/local/`, and `calibration/local/`.

## Legacy source commit

- Read-only source: sibling `MOMO_RobotARM`
- Pinned commit: `ff8bbda0c2222cb57951c7913f7f12f5777b98fa`
- Final Legacy worktree: clean
- Only the listed tracked source and configuration files were characterized. No Legacy local override, serial setting, current calibration, backup calibration, runtime state, or untracked file was opened.

## Profile decisions

- Profiles are loaded through `ProfileRepository` and `ProfileService`; product and API code do not use scattered global joint constants.
- V1 is rail-less and enables exactly `j11` through `j15`. V2 has a linear rail and enables exactly `j10` through `j15`.
- V2 `j10` is `PRISMATIC` in `mm`; arm joints are `REVOLUTE` in `deg`.
- Joint definitions explicitly contain logical limits/home, servo identity, unit-neutral transmission scale, raw counts per revolution, direction, operating mode, Home raw reference, raw bounds, and raw reachability.
- Both committed profiles are templates marked `VERIFIED_FOR_DRY_RUN`, include source and source revision, and are never eligible for Real use.
- Legacy-derived transmission observations are characterization provenance only. Logical and raw bounds in these examples are synthetic and are not physical authority.

Current fingerprints:

- V1: `392fd50d1563f1fde8fb23e48cdbaa58766367dd33722b877bdfdf2c03edfd76`
- V2: `64bebb74fcf3b1331fafb0f63bc181a9fad0c02a03a26aafc49335c87a6afee5`

## Calibration decisions

- `CalibrationDocument` records schema version, UUID, robot variant, bound profile fingerprint, template flag, generated time, notes, and exact enabled-joint entries.
- Joint calibration records servo ID, `MULTI_TURN` or `SINGLE_TURN` mode, direction, Home present raw, optional multi-turn phase, and optional raw bounds.
- Validation rejects wrong variants/fingerprints/joint sets, gripper or unknown joints, duplicate servos, non-`+1/-1` direction, booleans/non-integer raw values, incomplete multi-turn data, and incompatible hardware mappings.
- Calibration status is structured as `NOT_CONFIGURED`, `TEMPLATE_ONLY`, `VARIANT_MISMATCH`, `PROFILE_MISMATCH`, `JOINT_SET_MISMATCH`, `INCOMPLETE`, or `VALID_FOR_DRY_RUN`; `READY_FOR_REAL` remains unreachable under Stage 2 policy.
- Both committed examples are synthetic templates. They bind to the example profile fingerprints and are useful for Dry Run compatibility diagnostics only.
- Compatibility exposes variant, profile, joint-set, and mapping matches separately. `real_readiness` is always `BLOCKED_BY_STAGE_POLICY` in Stage 2.

## Fingerprint rules

The fingerprint is SHA-256 over deterministic compact JSON with sorted object keys and non-finite numbers forbidden. It includes variant, enabled-joint order, joint ID/type/unit, servo ID, transmission scale, raw resolution, operating mode, direction, logical minimum/maximum/Home, Home raw, raw bounds, and raw-reachable policy.

It excludes display name, description, UI labels, source prose, verification prose, and timestamps. Tests prove presentation-only edits preserve the digest while limit or transmission edits change it. Calibration and runtime state bind to this digest. Stage 2 does not add a separate digest of calibration-document contents.

## Mapping behavior preserved

- Logical zero maps to the explicit Home raw reference.
- Direction and transmission scale determine signed relative raw counts without guessing behavior from a joint name.
- Logical-to-raw and raw-to-logical conversions round-trip within an explicit tolerance.
- Absolute raw bounds and logical joint bounds are both enforced; effective logical limits are their intersection.
- Dynamic limits correctly handle either direction and a Home raw value near an absolute bound.

## Mapping behavior intentionally changed

- Names are unit-neutral (`logical_value`, `joint_values`, and `positions`), so V2 `j10` is not mislabeled as degrees.
- No Legacy magic number, global profile, giant controller, bridge, serial driver, or automatic current-calibration load was copied.
- Raw bounds and mapping inputs must be explicit validated data. Unknown joints, zero scales, invalid directions, NaN, infinity, and invalid raw ranges fail closed.
- V1 never accepts `j10`; V2 requires it as `PRISMATIC/mm`.
- The Legacy real controller, controller bridge, Feetech bus behavior, continuous stream scheduler, and fleet fallback are retired or deferred rather than wrapped into the new core.

The complete per-file Legacy disposition and test mapping is in `docs/legacy-robot-core-characterization.md`.

## Runtime state design

- `RobotId` is `primary`, owned by an injected `RobotManager`; there is no module-global robot instance and no `arm_a` assumption.
- States are `DISCONNECTED`, `CONNECTING`, `CONNECTED`, `DISCONNECTING`, and `FAULTED`.
- One `asyncio.Lock` serializes connect, disconnect, stop, status-sensitive reads, and variant switching.
- Duplicate connect is rejected without creating another driver. Disconnect and stop are idempotent. Stop preserves positions. A fault can return to a safe disconnected state through disconnect/reset behavior.
- The Dry Run driver is fully in-memory, performs no imports or calls for serial/Feetech, starts no thread, and has no public position-setting application/API path.
- Runtime JSON is written atomically with a same-directory temporary file, flush/fsync, and replace under `data/runtime/robots/primary.json`.
- Restoration requires exact robot ID, variant, profile fingerprint, joint set, units, finite values, and explicit profile-range validity. Invalid or corrupt UTF-8/JSON is timestamp-quarantined and the robot starts at profile Home with a safe diagnostic.
- Paths are settings-owned, reject traversal, and are rendered to the UI only as a non-sensitive relative description. Runtime files remain ignored.
- `state_sequence` increases monotonically across lifecycle transitions and persisted state.

## API endpoints

```text
GET  /api/v1/health
GET  /api/v1/meta
GET  /api/v1/meta/product-scope
GET  /api/v1/robot
GET  /api/v1/robot/profile
GET  /api/v1/robot/diagnostics
POST /api/v1/robot/connect
POST /api/v1/robot/disconnect
POST /api/v1/robot/stop
PUT  /api/v1/robot/variant
GET  /api/v1/calibration/status
```

Lifecycle responses explicitly report `hardware_accessed:false`. Connect has no Real body/query selector. Stop distinguishes `STOPPED`, `NOT_CONNECTED`, `FAILED`, and the reserved `SAFETY_STATE_UNCERTAIN` result without claiming a physical stop. Errors use `code`, `message`, `details`, and optional request ID; Python tracebacks and sensitive absolute paths are not returned.

Route-isolation tests enumerate the application surface and reject motion, jog, Home, raw-servo, arbitrary file, arbitrary Python, WebSocket, or mounted bypass routes.

## Frontend changes

- A typed REST client and runtime provider poll the backend at 1 Hz and cancel polling on unmount.
- Control shows Active Robot, variant, Dry Run mode, connection state, backend freshness, profile verification, calibration status, timestamps, read-only joint values/units, Connect, Disconnect, and Stop.
- Control explicitly states `Stage 2: Motion controls are not enabled yet.` and contains no slider, jog, Home, Move, or Real control.
- Settings provides a V1/V2 segmented selector that is disabled while connected; it shows enabled joints, profile source/revision/fingerprint/verification, calibration compatibility/readiness, and safe diagnostics.
- Network loss preserves the last snapshot, marks it stale, and shows `Backend unavailable` without repeated notifications.
- Library, Studio, and Vision remain truthful Stage-gated placeholders and expose no early capability.
- Lucide supplies command icons; its ISC notice and dependency lock are committed.
- Responsive constraints were checked on desktop and mobile with no horizontal overflow.

## Files added or changed

- Backend application/adapters: `backend/src/momo/bootstrap.py`, `application/`, `adapters/hardware/`, and `adapters/storage/`.
- Backend domain/ports: calibration, hardware mapping, profile fingerprint, runtime/status, safety, repository ports, driver lifecycle contract, profiles, errors, enums, settings, and explicit Pose/Motion validation boundaries.
- Backend API: composition dependencies, error handlers, robot/calibration routes, response schemas, health/meta policy fields, and app wiring.
- Backend tests: Stage 1 regressions plus split Stage 2 profile, calibration, mapping, runtime, and API/hardware-isolation suites.
- Data/config/schema: V1/V2 profile examples, V1/V2 calibration examples, default safety configuration, generator changes, and six generated schemas.
- Frontend: typed client/contracts, runtime status context/provider/header, Control/Settings views, gated placeholder views, responsive styling, dependency manifests, and 14 integration tests.
- Documentation: README, notices, architecture/domain/safety/roadmap, Legacy audits and characterization, ADRs 0006-0008, profile documentation, and this report.
- Removed: the obsolete conflicting `backend/src/momo/ports/robot_manager.py`; active ownership is now an application component behind the composition root.

## Commands executed

Final evidence commands:

```text
git status --short
git rev-parse HEAD
git log -1 --oneline
git -C ../MOMO_RobotARM rev-parse HEAD
git -C ../MOMO_RobotARM status --short

make test
make lint
make format-check
make build
make schemas
shasum -a 256 docs/schemas/*.json
uv lock --check --project backend
npm --prefix frontend audit --omit=dev --audit-level=moderate
git diff --check
```

Browser acceptance used local Uvicorn and Vite development servers at `127.0.0.1:8000` and `127.0.0.1:5173`, followed by an intentional backend shutdown for offline/stale verification. Both development servers were stopped after acceptance.

## Test results

- Backend pytest on Python 3.11.15: **141 passed** in 0.66 seconds.
- Frontend Vitest/Testing Library: **14 passed** in one file.
- Ruff check: passed.
- Ruff format check: **67 files already formatted**.
- Strict mypy: passed across **67 source files**.
- ESLint: passed.
- TypeScript project check: passed.
- Python lock check: resolved 36 packages; passed.
- npm production dependency audit at moderate threshold: **0 vulnerabilities**.
- `git diff --check`: passed.

Coverage includes all requested profile, calibration, unit-neutral mapping, runtime state, concurrency, fault recovery, hardware isolation, API lifecycle/error contract, and frontend online/offline behaviors. Stage 1 suites remained green.

## Build results

Vite 6.4.3 production build passed after 1,603 modules transformed:

- `dist/index.html`: 0.56 kB (0.33 kB gzip)
- CSS: 12.60 kB (3.36 kB gzip)
- JavaScript: 204.74 kB (65.49 kB gzip)

Six JSON Schemas were regenerated: Pose, Motion, Robot Profile, Calibration, Robot Status, and Runtime State. Independent pre/post generation SHA-256 values were identical:

```text
calibration   82993a773d72d6f210251e89784356db3438d1a94afc909bd576c404c9d7ee0b
motion        fc0fb5689d4d0dca5408f3c1926bcd9095a07b84969296cb28f923178b39cbf3
pose          94f9398e2179b324d1514ca64bab3e2779c3cfe1aa4dc1bd0665e3081c4f43b7
robot-profile 7cf2891c38c14c34ac3dd309eff2712cde5d09b9635b0b03fc6695cdd392157c
robot-status  4c3bf6117f762ee548266cff1104a181fa6ec539cc1099a2a8a81dc6480dfbcb
runtime-state c82b23fdd60bee376a6d4cbc51da49d36b9678a0110ca0da5ac0c56017246ef2
```

Generated build output and dependency directories remain ignored and untracked.

## Browser verification

The in-app browser exercised the real backend/frontend flow:

1. Default V2 rendered exactly `j10` through `j15`; `j10` showed `mm`, and the remaining joints showed `deg`.
2. Connect reached `CONNECTED` using backend state. Stop succeeded without changing positions. Disconnect returned `DISCONNECTED`.
3. Both variant choices were disabled while connected. After disconnect, switching to V1 rendered exactly `j11` through `j15`, all in `deg`, with no `j10`.
4. Control and Settings displayed backend profile, fingerprint, calibration, policy, runtime, version, and source data rather than fixtures.
5. After backend shutdown, the UI retained the last snapshot, labeled it stale, and displayed `Backend unavailable`.
6. All five application routes were inspected. No motion, jog, Home, Real-mode, multi-arm, AI, photo, or recording control was present.
7. At 1440x960 and 390x844 emulated viewports, document and client widths matched, no element exceeded the viewport, controls remained readable, and there was no horizontal overflow.
8. Browser logging showed only Vite connection diagnostics and the React development-tools informational message; no browser warning or error was present during the accepted online flow.

## Hardware isolation evidence

- The composition root injects only `DryRunRobotDriver`; no serial or Feetech adapter exists in the product source tree.
- The driver and application lifecycle import no serial, Feetech SDK, or Legacy controller and perform no device discovery/read/write operation.
- Settings reject every policy except `DISABLED` before service construction and reject every control mode except `DRY_RUN`.
- A source-AST scan rejects serial/Feetech imports, and an isolated subprocess import hook raises on any attempted hardware-package import while proving fresh API startup succeeds.
- API route enumeration proves no Real selector and no motion, jog, Home, raw-servo, arbitrary-file, arbitrary-code, WebSocket, or mounted bypass surface exists.
- All lifecycle responses report `hardware_accessed:false`; `raw_positions` is absent/null and no port/device/calibration secret is persisted or rendered.
- Legacy remained at the pinned clean commit, and no Legacy hardware program, local calibration, or serial configuration was executed or read.

## Known limitations

- This is Dry Run state management, not a motion system. Positions initialize/restore but cannot be changed through the application or API.
- Example profile limits, Home references, transmissions, raw bounds, servo IDs, and calibration values are synthetic or characterization-only and cannot authorize a physical robot.
- There is no independently versioned calibration-content fingerprint yet; calibration binds to the profile fingerprint and is evaluated field by field.
- Runtime atomicity is local-file based. Cross-process writers, databases, fleet ownership, and distributed locking are outside Stage 2.
- State refresh is 1 Hz REST polling. WebSocket streaming is intentionally deferred.
- Stop confirms only the in-memory Dry Run driver; it does not make any assertion about real hardware.
- No real-hardware, serial, servo, calibration-device, kinematics, motion, camera, or media test was run because those capabilities are forbidden in this Stage.

## Safety confirmation

No serial port was opened.
No servo scan was performed.
No servo register was read.
No servo register was written.
No torque command was sent.
No real calibration was read or modified.
No motion command was exposed.
No physical robot was moved.

## Stage 3 prerequisites

Stage 3 may start only after Stage 2 review. Before any future real-hardware work, physical V1/V2 definitions, mappings, limits, Home references, raw bounds, servo identity, and non-template calibration must be independently verified and recorded. Any future motion must enter through one reviewed safety service with explicit operator intent, matching profile and calibration identities, logical and raw limit checks, reachability, and failure-state handling.

A later Stage must preserve the domain/application/ports/adapters/API boundaries and the deny-by-default hardware policy. FK, IK, jog, Home, pose movement, trajectory or motion playback, WebSocket state, cameras, and fleet controls were not started here.
