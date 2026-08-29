# Operator guide

## Release status

MOMO Studio `0.1.0-rc1` is a local-first release candidate. Dry Run is validated. Real
hardware field acceptance remains required. V1 and V2 are physical variants, not
software versions.

The Stage 8 software gate, Dry Run browser acceptance, and final P1=0/P2=0 independent
audit pass. The production Feetech adapter has synthetic-SDK contract coverage, but do
not treat that software evidence or the release banner as proof that a physical robot,
Calibration, geometry, timing, or Stop behavior has passed field acceptance.

The safe repository defaults are:

```text
server_host: 127.0.0.1
server_port: 8000
control_mode: DRY_RUN
hardware_access_policy: DISABLED
commissioning_motion_test_enabled: false
real_motion_enabled: false
feetech_production_motion_adapter_enabled: false
hardware_startup_enabled: false
hardware_local_config_enabled: false
robot_unit_id: ""
camera_access_policy: SYNTHETIC_ONLY
live_camera_device_id: ""
live_camera_local_config_enabled: false
field_acceptance_checklist_version: "1"
```

There is no writable Field Acceptance status setting. Startup begins with a pending
legacy scalar internally and derives every usable capability only from semantically
resolved evidence.

Starting the backend does not connect, enumerate, scan, home, calibrate, enable torque,
move a Servo, or open/enumerate a camera.

## Local installation and verification

Use Python 3.11 or newer, `uv`, and a current Node.js/npm release:

```bash
make install
make test
make lint
make format-check
make build
make schemas
make audit
```

Create an ignored `config/local.yaml` containing at least the reviewed bind decision:

```yaml
server_host: 127.0.0.1
server_port: 8000
```

Start the backend and frontend in separate terminals. The supported backend command
requires that explicit local path, uses its validated host and port exactly, and disables
Uvicorn access logs so rejected credential-like query strings are not retained:

```bash
make dev-backend LOCAL_CONFIG=config/local.yaml
make dev-frontend
```

The development UI uses the local API proxy. The release build may instead be served
by the same backend when static hosting is explicitly configured.

When same-backend static hosting is enabled, the built React bundle uses relative local
assets and extensionless SPA refresh fallback. Missing API routes and missing assets stay
404, `index.html` is `no-store`, `/docs` and `/redoc` are disabled, and no CDN/Internet
asset is required. This is still the same React UI, not a second GUI or a Tauri native
application.

## Read-only live camera preview

This optional mode displays one explicitly identified local camera. It does not scan or
enumerate devices, save frames, record video, select or detect targets, start tracking,
or enable Follow. It is independent from robot hardware policy and does not grant any
motion capability.

Install the optional camera dependency:

```bash
make install-camera
```

Choose the device ID outside MOMO Studio, then place only that reviewed ID in ignored
`config/local.yaml`. Numeric IDs must be canonical decimal indexes such as `0` or `1`.
Never commit a device ID or local camera path.

```yaml
camera_access_policy: LIVE_CAMERA_ALLOWED
live_camera_device_id: "<reviewed-local-camera-id>"
live_camera_local_config_enabled: true
vision_frame_width_px: 1280
vision_frame_height_px: 720
vision_max_fps: 30
```

Restart the backend with that local file. Startup validates and composes a closed source
but performs no OpenCV import and no camera open. On Vision, confirm `LIVE_CAMERA_ALLOWED`,
`CLOSED`, and `READ ONLY CAMERA`, then press **Open live camera**. The request carries an
explicit read-only confirmation; the backend imports OpenCV, opens only the configured
ID, validates a first JPEG frame, and begins the bounded no-store stream. Press
**Close live camera** before unplugging or leaving the workflow. Backend shutdown also
releases an open device.

If opening fails, verify that another application is not using the camera and that the
ignored ID is correct. Change the local file and restart; the product deliberately has
no camera-enumeration endpoint. Return to the safe default by restoring
`SYNTHETIC_ONLY`, an empty ID, and `live_camera_local_config_enabled: false`.

