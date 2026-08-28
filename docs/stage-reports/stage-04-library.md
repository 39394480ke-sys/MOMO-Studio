# Stage 04: Pose and Motion Library

- Date: 2026-08-24
- Repository: `/Users/ke/Library/Mobile Documents/com~apple~CloudDocs/Code/MOMO-Studio`
- Branch: `codex/v1-autonomous-completion`
- Status: **GREEN / COMPLETE — final gates PASS; independent audit PASS P1=0/P2=0**
- Dedicated containing commit subject: `feat: add pose and motion library workflows`

## Summary

Stage 4 introduces the first durable user-entity slice: coherent Pose
Capture, Pose/Motion CRUD, compatibility-checked Dry Run Goto, a unified responsive
Library, and an explicit offline Legacy action importer. Persistence uses UUID-named,
schema-validated JSON with atomic replace, expected-revision conflicts, and corrupt-file
isolation. Formal Motion continues to embed complete Pose snapshots; playback remains
Stage 5.

The independent read-only audit identified multiple P1 issues during implementation and
additional P1/P2 issues on its first re-review. Implementation agents fixed every
reported snapshot-unit/TCP/provenance, safe-error, importer overflow/provenance,
pagination/action-state, and resource-bound issue. The final independent disposition is
**PASS — P1=0, P2=0**. Review was backed by targeted execution and did not substitute for
the main gate.

The final root gate passes 273 backend tests and 71 frontend tests across 8 files, all
lint/type/format/build/schema/lock/dependency checks, and a 65-test focused
route/import/hardware suite. Browser acceptance passed the full Stage 4 Dry Run workflow
at 1440 x 960 desktop and exactly 390 x 844 mobile with no horizontal overflow and no
console warning or error. Stage 4 is GREEN and complete. Its exact ending SHA and
post-commit remote state are necessarily recorded after the dedicated containing commit
is created; they are not fabricated in the commit's own report.

## Starting and ending point

- Starting commit: `133318e9437dff133a4c25bf01aec09cce5ae6e3`
- Starting subject: `feat: add dry-run kinematics and safe motion control`
- Stage 3 remote evidence: the starting commit is pushed to
  `origin/codex/v1-autonomous-completion`.
- Stage 4 remains on `codex/v1-autonomous-completion`; `main` has not been modified or
  merged by this worktree.
- Dedicated ending subject: `feat: add pose and motion library workflows`
- Exact ending SHA: **to be recorded by Stage 5**. A commit cannot contain its own SHA
  without changing that SHA, so this report identifies the dedicated containing commit
  by subject and starting point instead of inventing a self-SHA.
- Post-commit clean-tree and Stage 4 remote state: **not yet recorded**; the verified
  Stage 3 starting commit remains truthfully pushed as stated above.

## Legacy evidence boundary

- Read-only source: `MOMO_RobotARM`
- Pinned branch/commit: `V2` /
  `ff8bbda0c2222cb57951c7913f7f12f5777b98fa`
- The main task read only pinned tracked Git objects via `git show`: V1/V2 sample action
  JSON shapes, their README, and action-library/recorder/common-alias source text.
- No Legacy program, importer, robot controller, serial/Servo SDK, or camera was run. No
  worktree ignored/untracked/local data, Calibration, runtime file, backup, or operator
  export was opened; the tracked Git objects listed above were the complete read set.
- No tracked sample numeric motion/raw value, Legacy source implementation, recorded
  output, gripper state, Calibration value, model, asset, or binary was copied into the
  product or its tests.
- Import tests use newly written synthetic fixtures; the tool never automatically scans
  a Legacy checkout or user directory.

Detailed format disposition and operator behavior are recorded in
`docs/legacy-action-import.md` and `docs/legacy-migration-map.md`.

## Pose and Motion schema `2.0.0`

Stage 4 changes Pose and Motion independently from schema `1.0.0` to `2.0.0`.
`PoseSnapshot` now requires:

- `robot_variant` and exact keyed Joint state with units;
- canonical TCP Pose;
- lowercase SHA-256 `profile_fingerprint`;
- lowercase SHA-256 `kinematics_fingerprint`;
- `state_sequence` (non-null for live Capture; nullable only for explicit Legacy input
  without a coherent source counter);
- optional hardware snapshot and Calibration fingerprint provenance;
- timezone-aware capture time.

