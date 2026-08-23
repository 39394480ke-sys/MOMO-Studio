# Stage 01: Foundation

- Date: 2026-08-23
- Repository: `/Users/ke/Library/Mobile Documents/com~apple~CloudDocs/Code/MOMO-Studio`
- Stage commit message: `chore: establish MOMO Studio foundation`

## Summary

Stage 1 created an independent MOMO Studio repository with a runnable FastAPI metadata backend, a responsive React/Vite five-route shell, versioned Pydantic domain models, explicit external-capability ports, reproducible JSON Schemas, safe example data/profiles, a Legacy migration audit, ADRs, tests, and unified developer commands.

The backend route surface is read-only metadata. Stage 1 has no driver adapter, serial access, motion endpoint, motion control, kinematics algorithm, persistence CRUD, or camera access. Stage 2 has not started.

## Legacy source commit SHA

- Repository: `https://github.com/39394480ke-sys/MOMO_RobotARM.git`
- Branch: `V2`
- Commit: `ff8bbda0c2222cb57951c7913f7f12f5777b98fa`
- Local read-only reference checkout: sibling `MOMO_RobotARM/`
- Final Legacy status: clean (`## V2...origin/V2` with no changed paths)

The SHA was confirmed with the remote branch reference and the checked-out `HEAD`. No Legacy program or hardware dependency was executed.

## Created architecture

```text
React frontend
  -> centralized REST client
     -> FastAPI app factory/routes
        -> domain models and application policy boundary
           -> typed ports
              -> hardware / kinematics / storage / vision adapters (later Stages)
```

- Backend uses the standard `backend/src/momo` layout with no `sys.path.append`, import-time app/device connection, or working-directory-dependent runtime lookup.
- FastAPI exposes only `GET /api/v1/health`, `GET /api/v1/meta`, and `GET /api/v1/meta/product-scope` under the product prefix. Tests also reject hidden WebSocket/Mount command surfaces.
- Ports cover robot driver/manager, kinematics, Pose/Motion repositories, and vision without supplying a real adapter.
- Frontend owns transport in `src/api`, composition/routes in `src/app`, chrome/components/layouts, and five focused page modules.
- Runtime data is designed for UUID-named JSON with atomic replacement in a later storage adapter; Stage 1 commits only validated examples.

## Important domain decisions

1. V1 and V2 are hardware variants. V1 is rail-less J11-J15; V2 has J10-J15 with J10 as the linear rail.
2. Profile validation enforces the full variant contract: joint set/order, rail flag, and J10 `PRISMATIC/mm` versus revolute `deg` joints. Code consumes explicit `enabled_joints` rather than assuming six joints.
3. Product `ControlMode` contains only `DRY_RUN` and `REAL`. Safe default is `DRY_RUN`; Stage 1 settings are frozen and reject `real_motion_enabled=true` during construction, YAML/env loading, and later assignment.
4. Joint states are ID-keyed mappings validated for membership, explicit units, finite values, and profile ranges.
5. Canonical TCP uses millimetres and normalized `xyzw` quaternions. Named boundary helpers alone convert UI/domain mm/deg to kinematics m/rad.
6. A Motion embeds complete, deeply immutable Pose Snapshots. `source_pose_id` is provenance only; source rename, replacement, or deletion cannot affect the Motion.
7. Profile, settings, Pose, Motion, keyframe/tag collections, and safety-relevant nested mappings are immutable after validation. Edits require a newly validated revision.
8. The UI operates one Active Robot, while `RobotId` and `RobotManager` avoid a global or `arm_a` core. Fleet/coordination is not implemented.

## Files added or changed

This was an empty new repository; every tracked path in the Stage commit is new.

