# Library Resource Browser Design QA

Source visual truth: `/var/folders/9w/9q5gs7cx7ssgwmhs27wzkxfh0000gn/T/codex-clipboard-636478ca-5367-411e-a2d9-d650b9c24a78.png`

Implementation: `http://127.0.0.1:5173/library`

Implementation screenshot: `docs/stage-reports/evidence/library-resource-redesign/motion-selected-1440x960.png`

Normalized comparison: `docs/stage-reports/evidence/library-resource-redesign/reference-implementation-comparison.png`

Viewport and normalization:

- Source PNG: 1224 × 1731 px. The selected-resource reference board was cropped to
  1147 × 764 px, then normalized to 720 × 480 px.
- Implementation: 1440 × 960 CSS px and 1440 × 960 captured pixels at browser density
  1, normalized to 720 × 480 px.
- Both normalized states use the desktop Motion tab with the first Motion selected and
  the right detail panel open.

State: real local Repository/API data, V2, Dry Run, backend online, robot disconnected.
The disconnected status intentionally differs from the connected example in the visual
source and was not fabricated for fidelity.

## Findings

No actionable P0, P1, or P2 differences remain.

- Fonts and typography: the implementation preserves MOMO Studio's existing sans-serif
  family, compact optical weights, truncation, and hierarchy. Card names and panel titles
  remain readable at desktop and mobile sizes.
- Spacing and layout rhythm: the three-column browse grid, two-column selected grid,
  narrow sticky detail rail, white cards, light borders, compact radii, and low-elevation
  surfaces match the reference hierarchy. The 390 px view changes the rail into a fixed
  390 × 720 px bottom sheet rather than compressing the grid.
- Colors and tokens: existing gray surfaces and the MOMO purple accent drive tabs,
  selection, transport, badges, and primary actions. Runtime green remains limited to
  truthful backend state.
- Image quality and asset fidelity: cards use cached static Canvas projections generated
  from each resource's real joint and TCP data. Motion cards include real keyframe ghosts
  and a TCP path. Only the selected detail owns a live URDF/STL WebGL viewer; no placeholder
  icon or duplicated Three.js viewer remains.
- Copy and content: names, tags, variants, keyframe counts, durations, motion modes, TCP,
  and timestamps come from the local API. Legacy descriptions, UUIDs, revisions, and
  fingerprints no longer overload browse cards.
- Icons and controls: the implementation reuses the product's established icon family.
  More, close, simulation transport, Studio navigation, and management controls have
  semantic labels and visible focus states.
- Interaction states: selected, switch, close, Escape, More, rename, duplicate, delete,
  loading, empty, offline, preview fallback, Pose Goto, simulation Play/Pause/Scrub, and
  the separate safety-execution flow were exercised by tests or browser QA.

## Focused region comparison

The selected card, simulation thumbnail, right detail header, 3D preview, transport,
metadata row, primary action, and More/safety rows were inspected in the normalized
comparison. This focused region was sufficient because the requested change is confined
to Library and the surrounding application shell was intentionally preserved.

## Comparison history

1. First desktop pass found one P2 color drift: the Studio primary action inherited a
   teal global treatment instead of the reference/product purple.
2. The Library detail action token was explicitly mapped to the existing purple accent.
3. The 1440 × 960 post-fix capture shows the selected border, simulation transport, and
   primary action using the same purple family; no other P0/P1/P2 issue remained.

## Browser evidence

- Checked 1440 × 960, 1280 × 800, and 390 × 844.
- Opened Motion and Pose details, switched tabs/resources, closed the detail panel,
  played/paused/scrubbed the simulation, inspected real 3D viewers, and verified Studio
  link destinations.
- Mobile computed layout: one card column and a fixed 390 × 720 px bottom sheet inside a
  390 × 844 viewport, with no horizontal overflow.
- Browser console errors/warnings: 0.
- Backend remained Dry Run; no serial, servo, torque, real motion, or camera access was used.

## Follow-up polish

- P3: a later visual-only iteration could tune the static arm projection link lengths per
  hardware variant. The current projection already represents actual joint/TCP data and
  is intentionally lightweight.

## Implementation checklist

- [x] Browse cards are compact and whole-card selectable.
- [x] Low-frequency management lives behind More.
- [x] Static real-data thumbnails avoid per-card WebGL contexts.
- [x] One interactive detail viewer supports simulation playback and camera controls.
- [x] Pose Goto still uses the existing safety gateway.
- [x] Backend safety execution remains separately labeled and gated.
- [x] Desktop rail and mobile bottom-sheet layouts pass.

final result: passed

---

# Studio Timeline Redesign — Design QA

## Scope