Motion retains at least two keyframes, a first keyframe with no incoming transition,
incoming transitions for all later keyframes, complete embedded snapshots, and
`source_pose_id` as provenance only. Stage 4 additionally permits typed, bounded
`LegacyImportMetadata` for an import report without persisting a client path or allowing
API clients to forge importer provenance.

Schema `1.0.0` lacks evidence that cannot be recovered safely. Repository reads reject
and quarantine it; no code silently fills a Profile/Kinematics fingerprint, sequence,
unit, variant, or TCP. An explicit future migration must establish those facts. Updated
examples and generated schemas are present in the worktree. Domain/repository round-trip
and compatibility tests pass. Generation into two fresh temporary directories was
byte-identical and matched every tracked schema/example. Stage 4's changed artifacts
hash to Pose
`4714f9e3ce089f900d5f4e0bf00dc749ed95d3156b2dfb27eb6f55df395fe3ad`, Motion
`07ae1a39edb23f2a96bb2e429073c6459abf35f9305550d5c7e95076c91ac97b`, Pose example
`aeede4889b7604b94e132edbe2a73c6c9d4597864dc6334265160ab5d6ebec07`, and Motion example
`4c4192602193bbc65ffd277bdcea3b0f609e33f00d2e2ecf512fd073c22063a8`.
The matching baseline schema hashes are Calibration
`82993a773d72d6f210251e89784356db3438d1a94afc909bd576c404c9d7ee0b`, Kinematics
`d345c52f2392616cdec0afc908a7df9d84b248485a45ba4c22a75ae5670541f0`, Robot Profile
`7cf2891c38c14c34ac3dd309eff2712cde5d09b9635b0b03fc6695cdd392157c`, Robot Status
`4c3bf6117f762ee548266cff1104a181fa6ec539cc1099a2a8a81dc6480dfbcb`, and Runtime State
`c82b23fdd60bee376a6d4cbc51da49d36b9678a0110ca0da5ac0c56017246ef2`.

## Atomic repositories

`FilePoseRepository` and `FileMotionRepository` use server-owned roots:

```text
data/poses/<uuid>.json
data/motions/<uuid>.json
```

The shared adapter design:

1. accepts UUID identity only and checks filename/document equality;
2. validates generated Draft 2020-12 JSON Schema and the domain model;
3. caps one persisted entity at four MiB;
4. creates at revision 1 and requires `expected_revision` for update/delete;
5. requires an update to advance the revision exactly once;
6. serializes deterministic finite JSON;
7. writes a same-directory temporary file, flushes, file-`fsync`s, atomically replaces,
   and directory-`fsync`s;
8. preserves the old file when failure occurs before replace and cleans its temporary;
9. quarantines invalid entries with an injected-Clock timestamp/content digest when the
   filesystem permits, while continuing the list;
10. uses UUID as a stable tie-break for equal list sort values.

Repository work is bounded before a list or write proceeds: at most 5,000 root JSON
entity files, 10,000 scanned root entries, and 64 MiB aggregate regular-entity bytes.
Overflow fails closed with structured `REPOSITORY_CAPACITY_EXCEEDED` / HTTP 507 rather
than returning a misleading partial page or accepting another write.

The compare/check/write lock is local to one repository instance in one backend process.
Multi-process writers, remote/network filesystems with weaker durability guarantees,
transactional cross-entity updates, and automatic backup/restore remain unsupported.

## Capture and Goto

Capture requests contain display metadata only; they cannot supply a disk path,
fingerprint, sequence, or fabricated TCP. The service obtains a connected/fresh Dry Run
snapshot, performs FK against that exact state/Profile/sequence, and obtains a second
snapshot. It accepts only if sequence, Profile/variant, Joint state, and FK sequence
remain coherent; otherwise it retries up to three times and rejects. Stage 4 records
hardware and Calibration evidence as null rather than accessing or inventing either.

Goto requires the expected Pose revision and validates active variant, exact Profile
enabled-joint/unit set, Profile fingerprint, Kinematics fingerprint, and Joint state. It
then constructs a `LIBRARY`-source `MOVE_JOINTS` command and calls the normal Motion
application service. The existing Motion Safety Gateway is still the only admission
point. The repository has no driver/executor dependency and cannot move anything.

## Motion Library behavior

