# MOMO Studio documentation

This page is the navigation entry point for MOMO Studio `0.1.0-rc1`. Start with the
release-candidate summary and choose the section that matches the work you are doing.
Historical Stage reports are evidence records, not the current product guide.

## Product

- [Release candidate summary](release-candidate-0.1.0-rc1.md) — what this candidate
  contains, what was validated, and what remains blocked.
- [Software user-acceptance checklist](user-acceptance-checklist.md) — the user's Dry Run
  product acceptance procedure.
- [Product scope](product-scope.md) — first-version boundaries and excluded features.
- [Roadmap](roadmap.md) — post-candidate user acceptance and field-verification phases.
- [Final user-acceptance handoff](stage-reports/v0.1.0-rc1-user-acceptance-handoff.md) —
  candidate identity, evidence, limitations, and acceptance outcomes.

## Architecture

- [Architecture](architecture.md) — layers, runtime composition, data flow, APIs, and
  repository structure.
- [Domain model](domain-model.md) — Robot, Profile, Calibration, Pose, Motion,
  trajectory, Vision, authorization, and evidence contracts.
- [API audit](api-audit.md) — REST/WebSocket inventory, callers, scopes, and disposition.
- [Backup and restore](backup-and-restore.md) — deterministic export, preview, restore,
  and crash recovery.

## Using MOMO Studio

- [Operator guide](operator-guide.md) — installation, Dry Run workflow, commissioning
  boundary, recovery, and LAN operation.
- [Software user-acceptance checklist](user-acceptance-checklist.md) — Control, Library,
  Studio, Playback, Vision, Settings, responsive, and failure-state checks.
- [Release checklist](release-checklist.md) — repository and release gates.

## Motion and trajectory

- [Trajectory semantics](trajectory-semantics.md) — compilation, preflight, sampling,
  timing, and playback behavior.
- [Studio user workflow](studio-user-workflow.md) — authoring, validation, Save/Save As,
  conflicts, and limits.
- [Legacy action import](legacy-action-import.md) — explicit-source, default-dry-run
  migration tooling.
- [Legacy pose import](legacy-pose-import.md) — explicit-variant, default-dry-run named
  pose migration tooling.

## Vision

- [Vision provider capabilities](vision-provider-capabilities.md) — Synthetic and optional
  live-provider policies, bounds, tracking, and Follow leases.
- [ADR 0014: Vision access and Follow lease](adr/0014-vision-access-policy-and-follow-lease.md).
- [ADR 0020: Operator-controlled read-only live camera](adr/0020-operator-controlled-read-only-live-camera.md).

## Safety

- [Safety](safety.md) — deny-by-default hardware/camera policy, Motion Safety Gateway,
  deadmen, Stop truthfulness, evidence, and non-negotiable restrictions.
- [Security](security.md) — local/LAN exposure, authentication, bounds, and audit redaction.
- [ADR 0010: Unified Motion Safety Gateway](adr/0010-unified-motion-safety-gateway.md).
- [ADR 0015: Real-hardware authorization](adr/0015-real-hardware-authorization.md).
- [ADR 0016: Local and LAN security](adr/0016-local-and-lan-security.md).

## Commissioning

- [Raw ± direction bootstrap](raw-direction-bootstrap.md) — one-session current-unit Raw
  zero capture, fixed-count dual-sign checks, draft generation, and hardware-disabled
  verification boundary.
- [Commissioning Motion Test](commissioning-motion-test.md) — entry gates, backend hard
  envelope, deadman, permitted command, Evidence, API, and Stop limitations.
- [Staged Field Acceptance model](field-acceptance-model.md) — capability evidence,
  progress, staleness, and the removal of a writable global pass.
- [Kinematics field verification](kinematics-field-verification.md) — multi-point measured
  TCP workflow and local evidence overlay.
- [ADR 0018: Commissioning vs motion authorization](adr/0018-commissioning-vs-motion-authorization.md).
- [ADR 0019: Staged field acceptance](adr/0019-staged-field-acceptance.md).

## Real hardware acceptance

- [Real-hardware field acceptance](real-hardware-acceptance.md) — the separate Phase 0–10
  physical procedure. No checkbox is completed by software user acceptance.
- [Kinematics model audit](kinematics-model-audit.md) — provisional model facts,
  conflicts, and evidence still required.
- [Tauri packaging plan](tauri-packaging-plan.md) — deferred desktop packaging boundary.

## Development

- [Repository README](../README.md) — Quick Start, commands, project structure, status,
  and key limitations.
- [Release candidate summary](release-candidate-0.1.0-rc1.md) — current test and CI evidence.
- [API audit](api-audit.md) — route reproduction and CI mapping.
- [Third-party notices](../THIRD_PARTY_NOTICES.md) — dependencies, provenance, Legacy
  restrictions, and the pending project-license decision.

## Migration and Legacy

The Legacy source is read-only evidence pinned at commit
`ff8bbda0c2222cb57951c7913f7f12f5777b98fa`.

- [Legacy migration map](legacy-migration-map.md)
- [Legacy variant audit](legacy-variant-audit.md)
- [Legacy robot-core characterization](legacy-robot-core-characterization.md)
- [Legacy Kinematics characterization](legacy-kinematics-characterization.md)
- [Legacy action import](legacy-action-import.md)
- [Legacy pose import](legacy-pose-import.md)

## Architecture decision records

| Decisions | Topic |
|---|---|
| [ADR 0001](adr/0001-web-first-local-application.md)–[0005](adr/0005-single-active-robot-extensible-core.md) | Application shape, boundaries, data, persistence, and one active robot |
| [ADR 0006](adr/0006-profile-and-calibration-fingerprints.md)–[0009](adr/0009-kinematics-model-and-verification.md) | Fingerprints, access policy, runtime state, and provisional Kinematics |
| [ADR 0010](adr/0010-unified-motion-safety-gateway.md)–[0013](adr/0013-motion-draft-and-timeline-editor.md) | Motion safety, repositories, trajectory digest, and Studio drafts |
| [ADR 0014](adr/0014-vision-access-policy-and-follow-lease.md)–[0017](adr/0017-release-candidate-and-field-acceptance.md) | Vision, Real authorization, LAN security, and RC policy |
| [ADR 0018](adr/0018-commissioning-vs-motion-authorization.md)–[0019](adr/0019-staged-field-acceptance.md) | Commissioning separation and staged acceptance |

## Stage reports

Stage reports preserve implementation history and point-in-time evidence:

- [Stage 1 — Foundation](stage-reports/stage-01-foundation.md)
- [Stage 2 — Robot core](stage-reports/stage-02-robot-core.md)
- [Stage 3 — Kinematics and Control](stage-reports/stage-03-kinematics-and-control.md)
- [Stage 4 — Library](stage-reports/stage-04-library.md)
- [Stage 5 — Trajectory and Playback](stage-reports/stage-05-trajectory-and-playback.md)
- [Stage 6 — Studio](stage-reports/stage-06-studio-timeline.md)
- [Stage 7 — Vision](stage-reports/stage-07-vision-following.md)
- [Stage 8 — Release hardening](stage-reports/stage-08-release-hardening.md)
- [Commissioning authorization fix](stage-reports/commissioning-authorization-fix.md)
- [Final pre-merge hardening](stage-reports/final-pre-merge-hardening.md)
- [Autonomous V1 completion](stage-reports/autonomous-v1-completion.md)
- [Legacy V2 Library Import](stage-reports/legacy-v2-library-import.md)
