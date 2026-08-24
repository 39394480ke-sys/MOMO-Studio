# Studio user workflow

Studio is the local Dry Run timeline editor. It never opens serial, camera, microphone,
or raw-servo capabilities, and a draft is never directly playable.

## Start or recover work

Open **Studio** to create an empty draft, recover a local autosaved draft, or follow an
**Open in Studio** / **Add to Studio** link from Library. Opening a Motion records its
UUID and revision and copies complete keyframe snapshots. Adding a Pose copies its
snapshot; later Pose edits or deletion cannot alter the draft.

For a reviewed Legacy-imported Motion, the backend also copies typed importer provenance
and records canonical identities for exact snapshots whose source state sequence is
unavailable. These server-owned values survive autosave/recovery and conflict forks but
cannot be supplied or edited by the browser. Reorder, duplicate, delete then Undo of an
exact trusted snapshot are valid; replacing or fabricating a null-sequence snapshot is
rejected.

The header distinguishes Dirty, Saving, Saved, Conflict, and Offline states. Autosave
uses the last acknowledged draft revision and never clears Undo/Redo. Refreshing after a
successful autosave reloads the same draft. A corrupt draft is quarantined by the
backend and omitted without preventing other recovery entries from loading.

## Edit the timeline

The timeline is horizontally scrollable inside its own container; the application page
does not scroll sideways. Select a keyframe to inspect its label, Joint snapshot, TCP,
hold, source Pose, and incoming segment. Add or capture before/after the selection,
replace the snapshot with the current coherent Dry Run state, duplicate, or delete.

**Goto** is available only for a keyframe that belongs to the current persisted Draft
revision. The browser sends the Draft UUID, keyframe UUID, expected revision, and bounded
operator intent—not joint targets. The backend reloads that embedded snapshot, checks it
against the active Profile and Kinematics fingerprints, then submits it with Studio
provenance through the normal Dry Run safety gateway. One Studio mutation lock keeps
Draft recovery, revision/keyframe checks, and submission ordered ahead of any concurrent
autosave. A stale Draft revision, incompatible
snapshot, disconnected/stale robot, or active motion fails closed.

Drag controls and keyboard Move Earlier/Move Later actions use the same reducer. A
segment retains duration, Joint/Cartesian Linear mode, and easing only when its exact
directed source-to-target adjacency survives reorder. New adjacencies receive the shown
Studio default. The first keyframe never has an incoming transition. Undo and Redo are
bounded and do not rewind server autosave acknowledgements.

On narrow screens, the Inspector opens as a drawer/bottom sheet while the timeline stays
usable. Every icon action has an accessible name, visible focus, and a reason when
disabled.

## Validate and preview

Zero or one keyframe can be autosaved but cannot become a Motion. **Validate** converts a
candidate in memory and reports the formal domain checks. **Preview** calls the backend
Stage 5 compiler and displays its checks, violations, Joint traces, TCP summary, and
segment/keyframe markers. The browser does not interpolate.

Draft compile evidence is explicitly non-executable. To run it:

1. Save or Save As a formal Motion.
2. Run the normal Motion preflight for that exact Motion revision.
3. Review the returned digest and preview.
4. Start Dry Run playback through the Stage 5 playback controls.

Stop remains available during preflight or playback. Real preview and Real playback are
blocked pending Stage 8 and physical field acceptance.

## Save, conflicts, and leaving

**Save** updates the source Motion only with its recorded expected revision. Revision
conflicts are scoped by the backend to the Draft or Motion; missing/unknown scope and an
active formal-save recovery state fail closed. If another edit won, Studio preserves
the draft and offers:

- **Reload**: open the latest source revision as a new editor state;
- **Save As**: preserve the current local document on an authoritative server-side
  Draft fork, rebind Studio to it, then create a new Motion UUID at revision 1.

There is no overwrite-anyway action. **Save As** also works for a new draft and accepts
a new name. The source Motion is provenance only after the copy is made.

Formal Save/Save As first records a write-ahead marker, writes the exact Motion, and then
rebinds the Draft in a second revision. If the backend stops after the Motion write, the
next Draft read verifies the exact UUID/revision and semantic content before completing
the rebind; it never silently creates a duplicate Motion. A known-source Motion that has
advanced keeps the intended stale source revision so a later Save conflicts. An advanced
fresh/Save-As target or mismatched identity/content retains the marker and fails closed
rather than being adopted.

When a retained recovery marker cannot be reconciled, Studio shows its bounded
transaction identity. **Abandon formal save** requires the exact Draft revision,
operation UUID, and explicit confirmation. It clears only that marker in a new Draft
revision and never creates, updates, adopts, or deletes a Motion. After an ordinary
conflict, Save As captures local name/keyframes before any recovery request, forks the
authoritative Draft at its exact revision, PUTs the captured local document, then
rebinds and saves; server-owned provenance stays server-side and the original entities
remain untouched.

Navigation while Dirty asks for confirmation. Cancel keeps the editor and focus in
Studio; confirm leaves without claiming that unsaved local edits were persisted. When
offline, editing and Undo/Redo remain local, but validation, compile, capture, save, and
playback fail closed until backend status returns.

## Limits

- Draft and Motion writers support one backend process.
- A draft has at most 1,000 keyframes and inherits the four-MiB entity limit.
- All configured storage roots must be disjoint, including case/Unicode filesystem aliases.
- Timeline zoom is a review aid, not a change to motion duration.
- Multi-select, curve editing, custom Bezier easing, PyBullet UI, Real motion, and
  collaborative editing are outside Stage 6.
