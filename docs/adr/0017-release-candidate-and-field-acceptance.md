# ADR 0017: Release candidate with mandatory field acceptance

- Status: Accepted
- Date: 2026-08-24

## Context

Stages 1–7 and Stage 8 software boundaries can be verified safely with Dry Run,
Synthetic Vision, fixture repositories, and Fake adapters. Geometry, wiring, loads,
physical Stop behavior, serial/SDK compatibility, Calibration, and camera behavior cannot
be truthfully certified without the actual unit and a controlled field procedure.

## Decision

Publish the software milestone as `0.1.0-rc1` with API release status
`FIELD_ACCEPTANCE_REQUIRED`. The product must simultaneously display:

```text
MOMO Studio 0.1.0-rc1
Dry Run validated
Real hardware field acceptance pending
```

Committed settings remain loopback, Dry Run, hardware Disabled, real motion false,
Synthetic camera, and field acceptance Pending. The Real matrix, Calibration workflow,
and executor are software-complete only to the extent proven by Fake adapters. The
field checklist is a release gate for every physical variant/unit/deployment tuple, not
an instruction to run hardware during autonomous development.

The same FastAPI backend may serve the built React SPA. Full Tauri integration is deferred
to avoid adding an unreviewed native trust/dependency surface. Backup/security/CI and
operator documentation are part of the candidate, while distribution still requires a
repository-license decision and exact third-party license collection.

## Consequences

- Dry Run acceptance and Real acceptance are reported separately; neither implies the
  other.
- Real readiness is expected to be Blocked in the shipped configuration and is not a
  release-candidate software failure.
- No unchecked field item may be marked passed, and no software result may claim physical
  movement/Stop/camera evidence.
- A later release can remove the field-required status only after documented physical,
  security, recovery, provenance, packaging, and independent review evidence is complete.
