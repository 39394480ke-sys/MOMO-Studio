# ADR 0013: Motion Draft and timeline editor

- Status: Accepted
- Date: 2026-08-24

## Context

A formal `Motion` is durable, portable playback data and must always contain at least
two complete, compatible keyframes. Studio must nevertheless support an empty document,
incremental capture, crash recovery, undo/redo, and revision-conflict recovery. Weakening
the formal invariant would let incomplete editor state leak into Library, compilation,
or playback.

The domain stores an incoming transition on the target keyframe. A timeline reorder can
make that representation ambiguous: carrying a transition with the moved target would
silently attach its duration/mode/easing to a different source keyframe. Studio also
needs backend compiler truth without creating a second executable-sample API.

The pinned Legacy commit exposed a monolithic PyQt action page, a controller-coupled
recorder, and display-name-based action files containing raw/multi-turn/gripper fields.
It did not provide a revisioned draft, explicit directed-edge reorder semantics, bounded
undo history, or a safe compiler boundary. Those files are characterization evidence
only and are not reused.

## Decision

Studio persists a separate immutable `MotionDraft` schema `1.0.0`. It allows zero to
1,000 keyframes and carries its own UUID, optional paired source Motion UUID/revision,
name, description, robot variant, complete embedded keyframes, playback defaults, tags,
typed editor metadata, typed server-owned source metadata, a bounded server-owned Legacy
snapshot trust registry, revision, and aware timestamps. Optional source identity fields
must appear as a coherent pair. Draft validation preserves unique keyframe IDs, explicit
units, variant consistency, and safe finite public bounds, but deliberately does not
pretend that zero or one keyframe is playable.

Drafts use UUID filenames beneath the ignored server-owned `data/drafts` directory.
The existing atomic JSON repository rules apply: schema validation, compare-and-swap
revision, temporary sibling write, file and directory sync, atomic replace, bounded
files/scans/aggregate bytes, symlink rejection, and corrupt-file quarantine. Draft data,
temporary writes, quarantine, and recovery state are operational data and are never
committed. The API accepts entity values and UUIDs only, never a path.

The persisted recovery schema requires every serialized field, including nested UUIDs,
edge identities, server-owned provenance/trust, and transaction-marker identity.
Repository roots are validated before construction and must be pairwise disjoint,
including ancestor, symlink/inode, case-insensitive, and Unicode-normalizing aliases.
This prevents a Draft reader from mistaking a formal Motion document for corrupt Draft
data and quarantining it.

The bounded Studio API is rooted at `/api/v1/studio`:

```text
GET/POST    /drafts
POST        /drafts/from-motion/{motion_id}
GET/PUT/DELETE /drafts/{draft_id}
POST        /drafts/{draft_id}/fork
POST        /drafts/{draft_id}/save-intent/abandon
POST        /drafts/{draft_id}/validate
POST        /drafts/{draft_id}/compile
POST        /drafts/{draft_id}/save
POST        /drafts/{draft_id}/save-as
POST        /drafts/{draft_id}/keyframes/{keyframe_id}/goto
POST        /capture
```

`PUT` is the full-document CAS autosave operation. Every edit advances only from the
client's expected draft revision. A conflict never overwrites newer recovery data.
Opening a Motion copies all embedded snapshots into a draft and records source UUID and
revision; the source is provenance, not a live keyframe link. Imported snapshots with no
source state sequence are also registered by full canonical SHA-256 identity. Sorted-key
JSON makes mapping order irrelevant while any field mutation, replacement, or fabricated
null-sequence snapshot remains rejected. Clients cannot inject source metadata or trust;
autosave, recovery, rebind, abandon, and fork preserve both.

The frontend editor represents segment settings as an explicit directed
`Edge(from_keyframe_id, to_keyframe_id)`. Reorder preserves settings only when the exact
directed adjacency still exists. Every newly formed adjacency receives the explicit
editor default; the first keyframe has no incoming edge. Conversion back to Domain
attaches each edge to its target keyframe only after the ordered adjacency is known.
Pure reducer tests own these semantics. Add/delete/duplicate/reorder/snapshot/name and
transition edits enter a bounded undo/redo history; autosave acknowledgement does not
create an editor history entry. The exact directed adjacencies that still use the editor
default are persisted in bounded metadata, so crash recovery cannot turn an explicit
default marker into an indistinguishable manually edited segment.

