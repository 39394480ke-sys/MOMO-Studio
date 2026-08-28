# Local and LAN security

MOMO Studio is local-only by default. Starting the application must not scan a
network, open a tunnel, configure UPnP, or silently change the bind address. The
default decision is `LOCAL_ONLY` on `127.0.0.1` with real motion and hardware
startup independently denied.

## Exposure decisions

`NetworkSecurityPolicy` is a pure decision object. It does not bind a socket.

- `LOCAL_ONLY` accepts only `127.0.0.1`, `::1`, or `localhost`.
- `LAN` requires `lan_enabled=true`, authentication, and a concrete private IP.
- Wildcard (`0.0.0.0`/`::`) and public IP binds are rejected by the security
  policy, including in LAN mode.
- LAN never implies Internet exposure. MOMO Studio has no port-forwarding,
  discovery, tunnel, or UPnP feature.
- Every browser Origin is compared with a normalized exact allowlist entry.
  `*` and opaque `null` Origins are rejected, and responses never emit wildcard
  CORS.
- The Stage 8 server is HTTP-only. Every LAN browser Origin must therefore use
  `http`, the exact API `bind_host`, and an explicit/normalized port; only the UI
  port may differ. Cross-host and HTTPS Origins are rejected. This same-scheme,
  same-host rule keeps the `SameSite=Strict` session cookie same-site and is not
  a general reverse-proxy/TLS configuration.

An operator who deliberately enables LAN mode must put the capability-bearing
values in an ignored local configuration, not `config/default.yaml`. Do not
commit a LAN token, device port, camera identifier, or local calibration.

The supported server entry point is `momo-studio-serve --local-config PATH` (or
`make dev-backend LOCAL_CONFIG=PATH`). The path is required and must exist. Host
and port have no CLI override: the entry point calls `load_settings()` with that
explicit local path, constructs the application before binding, and passes the
validated `server_host` and `server_port` to Uvicorn exactly. Local-only settings
cannot validate a wildcard or non-loopback host. Uvicorn access logging and proxy
header trust are disabled so a rejected query credential is not copied into an
access-log request target.

Generate token material with `generate_lan_token()`. It uses at least 256 random
bits. `SecurityService` validates the supplied token once, then retains only a
keyed digest. A weak or missing token makes LAN composition fail closed.

## Authentication surfaces

The same verifier protects REST, control, WebSocket, and Vision surfaces.
Control authorization additionally consumes the bounded per-principal rate
limit. The composition root should use these helpers consistently:

- `authorize_rest_request` for normal REST reads and library writes;
- `authorize_control_request` for motion, Stop-sensitive state changes, and
  restore;
- `authorize_priority_stop_request` for Stop/Follow-Stop so authentication is
  still required but an exhausted normal control rate bucket cannot delay Stop;
- `authorize_vision_request` for frame, stream, selection, tracking, detection,
  and Follow endpoints;
- `authorize_websocket` before `websocket.accept()`.

Long-term credentials are accepted only from `Authorization: Bearer ...`.
Credential-like query keys such as `token`, `access_token`, and `session` are
rejected even in local-only mode. A long-term token must never be placed in an
image URL, WebSocket URL, log field, analytics event, or browser storage.

For a browser client, Settings exchanges the long-term bearer credential through
`POST /api/v1/security/session`, immediately clears the JavaScript input, and retains
only non-secret expiry metadata. The backend delivers the one-time session in an
HttpOnly, SameSite=Strict cookie; every Fetch request uses `credentials: include`, and
the browser supplies the cookie to the same API WebSocket automatically. The cookie
helper supports `Secure` for a separately reviewed HTTPS composition, but the Stage 8
LAN policy is HTTP-only. Explicit revoke uses `DELETE /api/v1/security/session`.
No token is put in localStorage, sessionStorage, a URL query, or a JavaScript-readable
response field. Session grants
carry an explicit surface set and expire after 30 seconds to 12 hours; the
release-candidate default is five minutes. The service prunes expired grants and has a hard session
capacity. A short-lived session may alternatively use the
`momo.session.<token>` WebSocket subprotocol. Do not echo either credential into
application logs.

An established Robot WebSocket and Vision stream reauthorize before every bounded
publish/frame. Expiry, explicit revoke, or restart therefore terminates the stream
rather than leaving a credential valid for the lifetime of an already-open connection.
The LAN session exchange is the one endpoint that deliberately ignores a stale session
cookie while validating the newly supplied long-term Bearer credential; this permits
safe recovery after a backend restart. Other routes reject ambiguous multiple
credentials.

