# Stage 06: Studio timeline authoring

- Date: 2026-08-24
- Repository: `/Users/ke/Library/Mobile Documents/com~apple~CloudDocs/Code/MOMO-Studio`
- Branch: `codex/v1-autonomous-completion`
- Status: **COMPLETE / GREEN — backend, frontend, browser, schema/lock/npm, independent
  integrated audit P1=0/P2=0, dedicated commit, and push recorded**
- Starting commit: `114f2a579df236b4824b23c9a0aae320a83a9a07`
- Ending commit: `37783bdf8c01146d3a312980dbe4a25716e5468c`
- Dedicated containing commit subject: `feat: add studio timeline authoring`
- Remote state: Pushed to `origin/codex/v1-autonomous-completion`

## Summary

Stage 6 introduces a recoverable timeline-authoring workspace without weakening the
formal `Motion` invariant. A separate `MotionDraft` accepts zero or more keyframes,
persists local autosave state with optimistic revisions, and becomes a formal Motion
only after backend validation and Stage 5 trajectory compilation. A draft and its
compile preview are never executable.

The implementation includes the backend domain, strict persisted schema, atomic draft
repository, bounded Studio API, coherent Capture, compiler-backed preview, write-ahead
Save/Save As reconciliation, explicit retained-marker release, persisted-keyframe Dry
Run Goto, the pure editor reducer, and the responsive Studio workspace.

Final implementation evidence is 393 passing backend tests, an independently rerun
36-test Stage 6 domain/repository/coordinator/actions/API selection, 174 passing frontend
tests across 12 files, an independently rerun 89-test Studio selection, green
Ruff/format/mypy over 141 backend files, green ESLint/TypeScript/build, browser
acceptance, and final independent integrated audit **P1=0/P2=0**. The containing commit
is `37783bdf8c01146d3a312980dbe4a25716e5468c` and is pushed to the working remote
branch.

## Domain boundary

Formal `Motion` schema `2.0.0` remains unchanged and still requires at least two valid,
compatible keyframes. `MotionDraft` schema `1.0.0` is a separate persisted entity with:

- its own UUID and optimistic revision;
- a coherent optional source Motion UUID/revision pair;
- name, description, robot variant, tags, and playback defaults;
- zero to 1,000 complete embedded `MotionKeyframe` values;
- bounded editor metadata for selection, playhead, zoom, scroll, and default-edge
  provenance;
- optional typed, importer-owned `source_metadata` copied from a source Motion;
- a bounded, backend-owned registry of canonical SHA-256 digests for exact trusted
  Legacy snapshots whose `state_sequence` is unavailable;
- an optional bounded formal-save intent used only for crash reconciliation;
- aware creation/update timestamps.

Complete snapshots remain embedded by value. `source_pose_id` and the optional source
Motion pair are provenance only; later Pose or Motion edits cannot mutate draft
keyframe data. Draft validation requires unique keyframe IDs, exact explicit units,
variant/Profile/Kinematics compatibility, a transition on every non-first keyframe,
and no transition on the first keyframe. Zero- and one-keyframe drafts remain valid
authoring state but fail conversion to a formal Motion.

## Explicit edge semantics and editor history

The editor reducer models segment settings as a directed
`Edge(from_keyframe_id, to_keyframe_id)`. Reorder preserves duration, mode, easing, and
default provenance only for an exact directed adjacency that survives. A new adjacency
receives the explicit editor default:

```text
duration = 1.0 s
motion mode = JOINT
easing = SMOOTHSTEP
```

The first keyframe has no incoming edge. A former first keyframe moved later receives a
new default edge. Conversion to the formal domain attaches each edge as the target
keyframe's `incoming_transition` only after the final order is known. Bounded
`default_edges` metadata records which exact directed adjacencies still use the default,
so autosave/restart does not erase the UI distinction between a default and a manually
edited segment.

The pure reducer covers add before/after, Capture, add from Pose, replace snapshot,
duplicate, delete, drag/keyboard reorder, label, duration, hold, mode, easing, name,
Undo, and Redo. Default history is 100 documents and the defensive configurable cap is
500. Autosave acknowledgements update persistence state without adding editor history.
Non-finite or out-of-bound hold/duration values are rejected before they can enter
history or an autosave payload.

