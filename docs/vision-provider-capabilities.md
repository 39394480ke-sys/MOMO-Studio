# Vision provider capabilities

This document describes the Stage 7 provider surface exactly as composed. It does not
claim live-camera, general-model, or Real Follow readiness.

## Camera access policy

| Policy | Effective Stage 7 behavior |
|---|---|
| `DISABLED` | Uses the disabled source. No source is imported, opened, or enumerated. |
| `SYNTHETIC_ONLY` | Default. Uses the deterministic in-memory PNG source. |
| `LIVE_CAMERA_ALLOWED` | Records that a live grant may be configured, but Stage 7 startup still composes the Synthetic source. There is no live-open route. |

A future explicit OpenCV construction must supply the live policy, explicit local
configuration, one explicit device identifier, and explicit operator action. The policy
check runs before the lazy `cv2` import. Source construction does not call
`VideoCapture`; only a later explicit `open()` may do so. No code enumerates devices.

Stage 7 did not add OpenCV to `backend/pyproject.toml` or `backend/uv.lock`. Normal
startup therefore neither imports OpenCV nor opens a camera. No detector/tracker asset
is downloaded.

## Composed capabilities

| Provider | Kind | Stage 7 state | Source and limits |
|---|---|---|---|
| `synthetic-frame-source` | Frame source | Available and active unless policy is `DISABLED` | MOMO-generated deterministic scene; no external model, storage, or recording |
| `synthetic-target-tracker` | Target tracker | Available | Tracks only the deterministic Synthetic scene; not a live-camera tracker |
| `synthetic-person-detector` | Target detector | Available | Scenario annotation fixture, confidence `0.99`; not a general learned detector |
| `synthetic-face-detector` | Face detector | Available | Scenario annotation fixture, confidence `0.97`; not a general learned detector |
| `bounded-passthrough-stream-encoder` | Stream encoder | Available | Passes already encoded PNG frames; no recording or transcode queue |
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
| Synthetic source | `synthetic-stage7` | One composed source |
| Frame rate | 12 fps | Configured maximum 30 fps |
| Frame size | 640 × 360 | Configured maximum 1280 × 720 |
| Stream clients | 4 | Configurable 1-16; the default is 4 |
| Fan-out backlog | One latest frame | Slow clients skip older frames; no per-client frame queue |
| Application frame history | Up to 64 frames | Also capped at 32 MiB encoded content; oldest frames are removed |
| Encoded frame | PNG in the Synthetic composition | Domain cap 8 MiB per encoded frame; `Cache-Control: no-store` |
| Detections | Latest requested frame | At most 100 results per request |

The stream is `GET /api/v1/vision/stream` using
`multipart/x-mixed-replace`. `GET /api/v1/vision/frame` returns one latest frame with
frame/source/timestamp headers. Metadata, selection, tracking, Robot state, and Follow
state are read through REST status; Stage 7 adds no Vision metadata WebSocket.

Closing a stream releases its client slot. If Follow is active, a browser-stream
disconnect stops the lease with `BROWSER_DISCONNECTED`. Frames are not saved to disk,
added to a media library, photographed, or recorded.

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