The Library creates only formal playable-shape Motion entities: at least two embedded
snapshots, exact variant consistency, first/no-incoming and later/required-transition
invariants, bounded durations, and UUID identity. The current UI supplies a focused
two-Pose creation path. Duplicate performs a deep value copy under a new UUID and
revision 1. Deleting or editing a source Pose cannot alter a stored Motion because the
snapshot is embedded; deleting a Motion cannot delete a Pose.

Stage 4 does not compile or play a Motion. Cards expose Play as unavailable until Stage
5. Incomplete authoring is not stored by weakening Motion; Stage 6 will introduce a
separate `MotionDraft`.

## Legacy action importer

The importer is an independently written offline CLI. It requires one explicit source,
defaults to dry-run/report-only behavior, produces fresh Motion UUIDs, and writes only
through the validated Motion repository when the operator explicitly requests it. It
accepts only explicit schema `arm_replay_sequence_v1` and `robot_variant`/`variant`
values V1 or V2 (`source` is provenance, never an alias), requires a top-level ordered
Joint set and exact `pose_count`, recognizes only the documented Joint alias mapping and
characterized primary/replay target and duration/hold spellings, reports ignored
gripper/raw fields, requires known units, reconstructs typed snapshots, recomputes TCP
through the selected provisional Dry Run model, and
rejects/report-quarantines incomplete or ambiguous actions. Source metadata is bounded
and excludes an absolute source path.

The exact command, accepted fixture shapes, alias table, report fields, exit behavior,
and limitations are documented in `docs/legacy-action-import.md`. Post-fix synthetic
importer coverage passes within the 273-test backend gate and focused 47-test fix set; no
real Legacy runtime/user input was used.

## API surface

| Method | Path | Normal success | Stage 4 verification |
|---|---|---:|---|
| GET | `/api/v1/poses` | 200 | Verified |
| POST | `/api/v1/poses` | 201 | Verified |
| POST | `/api/v1/poses/capture` | 201 | Verified |
| GET | `/api/v1/poses/{pose_id}` | 200 | Verified |
| PATCH | `/api/v1/poses/{pose_id}` | 200 | Verified |
| DELETE | `/api/v1/poses/{pose_id}` | 204 | Verified |
| POST | `/api/v1/poses/{pose_id}/duplicate` | 201 | Verified |
| POST | `/api/v1/poses/{pose_id}/goto` | 202 | Verified |
| GET | `/api/v1/motions` | 200 | Verified |
| POST | `/api/v1/motions` | 201 | Verified |
| GET | `/api/v1/motions/{motion_id}` | 200 | Verified |
| PATCH | `/api/v1/motions/{motion_id}` | 200 | Verified |
| DELETE | `/api/v1/motions/{motion_id}` | 204 | Verified |
| POST | `/api/v1/motions/{motion_id}/duplicate` | 201 | Verified |

List requests use explicit pages, page size 1-50, search up to 200 characters, at most
32 Tag query values, and created/updated/name sorting with stable UUID tie-breaks. List
responses contain bounded summaries rather than complete snapshots/keyframes; one UUID
detail request returns the formal entity. Entity request DTOs bound names, descriptions,
Tags, keyframe count, durations, speed scale, and finite JSON values. Public snapshot
writes require explicit units, current Profile/Kinematics evidence, a non-null sequence,
and TCP exactly recomputed by current FK; they reject client hardware/Calibration
provenance. Explicit-null PATCH fields, normalized duplicate Tags, aggregate Motion
invariant failures, and capacity overflow return safe structured errors. Default
duplicate names truncate the source prefix before appending ` Copy`. No response contains
a repository path or traceback. Executed route enumeration found 37 method/path
combinations across 31 unique HTTP paths plus the existing read-only
`/api/v1/ws/robot`; adversarial unitless/forged/null/normalized-Tag cases passed the
final semantic re-review.

## Library UI

The responsive `/library` workspace contains POSES and MOTIONS tabs. Shared controls
support search, comma-separated Tag filters, and stable sort choices. It displays
loading, empty, offline, backend error, bounded-page, busy, and revision-conflict states.
Mutations use fresh entity revisions; list/detail requests use abort/generation guards so
late responses cannot overwrite a newer selection. After deletion changes the last page,
a successful list response clamps to the new last page while retaining loading state and
refetches instead of showing a false empty result. Destructive/Goto actions use inline
confirmations.

