# ADR 0011: Atomic Pose and Motion entity repositories

- Status: Accepted
- Date: 2026-08-24

## Context

MOMO Studio is a local, single-operator workstation. Pose and Motion are durable user
entities, but their display names are editable and non-unique. Capture and Goto also
need exact Profile/Kinematics identity, while Motion must retain complete embedded
snapshots independently of any source Pose. A partial write, stale editor, malformed
document, unsafe filename, or silent interpretation of an older schema could otherwise
corrupt the Library or authorize an incompatible Dry Run target.

The Stage 1 `1.0.0` examples did not carry the complete compatibility evidence required
by Stage 4 capture and Goto. In particular, a snapshot did not require Profile and
Kinematics fingerprints or an observation sequence.

## Decision

Pose and Motion are persisted as independent schema `2.0.0` JSON documents under
server-owned directories:

```text
data/poses/<uuid>.json
data/motions/<uuid>.json
```

The filename is always the entity UUID; a display name never becomes a path. API and web
clients can submit only UUID identities and entity fields, never a filesystem path.
Each read verifies that the filename UUID equals the document UUID, the document
satisfies its generated Draft 2020-12 JSON Schema, and the Pydantic domain model accepts
it. Symlinks, malformed JSON, non-finite values, oversized documents, schema failures,
unsupported versions, and ID/filename mismatches are invalid entities.

Pose Snapshot `2.0.0` requires an explicit non-null unit for every enabled Joint plus
exact `profile_fingerprint`, `kinematics_fingerprint`, and `state_sequence` fields. A live
capture always records a non-null sequence. An explicit Legacy import may use `null` only
when the source has no coherent observation counter; that fact does not authorize Goto
without the other exact compatibility evidence. Public snapshot writes must carry
current compatibility evidence and canonical FK-derived TCP and cannot claim hardware or
Calibration provenance. Motion `2.0.0` may also retain typed, bounded
`LegacyImportMetadata` (importer ID, source basename/digest, optional Legacy ID/source,
and warnings). The API cannot set that importer-owned provenance. Full Pose snapshots
remain embedded in keyframes;
`source_pose_id` remains provenance only.

Schema `1.0.0` Pose/Motion files are not silently upgraded. They lack evidence that
cannot be reconstructed safely. Repository reads reject and quarantine them, and an
operator must use an explicit reviewed migration/import path. No migration invents a
fingerprint, unit, state sequence, or robot variant.

Every create begins at revision 1. An update or delete must include
`expected_revision`; updates advance exactly once. The repository performs the
read/check/write sequence under a repository-local lock and returns a structured
revision conflict rather than overwriting newer data. The lock provides concurrency
safety only for callers sharing one process and repository instance; it is not a
multi-process or distributed lock.

Writes are crash-resistant within the guarantees of the host filesystem:

1. serialize deterministic finite JSON and enforce the four-MiB entity cap;
2. create a temporary sibling in the destination directory;
3. write, flush, and `fsync` the temporary file;
4. atomically replace the destination;
5. `fsync` the parent directory.

On failure before replacement, the previous entity remains intact and the temporary
file is removed. Deletes unlink the expected revision and `fsync` the entity directory.
An invalid stored file is moved into a server-owned `quarantine/` sibling using an
injected Clock for a deterministic timestamp plus a content digest. A list omits that
entity and continues. If a read-only filesystem prevents quarantine, the invalid entry
is still omitted. Lists use a stable UUID tie-break for equal sort values.

Repository traversal and aggregate work are explicit local-workstation budgets: 5,000
root JSON entity files, 10,000 scanned root entries, 64 MiB aggregate regular-entity
bytes, and four MiB per entity. List/create/update fail closed with a structured capacity
error when a relevant ceiling is exceeded; they do not silently return a partial Library.

`FilePoseRepository` and `FileMotionRepository` implement the domain ports; the API does
not import either adapter. Runtime Pose/Motion directories and quarantine data remain
ignored operational data, not tracked examples.

## Alternatives

- Reuse schema `1.0.0` and fill missing fields: rejected because invented compatibility
  evidence would make Goto unsound.
- Use display names as filenames: rejected because names may repeat, change, or contain
  unsafe path syntax.
- Write JSON in place: rejected because interruption can destroy the only valid copy.
- Let the browser choose an import or repository path: rejected because it creates an
  arbitrary-file surface.
- Introduce SQLite or a cross-process file-lock dependency now: deferred until actual
  multi-process, query, or transactional requirements justify that migration.

## Consequences

The Library gets portable, inspectable documents, explicit compatibility, bounded
storage, optimistic concurrency, and isolation from a single corrupt file. Schema
`1.0.0` data now requires deliberate migration and is not automatically usable. Atomic
replace and directory sync improve crash behavior but cannot promise durability beyond
the mounted filesystem's documented semantics. Running multiple backend processes
against the same directory remains unsupported; deployment must use one writer until a
future storage decision adds cross-process coordination. Quarantine remains best effort
and has no automatic retention/pruning policy; operators must manage its disk usage.
