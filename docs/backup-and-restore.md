# Backup, preview, migration, and restore

MOMO Studio backups are configuration-free, deterministic JSON envelopes. They
contain Pose, Motion, and MotionDraft entities. Calibration is excluded unless
the operator explicitly opts in. A backup never includes LAN credentials,
serial/device configuration, runtime connection state, logs, camera paths, or
server filesystem paths.

The media type is `application/vnd.momo.backup+json`. The maximum uploaded body
is 32 MiB, each document is at most 4 MiB, and an envelope contains at most 5,000
documents.

## API flow

All routes are under `/api/v1`. REST authentication applies to
export and preview; confirmed restore uses control authentication and its rate
limit.

### Export

`POST /backup/export`

```json
{"include_calibration": false}
```

The response is raw backup bytes with:

- `Content-Type: application/vnd.momo.backup+json`
- `Content-Disposition: attachment; filename="momo-studio-backup.json"`
- `X-MOMO-Backup-SHA256: <64 lowercase hex characters>`
- `Cache-Control: no-store`

No request or response field accepts a server path. Calibration export requires
`include_calibration: true`; omitting the field is the safe `false` default.

### Dry-run preview

`POST /backup/import/preview?collision_policy=reject&allow_calibration=false`

Send the raw backup bytes as the request body with the backup media type. The
response includes:

```json
{
  "bundle_sha256": "…",
  "format_version": "1.0.0",
  "valid": true,
  "contains_calibration": false,
  "collision_policy": "reject",
  "totals": {
    "documents": 3,
    "create": 3,
    "skip": 0,
    "conflict": 0,
    "invalid": 0
  },
  "items": [
    {
      "kind": "pose",
      "id": "00000000-0000-0000-0000-000000000000",
      "source_revision": 2,
      "action": "create",
      "migrated_from": null,
      "message": null
    }
  ],
  "issues": []
}
```

Preview does not retain the upload and does not mutate a repository. A successful
valid preview records only a bounded, server-side, one-use grant bound to the exact
bundle SHA-256, collision policy, and Calibration choice. The grant expires after five
minutes, the table is capped at 128 entries, and restore consumes it before doing any
work. A failed restore therefore requires a new preview. The UI may display export and
this preview summary without exposing a server path. Malformed JSON, duplicate keys,
digest mismatch, unsupported format, unsafe content, or an oversized upload is rejected
with a structured error.

`collision_policy` is deliberately limited to:

- `reject` — any matching entity ID (or matching calibration variant) makes the
  preview invalid;
- `skip` — leave every matching destination document unchanged.

There is no silent overwrite policy. This preserves local changes and gives the
operator an inspectable decision.

### Confirmed restore

`POST /backup/import/restore` accepts the same raw body and query options plus:

- `X-MOMO-Backup-SHA256: <digest returned by preview>`
- `X-MOMO-Restore-Confirmation: RESTORE`

The service reparses and revalidates the bytes under a maintenance lock and
recomputes the preview/digest. It does not trust a retained server-side file or
client-supplied path. If bytes, policy, collisions, or repository state changed,
restore fails before claiming success.

The response contains the digest, `outcome: "restored"`, restored counts by
entity kind, and a skipped count.

Calibration requires three deliberate choices: opt in during export, pass
`allow_calibration=true` during preview, and pass it again during restore. The Stage 8
release composition supplies a bounded atomic V1/V2 Calibration importer and exact
rollback callback. A different composition without both capabilities reports
`CALIBRATION_RESTORE_UNAVAILABLE` during preview.

## Deterministic envelope

Documents are sorted by kind and UUID. Every descriptor records kind, UUID,
schema version, source revision (except calibration), and a SHA-256 of canonical
payload JSON. The manifest records format/version, count, whether calibration is
present, a digest of ordered descriptors, and its own digest. The full canonical
envelope has the digest returned by the API.

There is no export timestamp in the wrapper. Entity timestamps remain in their
validated payloads, and exporting unchanged repositories produces identical bytes.
The manifest retains source revisions. Restore validates and writes the exact final
entity revision in one repository import; it does not replay intermediate revisions or
fabricate history. Revisions remain bounded to 50,000 by the domain contract.