## Draft persistence and strict recovery

Drafts use UUID filenames under the ignored, server-owned `data/drafts` root. The atomic
repository applies the same bounded write and recovery rules as Pose/Motion storage:
schema and domain validation, filename/document UUID equality, expected-revision CAS,
a same-directory temporary sibling, file flush and `fsync`, atomic replace, directory
`fsync`, symlink rejection, entity/scan/aggregate byte bounds, and best-effort corrupt
quarantine.

The generated persisted recovery schema requires every serialized field recursively,
including values that have safe constructor defaults, nested keyframe UUIDs,
`default_edges` identities, the Legacy trust registry, and formal-save intent identity.
An API create request may use documented defaults; an on-disk recovery document may not
omit fields and ask the loader to invent past state. Unsupported or incomplete recovery
data is quarantined rather than silently repaired. The Stage 6 schema was regenerated
and round-tripped before acceptance; no earlier released Stage 6 Draft schema exists to
migrate.

Opening an imported Motion seeds at most 1,000 unique digests from its exact null-sequence
snapshots. The digest covers the complete parsed snapshot with sorted JSON object keys,
compact deterministic encoding, and non-finite-number rejection, so mapping order is not
identity. API create/update commands cannot provide `source_metadata` or the registry.
Autosave, recovery, rebind, abandon, and conflict forks preserve both server-owned
fields. Reorder, duplicate, delete/autosave/Undo restoration of an exact trusted
snapshot remain valid; an altered or fabricated null-sequence snapshot fails closed.

Configuration validates all runtime/Profile/Calibration/Kinematics/Pose/Motion/Draft
storage roots before constructing repositories. Roots must be pairwise disjoint under
resolved equality, ancestor/descendant relationships, existing filesystem identity,
NFC Unicode normalization, and case folding. This prevents a Draft reader from
quarantining a formal Motion when differently spelled paths resolve to the same storage.

## Write-ahead Save and Save As reconciliation

A formal save crosses two independent atomic repositories and therefore uses a
write-ahead intent on the Draft:

```text
compile accepted candidate
  -> CAS Draft revision N to N+1 with save_intent
  -> persist exact Motion UUID/revision through the Library revision lease
  -> CAS Draft revision N+1 to N+2, bind source UUID/revision, clear intent
```

Once the intent-backed commit starts, caller cancellation cannot cancel that commit.
Process termination can still interrupt it; list/get or the next mutation reconciles a
persisted marker before exposing the Draft.

Example: a new Draft at revision 1 targets Motion `M` revision 1. The intent is durable
at Draft revision 2, `M` revision 1 is persisted, and the process stops before the final
Draft CAS. On restart, recovery loads the exact target, verifies its UUID, revision,
creation time, name, description, variant, complete keyframes, playback defaults, tags,
and typed `source_metadata` against the intent-bearing Draft, then writes Draft revision
3 bound to `M` revision 1 with the marker cleared. It does not create a second Motion.

Recovery fails closed in the other orderings:

| Observed target state | Reconciliation |
|---|---|
| Target absent | Clear the failed intent in a new Draft revision; do not claim a Motion was saved |
| Exact targeted revision and semantic content match | Bind that Motion/revision and clear the intent |
| Known-source Save target advanced beyond the intended revision | Bind the known UUID but retain the intended source revision, forcing the next Save to conflict |
| Fresh Save/Save-As target advanced beyond the intended revision | Preserve the marker and fail closed because the interrupted write cannot be proven |
| New/Save-As UUID contains different content or creation identity | Preserve the marker and return a conflict for operator recovery |
| Existing-source update lost the exact next revision to another writer | Clear the marker, retain the old source revision, and force the next Save to conflict |

Save carries both the expected Draft revision and, when a source exists, the expected
source Motion revision. Save As generates a new Motion UUID at revision 1 and may take a
new name. Neither path offers overwrite-anyway or last-writer-wins behavior. Formal
Motion persistence shares the Library mutation/revision lease with Stage 5 playback,
so a save cannot revise a Motion through an in-flight playback claim.

A retained marker is never silently discarded. The initialization gate exposes its
bounded transaction identity and offers only an explicit release operation:

