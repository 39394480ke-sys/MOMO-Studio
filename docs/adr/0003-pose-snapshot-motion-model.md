# ADR 0003: Motions embed pose snapshots

- Status: Accepted
- Date: 2026-08-23

## Context

A saved Motion must remain reproducible after a user renames, changes, or deletes a Pose. Referencing mutable Pose files at playback would make an existing Motion change silently or fail to load.

## Decision

Each Motion keyframe embeds a complete `PoseSnapshot` containing the variant, keyed joint state, canonical TCP pose, capture time, and optional safety provenance. `source_pose_id` is optional provenance only and is never dereferenced for playback.

## Alternatives

- Store Pose IDs only: rejected because deletion/editing changes Motion semantics.
- Copy only joint arrays: rejected because arrays lose joint identity and omit TCP/calibration context.
- Automatically propagate Pose edits: rejected because it breaks reproducibility and reviewability.

## Consequences

Motion files are self-contained and somewhat larger. A user must explicitly replace/update a keyframe to adopt a changed Pose. Migration code must materialize complete validated snapshots.