## Validation and migrations

Import validates, in order:

1. upload byte bound, UTF-8/JSON syntax, constants, and duplicate object keys;
2. envelope ordering, identity, revision, calibration flag, and every digest;
3. exclusion of credential/device/log/runtime/camera/local-path content;
4. an explicit schema migration chain, if the entity is older;
5. the current Pydantic domain model and its invariants;
6. collision policy and bounded restore work.

`BackupMigrationRegistry` starts without speculative migrations. Each registered
step names one entity kind, source version, and destination version and supplies
a deterministic function. A step must set exactly its declared schema version
and may not change the entity UUID or revision. Missing steps, cycles, and chains
longer than eight fail. Migration functions must not invent unavailable data;
when required source information does not exist, reject the import and document
a manual migration decision.

Adding a migration does not change a persisted schema. Follow the repository
schema rules: compatibility analysis, round-trip tests, regenerated JSON Schema,
and a Stage decision record remain required.

## Process-crash atomicity, WAL, and rollback

Before the first create, restore durably writes one bounded transaction intent to the
fixed ignored restore-journal directory. The journal records the bundle digest, exact
kind/UUID/final revision for every absent Pose/Motion/MotionDraft target, and exact
variant/UUID for every absent Calibration target. The file is written through a private
same-directory temporary file, file `fsync`, atomic replace, and directory `fsync`;
parent directories are durably created. Symlinks and non-regular journal files fail
closed. The journal contains no entity payload, secret, local path from the upload, or
device credential.

Pose, Motion, and MotionDraft documents are then created through their validated
repository ports at the exact source revision. Restore never overwrites an existing
document. Repository create/delete workers are allowed to reach a known terminal
filesystem result despite caller cancellation. A post-`os.replace` directory-fsync
error is treated as a committed create, so compensation removes the exact revision
before the error is reported. Calibration is invoked last as one bounded staged batch;
the adapter validates both variants first, writes only fixed server-configured
destinations that were proven absent during preview/revalidation, and compensates all
new destinations on failure. Existing Calibration revisions are collisions and are
never overwritten by backup restore.

On ordinary failure or cancellation, every intended Calibration and revisioned entity
is removed in reverse order. Deletion uses exact identity/revision compare-and-swap, so
a concurrent later edit is never silently deleted; inability to prove exact rollback is
reported as `BACKUP_ROLLBACK_FAILED`. The journal is durably cleared only after the
entire restore commits or all compensation is proven complete.

On process or host crash, application lifespan calls `recover_pending_restore()` before
serving traffic. A surviving journal makes startup compensate every exact target and
durably clear the intent. Invalid journal data or an incomplete rollback blocks startup
rather than exposing a partially restored application. Directory-fsync failure leaves
the journal in place for another recovery attempt. Within the supported single-process,
server-owned repository configuration, this is a write-ahead-log (WAL) based
**process-crash atomic restore**: after recovery, observers see either none of the
transaction's creates or the complete committed restore.

This guarantee does not make multiple backend writer processes, unsupported/network
filesystems, storage corruption, disk loss, or external manual edits transactional.
Keep one backend writer and test disaster recovery on the deployment filesystem.

## Operator procedure

1. Stop editing Pose/Motion/Draft data and stop active playback/Follow.
2. Export without calibration unless hardware-local calibration is explicitly
   needed and approved.
3. Store the downloaded bytes in operator-controlled storage and record the
   shown SHA-256 separately.
4. Upload the bytes to Preview. Review counts, every conflict/skip, migrations,
   and calibration presence.
5. Resolve invalid items; never edit payload data without rebuilding all
   canonical digests through a reviewed tool.
6. Re-upload the exact bytes with the preview digest, unchanged options, and exact
   `RESTORE` confirmation before the five-minute one-use preview grant expires.
7. Verify entity counts/exact revisions and run Dry Run playback checks. Calibration
   restore does not authorize real motion; hardware field acceptance and every
   independent safety gate still apply.
8. If startup reports pending-restore recovery failure, do not delete the WAL manually
   or retry writes. Preserve bounded audit evidence and inspect the fixed repository and
   journal directories under the documented recovery procedure.
