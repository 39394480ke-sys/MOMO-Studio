# Stage 07: Vision and safe following

- Date: 2026-08-24
- Repository: `/Users/ke/Library/Mobile Documents/com~apple~CloudDocs/Code/MOMO-Studio`
- Branch: `codex/v1-autonomous-completion`
- Status: **COMPLETE / GREEN — P1=0/P2=0**
- Starting commit: `37783bdf8c01146d3a312980dbe4a25716e5468c`
- Ending commit: `dedbdabb9a35aefea01df05f0652214428305a93`
- Containing commit subject: `feat: add safe vision following`
- Remote state: pushed to `origin/codex/v1-autonomous-completion`

## Summary

Stage 7 replaces the Vision placeholder with a Synthetic-first, frame-bound target
selection and safe Dry Run Follow workflow. It adds strict Vision domain contracts,
ports and deterministic adapters, honest optional-provider capability reporting, a
bounded local stream, manual ROI, person/face fixture detection, tracking, Follow
controller/lease ownership, API routes, and a responsive frontend workspace.

The current automated gate passes 432 backend tests with one known
Starlette/httpx deprecation warning, including 34 focused Stage 7 core/Follow/API tests.
The frontend passes 190 tests across 14 files, including 16 focused Vision client/page
tests across 2 files. Ruff, Ruff format, strict mypy, ESLint, TypeScript, Vite build,
lock, schema, and npm-audit gates pass. Desktop/mobile browser acceptance and independent
final review pass P1=0/P2=0. Commit
`dedbdabb9a35aefea01df05f0652214428305a93` contains this Stage and is pushed.

## Access and provider boundary

The tracked default is:

```text
camera_access_policy: SYNTHETIC_ONLY
vision_source_id: synthetic-stage7
vision_frame_width_px: 640
vision_frame_height_px: 360
vision_max_fps: 12
vision_max_stream_clients: 4
```

The public policy vocabulary also includes `DISABLED` and `LIVE_CAMERA_ALLOWED`.
`DISABLED` composes no active source. `LIVE_CAMERA_ALLOWED` alone does not select or
open a camera: Stage 7 startup continues to use Synthetic, and no route invokes the
optional factory.

The OpenCV camera shell has no module-level `cv2` import. Its explicit factory checks
live policy, local enablement, device ID, and operator action before a lazy import;
construction still does not call `VideoCapture`. OpenCV was not added to the Python
manifest or lock. The executed task opened and enumerated no camera and downloaded no
model or cascade.

Synthetic person/face detection and tracking use known deterministic scene annotations.
They are fixtures for this source only, not general learned detectors. Optional OpenCV
tracker, HOG person, and Haar face capability rows remain unavailable and visible with
honest reasons. Exact package/model/cascade provenance remains a release blocker.

## Domain and frame identity

`FrameMetadata` binds a non-empty ID, source ID, aware capture timestamp, and explicit
dimensions. `NormalizedBoundingBox` adds finite normalized `x/y/width/height`, must have
positive size and remain inside the frame, and carries the complete originating frame
identity. `TargetSelection`, `Detection`, and `TrackingResult` preserve that identity
through detection/tracking and reject mismatch or staleness.

A new Follow frame ID must advance `captured_at` strictly. A different ID at an equal or
older timestamp stops with `FRAME_STALE`; a same-frame `LOST` or low-confidence
correction is accepted so it can cancel the old direction immediately. Tracking status
is explicit: `UNINITIALIZED`, `LOCKED`, `LOST`, `STALE`, or `FAULTED`.

The generator adds these transient-contract artifacts without changing a persisted
user-data schema:

- `vision-frame-metadata.schema.json`;
- `vision-tracking-result.schema.json`;
- `vision-follow-status.schema.json`.

## Follow controller and safety path

