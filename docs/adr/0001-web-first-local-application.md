# ADR 0001: Web-first local application

- Status: Accepted
- Date: 2026-08-23

## Context

MOMO Studio needs a local operator UI that works during development in a browser and can later become a desktop application without maintaining a second GUI. The Legacy project contains PyQt and web surfaces with overlapping concerns.

## Decision

Use a React/TypeScript web frontend and a local FastAPI backend. REST carries command/query APIs and WebSocket may later carry live state. Keep paths and transport configuration compatible with a future Tauri wrapper and local-network access.

## Alternatives

- Continue PyQt: rejected because it duplicates the desired web product and couples UI evolution to Python desktop code.
- Build Tauri immediately: deferred until the browser-based UI and trust boundaries stabilize.
- Remote/cloud-first service: rejected because hardware control and operator feedback are local and must not depend on cloud availability.

## Consequences

One UI can serve browser and future desktop packaging. The backend becomes an explicit safety/security boundary. Development needs two processes for now, and later packaging/network authentication require separate decisions.
