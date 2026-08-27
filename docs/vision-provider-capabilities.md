# Vision provider capabilities

This document describes the current Synthetic workflow and the separately gated
read-only live-camera preview. It does not claim general-model, tracking, recording, or
Real Follow readiness for live frames.

## Camera access policy

| Policy | Effective Stage 7 behavior |
|---|---|
| `DISABLED` | Uses the disabled source. No source is imported, opened, or enumerated. |
| `SYNTHETIC_ONLY` | Default. Uses the deterministic in-memory PNG source. |
| `LIVE_CAMERA_ALLOWED` | Requires an explicit device ID and boolean opt-in from the selected ignored local file. Composes one closed read-only source; it does not open at startup. |

The live OpenCV construction requires the policy, explicit local configuration, one
explicit device identifier, and a confirmed operator action. The policy check runs
before the lazy `cv2` import. Source construction does not call `VideoCapture`; only
`POST /api/v1/vision/camera/open` can do so. The request contains no device ID. No code
enumerates devices. `POST /api/v1/vision/camera/close` releases the source through the
priority authorization path.

The optional `camera` dependency extra supplies `opencv-python-headless`; normal
installation omits it. Both Synthetic startup and authorized live-camera startup avoid
the import and device access until explicit Open. No detector/tracker asset is included
or downloaded.

## Composed capabilities

| Provider | Kind | Stage 7 state | Source and limits |
|---|---|---|---|
| `synthetic-frame-source` | Frame source | Available and active unless policy is `DISABLED` | MOMO-generated deterministic scene; no external model, storage, or recording |
| `synthetic-target-tracker` | Target tracker | Available | Tracks only the deterministic Synthetic scene; not a live-camera tracker |
| `synthetic-person-detector` | Target detector | Available | Scenario annotation fixture, confidence `0.99`; not a general learned detector |
| `synthetic-face-detector` | Face detector | Available | Scenario annotation fixture, confidence `0.97`; not a general learned detector |
| `bounded-passthrough-stream-encoder` | Stream encoder | Available | Passes already encoded PNG frames; no recording or transcode queue |
| `opencv-camera-source` | Frame source | Available only in the authorized live composition; initially closed | Explicit-ID local JPEG preview; no enumeration, persistence, recording, tracking, or Follow |
| `opencv-live-target-tracker` | Target tracker | Unavailable | Optional OpenCV live tracker is not loaded in the Synthetic session; no package/model was downloaded |
| `opencv-hog-person-detector` | Target detector | Unavailable | Describes OpenCV's built-in HOG descriptor only; no weights were downloaded |
| `optional-face-detector` | Face detector | Unavailable | Reserved placeholder for optional OpenCV Haar-based detection; no cascade/model was installed or downloaded by MOMO Studio |

`GET /api/v1/vision/capabilities` is authoritative. An unavailable provider remains
visible with `available=false`, `active=false`, its model source/notice, and a safe
reason. Detection failure is not converted into a fabricated empty success.

The HOG/Haar rows are capability descriptions, not dependency or redistribution
approval. Exact OpenCV package/version/license, HOG implementation provenance, and the
origin/license/checksum of any Haar cascade selected for distribution remain required.

## Frame, stream, and client bounds

| Resource | Default | Enforced limit/behavior |
|---|---:|---|
| Source | `synthetic-stage7` by default | One composed source; live starts `CLOSED` and requires explicit Open |
| Frame rate | 12 fps | Configured maximum 30 fps; live devices may negotiate a lower effective rate |
| Frame size | 640 × 360 | Configured maximum 1280 × 720; live metadata reports actual captured dimensions |
| Stream clients | 4 | Configurable 1-16; the default is 4 |
| Fan-out backlog | One latest frame | Slow clients skip older frames; no per-client frame queue |
| Application frame history | Up to 64 frames | Also capped at 32 MiB encoded content; oldest frames are removed |
| Encoded frame | PNG for Synthetic; JPEG for live preview | Domain cap 8 MiB per encoded frame; `Cache-Control: no-store` |
| Detections | Latest requested frame | At most 100 results per request |

The stream is `GET /api/v1/vision/stream` using
`multipart/x-mixed-replace`. `GET /api/v1/vision/frame` returns one latest frame with
frame/source/timestamp headers. Metadata, selection, tracking, Robot state, and Follow
state are read through REST status; Stage 7 adds no Vision metadata WebSocket.

Closing a stream releases its client slot. If Follow is active, a browser-stream
disconnect stops the lease with `BROWSER_DISCONNECTED`. Frames are not saved to disk,
added to a media library, photographed, or recorded.

In live mode, the stream cannot start while the source is `CLOSED`. Open validates one
real frame before returning; Close clears latest/history/selection/tracking state. The
UI does not mount the stream image before successful Open. Live selection, detection,
tracking, tuning, and Follow controls remain disabled, and the backend rejects those
operations independently.

## Follow capability

Follow is available only as confirmed `DRY_RUN` intent. The public start request uses
these defaults:

| Field | Default | Public bound |
|---|---:|---:|
| `dead_zone_x`, `dead_zone_y` | `0.08` | `0.0`-`0.45` |
| `ema_alpha` | `0.35` | `(0.0, 1.0]` |
| `gain` | `5.0` | `(0.0, 100.0]` |
| `max_step` | `2.0` deg | `(0.0, 15.0]` |
| `max_rate` | `5.0` deg/s | `0.2`-`20.0` |
| `confidence_threshold` | `0.5` | `0.0`-`1.0` |
| `frame_freshness_limit_s` | `0.5` | `(0.0, 2.0]` |
| `target_lost_limit_s` | `0.75` | `(0.0, 5.0]` |
| `lease_ttl_s` | `0.75` | `0.25`-`2.0` |

The current frontend initializes a deliberately explicit tuning request (`0.08`,
`0.08`, `0.35`, `0.5`, `2`, `4`, `0.55`, `0.75`, `0.5`, `2` in the table's field
order) rather than relying on omitted transport defaults. It derives the first two
enabled revolute/degree Profile joints for pan/tilt, uses explicit signs, and sends
`VERIFIED_FOR_DRY_RUN`; the backend independently revalidates membership/type/unit.

Follow reports raw and EMA center errors plus the last command. It stops on operator or
Global Stop, lease expiry, stale/non-advancing frame, sustained target loss or low
confidence, camera/browser disconnect, tracker fault, backend shutdown, robot
disconnect/fault/staleness, or motion conflict/rejection. Active Vision commands are
cancelled through the injected motion application surface. Real Follow reports blocked
and cannot be requested through this Stage 7 API.

## Generated contracts

Stage 7 adds three deterministic generated JSON Schemas:

- `docs/schemas/vision-frame-metadata.schema.json`;
- `docs/schemas/vision-tracking-result.schema.json`;
- `docs/schemas/vision-follow-status.schema.json`.

They document transient frame/tracking/Follow contracts. They do not create persisted
camera media, a recording schema, or a live-camera authorization token.