- Root: `.gitignore`, `AGENTS.md`, `README.md`, `Makefile`, `THIRD_PARTY_NOTICES.md`.
- Backend: `backend/pyproject.toml`, `backend/uv.lock`, package source, ports, schema generator, and 55 tests.
- Frontend: npm manifests/lock, Vite/TypeScript/ESLint/Vitest configuration, API client, layout/components/pages/styles, and 15 tests.
- Safe configuration/examples: `config/default.yaml`, `robot_profiles/*.example.yaml`, `data/examples/*.json`.
- Documentation: product/architecture/domain/safety/roadmap, five ADRs, design reference/spec/fidelity ledger, Legacy migration map and variant audit, generated schemas, and this report.

## Commands executed

Representative evidence-producing commands, including final gates:

```text
git ls-remote https://github.com/39394480ke-sys/MOMO_RobotARM.git refs/heads/V2
git clone --branch V2 --single-branch https://github.com/39394480ke-sys/MOMO_RobotARM.git ../MOMO_RobotARM
git -C ../MOMO_RobotARM rev-parse HEAD
git -C ../MOMO_RobotARM status --short --branch

make test
make lint
make format-check
make build
uv lock --check --project backend
npm --prefix frontend audit --omit=dev --audit-level=moderate
make schemas
shasum -a 256 docs/schemas/*.json

PYTHONPATH=backend/src backend/.venv/bin/python -m uvicorn momo.api.app:create_app --factory --host 127.0.0.1 --port 8877
curl -sS -f http://127.0.0.1:8877/api/v1/health
curl -sS -f http://127.0.0.1:8877/api/v1/meta
curl -sS -f http://127.0.0.1:8877/api/v1/meta/product-scope
```

The in-app browser also exercised every route, direct subroute refresh, online/offline states, and 1440×960, 390×844, 720, 721, 840, and 841 px responsive widths. The original concept and final desktop screenshot were inspected at original detail.

## Test results

Final results:

- Backend pytest: **55 passed** on Python 3.11.15.
- Backend Ruff check: passed.
- Backend Ruff format check: 36 files already formatted.
- Backend mypy strict check: passed across 36 source files, including schema script and tests.
- Frontend Vitest/Testing Library: **15 passed**.
- Frontend ESLint: passed.
- Frontend TypeScript project check: passed.
- Python lock check: resolved 36 packages; passed.
- npm production dependency audit at moderate threshold: 0 vulnerabilities.
- Reproducible install entry: `uv sync --locked` and `npm ci` consume the committed Python and npm lockfiles.
- Schema sync test: committed artifacts match generator output.
- Independent before/after SHA comparison for all three generated schemas: identical (`motion` `fc0fb5689d4d0dca5408f3c1926bcd9095a07b84969296cb28f923178b39cbf3`; `pose` `94f9398e2179b324d1514ca64bab3e2779c3cfe1aa4dc1bd0665e3081c4f43b7`; `robot-profile` `efa0303a5129271b17d6564a3cb2ce393c981353b951801b8052a45e0e1cc8a0`).
- Profile, Pose, and Motion committed examples: parsed and validated by backend tests.
- Browser: all five route clicks and direct refresh passed; connected/unavailable states were truthful; no console warnings/errors, prohibited entries, fake buttons, or horizontal overflow were found.
- API smoke: all three endpoints returned HTTP 200; health returned `DRY_RUN` and `real_motion_enabled=false`; Uvicorn shut down cleanly.

Development-time failures were retained as engineering evidence and fixed before the final gates:

- The first frontend run passed 6/11 and failed 5/11 because rendered DOM was not cleaned between tests. Explicit cleanup fixed isolation; final count is 15/15 after adding all-route prohibited-surface coverage.
- An adversarial backend-hardening run passed 52/54 and failed two newly added tests due to an incorrect nested-route expectation and an uncleared test environment variable. The tests were corrected; product logic was unchanged; final count is 55/55.
- The first local smoke attempt used port 8765 and exited cleanly because the port was reported busy. Port 8877 was confirmed and the full smoke check then passed.

## Build results

Vite 6.4.3 production build passed after 55 modules transformed:

- `dist/index.html`: 0.56 kB (0.34 kB gzip)
- CSS: 5.88 kB (1.88 kB gzip)
- JavaScript: 189.45 kB (62.06 kB gzip)

Build output and dependency directories are ignored and are not part of the Stage commit.

## Known limitations

- All joint ranges, homes, hardware mappings, TCP link names, and URDF references in Stage 1 profiles are unverified placeholders and cannot authorize real motion.
- No file repository CRUD/atomic writer exists yet; only ports, models, schemas, and examples exist.
- No real or fake movement application service, trajectory generator, FK/IK implementation, hardware adapter, calibration loader, device diagnostic, WebSocket state stream, or vision implementation exists.
- There is no production host/Tauri packaging decision yet. Vite development routing and direct subroute refresh were verified.
- Legacy repository licensing is unresolved; no Legacy code, URDF, mesh, model weight, recorded action, or calibration was copied.
- No open-source license has been selected for MOMO Studio.
- The new remote was configured by the workspace, but Stage 1 creates only the requested local commit; no push was performed.

## Legacy inconsistencies found

1. Explicit Legacy Web config/docs/tests correctly define V1 as rail-less J11-J15 and V2 as rail-equipped J10-J15.
2. `配置/robot_v1.yaml` is named `with_linear_rail`, includes J10 in every map, and conflicts with the product V1 contract.
3. The Legacy profile loader/global constants and profile tests require J10-J15 for both variants.
4. The V1 URDF includes a prismatic J10; it is not a no-rail V1 model and cannot be hidden only at the UI.
5. The V1 calibration template contains J10-J15 plus a gripper. It cannot be cropped silently into a valid new calibration.
6. Legacy `fleet.py` fallback declares V1 with J10 and a rail when explicit devices are absent.
7. The V2 profile applies angle-shaped `[-360, 360]` data to prismatic J10 despite other layers treating it as mm/m.
8. Older V1 action backups use `shoulder_*` aliases while current examples use J11-J15; audited actions also carry retired gripper data.
9. Legacy default Dry Run is undermined by `real_mode_requires_confirm:false`, which the bridge treats as confirmation satisfied. This bypass must never migrate.
10. A local calibration-backup JSON is tracked despite Legacy ignore rules. Its contents were not read and it is explicitly excluded/retired.
11. URDF/STL provenance and bundled vision-model licenses are unresolved; the Legacy tree has no root LICENSE/COPYING.

## Decisions still requiring later verification

- Exact V1/V2 physical limits, homes, servo/raw mapping, signs/scales, multi-turn representation, and calibration identity.
- A verified no-rail V1 URDF, authoritative V2 URDF, link axes, TCP links, reference FK poses, and IK tolerances.
- Calibration schema/version/fingerprint and device/profile matching rules.
- Legacy action importer policy, alias reports, raw/multi-turn preservation, and quarantine behavior for V1+J10.
- Atomic repository locking/revision/recovery behavior.
- Network authentication, WebSocket lifecycle, Tauri packaging, and distribution model.
- Third-party license/attribution clearance and the MOMO Studio repository license decision.

## Safety confirmation

- `config/default.yaml` is `dry_run` with `real_motion_enabled:false` and an empty serial port.
- No settings/API request can enable real motion; settings and domain safety aggregates are frozen.
- The full Stage 1 product API surface has only three GET endpoints and no WebSocket/Mount command surface.
- No serial port was opened or scanned. No servo was read/written. No Home, motion, Stop, calibration, camera, or hardware dependency was invoked.
- No real calibration, runtime state, serial override, secret, captured media, or Legacy binary asset was read into or committed to the new repository.
- The Legacy checkout remained clean.

## Next-stage prerequisites

A later Stage may begin only after Stage 1 review. It must choose one bounded capability, preserve Dry Run, consume the existing domain/port contracts, add characterization and negative tests, and update safety/provenance evidence. Hardware work additionally requires verified variant profiles, calibration identity, a single deny-by-default safety gateway, and explicit operator authorization. No such Stage 2 implementation is present here.