```text
POST /drafts/{draft_id}/save-intent/abandon
  { expected_revision, operation_id, confirm: "ABANDON_FORMAL_SAVE" }
```

The service performs a raw Draft CAS that clears only that exact marker and increments
the Draft revision. It never creates, updates, adopts, or deletes a Motion. A stale
Draft revision, missing/replaced marker, or operation mismatch remains a structured
conflict.

Every Studio revision conflict carries the bounded entity scope `MotionDraft` or
`Motion`. Active `FORMAL_SAVE_*`, missing, or unknown scopes remain generic and fail
closed. An ordinary conflict Save As captures local editor state before any request,
GETs the authoritative Draft, forks it with exact CAS, PUTs the captured local document
onto the fork, and only then creates a new formal Motion. The fork preserves server-owned
Legacy metadata/trust, starts at a new UUID/revision 1, clears any intent, and leaves the
original Draft and Motion untouched.

## Compiler, preview, playback, and Goto

Validate and compile are backend operations. Draft conversion constructs a new formal
Motion candidate and re-applies its cardinality, snapshot, compatibility, and transition
invariants. Compile calls the Stage 5 `TrajectoryCompiler` and returns structured
preflight plus bounded preview data marked `executable=false`. It does not put the draft
candidate in the prepared-plan cache and does not return a client-executable trajectory.

Playback therefore remains:

```text
Draft -> Save/Save As formal Motion -> revision-bound Stage 5 preflight
      -> exact prepared digest -> Dry Run playback through MotionSafetyGateway
```

Inspector Goto also avoids browser-owned targets. The request identifies a persisted
Draft UUID, keyframe UUID, expected Draft revision, bounded duration/speed, and
idempotency intent. The backend reloads the embedded snapshot, rechecks the active
variant, exact enabled-joint/unit set, Profile/Kinematics fingerprints, and snapshot
validity, then submits a `STUDIO` + `MOVE_JOINTS` command through the existing Motion
application service and the one safety gateway. Missing/stale/incompatible state fails
closed. The sole Studio mutation lock stays held from Draft recovery through revision/
keyframe checks and command submission, so a concurrent autosave cannot replace the
target inside that interval. Goto is Dry Run-only.

## API surface