Pose cards display name, variant, capture time, Tags, TCP summary, exact Joint values and
units, revision, UUID, Goto, Duplicate, Delete, and Add to Studio. Goto is disabled when
the active robot is offline, disconnected, stale, busy, or incompatible. Motion cards
display name, variant, created time, keyframe count, total duration, movement-type
summary, Tags, revision, UUID, Open in Studio, Duplicate, Delete, and visibly disabled
Play. Open/Add hand off UUIDs in the Studio query without treating names as identities.

The worktree includes actual coherent Pose Capture and a bounded valid two-Pose Motion
creation form. The form lists at most the first 50 Pose summaries by name, fetches both
full entities on submit, verifies their listed revisions, rejects hardware snapshots,
then embeds detached values. Frontend tests cover offline cache/disablement,
revision-conflict draft retention and Reload, confirmations, request-race guards, UUID
handoff, and creation invariants. Browser QA covered the connected Stage 4 workflow,
recovery, and layout described below.

## Resource bounds

| Resource | Implemented bound | Verification |
|---|---|---|
| Persisted entity | Four MiB each | Pass in repository/root tests |
| Entity list | Page 1-100000; page size 1-50; default 24 | Pass in API/root tests |
| Motion-creation Pose source list | First 50 summaries sorted by name; full details fetched on submit | Pass in frontend tests |
| Search/Tag filters | Search max 200 characters; at most 32 Tag query values | Pass in API/frontend tests |
| Entity metadata | Name max 200; description max 5000; at most 32 Tags; Tag max 64 | Pass in domain/API tests |
| Formal Motion create/update | 2-1000 keyframes; domain transition/duration invariants | Pass in domain/API tests |
| Capture consistency | Three attempts; no unbounded retry | Pass in service/API tests |
| Repository capacity | 5,000 JSON entities; 10,000 scanned root entries; 64 MiB aggregate regular-entity bytes | Pass in repository/fix tests; overflow is structured 507 |
| Repository concurrency | One process/repository instance lock; no writer queue | Known limitation |
| Import source selection | One explicit file/directory; immediate regular JSON only; four MiB/file; 1,000 selected JSON files; 2,000 scanned entries; 32 MiB aggregate | Pass in importer/fix tests |
| Import conversion/report | 1,000 actions/file; 2,000 total actions; 2-1,000 keyframes/action; 20,000 total keyframes; 2,000 report entries | Pass in importer/fix tests |
| HTTP body | No application-wide byte cap beyond server/framework; four-MiB persisted output cap | Known limitation |

## Independent review status

The independent read-only audit examined schema compatibility, atomic/CAS/path behavior,
quarantine/list continuation, stable sorting, capture coherence, Goto gateway routing,
embedded-snapshot independence, bounded safe APIs, explicit/default-dry-run import, UI
offline/conflict/race behavior, and mobile layout. After its findings and first re-review
findings were fixed, its final disposition was **PASS — P1=0, P2=0**.

Independent evidence included 93 targeted backend tests and 44 focused frontend tests;
Ruff, strict mypy across 112 files, ESLint, TypeScript, and diff check; deterministic
double schema generation matching the tracked artifacts; adversarial unitless/forged/
null/normalized-duplicate API cases; isolation and Gateway checks; and exact 390 x 844
worst-bound 200-character Pose/Motion/keyframe/Goto UI states without horizontal
overflow. The audit made no edits and accessed no ignored/local Legacy input, hardware,
or media.

## Commands and results

| Check | Result |
|---|---|
| `make test` | **PASS** — backend 273 passed with one known Starlette `TestClient`/httpx deprecation warning; frontend 71 passed in 8 files |
| `make lint` | **PASS** — Ruff, strict mypy across 112 files, ESLint, and TypeScript |
| `make format-check` | **PASS** — 112 Python files checked |
| `make build` | **PASS** — 1,621 modules; CSS 32.80 kB (gzip 7.10 kB); JS 278.61 kB (gzip 85.19 kB) |
| `make schemas` plus two fresh temporary generations | **PASS** — both fresh outputs were byte-identical and matched all tracked schemas/examples; hashes recorded above |
| `uv lock --check --project backend` | **PASS** — lock resolves 44 packages |
| npm production audit | **PASS** — 0 vulnerabilities |
| locked Python runtime audit | **PASS** — no known vulnerabilities |
| `git diff --check` | **PASS** for the complete Stage 4 worktree at the recorded gate |
| focused route/import/hardware isolation | **PASS** — 65 tests; 37 method/path combinations, 31 unique HTTP paths, `/api/v1/ws/robot`, forbidden loaded modules `[]` |
| independent read-only audit | **PASS — P1=0, P2=0**; 93 targeted backend + 44 focused frontend tests and static/schema/layout/isolation checks |

