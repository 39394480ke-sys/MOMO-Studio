# ADR 0007: Hardware access policy

- Status: Accepted
- Date: 2026-08-24

## Context

Dry Run versus Real describes operator-visible control intent, while permission to construct or call a hardware adapter is a deployment capability. Treating these as one boolean would make it easy for a UI/body/query option or Legacy compatibility flag to enable device I/O accidentally.

Stage 2 must preserve future vocabulary without providing a latent real-hardware path. Changing configuration to a more permissive value must not cause a scan, connection, read, write, or quiet fallback into an ambiguous mode.

## Decision

Model three independent gates:

- `ControlMode`: `DRY_RUN` or future `REAL` operator mode;
- `HardwareAccessPolicy`: `DISABLED`, future `READ_ONLY`, or future `FULL` deployment capability;
- `real_motion_enabled`: a coarse release gate that remains false in Stage 2.

The only valid Stage 2 combination is:

```text
control_mode = DRY_RUN
hardware_access_policy = DISABLED
real_motion_enabled = false
```

Settings validation rejects every other combination during application construction. Stage 2 does not downgrade `READ_ONLY`, `FULL`, or `REAL`; it fails closed with a configuration error before a hardware adapter can be selected. The additional enum values define future vocabulary only and confer no present capability.

The composition root provides only `DryRunRobotDriver`. There is no Feetech/serial adapter, optional Servo SDK dependency, discovery service, or raw bus port on the API surface. The `serial_port` setting remains inert compatibility shape and is never opened.

HTTP Connect accepts no body, query string, or requested mode. Robot status and every lifecycle response expose the effective policy and `hardware_accessed=false`. API routes depend on `RobotApplicationService`, never a concrete device adapter. The application service repeats the disabled-policy check before Connect as defense in depth.

Dry Run Stop affects only the in-memory runtime. `STOPPED` does not claim that a physical robot stopped. The result contract reserves `FAILED` and `SAFETY_STATE_UNCERTAIN` so a future Real implementation cannot turn uncertainty into ordinary success.

A later Stage may implement `READ_ONLY` or `FULL` only after a new decision defines adapter construction, device identity, local authorization, operator intent, Calibration/Profile acceptance, allowed operations, auditability, failure/uncertain-state handling, and isolation tests. A future real driver must still sit behind one reviewed application safety entry point; `FULL` alone is never motion authorization.

## Alternatives

- Keep only `real_motion_enabled`: rejected because it conflates product mode, release authorization, and hardware capability.
- Interpret `DRY_RUN` as permission to probe hardware read-only: rejected because Dry Run must be fully usable without a device or SDK and must have zero physical side effects.
- Accept permissive configuration but silently downgrade: rejected for Stage 2 because diagnostics would no longer reflect operator/deployment intent and a future adapter could be instantiated before the downgrade.
- Remove Real/read-only/full vocabulary entirely: rejected because the distinction is a durable domain contract, not a promise that Stage 2 implements it.

## Consequences

Stage 2 startup is deterministic and hardware-isolated. A client cannot escalate capability, tests can assert the effective policy from health/status responses, and introducing a real adapter requires an explicit composition-root and policy change rather than a new query parameter.

Configuration that requests future capability fails startup instead of running. This is intentional: operators receive a visible denial, and no code path can imply that real hardware is active or safe.
