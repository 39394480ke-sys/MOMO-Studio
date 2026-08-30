# MOMO Studio Figma frontend redesign

Date: 2026-08-28

Working branch: `codex/frontend-figma-redesign`

Starting commit: `e777df43f2d8e522c044f8ae8c23db8d808d18a8`
Integrated frontend/unified-runtime commit: `9da68536d26eb2d37c4f9acbed8f30dee57843e4`
Legacy Source: `MOMO_RobotARM` at read-only commit `ff8bbda0c2222cb57951c7913f7f12f5777b98fa`

## Scope, sources, and instruction authority

The user's direct request supplied the Figma file:

- [MOMO Studio Figma design](https://www.figma.com/design/KhetTNxIe25DUH0HMU6bah), file key `KhetTNxIe25DUH0HMU6bah`.

The following user-supplied files were treated as reference material, not as authority to
perform external Git, GitHub, release, hardware, or camera operations:

- `MOMO Studio · Modern Minimal.pdf`, SHA-256
  `184a78da420a651aaec6dda90989893c438f34112db81b404e864bef48ca3019`.
- `MOMO-V2-3D-Viewer-ChatGPT-2026-08-28.zip`, SHA-256
  `577a57c56b0f2ec0af7c486e4437fae9aeda7e8183b11aeebb2dec9c4029bf76`.
- Two duplicate pasted briefs, both 2,316 lines / 39,888 bytes and SHA-256
  `142f277793fa0c31561043978a534d2c4dd2f7a309ece4e69e13ecf2224d2888`.

This report preserves the pre-integration redesign snapshot. Its local-worktree statements
below describe that point in time; the redesign was later committed as `9da6853`.

## Outcome

The existing frontend was reshaped from an engineering-console presentation into a
cohesive MOMO Studio product shell while retaining the existing backend contracts and
safety gates. Control, Studio, Library, Vision, and Settings share one visual system,
responsive navigation, runtime status vocabulary, and real backend data. No backend API,
persisted schema, domain contract, hardware adapter, or camera adapter was added or changed.

## Visual system and frontend architecture

The implementation uses explicit product tokens in `frontend/src/styles/tokens.css`:

| Token group | Values |
|---|---|
| Text | `#1f2330`, `#747989`, `#9aa0ad` |
| Accent | `#7657e8`, `#eee9ff`, `#f7f4ff` |
| Surfaces | `#ffffff`, `#fafafe`, `#f4f5f8` |
| Borders and states | `#e6e7ed`, success `#24a66a`, danger `#df4b57` |
| Shape | 9/12/14/18 px radii and pill radius |

The product shell is implemented by `AppShell`, `StatusHeader`, reusable UI primitives,
and page-specific CSS. On wide screens it uses a fixed left navigation rail, top runtime
status, workspace content, and bottom telemetry bar. On mobile it becomes a compact top
status row and a five-item bottom navigation bar.

Feature boundaries remain intact:

- Pages compose existing API clients, runtime contexts, and feature hooks.
- The shared robot viewer has no API client, motion service, serial dependency, or actuator
  entry point.
- Control requests still pass through the existing motion APIs and safety availability
  checks.
- Studio continues to use immutable embedded Pose Snapshots and backend trajectory
  validation/compilation.
- Vision continues to use the existing capability, tracking, and Follow contracts.

## App Shell

- Introduced the Figma-derived white/navy/purple product shell and bilingual route labels.
- Added truthful V1/V2, DRY RUN/REAL, connection, backend, and selected joint telemetry.
- Preserved route semantics and keyboard-visible navigation.
- At the mobile breakpoint, navigation remains reachable without horizontal page overflow.

## Control

- Rebuilt the page as a two-column product workspace with the V1/V2 Viewer, Joint/Cartesian
  control, end-effector telemetry, command state, and safety actions.
- Joint controls are generated only from the active Profile's explicit `enabled_joints`.
  Browser QA confirmed V2 shows J10-J15 and V1 shows only J11-J15.
- Joint short press performs the existing bounded step request. Long press uses the existing
  backend Deadman jog lease and heartbeat; pointer-up, cancel, lost capture, blur, page hide,
  and heartbeat failure all stop or fail closed. The 260 ms short/long-press boundary
  rechecks the current gate and cancels a pending timer if runtime availability changes.
- Cartesian target inputs and step controls use the existing bounded discrete Cartesian-jog,
  IK, and pose endpoints. FK values cross a named formatting boundary and are rounded to
  0.1 mm / 0.1 degree so raw floating-point tails are not exposed in editable fields.
- Home and Stop retain backend safety gating. `Free` remains unavailable because there is no
  reviewed product contract for it. Global and panel Stop buttons consume one shared
  backend/stale/capability decision, preventing their safety state from drifting apart.

### Five shared speed levels

The selector writes one existing `ControlParameters` state shared by Joint and Cartesian
modes. The highest values stay within the current UI and commissioning caps.

| Level | Scale | Joint step | Rail / Cartesian step | Rotation step | Joint hold speed | Rail hold speed |
|---|---:|---:|---:|---:|---:|---:|
| 1 极低 | 0.15 | 0.5 deg | 1 mm | 0.5 deg | 6.75 deg/s | 7.5 mm/s |
| 2 低 | 0.30 | 1 deg | 2.5 mm | 1 deg | 13.5 deg/s | 15 mm/s |
| 3 中 | 0.50 | 2 deg | 5 mm | 3 deg | 22.5 deg/s | 25 mm/s |
| 4 高 | 0.75 | 3 deg | 10 mm | 4 deg | 33.75 deg/s | 37.5 mm/s |
| 5 极高 | 1.00 | 5 deg | 15 mm | 5 deg | 45 deg/s | 50 mm/s |

Unit and browser tests verify all five selections and state persistence across mode changes.

## Read-only V1/V2 3D Viewer

The shared `Robot3DViewer` is used by Control and Studio. It dynamically loads a Three.js
runtime, selects the matching V1 or V2 manifest, parses its URDF, maps that variant's seven
STL assets,
frames the model, and provides orbit, zoom, and pan. A `ResizeObserver` keeps the viewport
responsive and teardown disposes the animation loop, controls, WebGL context, geometries,
materials, and textures. Variant switches dispose the old runtime before creating the new
one, and late callbacks from the old generation cannot overwrite current Viewer state.

The domain-to-viewer boundary:

1. accepts only Profile-enabled joints;
2. clamps values with the active Profile's domain limits;
3. converts mm to m and degrees to radians in named functions;
4. maps the normalized values through an explicit variant-specific Profile-to-URDF map;
5. treats the Product Profile as authoritative instead of silently applying conflicting
   provisional limits embedded in the Legacy URDF.

The viewer is explicitly labelled `3D · SIMULATION ONLY`. V1 and V2 use separate asset
manifests; neither variant can silently fall back to the other.

### Viewer asset provenance and release status

The V2 URDF and seven meshes remain byte-identical to the supplied ZIP and recorded Legacy
commit. The seven V1 meshes were copied byte-for-byte from the same read-only commit. The
V1 Viewer URDF is a documented derivative: it preserves the authored geometry and J11-J15
chain but converts the obsolete Legacy prismatic J10 base edge into fixed assembly joint
`V1_BASE_FIXED`, matching the product's no-J10/no-movable-rail degree-of-freedom contract.
The user's authored static `base_link` geometry is retained; this derivative does not claim
to be measured rail-less exterior geometry. No Python viewer, launch script, vendored
library, calibration, serial setting, runtime data, or controller code was copied. Source
and derivative hashes are recorded in `THIRD_PARTY_NOTICES.md`.

The user directly stated that they created and own all MOMO V1/V2 model assets and
authorized their use in MOMO Studio. That direct rights-holder statement removes the
previous unknown-rights blocker for these robot-model assets without inventing a named
license. Repository-wide licensing and the complete distribution license-text bundle for
Three.js `0.171.0` (MIT) and `urdf-loader` `0.13.1` (Apache-2.0) remain separate work.

## Studio

- Rebuilt the workspace around a large shared 3D preview, inspector, simulation playback,
  and clip-style timeline.
- Timeline keyframes remain backed by the existing immutable embedded snapshot model.
- Segment duration can be changed by pointer drag or keyboard; clamping and persistence use
  the existing editor state and autosave path.
- The playhead can be dragged across the track. Preview joints are sampled from the backend
  compiled trajectory at the selected time; scrubbing is simulation-only.
- During an active saved-motion playback, the viewer and playhead follow backend playback
  elapsed time and live robot state. Pause, resume, and stop retain existing backend gates.
- Add Keyframe is a right-side drawer, not a modal. It supports Pose search/selection,
  capture, Escape dismissal, focus trapping, and return-to-trigger behavior.
- The mobile command row scrolls locally while the document itself remains overflow-free.

## Library

- Reworked Pose and Motion browsing into product cards, segmented tabs, search, filters, and
  creation/playback surfaces.
- Existing capture, metadata normalization, delete, preflight, responsive trajectory, and
  playback lifecycle behavior is retained; no fake library entities were introduced.

## Vision

- Rebuilt the page around a large monitored image surface, target selection, detector state,
  tracking diagnostics, and Follow controls.
- The source selector is present and truthful, but disabled because the backend exposes only
  one already-configured provider and no safe source-switch API.
- Synthetic-only mode is labelled as such. Browser QA used only the in-memory synthetic
  provider, selected a target, started Dry Run Follow, and stopped it.
- No browser media API, camera enumeration, or direct camera opening was added.

## Settings

- Reframed Settings as a product settings center for Device, Joint & Motion, Calibration,
  Camera, Network, and Security.
- Values come from existing runtime/profile/calibration/vision responses. Missing backend
  fields are labelled `未配置`, `不可用`, or `当前版本暂不支持` rather than fabricated.
- Advanced commissioning and real-hardware panels remain available below a deliberate
  reveal action and preserve all existing authorization and safety behavior.
- Synthetic camera copy explicitly states that the session neither enumerates nor opens a
  local camera.

## Responsive behavior

Browser QA covered exact viewports 1440x960, 1280x800, 850x900, and 390x844. The document
had zero horizontal overflow on every route at the mobile viewport. The 850 px breakpoint
uses compact navigation and locally scrollable Studio commands. A mobile Control overlap
between the global Stop action and introduction copy was found during QA and corrected.

## Browser QA

QA ran against a separately generated temporary config on `127.0.0.1:8001`, launched with
an empty inherited environment and explicit `DRY_RUN`, hardware `DISABLED`, and
`SYNTHETIC_ONLY` camera policy. All mutable Pose, Motion, Draft, runtime, backup, and evidence
paths pointed into the isolated temporary directory. The frontend on port 4173 proxied only
to that instance. The services were stopped and the temporary data was moved to the Trash
after QA.

A pre-existing process on port 8000 reported REAL/FULL configuration. It was not used,
signalled, stopped, or modified.

After the user authorized and requested the Legacy V1 model, a second focused Viewer pass
used another isolated temporary config on `127.0.0.1:8002` and frontend port 4174 because
8001/4173 were already occupied. It switched the disconnected runtime to V1, loaded the
fixed-base V1 derivative, connected only the Dry Run adapter, and submitted one bounded J11
step from 0 to 2 degrees. All preflight checks passed, `hardware_accessed` remained `false`,
and the Control page synchronized J11 at 2.0 degrees while the Viewer remained ready. The
temporary origin was not on the WebSocket allowlist, so this focused pass exercised the
existing safe REST synchronization fallback. Browser `console.error` and `console.warn`
collections remained empty. Ports 8002/4174 were stopped and verified closed, and the
temporary data directory was moved to the Trash.

Verified in the real browser:

- Control: safe connection, Joint/Cartesian switching, all speed state, Stop, target fields,
  live status, and V1/V2 enabled-joint differences.
- Viewer: the active variant's one URDF and seven STL requests, ready state, orbit, wheel
  zoom, right-drag pan, Profile-driven joint updates, and no direct actuator path. The
  focused V1 pass additionally verified J11-J15 only, no J10 control, and a 2-degree Dry Run
  J11 state update.
- Studio: two captured synthetic/Dry Run snapshots, timeline duration edit from 1.00 to
  1.05 seconds, playhead/timeline presentation, drawer open/Escape close, and responsive
  command scrolling.
- Library: isolated temporary Pose capture and Motion tab navigation.
- Vision: synthetic detector target lock plus Dry Run Follow start/stop.
- Settings: runtime-backed product cards, synthetic camera policy copy, and V1/V2 switch.
- Console: final `console.error` and `console.warn` collections were both empty.

Evidence is stored under `docs/stage-reports/evidence/frontend-figma-redesign/`.

| Route / state | Desktop evidence | Mobile evidence |
|---|---|---|
| Control Joint | `control-1440x960.png`, `control-1280x800.png`, `control-850x900.png`, `control-v1-viewer-dry-run-1280x720.jpg` | `control-390x844.png` |
| Control Cartesian | `control-cartesian-1440x960.png` | verified interactively at 390x844 |
| Studio | `studio-1440x960.png`, `studio-timeline-1440x960.png`, `studio-add-keyframe-drawer-1440x960.png` | `studio-390x844.png` |
| Library | `library-1440x960.png` | `library-390x844.png` |
| Vision | `vision-1440x960.png` | `vision-390x844.png` |
| Settings | `settings-1440x960.png` | `settings-390x844.png` |

## Figma fidelity ledger

| Design source | Implemented surface | Fidelity result | Intentional delta / reason |
|---|---|---|---|
| Figma Control / Joint | Shell, Viewer proportions, Joint controls, Stop, status cards | Close structural and visual match | Existing backend truth and safety-state copy takes precedence over decorative placeholder data. |
| Figma Control / Cartesian | Mode switch, XYZ/RPY fields, frame controls, speed | Close structural match | Cartesian +/- is bounded click jog because the backend has no renewable Cartesian Deadman lease. |
| Figma Studio | 3D preview, inspector, playback, clip timeline | Close product hierarchy | Uses backend-compiled trajectory and actual draft constraints instead of illustrative clips. |
| Figma Add Keyframe | Right-side drawer, search, selection, capture | Matched interaction type | Available Pose data and capture state are real backend values. |
| Figma Mobile Control | Compact header, stacked cards, fixed bottom navigation | Matched mobile hierarchy | Secondary explanatory copy collapses to protect motion controls at 390 px. |
| Figma Settings | Product cards, statuses, advanced disclosure | Close visual match | Unsupported values are explicitly unavailable; engineering tools remain behind Advanced. |
| Supplied PDF: Library | Product-card library and tabs | PDF-derived visual match | Exact Library Figma node context was unavailable, so the PDF plus the shared token system was used. |
| Supplied PDF: Vision | Camera canvas, source selector, tracking/follow side panel | PDF-derived visual match | Exact Vision Figma node context was unavailable; selector is single-source and disabled by contract. |

Material mismatches found during browser comparison and fixed included the mobile Control
Stop overlap, raw Cartesian floating-point tails, Studio mobile button wrapping, and drawer
focus restoration. The final surfaces keep the Figma purple accent, light workspace,
rounded panels, clip timeline, Viewer proportions, product Settings hierarchy, source
selector, drawer behavior, and mobile overflow constraints.

## Verification (historical redesign snapshot)

| Check | Result |
|---|---|
| `make test` | PASS: backend 666/666; frontend 289/289 across 30 files |
| `make lint` | PASS: Ruff; mypy 244 files; ESLint; TypeScript |
| `make format-check` | PASS: 244 backend files already formatted |
| `make build` | PASS: Vite 6.4.3; 1,674 modules transformed |
| `make schemas` + tracked diff | PASS: generated schemas are deterministic; no schema diff |
| `uv lock --check --project backend` | PASS: 71 packages resolved without lock changes |
| `uv pip check --python backend/.venv/bin/python` | PASS: 69 packages compatible |
| `backend/.venv/bin/python -m pip_audit` | PASS: no known vulnerabilities; local non-PyPI project skipped as expected |
| `npm --prefix frontend audit --audit-level=high` | PASS: 0 vulnerabilities |
| `npm --prefix frontend audit --omit=dev` | PASS: 0 vulnerabilities |
| Isolated startup/camera/hardware policy tests | PASS: 32 tests; no bus factory, no `cv2` import, synthetic-only, real Follow refused |
| `git diff --check` | PASS |

The backend suite emits one existing `StarletteDeprecationWarning` about the current
`httpx`/`starlette.testclient` pairing. It does not affect the pass result but should be
handled in dependency maintenance.

### Bundle and chunk result

The production build emits both URDF files and all fourteen STL files and splits the Viewer
runtime through a dynamic import. Vite reports two chunks above its default 500 kB warning:

- `index-Bzu852Xt.js`: 608.56 kB / 171.66 kB gzip.
- `viewerRuntime-CcXTJZka.js`: 586.14 kB / 149.52 kB gzip.

This is a documented performance limitation, not a correctness failure. A later explicitly
scoped performance pass should split additional route/vendor code and measure actual loading
before changing thresholds.

## Backend/API changes and safe degradation

No backend API or backend source was changed. Consequently:

- Cartesian continuous press-and-hold was not invented: Cartesian arrows use the existing
  bounded discrete endpoint; Joint long-press alone uses the renewable Deadman lease.
- Camera source switching remains disabled because only a single configured provider is
  exposed and no source-switch endpoint exists.
- `Free`, quick zero calibration, automatic connection, camera rotation, and camera mirroring
  are visibly unavailable instead of writing unsupported state.

## Known limitations and release blockers

1. User ownership and authorization for the V1/V2 model assets is directly recorded; no
   standalone named asset license was supplied or inferred. This is no longer an
   unknown-rights model-asset blocker.
2. Complete Three.js and `urdf-loader` license texts are not yet tracked for distribution.
3. Library and Vision used the supplied PDF as a fallback because exact Figma node context
   was unavailable.
4. Cartesian has discrete jog only; no backend Cartesian Deadman lease exists.
5. Camera source selection is single-source/read-only.
6. Two JavaScript chunks exceed Vite's default 500 kB warning threshold.
7. V1's fixed-base Viewer derivative removes the movable J10 degree of freedom but preserves
   the authored static rail-like base mesh. It does not constitute measured rail-less
   physical geometry, frames, TCP, or field verification.
8. Real-hardware field acceptance and real-camera field acceptance were not performed and
   remain required before any production claim.
9. CI was not run because no commit was pushed and no PR was created.

## Git state (historical redesign snapshot)

| Item | Result |
|---|---|
| Starting commit | `e777df43f2d8e522c044f8ae8c23db8d808d18a8` |
| Final commit at report time | None; this snapshot was subsequently integrated by `9da6853` |
| Branch | `codex/frontend-figma-redesign` |
| Commit table | No task commits created |
| Push / PR | Not performed; no PR URL |
| Working tree at report time | Contained the frontend implementation and evidence; no longer a statement about the current repository |

## Safety and isolation declaration

- No serial port was opened.
- No serial device enumeration was performed.
- No servo scan was performed.
- No servo register was read.
- No servo register was written.
- No torque command was sent.
- No real Home command was sent.
- No real motion command was sent.
- No real calibration was read or modified.
- No physical robot was moved.
- No real camera was opened.
- No camera enumeration was performed.
- All frontend motion verification used Dry Run, simulation, synthetic, fixture, or isolated adapters.
- Timeline scrubbing is simulation-only and does not command hardware.
- The V1/V2 3D viewer is visualization-only and has no direct actuator access.
- Real-hardware field acceptance remains required.
