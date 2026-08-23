# ADR 0004: Versioned files before a database

- Status: Accepted
- Date: 2026-08-23

## Context

The first version is a single-operator local workstation. Poses and Motions are document-sized entities, and introducing a database would add migration, backup, and packaging complexity before concurrency needs are known.

## Decision

Persist later as schema-versioned JSON under UUID filenames: `data/poses/<uuid>.json` and `data/motions/<uuid>.json`. Display names remain attributes. File adapters must write a temporary sibling and atomically replace the target. Runtime files stay untracked.

## Alternatives

- SQLite now: deferred because query and concurrency requirements do not yet justify it.
- Filename from display name: rejected because names can repeat/change and may be unsafe paths.
- In-place JSON writes: rejected because interruption could corrupt the only copy.

## Consequences

Data is inspectable and portable, with simple backup. Repository interfaces insulate the domain from a later database. File locking, revision conflicts, recovery, and migrations still require deliberate implementation.