The Real-hardware Operator Session is a distinct, more narrowly scoped grant. Creating
one of the three immutable purposes sets `momo_operator_session` as an HttpOnly,
SameSite=Strict cookie scoped to `/api/v1` and marked Secure when the request uses HTTPS.
The response contains only token-free session evidence. Browser code, the global
`RealSessionContext`, LocalStorage, SessionStorage, URLs, logs, and audit events never
receive the raw token. A bounded legacy header remains only for non-browser/local-tooling
compatibility; supplying conflicting cookie/header credentials fails closed. Refresh
reads the existing backend summary, never auto-issues authority, and backend restart
invalidates all in-memory Operator Sessions.

The application factory must install `StrictOriginMiddleware`,
`BodySizeLimitMiddleware`, and `StructuredRequestAuditMiddleware`, store the
same `SecurityService` in `app.state.security_service`, and apply the relevant
dependency/helper to every protected route. Middleware is composable and does
not itself open the server socket.

## Bounds and denial behavior

- Request bodies have a declared and streamed byte cap. Malformed, duplicate,
  negative, or oversized `Content-Length` values fail closed. Backup routes also
  enforce their own 32 MiB raw-upload cap.
- Control rate limiting uses a bounded principal table. When that table is full,
  a new principal is denied rather than allocating memory or evicting an active
  principal to reset its limit.
- Session storage is bounded. Capacity exhaustion denies issuance.
- Invalid authentication returns a stable code without disclosing whether a
  token or session once existed.
- WebSocket Origin/authentication is checked before accept. A denied socket is
  closed with 4401 or 4403.
- Vision authentication is independent of image availability. A stream failure
  does not relax authentication or imply a capability.

Priority Stop remains an application safety rule. Authentication must not create
a lower-level raw-servo endpoint or bypass reviewed Stop handling, and the normal
control rate limiter must not block Stop. If policy requires authenticated Stop,
the client should keep a valid short session; the server must still expire leases
on disconnect or loss.

## Structured audit and redaction

Each HTTP request receives a bounded `request_id` and one structured audit event
with:

- `request_id`, optional `command_id`, `robot_id`, and authenticated principal;
- source, mode, and preflight summary;
- outcome, duration in milliseconds, HTTP status, and safe error code.

Routes/services put `command_id`, `robot_id`, `mode`, `preflight`, and `error_code`
into request state when that evidence exists. Stage 8 motion submission/Jog-start
routes publish the exact command ID, `primary` robot, `DRY_RUN` mode, and
`PENDING`/`ACCEPTED`/`REJECTED` preflight state. The middleware derives a bounded safe
HTTP error code when a route has no more specific code. It never logs the URL query or
request body.

Redaction runs recursively before an event reaches a sink:

- authorization, cookie, password, secret, session, token, and credential keys
  become `<redacted>`;
- absolute POSIX/Windows paths, file URIs, and colon-adjacent path text become
  `<redacted-path>`; HTTP URLs become `<redacted-url>`;
- serial/port identifiers retain at most a short suffix;
- depth, collection length, key length, and string length are bounded.

The default `BoundedMemoryAuditSink` is a fixed-size deque, so a process without
an audit directory cannot grow logs indefinitely. Deployments that need local
evidence may opt into `BoundedJsonlAuditSink`. It uses the fixed filename
`security-audit.jsonl`, private directory/file permissions, `O_NOFOLLOW`, a
per-event cap, a total file-size threshold, and a bounded number of rotations.
The directory is injected by trusted local composition; no API accepts a log
path. Audit I/O failure does not turn an already completed safety Stop into an
HTTP failure.

The release application disables the framework's CDN-backed `/docs` and `/redoc`
pages. `/openapi.json` remains available as local JSON and contains no CDN reference.
The React release build uses repository-installed modules and local relative assets;
security does not depend on an Internet/CDN fetch.

## Operator checklist

Before enabling LAN:

1. Keep control mode and hardware gates at their intended reviewed values.
2. Generate a new random token and store it only in ignored local configuration
   or a process secret source.
3. Bind a concrete private IP and list every exact HTTP UI Origin using that same
   host (the UI port may differ). Do not use a wildcard, alias, other host, or HTTPS
   Origin with the Stage 8 server.
4. Use LAN only on a trusted private network. Stage 8 does not provide TLS termination;
   adding TLS/reverse-proxy support requires a separate same-origin/cookie/proxy-header
   security review before bearer traffic can be considered protected on an untrusted
   network.
5. Confirm REST, WebSocket, and Vision all reject missing/invalid credentials.
6. Confirm request/body/rate/session limits and audit rotation in the deployed
   composition.
7. Confirm the host firewall does not expose the port beyond the intended LAN.

Rotate the long-term token after suspected disclosure. Restarting the service
invalidates every in-memory browser session; the long-term token verifier is rebuilt
from the still-configured secret and retains only a new keyed digest. Review only
redacted, bounded audit data; never copy local device configuration into a support
bundle.