Confirmed operator intent provides dead zones, EMA alpha, gain, maximum step/rate,
confidence/freshness/lost thresholds, lease TTL, and explicit pan/tilt mapping/signs.
The mapping must be `VERIFIED_FOR_DRY_RUN`; each distinct joint must appear in the
Profile's explicit `enabled_joints` and be `REVOLUTE`/`deg`. This rejects the V2 rail,
unknown joints, and implicit fixed-joint assumptions.

The pure controller computes center error, EMA, dead zone, sign/gain, and bounded
increment. The application command factory combines that increment with a fresh Robot
snapshot. The command coordinator submits only through the injected high-level motion
application/gateway-facing protocol:

```text
TrackingResult
  -> FollowController
  -> VisionFollowCommandFactory
  -> VisionCommandCoordinator
  -> MotionApplicationService
  -> MotionSafetyGateway
  -> Dry Run executor
```

No Vision route/service imports a raw adapter, driver, or executor. Follow shares the
one motion slot and Real Follow is hard-blocked pending field verification.

Only one lease may be active. Heartbeat renews a bounded expiry. The following events
stop ownership and command production:

- operator Stop, browser disconnect, backend shutdown, or Global Stop;
- stale/non-advancing frame, sustained target loss, or low confidence;
- camera disconnect or tracker fault;
- Robot disconnect, fault, or stale state;
- motion conflict/rejection or lease expiry.

Target loss/low confidence suspends and cancels the current Vision command immediately,
then applies the bounded lost-target grace period. Centered targets still refresh Robot
lifecycle evidence, so frames and heartbeats cannot conceal an asynchronous disconnect
or fault. Lifecycle epoch fences prevent a start awaiting a Robot snapshot from
installing a lease after Global Stop or backend shutdown. Global Stop does not re-enter
motion cancellation from its registered hook; shutdown performs normal cancellation and
permanently closes the service.

## Bounded API surface