- Page: Studio / Motion Workspace only.
- Reference: `MOMO Studio · Modern Minimal.pdf`, Desktop / Studio board.
- Evidence: `docs/stage-reports/evidence/studio-timeline-redesign/`.
- Safety posture: DRY_RUN. Timeline playback and scrubbing update only the frontend simulation viewer; no hardware motion route is invoked.

## Visual comparison

- Reference and implementation were reviewed side by side in `reference-vs-implementation.jpg`.
- The workspace is reduced to the intended three primary regions: Viewer, Inspector, and Timeline.
- The Viewer is free of engineering workflow cards and exposes only lightweight simulation status.
- The Inspector contains only name, incoming transition duration, motion mode, duplicate, and delete.
- Timeline is the only visible Add Keyframe entry point and uses the existing left-side drawer.
- Timeline ruler, duration-proportional segments, keyframe points, and red playhead match the reference hierarchy.

## Responsive checks

| Viewport | Result |
| --- | --- |
| 1440×960 | Viewer, Inspector, and Timeline fit without page scrolling; document width matches viewport. |
| 1280×800 | All three primary regions remain visible above the status footer; document width matches viewport. |

Long timelines use local horizontal scrolling inside the Timeline instead of expanding the page.

## Interaction checks

- Selecting a keyframe synchronizes the Inspector, playhead, and 3D viewer.
- Dragging a keyframe updates its time, the adjacent transition durations, the total duration, and the Inspector value.
- Scrubbing the playhead updates the viewer without issuing robot commands.
- Duplicate inserts an immutable snapshot after the selected keyframe; delete respects the two-keyframe minimum.
- Add Keyframe drawer opens from Timeline, uses the real Pose Library, adds the selected pose, and closes.
- Orbit and zoom remain available in the 3D viewer.
- The existing imported legacy draft is rejected by backend compilation because its stored snapshot fingerprint does not match its declared robot contract. The compact `无法预览` state is shown as designed. Valid compile/play/pause/save/reload paths are covered by frontend integration tests.
- Browser console errors and warnings: 0.

## Automated verification

- Studio interaction and state tests cover timing edits, minimum spacing, no crossing, synchronization, simulation playback, no hardware calls, duplicate/delete, hidden zero hold, save, undo, and redo.
- Frontend: 68 suites, 307/307 tests passed.
- Backend: 670/670 tests passed.
- TypeScript, ESLint, Ruff, and mypy passed.
- Frontend production build and repository `make build` passed. Vite reports only the existing large-chunk advisory.

## Keyframe selection and first-frame refinement

- Source visual truth: `/var/folders/9w/9q5gs7cx7ssgwmhs27wzkxfh0000gn/T/codex-clipboard-f7f8581a-6011-4f8c-a717-b9476e9384c9.png`, 1177×787 px, plus the user's explicit state direction that selected markers are filled and unselected markers are hollow.
- Browser implementation captures: `keyframe-selected-k2.jpg` and `keyframe-start-mode-disabled.jpg`, each 1471×1250 px from a 1177×1000 CSS viewport. The in-app browser capture surface adds unused right/bottom pixels; comparisons use the rendered page region only.
- Full-state comparison: `keyframe-selection-state-comparison.jpg`.
- Focused timeline comparison: `keyframe-marker-focused-comparison.jpg` clearly shows K2 changing from the former hollow/ambiguous state to a purple filled selected marker, while K1, K3, and K4 remain hollow.
- K1 browser state shows `进入运动模式` as a gray disabled control with `起始关键帧（无进入运动）`; selecting K2 restores the enabled `JOINT`/`CARTESIAN_LINEAR` choices.
- Fonts and typography, layout rhythm, product tokens, 3D image quality, and surrounding copy remain unchanged. The state-only styling uses the existing MOMO purple, surface, border, and muted-text tokens.
- Browser interactions tested: K1, K2, and K3 selection; playhead/Inspector synchronization; first-frame disabled mode; non-first-frame enabled mode. Console errors/warnings: 0.

### Comparison history

1. The supplied current-state screenshot used an ambiguous marker convention in which the selected frame was not represented by a clear purple fill.
2. Marker fills were inverted so hollow means unselected and purple filled means selected; the first-frame mode was given an explicit disabled presentation and truthful empty-state copy.
3. The post-fix focused comparison has no remaining actionable P0/P1/P2 difference for this requested refinement.

## Result

final result: passed

---

# Studio Responsive Timeline and Last-frame Extension — Design QA

## Scope and evidence