## Dry Run workflow

1. Open Control, confirm `DRY RUN`, `Hardware DISABLED`, the intended V1/V2 variant, and
   the exact enabled-joint set.
2. Connect the in-memory robot. Use Joint/Cartesian controls, FK/IK, and Stop. Jog must
   be held; pointer release, loss of focus, network loss, or lease expiry stops it.
3. Capture immutable Poses. Create Motions in Library or create/recover a Draft in
   Studio. Set transition mode, duration, hold, and easing explicitly.
4. Preflight before playback. Review every check, the exact digest, path, duration, and
   violations. Play, pause, resume, Stop, rate, and loop remain bound to that prepared
   revision and the single active-motion slot.
5. In Vision, start only the Synthetic source, select a frame-bound ROI or deterministic
   fixture target, then start Follow. Follow owns one renewable lease and stops on
   stale/lost/low-confidence frames, conflict, disconnect, fault, expiry, or Stop.
6. Disconnect when finished. A saved runtime connection flag never reconnects anything.

Dry Run `STOPPED` means the in-memory executor stopped at its last accepted sample. It
is not a physical emergency-stop guarantee.

## Commissioning and Real-hardware boundary

Do not attempt Real operation until every item in
[`real-hardware-acceptance.md`](real-hardware-acceptance.md) has been performed by an
authorized field team with the correct physical robot and a tested physical E-stop.

Commissioning follows one evidence sequence, never “mark passed, then test”:

```text
0 Physical preparation
1 Read-only commissioning
2 Calibration
3 Pre-motion safety checks
4 Restricted joint motion test
5 Joint motion acceptance
6 Kinematics verification
7 Cartesian acceptance
8 Playback acceptance
9 Vision Follow acceptance
10 Final review
```

The three session purposes are independent. `COMMISSIONING_READ_ONLY` allows explicit-ID
diagnostics and Calibration capture only. `COMMISSIONING_MOTION_TEST` allows only one
separately armed, low-speed, bounded relative joint test under the backend deadman.
`REAL_MOTION` allows only production capabilities backed by current evidence. A purpose
never upgrades; changing purpose requires another confirmation and session.

For Phases 1–3, configure a stable `robot_unit_id` in ignored local configuration and
verify the masked unit, variant, Profile, Device, and Calibration fingerprints in
Settings. Request the read-only session, connect only the explicit device/Servo IDs, run
diagnostics, create or revise Calibration, and complete pre-motion checks. No write,
scan, Home, Jog, or motion is available. The committed pre-motion record embeds the typed
read-only diagnostic snapshot. After the required READ_ONLY → FULL restart, bootstrap
restores capability only if exact joint/Servo coverage, mode, torque-off state,
raw/logical mapping/bounds, timestamp relationship, and current bindings all revalidate.

Phase 4 is a visibly separate Settings → Commissioning workflow, not the Control page.
It requires `FULL` policy and the independent default-false
`commissioning_motion_test_enabled` switch, but not final acceptance, production
`real_motion_enabled`, or verified Kinematics. Keep the tested physical E-stop ready and
workspace clear. Press and hold `-` or `+` for one joint; release, pointer cancellation,
blur, hidden visibility, route change, network loss, session/lease expiry, operator Stop,
or backend shutdown ends the attempt. `STOP TEST` is a software request and must not be
represented as equivalent to the physical E-stop.

Complete positive and negative direction plus fresh logical/raw readback evidence for
every enabled joint: V1 uses `j11`–`j15`; V2 uses `j10`–`j15`. Joint acceptance is then
derived from those records. Kinematics verification uses at least three independently
measured TCP points; the backend—not the browser—must capture the corresponding fresh
joint states. It creates a local evidence overlay and does not alter the tracked
provisional YAML. The release candidate has no physical snapshot adapter and does not
restore persisted Kinematics authority after restart, so Phase 6 remains unavailable
until that adapter is reviewed and must be repeated after restart. Cartesian, Playback,
and Vision Follow each require their own later acceptance evidence. There is no Accept
All or writable global `PASSED` action.