The current backend implements 14 Stage 6 method/path combinations across 11 unique
HTTP paths:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/studio/drafts` | Bounded recovery list, page size 1-50 |
| POST | `/api/v1/studio/drafts` | Create an empty or populated Draft |
| POST | `/api/v1/studio/drafts/from-motion/{motion_id}` | Copy an expected Motion revision into a Draft |
| GET | `/api/v1/studio/drafts/{draft_id}` | Recover/read one Draft |
| PUT | `/api/v1/studio/drafts/{draft_id}` | Full-document expected-revision autosave |
| POST | `/api/v1/studio/drafts/{draft_id}/fork` | Exact-revision provenance-preserving conflict fork |
| DELETE | `/api/v1/studio/drafts/{draft_id}` | Expected-revision delete |
| POST | `/api/v1/studio/drafts/{draft_id}/save-intent/abandon` | Exact operator release of one retained recovery marker |
| POST | `/api/v1/studio/drafts/{draft_id}/validate` | Validate formal-Motion conversion |
| POST | `/api/v1/studio/drafts/{draft_id}/compile` | Backend compile and non-executable preview |
| POST | `/api/v1/studio/drafts/{draft_id}/save` | Compile and revision-safe formal Save |
| POST | `/api/v1/studio/drafts/{draft_id}/save-as` | Compile and create a fresh formal Motion |
| POST | `/api/v1/studio/drafts/{draft_id}/keyframes/{keyframe_id}/goto` | Persisted-keyframe Dry Run Goto |
| POST | `/api/v1/studio/capture` | Coherent current Dry Run snapshot without creating a Pose |

No route accepts a server filesystem path, driver selector, raw Servo value, arbitrary
sample array, Python expression, or Real override.

Executed OpenAPI enumeration records 60 method/path combinations across 51 unique HTTP
paths after Stage 6, plus the existing read-only RobotStatus WebSocket.

## Bounded implementation structure

The final backend does not place all Studio capabilities in one service. The route-facing
`StudioApplicationService` is a 580-line Draft/compile facade and the sole owner of the
Studio mutation/compile locks. A 415-line lock-free formal-save coordinator owns the
compile-to-intent, Library CAS, rebind, recovery branch table, bounded conflict details,
and exact abandon transaction. A 145-line lock-free robot-actions collaborator owns
coherent Capture and persisted-keyframe Goto. Direct collaborator tests complement the
API concurrency suite.

The 265-line frontend workspace hook owns only the reducer, three viewport values,
composition, Capture/replace, keyboard handling, and derived view model. It composes a
cohesive Draft revision/generation/CAS session, a Motion playback/Goto/priority-Stop
session, a Pose insertion session, and a dirty-navigation guard. Viewer, Timeline,
Inspector, dialogs, and the pure reducer remain separate. This closes the explicit
God-Object findings without duplicating coupled race state.

## Frontend and browser acceptance

The desktop Viewer/Timeline/Inspector workspace and mobile Inspector drawer pass their
final automated and browser gates. The frontend suite passes 174 tests across 12 files;
the focused four-file Studio selection passes 89. ESLint and TypeScript pass. Vite 6.4.3
builds 1,635 modules with HTML 0.56 kB (0.33 kB gzip), CSS 57.26 kB (11.47 kB gzip),
and JS 394.58 kB (114.40 kB gzip).

The final post-refactor root-level browser run used an isolated real-backend data root at
`/tmp/momo-stage6-refactor-browser.PJBPjG` and verified:

- Dry Run Connect, automatic blank-Draft creation/rebind, Capture, Duplicate, autosave
  revision 4, and Save of a formal Motion revision 1;
- an external API update of that Motion to revision 2 followed by an exact UI revision
  conflict on Save, with no overwrite of the external content;
- **Keep editing**, a local name change and K2 label change, then conflict Save As via
  authoritative recovery/fork/rebind into a new Draft at revision 4 and new formal
  Motion at revision 1 containing the local label;
- the original Motion remaining at the external revision 2 and both original/new Draft
  `save_intent` fields remaining `null`;
- desktop console warnings/errors `[]`;
- a fresh active 390 x 844 tab with no desktop-layout residue, focusable/closable mobile
  Inspector drawer, and console warnings/errors `[]`.

The earlier exact responsive measurement recorded desktop 1440 x 960 document widths
1440/1440 and Timeline 755/755, plus mobile 390 x 844 document widths 390/390 and
Timeline 322/680 with container-local `overflow:auto`; Inspector close restored focus to
its opener. The preceding isolated full Studio pass also displayed the retained
formal-save recovery gate. The post-refactor run above confirms the refactor preserved
the accepted workflow and mobile behavior.

## Independent integrated audit and fix closure

The independent audit examined draft invariants, storage isolation, repository recovery,
Legacy provenance, compiler/playback separation, Save concurrency, lifecycle
cancellation, frontend conflict flows, and Goto safety.
Findings closed before the current gate included:

1. rejecting equal, nested, case-aliased, Unicode-aliased, or filesystem-aliased
   configured storage roots before any repository can quarantine another entity type;
2. replacing a cross-repository best-effort save with a write-ahead intent, shielded
   commit, semantic reconciliation, and playback-safe Library revision lease;
3. making the persisted Draft schema recursively strict so recovery never invents
   missing nested identity/default fields;
4. persisting exact default-edge provenance instead of losing it after autosave/restart;
5. removing the compile/save lock-order inversion and covering the interleaving with a
   bounded concurrency regression;
6. loading Goto targets only from an expected persisted Draft revision and submitting
   `STUDIO` provenance through the safety gateway;
7. making fresh/Save-As advanced recovery fail closed, including `source_metadata` in
   semantic reconciliation, and adding exact operator abandon;
8. retaining a canonical server-owned Legacy snapshot trust registry across
   delete/autosave/Undo, fork, recovery, and formal Save flows;
9. separating Draft/Motion conflict scope, failing closed on unknown/formal active
   conflicts, and preserving post-conflict local edits through an authoritative fork.
10. replacing the oversized backend service and frontend workspace hook with bounded
    formal-save/robot-action collaborators and composed Draft/Motion/Pose/navigation
    hooks without splitting their coupled lock or epoch state;
11. holding the sole Studio mutation lock from persisted Draft recovery through
    revision/keyframe checks and Goto command submission, so autosave cannot replace the
    target in the check-to-submit interval.

The final independent integrated and code-quality re-review reports **P1=0/P2=0**.

## Commands and current results

| Check | Result |
|---|---|
| Backend pytest | PASS — 393 passed; one known Starlette/httpx deprecation warning |
| Focused Stage 6 domain/repository/coordinator/actions/API suite | PASS — 36 passed |
| Final independent integrated/code-quality audit | PASS — P1=0/P2=0 |
| Ruff | PASS |
| Strict mypy | PASS — 141 source files |
| Ruff format check | PASS — 141 files |
| Frontend Vitest | PASS — 174 passed / 12 files |
| Focused frontend Studio suite | PASS — 89 passed / 4 files |
| ESLint | PASS |
| TypeScript | PASS |
| Vite build | PASS — 1,635 modules; HTML 0.56/0.33 gzip kB; CSS 57.26/11.47 gzip kB; JS 394.58/114.40 gzip kB |
| Full schema determinism command | PASS — two fresh generations byte-identical; final temporary generation matches tracked schema tree |
| `uv lock --project backend --check` | PASS — 44 packages |
| `npm --prefix frontend audit --audit-level=moderate` | PASS — 0 vulnerabilities |
| Python runtime vulnerability audit | Not rerun — no Stage 6 dependency or lockfile change; no result inferred |
| `git diff --check` | PASS |
| Browser desktop/mobile/boundary | PASS — isolated desktop/mobile, focus, overflow, conflict retention, console `[]` |
| Final Stage integration audit | PASS — P1=0/P2=0 |
| Dedicated commit and push | PASS — `37783bdf8c01146d3a312980dbe4a25716e5468c`, pushed to `origin/codex/v1-autonomous-completion` |

The current Stage 6 diff adds no runtime dependency and does not modify either lockfile.
The lock and npm audit commands above were executed; the Python runtime vulnerability
audit was not rerun and is not reported as passing.

The exact independently rerun backend selection was:

```bash
cd backend
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider -q \
  tests/test_stage6_motion_draft.py \
  tests/test_stage6_draft_repository.py \
  tests/test_stage6_formal_save_coordinator.py \
  tests/test_stage6_studio_robot_actions.py \
  tests/test_stage6_studio_api.py
