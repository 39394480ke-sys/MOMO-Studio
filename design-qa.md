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