- Source visual truth: `/var/folders/9w/9q5gs7cx7ssgwmhs27wzkxfh0000gn/T/codex-clipboard-66b07458-601f-4486-81a7-df7420b4cb2b.png` (685×111 px). This is the supplied defect baseline: the ruler ends early and leaves an uncovered region at the right.
- Implementation URL: `http://127.0.0.1:5173/studio?draft=6ea9af28-08fe-4a3d-a980-083318834a85`.
- Browser implementation screenshot: `docs/stage-reports/evidence/studio-timeline-responsive/studio-timeline-responsive-1440x960.jpg` (1800×1200 capture surface).
- Density-normalized implementation: `docs/stage-reports/evidence/studio-timeline-responsive/studio-timeline-responsive-1440x960-normalized.jpg` (1440×960 rendered page region for the 1440×960 CSS viewport).
- Focused combined comparison: `docs/stage-reports/evidence/studio-timeline-responsive/studio-timeline-reference-vs-implementation.png`. The 685×111 source was normalized to 1147×186; the implementation Timeline was cropped to the same 1147×186 region. The supplied screenshot and current draft have different playhead/keyframe times, so comparison is limited to the requested ruler coverage, track geometry, and right-side space.
- State: local Vite app, existing four-keyframe V2 draft, DRY_RUN, short-motion non-scrolling state. No hardware route was invoked.

## Findings

No actionable P0, P1, or P2 differences remain for this requested change.

- Fonts and typography: ruler labels, Motion heading, transport labels, frame labels, and segment durations continue to use the existing Studio type scale and hierarchy. Tail-space ticks use the same formatting and optical weight.
- Spacing and layout rhythm: the ruler and track now cover the complete measured Timeline viewport at both target widths. The final frame retains visible tail space instead of being pinned to the right edge. Border, padding, track height, and surrounding panel rhythm are unchanged.
- Colors and visual tokens: existing Studio surface, divider, purple selection/segment, muted ruler, and red playhead tokens are preserved. No new visual token drift was introduced.
- Image quality and asset fidelity: this change adds no image assets and leaves the real URDF/STL viewer unchanged. The comparison uses a lossless focused PNG so ruler and marker alignment remain readable.
- Copy and content: real draft labels, transition durations, and total motion duration remain data-driven. The ruler may extend beyond the true motion duration to expose the requested tail buffer; transport output and playhead bounds still report the true motion duration.
- Responsiveness: at 1280×800, the short-motion track measured 998.24 px against a 998 px scroll viewport; at 1440×960 it measured 1176.99 px against a 1177 px viewport. The 1.25 px outer-border remainder is covered by the Timeline panel and produces no visible blank ruler area. Document-level horizontal overflow was 0 px at both sizes.
- Interaction: real-page keyboard extension moved K4 from 2.60 s to 2.65 s, and one Undo restored it to 2.60 s. Component-level pointer testing covers final-frame edge extension, `requestAnimationFrame` auto-scroll, and a single committed edit. Interior-frame crossing, K1 locking, 0.05 s spacing, Inspector synchronization, and playhead clamping remain covered by regression tests.

## Full-view and focused comparison

The 1440×960 full view confirms that Viewer, Inspector, Timeline, and the app shell retain their established proportions with no page-level horizontal overflow. The focused combined comparison is required because the source only shows the Timeline strip; it clearly shows the defect baseline ending its ruler early, while the implementation carries the ruler and lavender track treatment through the full available width and keeps useful space after the final keyframe.

## Comparison history

1. The supplied baseline exposed a P2 responsive defect: the time ruler was width-bound to the motion duration, leaving a large uncovered right-side region after the page widened, and the last frame had no practical extension area.
2. Timeline layout was split into measured viewport width, true motion duration, view duration, track width, and pixels-per-second. A bounded 15% tail buffer and minimum readable long-motion density were added.
3. Last-frame dragging now locks the initial time scale, grows the track near the 40 px right-edge zone, auto-scrolls locally, and commits once on release. The final focused comparison and 1280/1440 browser metrics show no remaining P0/P1/P2 issue.

## Verification

- Browser sizes: 1280×800 and 1440×960, plus live resize between them.
- Browser console: 0 error-level entries; only Vite/React development messages were present.
- Frontend tests: 31 files, 312/312 tests passed.
- Studio Timeline focused tests: 16/16 passed.
- TypeScript, ESLint, and Vite production build passed. Vite reports only the existing large-chunk advisory.
- Safety: frontend-only change; no API, schema, PoseSnapshot, calibration, serial, servo, or real-motion boundary changed.

## Follow-up polish

No P3 visual follow-up is required for this scope.

## Implementation checklist

- [x] Short motions fill the measured Timeline viewport.
- [x] Long motions preserve at least 112 px/s and scroll only inside Timeline.
- [x] Tail buffer is 15% of motion duration, clamped to 0.5–2 s.
- [x] Ruler uses view duration; playhead and transport use true motion duration.
- [x] Final frame can extend later and auto-scrolls at the right edge.
- [x] Middle-frame ordering, K1 locking, minimum spacing, and atomic history semantics remain intact.
- [x] No page-level horizontal overflow or console error is present at target sizes.

final result: passed