```

The exact independently rerun frontend selection was:

```bash
cd frontend
npm test -- --run \
  src/features/studio/useStudioMotionSession.test.tsx \
  src/pages/StudioPage.test.tsx \
  src/api/studioClient.test.ts \
  src/features/studio/studioEditorState.test.ts
```

## Known limitations

- Draft and formal Motion writers support one backend process. Locks and revision leases
  are process-local.
- Draft recovery is local operational persistence, not cloud sync, collaboration, or a
  distributed transaction.
- Quarantine is best effort and has no automatic count/age/byte pruning policy.
- A Draft compile preview is diagnostic and non-executable; saving and normal Stage 5
  preflight are required for every playable revision.
- Default editor geometry/dynamics and both kinematics models remain provisional Dry Run
  evidence only.
- Multi-select, curve editing, custom Bezier easing, a PyBullet product view,
  collaborative editing, and Real Studio motion are outside Stage 6.
- Multi-process/distributed persistence and Real Studio motion remain later work; the
  Stage 6 dedicated commit/push gate is closed.

## Current safety statement

All executed Stage 6 backend and browser motion verification used Dry Run/Fake paths.

No serial port was opened.
No serial device enumeration was performed.
No servo scan was performed.
No servo register was read.
No servo register was written.
No torque command was sent.
No real Home command was sent.
No real motion command was sent.
No real calibration was read or modified.
No physical robot was moved.
No real camera was opened.
No camera enumeration was performed.
No microphone was opened.
All Stage 6 motion verification used Dry Run or Fake adapters.
Real-hardware field acceptance remains required.

## Delivery evidence

Stage 6 is contained by commit `37783bdf8c01146d3a312980dbe4a25716e5468c`
(`feat: add studio timeline authoring`) and is pushed to
`origin/codex/v1-autonomous-completion`.