Stage 7 adds 11 method/path combinations across 10 unique HTTP paths:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/vision/capabilities` | Effective source/tracker/detector/stream capabilities and Real block reason |
| `GET` | `/api/v1/vision/status` | Latest frame, selection, tracking, Follow, and Robot state |
| `GET` | `/api/v1/vision/frame` | One no-store frame with identity headers |
| `GET` | `/api/v1/vision/stream` | Bounded no-store multipart latest-frame stream |
| `POST` | `/api/v1/vision/selection` | Select a normalized ROI on an exact retained frame |
| `DELETE` | `/api/v1/vision/selection` | Clear selection and active tracking/Follow ownership |
| `POST` | `/api/v1/vision/detect/{detector}` | Run `person` or `face` provider on an exact frame |
| `POST` | `/api/v1/vision/tracking/reset` | Reset tracker/selection state |
| `POST` | `/api/v1/vision/follow/start` | Start one explicit Dry Run Follow lease |
| `POST` | `/api/v1/vision/follow/{lease_id}/heartbeat` | Renew the matching lease |
| `POST` | `/api/v1/vision/follow/{lease_id}/stop` | Stop the matching lease and its Vision command |

The route layer accepts no camera device ID, server path, raw Servo value, driver
selector, executable sample, recorded-media request, or Real override.

## Resource limits

| Resource | Stage 7 contract |
|---|---|
| Source/FPS/resolution | One Synthetic source; default 12 fps at 640×360; configured maxima 30 fps and 1280×720 |
| Stream clients | Default 4, configurable 1-16 |
| Slow-client queue | One latest-value slot, no per-client backlog |
| Frame retention | At most 64 frames and 32 MiB encoded content; oldest removed |
| Encoded frame | 8 MiB domain cap; Synthetic PNG; no persistence/recording |
| Detection result | At most 100 detections per request |
| Follow ownership | One active lease; one active Vision dispatch; conflicts are rejected, not queued |
| Public lease TTL | Default `0.75 s`, bounded `0.25-2.0 s` |
| Public frame/lost thresholds | Defaults `0.5 s` freshness and `0.75 s` lost; maxima `2.0 s` and `5.0 s` |

Stream disconnect releases its client and stops an active Follow. Source failure is
sticky/fail-closed for the process lifetime. No Vision frame or target history becomes a
persisted user entity.

## Frontend surface

The Vision workspace shows the Synthetic/live status, effective Camera Policy, frame
age and identity, provider capabilities, manual pointer ROI, detector results, tracking
box/confidence/status, center/EMA error, dead zone, Follow lease state, Robot state,
Dry Run state, Stop, and the exact Real Follow blocked reason. Selection remains bound
to the frame visible at pointer-down, and overlay math supports non-default aspect
ratios.

Priority Stop, unmount, and loss of runtime connectivity compensate a late Follow-start
response by stopping the returned lease. Broken stream images and disconnected sources
fail closed. The page contains no photo, recording, media-library, gesture, or Cinematic
Director capability.

Real-app browser acceptance at 1440×960 and 390×844 exercised manual ROI and Synthetic
person detection (both LOCKED at 98%), Follow ACTIVE with EMA/tuning state, an accepted
gateway preflight and completed command with `hardware_accessed=false`, operator Stop to
`OPERATOR_STOP`, and navigation/unmount cleanup ending at `LEASE_EXPIRED`. Mobile
document/body/inner widths were 390 px, with a 324 px canvas and 350 px controls; warning
and error logs were `[]`. Target Lost/automatic Stop is separate automated backend and
component evidence, not a claimed browser action.

## Verification evidence

| Check | Current result |
|---|---|
| Backend pytest | PASS — 432 passed; one known Starlette/httpx deprecation warning |
| Focused Stage 7 core/Follow/API | PASS — 34 passed |
| Ruff | PASS |
| Strict mypy | PASS — 168 source files |
| Ruff format check | PASS — 168 files |
| Frontend Vitest | PASS — 190 passed / 14 files |
| Focused Vision client/page | PASS — 16 passed / 2 files |
| ESLint | PASS |
| TypeScript | PASS |
| Vite build | PASS — Vite 6.4.3; 1,638 modules; HTML 0.56/0.34 gzip kB; CSS 64.19/12.87; JS 422.12/121.76 |
| Generated schema determinism/current tree | PASS — three Stage 7 schemas included in deterministic full generation |
| `uv lock --project backend --check` | PASS — 44 packages |
| `npm --prefix frontend audit --audit-level=moderate` | PASS — 0 vulnerabilities |
| Python runtime vulnerability audit | Not rerun — no dependency/lock change; no pass inferred |
| Camera isolation | PASS — policy-first lazy-import Spy coverage; no real camera open/enumeration |
| Hardware isolation | PASS — Dry Run/Fake only; no serial/Servo path |
| Browser desktop/mobile Vision workflow | PASS — real app at 1440×960 and 390×844; Select/Detect/Follow/Stop/lease cleanup; logs `[]` |
| Automated Target Lost/auto-stop | PASS — focused backend/component coverage |
| Independent final audit | PASS — P1=0/P2=0 |
| Dedicated Stage 7 commit and push | PASS — `dedbdabb9a35aefea01df05f0652214428305a93` |

## Known limitations and open gates

- OpenCV is not installed; the optional live camera/tracker/detector composition is not
  exposed by a Stage 7 route.
- Synthetic detector/tracker behavior is fixture-specific, not general Vision.
- HOG/Haar package and asset provenance must be completed before distribution or use.
- Stream/API access has no Stage 8 LAN token/session boundary yet; local operation only.
- Real Follow remains blocked until independently verified Profile mapping, Kinematics,
  Calibration, live camera, device, Stop, operator-session, and field evidence exist.

## Current safety statement

All executed Stage 7 motion tests used Dry Run or Fake adapters. OpenCV was not added as
a dependency. No real camera was opened or enumerated, no frame/model/cascade was
downloaded or recorded, no serial/Servo operation was performed, no physical robot was
moved, and Real Follow remains blocked.
