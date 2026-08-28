# Tauri packaging plan

## Decision for 0.1.0-rc1

Do not introduce a second GUI or a native Tauri project in this Stage. Keep the React
application as the only UI, verify a relative offline build and same-backend SPA hosting,
and treat Tauri as a later packaging adapter after field acceptance and distribution
licensing. This avoids expanding the trusted native surface during safety hardening.

## Existing packaging seams

- The frontend API base is configurable and defaults to relative `/api/v1`.
- Vite emits self-contained relative/local assets and uses no CDN or runtime internet.
- The FastAPI application can explicitly mount the built distribution with extensionless
  SPA fallback; API routes and missing asset paths remain 404 and `index.html` is
  `no-store`.
- Control API, Robot status, WebSockets, Vision stream, and authentication are never
  represented by an offline cache. An offline shell must display unavailable/stale,
  never a cached safe/connected state.
- Data repositories remain backend-owned. The browser receives no server path and cannot
  read arbitrary files.

## Proposed later architecture

1. Package the existing built React output as Tauri web assets without UI duplication.
2. Launch or connect to one loopback-only backend process using an OS-assigned port and
   per-launch random bearer credential delivered through a protected native channel.
3. Restrict Content Security Policy and Tauri capabilities to the minimum window/process
   integration. Disable arbitrary shell, filesystem, HTTP, updater, clipboard, and deep
   link access unless separately reviewed.
4. Store no Operator Session in native persistence, WebView storage, URL, command line,
   environment dump, crash report, or log. Backend restart invalidates it.
5. Keep serial/camera optional adapters behind the same backend gates. Tauri must never
   enumerate or open them directly.
6. Sign/notarize reproducible platform bundles only after dependency/license/SBOM,
   native-binary provenance, update signing, and incident rollback are approved.

## Required validation before implementation

- Pin Rust/Tauri/Node/Python/native toolchains and audit all licenses/vulnerabilities.
- Reproduce frontend and backend artifacts from clean offline inputs.
- Verify macOS/Windows path confinement, Unicode/case behavior, atomic backup/restore,
  lifecycle cleanup, single backend, port collision, crash recovery, and stale UI.
- Threat-model loopback request forgery, Origin, WebSocket/Vision authentication, token
  delivery, WebView navigation, CSP, updater, protocol handlers, and log/crash redaction.
- Repeat all Dry Run/browser/isolation/resource gates inside the packaged application.
- Perform Real field acceptance per supported OS/adapter/hardware tuple; packaging does
  not inherit acceptance from development mode.