Operator authority is carried by a same-origin HttpOnly cookie, not returned to or stored
by JavaScript. The global UI context restores only the backend session summary,
capabilities, expiry, and structured blocked reasons. Refresh never creates a session;
backend restart invalidates it. Control, Library, Studio, and Vision all consume this
same summary.

The release candidate's committed configuration cannot pass the physical gates. The
optional Feetech dependency, goal write, software/physical Stop, physical E-stop, and
Real Kinematics remain pending field verification. Fake workflow success proves only the
software path.

## Calibration workflow

Calibration is protected and joint-explicit. When none exists, the workflow starts a
Profile-bound incomplete draft; missing capture values remain empty rather than becoming
zeroes. It reads only the selected configured Servo's current position and cannot move,
write, change mode, toggle torque, or scan. For each enabled joint, enter the observed
logical value and confirm direction, Home, phase, raw bounds, round-trip error, and the
preview fingerprint. A complete validated first draft saves atomically as Revision 1;
later recalibration saves Revision N+1 and preserves the prior backup. Rollback is
explicit and forward-only. Calibration completion does not grant motion: current staged
evidence for the requested capability and a new purpose-specific session are still
required. Example Calibration cannot be promoted.
Legacy import requires a separate exact confirmation and reviewed input.

## Backup and recovery

See [`backup-and-restore.md`](backup-and-restore.md). Export is deterministic and omits
runtime connections, secrets, serial paths, logs, camera paths, and Calibration unless
explicitly requested. Always run import preview first, inspect migrations/collisions,
verify the digest, then perform the separately confirmed restore before its five-minute
one-use preview grant expires. The web API accepts bytes, never a server filesystem path.
Restore writes a durable WAL intent before the first entity, uses exact final revisions,
and recovers/compensates any surviving transaction before the application serves traffic.
An invalid or unrecoverable journal blocks startup; do not delete it manually. This is
process-crash atomic in the supported one-backend, server-owned repository configuration.

## LAN operation

Localhost is the default and recommended mode. LAN mode requires an explicit non-loopback
configuration, a strong token of at least 32 characters, and exact HTTP Origins with no
wildcard. Every browser Origin must use the exact API bind host and HTTP scheme; the UI
port may differ. Other hosts, aliases, HTTPS Origins, public/wildcard binds, proxy
headers, tunnels, and UPnP are unsupported. REST, WebSocket, and Vision requests are
authenticated; control commands are rate limited; tokens, full paths, and serial
identifiers are redacted from logs.
In Settings, exchange the long-lived bearer once for the backend's short-lived HttpOnly
cookie, then clear it from the field; the UI retains only non-secret expiry metadata and
offers explicit revoke. Fetch and WebSocket requests use that cookie without a query
credential, browser storage, or JavaScript-readable session token. Never put a long-lived
token in a URL, commit it, or expose the service through a tunnel, UPnP, or public bind.
Established Robot WebSocket and Vision streams are reauthorized on each publish/frame,
so expiry or revoke closes them. Stage 8 LAN is HTTP-only and should be used only on a
trusted private network; TLS/reverse-proxy deployment needs a separate security review.
See [`security.md`](security.md).

## Fault response

- Press the visible software Stop, then use the physical E-stop whenever physical state
  is uncertain.
- Do not retry repeatedly after a bus, readback, divergence, partial-write, power, or
  network fault. Preserve the audit record and last structured error.
- Revoke the Operator Session, disconnect if safe, remove power under the field procedure,
  and investigate before reauthorization.
- Corrupt persisted entities are isolated rather than guessed. Restore only after a
  preview and backup; never edit runtime/calibration data while the backend is active.
- Request audit is structured and bounded. Motion submissions record request/command/
  robot identity, Dry Run mode, preflight outcome, duration, and safe error code; tokens,
  local paths, URLs, and serial/device identifiers are redacted. Audit is correlation
  evidence, not a substitute for the physical field record.
