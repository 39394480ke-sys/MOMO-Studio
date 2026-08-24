# Operator guide

## Release status

MOMO Studio `0.1.0-rc1` is a local-first release candidate. Dry Run is validated. Real
hardware field acceptance remains required. V1 and V2 are physical variants, not
software versions.

The Stage 8 software gate, Dry Run browser acceptance, and final P1=0/P2=0 independent
audit pass; its dedicated commit is pushed and Draft PR #1 is open. Do not treat the
release banner as evidence that any field item or Feetech adapter behavior has passed.

The safe repository defaults are:

```text
server_host: 127.0.0.1
server_port: 8000
control_mode: DRY_RUN
hardware_access_policy: DISABLED
real_motion_enabled: false
hardware_startup_enabled: false
hardware_local_config_enabled: false
camera_access_policy: SYNTHETIC_ONLY
field_acceptance_status: PENDING
field_acceptance_checklist_version: "1"
```

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

First commissioning is intentionally read-only. It requires Real mode, `READ_ONLY`
hardware policy, startup and local opt-ins, a verified non-template Profile, an available
verified adapter, and one explicitly configured serial device/protocol/Servo-ID set. It
does not require an existing Calibration, `real_motion_enabled`, passed field acceptance,
or verified Kinematics.

For commissioning:

1. Open Settings and review every masked identity/fingerprint and blocked reason.
2. Ensure the physical E-stop is reachable and the workspace is clear.
3. Request a `COMMISSIONING_READ_ONLY` session with the exact confirmation.
4. Use Connect Read-Only. Connection opens only the configured device, pings only the
   configured IDs, reads bounded status, and never scans, homes, moves, or enables torque.
5. Run diagnostics and the joint-explicit Calibration capture. No motion control is
   available in this session.
6. Complete field acceptance and store its fingerprint-bound local evidence. End or
   retain the old session only for read-only work.

Real Motion is a second authorization. It requires `FULL` policy,
`real_motion_enabled`, the same opt-ins and exact device, a complete matching Calibration,
current Field Acceptance Evidence, and a newly confirmed `REAL_MOTION` session. Verified
matching Kinematics is additionally required for Cartesian, Cartesian Playback, and
Vision Follow. Never reuse a commissioning token; it cannot be upgraded. Tokens live in
backend/frontend memory only, expire, and fail closed after restart or context drift.

The release candidate's committed configuration cannot pass these gates. The optional
Feetech dependency remains unavailable until its exact package/API/license and physical
Stop semantics are verified.

## Calibration workflow

Calibration is protected and joint-explicit. When none exists, the workflow starts a
Profile-bound incomplete draft; missing capture values remain empty rather than becoming
zeroes. It reads only the selected configured Servo's current position and cannot move,
write, change mode, toggle torque, or scan. For each enabled joint, enter the observed
logical value and confirm direction, Home, phase, raw bounds, round-trip error, and the
preview fingerprint. A complete validated first draft saves atomically as Revision 1;
later recalibration saves Revision N+1 and preserves the prior backup. Rollback is
explicit and forward-only. Calibration completion does not grant motion: field acceptance
and a new Real Motion session are still required. Example Calibration cannot be promoted.
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