Draft validation and compilation occur on the backend. Conversion constructs a new
formal `Motion` and therefore re-applies its two-keyframe, transition, compatibility,
and snapshot invariants. `save` uses the source Motion's expected revision; `save-as`
creates a fresh Motion UUID at revision 1. Every revision conflict identifies only
`MotionDraft` or `Motion`; missing/unknown scope fails closed. A conflict offers Reload
or Save As and never uses last-writer-wins. Save As captures local state before loading
the authoritative Draft, exact-revision forks the server entity, PUTs captured local
content onto the fork, rebinds, and only then creates the new Motion. The original Draft
and Motion are not overwritten.

A formal save spans the Draft and Motion repositories through a write-ahead intent on
the Draft. The intent records operation identity, target UUID/revision/name, immutable
target creation time, and expected source revision before the Motion write. The final
Draft rebind clears the marker in a second CAS revision. Request cancellation cannot
cancel an in-flight commit; a process restart reconciles a persisted marker. Exact target
revisions require a full semantic match, including typed source metadata. If the target
of a known-source Save has advanced, recovery binds its UUID but retains only the
revision actually targeted, so the next Save conflicts instead of overwriting the later
writer. An advanced fresh/Save-As target or creation/content mismatch cannot be proven:
the marker is retained and access fails closed. No recovery branch automatically
creates a second UUID.

A retained marker can be released only by an exact operator request carrying the
current Draft revision, marker operation UUID, and fixed confirmation literal. That raw
CAS clears only the exact marker and advances the Draft once; it never creates, updates,
adopts, or deletes a Motion. Stale or mismatched release requests remain conflicts.

For example, a new Draft revision 1 may target Motion `M` revision 1. The marker is
first persisted at Draft revision 2. If `M` is then written but the process stops before
the final Draft CAS, the next Draft read verifies the exact target identity and semantic
content, binds `M` revision 1, clears the marker, and persists Draft revision 3. It does
not create another Motion. If a known-source `M` has already advanced, recovery retains
the intended source revision so the next Save conflicts; if a fresh target has advanced
or has different identity/content, recovery preserves the marker and returns a conflict
for explicit operator resolution.

Inspector Goto never submits browser-owned joint values through the generic Control
route. Its endpoint loads the requested keyframe from the persisted Draft at an expected
revision, revalidates variant, enabled-joint set, units, profile and kinematics
fingerprints against the active robot, and submits a `STUDIO` Joint Goto through the
single reviewed motion safety gateway. The Studio mutation lock is retained from Draft
recovery through revision/keyframe checks and command submission, preventing concurrent
autosave from replacing the persisted target in that interval. It remains Dry Run-only.

Draft compile returns structured Stage 5 preflight and bounded preview evidence with
`executable=false`. It neither inserts a prepared trajectory into the Stage 5 playback
cache nor returns executable sample arrays. Dry Run playback requires saving a formal
Motion, running its normal revision-bound Stage 5 preflight, and playing that exact
digest. Real preview/playback remains blocked.

## Alternatives

- Allow incomplete formal Motion entities: rejected because Library and playback could
  no longer rely on the two-keyframe invariant.
- Store drafts only in browser storage: rejected because recovery, schema validation,
  CAS conflicts, and cross-reload behavior would be weaker and browser-specific.
- Carry target-keyframe transition values through reorder: rejected because a moved
  target can acquire a different source and silently change segment meaning.
- Compile or interpolate in React: rejected because it would create a second trajectory
  implementation with different safety evidence.
- Put draft compile output into the playback cache: rejected because an incomplete or
  unsaved editor document must never become executable.
- Reuse the Legacy recorder or action-file manager: rejected because they couple UI,
  controllers, mutable files, raw hardware data, and display names without the new
  boundaries.

## Consequences

Incomplete editor work is recoverable without weakening the formal domain. Reorder has
deterministic, reviewable segment semantics, and Save/Save As have explicit optimistic
concurrency. Draft compilation remains useful for correction and preview while playback
continues through the single reviewed gateway.

Draft and Motion repositories remain single-process writers. Autosave creates bounded
local write traffic and requires UI status for saving/saved/conflict/offline states.
Recovery does not imply cloud sync or multi-user collaboration. A formal Motion must be
saved and preflighted again after every relevant draft or source revision change.

The route-facing backend facade owns only Draft/compile coordination and the two Studio
locks; lock-free formal-save and robot-action collaborators own their cohesive policies.
The frontend workspace is a small composition facade over the pure reducer and bounded
Draft, Motion, Pose, and dirty-navigation session hooks rather than one all-state
component.