These are the exact results supplied by the main task; no duration or skipped result is
invented where none was reported.

## Dependency and license change

Stage 4 adds `jsonschema` at runtime and `types-jsonschema` for development. The current
lock resolves jsonschema `4.26.0`, attrs `26.1.0`, jsonschema-specifications `2025.9.1`,
referencing `0.37.0`, rpds-py `2026.6.3`, and types-jsonschema
`4.26.0.20260518`. Installed Python 3.11 metadata reports MIT for the runtime set and
Apache-2.0 for the stubs. Exact purpose and the requirement to inspect shipped license
files are recorded in `THIRD_PARTY_NOTICES.md`. The locked Python runtime audit reported
no known vulnerabilities and the npm production audit reported zero; distribution-time
license-file and vulnerability review remains required.

## Browser and safety evidence

Chromium browser QA exercised connected Dry Run, coherent Pose Capture, Pose/Motion
search, Tag filtering, sorting, detail, two-Pose Motion creation, UUID-only Studio
handoff, duplicate, delete cancel/confirm, and inline confirmed Goto. Deleting a source
Pose left the Motion's embedded snapshots unchanged. An external revision-2 patch
produced the explicit Revision Conflict state, and Reload recovered it. Stopping the
backend retained a cached Motion while disabling mutations; restart recovered
automatically. Final browser data used isolated temporary storage.

Responsive acceptance passed at 1440 x 960 (`document` and body width 1440) and exactly
390 x 844 (`document` and body width 390), with no horizontal overflow; mobile
navigation was present and the stored Motion remained visible. Independent re-review
also rendered worst-bound 200-character Pose/Motion/keyframe/Goto states at 390 x 844
without overflow. The final healthy browser console warning/error list was `[]`.
Development servers were stopped and the browser tab was closed.

The independent browser observed one benign missing-favicon 404 resource request, not an
application exception or console warning. Pagination edge cases, request-race
suppression, and cached-error states are additionally covered by the 71 frontend tests.

Final Stage 4 route/import/hardware isolation **PASS**: 65 focused tests ran and the
forbidden loaded-module inventory was `[]`. All execution used existing Dry Run/Fake
high-level adapters or offline synthetic importer fixtures. No serial, Servo, camera, or
microphone path was loaded or used, and no raw-control or arbitrary-file API exists.

## Known limitations

- Schema `1.0.0` Pose/Motion data is not auto-migrated; explicit migration is required.
- Repository concurrency protection is not cross-process and there is no cross-entity
  transaction, backup, or restore workflow yet.
- Repositories fail closed above 5,000 entity files, 10,000 scanned root entries, or
  64 MiB aggregate entity bytes; this is a local workstation ceiling, not a scalable
  database/query design.
- Durability depends on host-filesystem `fsync`/atomic-replace semantics; networked or
  unusual filesystems are not certified.
- Quarantine is best effort on a read-only filesystem; invalid entries are still omitted.
- Quarantine retention has no automatic count/age/byte pruning policy.
- Goto is Joint Motion only and uses provisional Dry Run Profile/Kinematics evidence.
- Motion Play, compilation, preflight digest, loop, pause/resume, and scheduling are
  Stage 5; formal Motion is not weakened for incomplete editing.
- The importer supports only characterized formats/aliases and does not recover unknown
  units, raw-only values, gripper semantics, missing observations, or device truth.
- A hostile local writer can mutate an explicitly selected importer source between the
  scope-validation and conversion passes; that is outside the local single-operator
  threat model. Preserve and review the source before import.
- No application-wide HTTP request-body byte cap is added in Stage 4.
- Library transport remains local and unauthenticated; LAN hardening remains Stage 8.
- Real hardware, real Calibration, physical kinematic accuracy, and field acceptance
  remain blocked.

## Stage transition gate

Stage 4 is **GREEN / COMPLETE**. The final root, focused isolation, browser, schema,
dependency, and independent review gates all pass, with **P1=0 and P2=0**. The dedicated
containing commit uses subject `feat: add pose and motion library workflows`; Stage 5
must record its resulting SHA/remote state because a commit cannot embed its own SHA.
Stage 5 must reuse immutable embedded snapshots and the single Motion Safety Gateway.
