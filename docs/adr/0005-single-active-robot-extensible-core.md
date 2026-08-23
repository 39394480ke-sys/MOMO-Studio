# ADR 0005: One active robot with identity-aware core

- Status: Accepted
- Date: 2026-08-23

## Context

The first product controls one robot. Legacy `fleet.py` includes abstractions motivated by multiple arms, but multi-arm product workflows are explicitly excluded. A process-global driver would nevertheless make identity, lifecycle, and tests ambiguous.

## Decision

Expose one active robot in the UI while identifying drivers with `RobotId` through a manager/registry port. Do not add Fleet, coordination, synchronized movement, or multi-robot APIs.

## Alternatives

- Global `robot`: rejected because it hides lifecycle/dependencies and makes parallel tests unsafe.
- Build fleet features now: rejected as out of scope and a distraction from single-robot safety.
- Names such as `arm_a`: rejected because they encode a coordination scenario into the core.

## Consequences

The first UI stays simple, but application services remain explicit about which device they address. Future expansion would not require replacing every interface; it would still require new product and safety decisions.
