# ADR 0023: Capability-bound production motion and exact executable plans

- Status: Accepted
- Date: 2026-08-30

## Context

ADR 0019 requires capability-specific field evidence for production Joint, Cartesian,
Playback, and Vision Follow. ADR 0022 later unified DRY_RUN and REAL behind the same
product application services and executor ports. That runtime consolidation is an
architecture decision; it does not replace the field-acceptance decision.

The first unified REAL implementation accidentally used the pre-motion/manual base for
Joint, Cartesian, and Playback readiness. It could therefore issue a production session
without the verified Profile, Physical Stop, capability acceptance, and Kinematics
evidence required by ADR 0019. Its command adapter also generated the samples it would
execute after the Motion Safety Gateway had returned, then constructed a new accepted
preflight report. The checked path and executed path were not necessarily the same
artifact.

The architecture cleanup ledger compounded the ambiguity by describing ordinary
production Joint/Home/Cartesian and Studio Playback as the field-acceptance surface and
by saying Playback needed no Playback acceptance. That statement conflicts with ADR
0019 and cannot remain an authorization rule.

## Decision

ADR 0019 remains authoritative for production capability evidence. ADR 0022 remains
authoritative for the single UI/API/application/port architecture. A unified runtime
does not imply a unified grant.

Production REAL capabilities require these current, unit-bound conditions in addition
to the common startup, explicit-local-config, exact-device, exact-Servo-ID, dependency,
verified-Profile, complete-Calibration, Physical Stop, and fresh-operator-session gates:

| Execution capability | Additional current evidence |
|---|---|
| Joint, Home, Pose Goto, Studio keyframe Goto | Joint Motion acceptance |
| Cartesian step or bounded Cartesian hold | Joint Motion acceptance, Kinematics verification, Cartesian acceptance |
| Joint-only Playback | Joint Motion acceptance and Playback acceptance |
| Playback containing any `CARTESIAN_LINEAR` segment | Joint Motion acceptance, Kinematics verification, Cartesian acceptance, and Playback acceptance |
| Vision Follow | Joint Motion acceptance, controller-required Kinematics verification, and Vision Follow acceptance |

`COMMISSIONING_MOTION_TEST` remains the only implemented pre-production motion-test
purpose. It remains single-joint, bounded-delta, deadman-controlled, independently
confirmed, and non-upgradeable. Ordinary `REAL_MOTION` cannot be used to manufacture
the evidence that authorizes itself. Future Cartesian or Playback field tests require a
separate ADR and purpose-limited workflow. Until such a workflow exists, those evidence
transitions remain Fail Closed.

Every `REAL_MOTION` session freezes an explicit map from capability to current evidence
UUID. Geometry-dependent scopes also freeze the current Kinematics verification UUID and
fingerprint. The former `field_acceptance_evidence_id` may remain only as a deprecated
Joint Motion compatibility alias. A session receives only the scopes whose evidence is
current when it is issued. Evidence, Profile, Calibration, Device, unit, Kinematics, or
software-context changes invalidate the session. A session is never upgraded in place;
new evidence requires a new confirmation, session ID, token, expiry, and immutable
evidence snapshot.

The final executable trajectory is one immutable artifact:

```text
command intent
  -> compile exact time-stamped samples
  -> validate every sample and transition
  -> calculate the immutable digest
  -> publish one PreparedExecutableTrajectory and its preflight
  -> REAL executor consumes that exact object and digest
```

An adapter may map reviewed logical samples to reviewed raw goals, but it may not
interpolate a new path, mutate samples, replace the digest, or construct an accepted
preflight report. Joint/Home and bounded continuous commands must therefore compile their
exact samples before final preflight just as Cartesian and Playback do. A continuous
deadman command must also revalidate its lease/fence before every write; pre-generating a
long path never permits writes after lease expiry or Stop.

Priority Stop increments an execution/write fence. Queued work from an older fence may
not begin after Stop or Close. Blocking SDK calls remain non-hard-real-time: if the SDK
cannot prove that an in-flight physical write was cancelled, the result is
`SAFETY_STATE_UNCERTAIN`, not a successful physical stop. Software Hold is not a physical
E-stop and cannot create Physical Stop evidence.

Torque is an explicit execution lifecycle. Authorization is rechecked before enable;
partial enable is recorded and rolled back best-effort; cleanup attempts every configured
Servo; any incomplete transition remains safety-uncertain. Startup never enables torque.

## Compatibility and supersession

This ADR clarifies, rather than replaces, ADR 0019 and ADR 0022:

- ADR 0019 defines which evidence authorizes each production capability.
- ADR 0022 defines the shared product runtime and dependency direction.
- ADR 0023 binds those decisions to immutable session evidence and to the exact
  preflighted executable artifact.

It supersedes any text in `docs/architecture-cleanup.md` or the ADR 0022 implementation
note that says ordinary production motion is a field-test bypass, that Joint acceptance
alone authorizes Cartesian/Playback, or that Studio Playback has no Playback gate.

## Consequences

- A freshly calibrated unit with no acceptance evidence cannot obtain a production
  motion session.
- A writable or legacy global `PASSED` setting cannot authorize motion.
- A session can expose Joint while Cartesian, Playback, or Vision remain unavailable.
- Playback authorization depends on the prepared trajectory's actual segment kinds.
- Tests using Fake/Bomb/blocking adapters can prove software gating, digest identity,
  and fence behavior, but cannot establish physical field acceptance.
- Physical Stop, torque behavior, Feetech timing, and cancellation remain independently
  field-verification-gated for each exact robot unit.
