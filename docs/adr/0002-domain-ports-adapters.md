# ADR 0002: Domain, ports, and adapters

- Status: Accepted
- Date: 2026-08-23

## Context

Legacy hardware, kinematics, storage, and vision code use different dependencies and safety assumptions. Importing them from HTTP routes would make behavior difficult to test and let transport code bypass policy.

## Decision

Place invariants in dependency-free domain models, orchestrate use cases in application services, express external capabilities as typed ports, and implement them in adapters. API routes depend only on application/port-bound dependencies. Raw hardware drivers are never imported by routes.

## Alternatives

- One backend service module: rejected because it conflates transport, policy, state, and I/O.
- Routes call drivers directly: rejected because it creates a safety bypass and makes offline testing fragile.
- Framework-specific domain entities: rejected to preserve serialization and test portability.

## Consequences

Adapters can be migrated and tested independently, and safe fakes do not become product modes. The design adds interfaces and composition work, but makes dependency direction and review ownership visible.
