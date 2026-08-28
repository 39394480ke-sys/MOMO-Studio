# ADR 0016: Local-only default and explicit LAN security

- Status: Accepted
- Date: 2026-08-24
- Decision scope: Stage 8 release-candidate network and audit boundary

## Context

MOMO Studio controls safety-relevant robot workflows and serves live-looking
Vision surfaces. Local development previously relied on the application being
reached only from the same host. Stage 8 must define a usable LAN option without
turning a convenience setting into public exposure, leaking long-lived secrets
through URLs, or allowing request/session/log state to grow without bounds.

Browser REST, WebSocket, and image/stream requests use different credential
transports. A CORS-only decision would not protect non-browser clients, while a
REST-only bearer dependency would leave WebSocket and Vision inconsistent.
Operational audit is needed, but raw request bodies, tokens, serial identifiers,
and absolute paths are themselves sensitive and unlimited log files are a local
availability risk.

## Decision

1. The default exposure mode is `LOCAL_ONLY`, bound to `127.0.0.1`. The pure
   domain policy also accepts the other explicit loopback spellings.
2. LAN is a separate explicit decision requiring `lan_enabled=true`, a concrete
   private bind address, authentication, and at least the Origins required by the
   chosen UI deployment. Wildcard/unspecified/public binds are rejected. MOMO
   Studio will not implement UPnP, port forwarding, public hosting, or tunnels.
3. Browser Origin is normalized and compared exactly. Wildcard CORS is forbidden.
   Origin validation complements authentication; it does not replace it.
4. A strong random long-term token is supplied only by ignored local
   configuration or a process secret source. The runtime stores only a keyed
   digest and compares digests in constant time. Long-term credentials are never
   accepted from URL queries.
5. One verifier serves REST, control, WebSocket, and Vision. Browser clients may
   exchange the long-term token for a bounded, scoped, expiring session delivered
   through a protected cookie or short-lived WebSocket subprotocol.
6. Control requests consume a bounded per-principal rate limit. Session and rate
   tables have hard capacities and deny on capacity instead of growing or
   silently resetting an active principal.
7. Request bodies have declared and streamed byte bounds. Backup upload has an
   independent 32 MiB bound.
8. Every HTTP request produces a structured event with request/command/robot
   identity when available, source, mode, preflight, outcome, duration, and safe
   error code. Query strings and bodies are not audit fields.
9. Recursive redaction removes credentials/sessions and absolute paths and
   partially masks serial identifiers. The default sink is bounded memory. The
   optional JSONL sink has a fixed server-side filename, private permissions,
   symlink protection, a byte cap, and bounded rotations. No API accepts its path.
10. None of these decisions weakens hardware authorization, calibration,
    reachability, motion preflight, operator confirmation, lease expiry, or
    physical E-stop requirements.

## Consequences

- A default checkout remains reachable only on its host and requires no network
  discovery.
- LAN setup is intentionally more work: operators manage a token, exact Origins,
  firewall scope, and preferably TLS. A bare `0.0.0.0` convenience bind is not an
  accepted product configuration.
- Browser session issuance must be composed alongside middleware and every route
  must select the correct REST/control/Vision/WebSocket helper. Missing coverage
  is a release blocker.
- Restarting invalidates in-memory sessions. This is an acceptable secure default
  for a local operator application.
- Audit storage is bounded and redacted, so it is useful for correlation rather
  than a complete replay of sensitive input.
- Audit-volume failure is observable operationally but does not rewrite the
  outcome of an already completed Stop.

## Alternatives rejected

- Bind all interfaces by default: exposes the control surface through host/network
  configuration the operator may not understand.
- CORS without authentication: protects only cooperating browsers.
- A token in WebSocket/Vision query strings: URLs are routinely retained in
  history, proxy, analytics, screenshot, and server logs.
- A process-global unbounded session/rate dictionary: attacker-controlled memory
  growth and rate-limit reset behavior are unacceptable.
- Raw framework access logs as the audit record: they omit command/preflight
  semantics and commonly leak queries, paths, and headers.
- Unlimited JSONL: turns normal operation or an attacker into disk exhaustion.

## Verification

Stage 8 focused tests cover loopback/LAN decisions, wildcard rejection, strong
digest-only authentication, query credential denial, session scope/expiry,
bounded rate/session state, strict Origin responses, request body limits,
redaction, bounded audit rotation, and structured request audit. CI repeats these
tests with model downloads blocked and runs separate hardware/camera isolation
evidence.
