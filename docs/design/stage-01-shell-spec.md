# Stage 1 shell visual specification

Source concept: `stage-01-shell-concept.png` (generated for this repository on 2026-08-23).

## Visual direction

The shell combines a restrained photography workstation with industrial control clarity. A dark charcoal/navy navigation rail and status header frame a true-white working surface. Muted cyan is reserved for the selected route. Status colors are semantic and small; there are no gradients, glow, glass, or decorative dashboard cards.

## Container and layout

- Desktop: fixed navigation rail; status header and footer span the content column; main content is one open vertical surface.
- Main page anatomy: route title and Stage explanation followed by flat, separated availability rows. No nested panels or bento grid.
- Mobile: navigation becomes a compact horizontal/scrollable route bar; status items wrap without clipping; content remains a single column.
- Primary concept viewport: 1536 × 1024 generated canvas. Browser comparison should use 1440 × 960 when available and also check a narrow mobile viewport.

## Type and tokens

- UI font: a system sans stack with deliberate weights and line heights.
- Backgrounds: shell approximately `#101c27`; top/footer approximately `#0d1721`; work surface true white.
- Text: near-black headings, slate body text, white shell labels.
- Accent: muted cyan for selected navigation and focus indication.
- Semantic state: green for backend online, amber for Dry Run, red for real-motion prohibition, neutral gray for offline.
- Geometry: small radii on navigation selection only; 1 px separators; no elevated cards or large shadows.

## Component inventory

- `AppShell`: navigation, top status, content outlet, Stage footer.
- `PrimaryNavigation`: exactly five route links with clear active state and accessible focus.
- `SystemStatus`: backend availability plus `DRY RUN` and `Real motion disabled`.
- Page heading/introduction.
- Flat availability/placeholder rows. Any icons are restrained, single-stroke, and non-interactive.

## Allowed shell copy

Above the main content, visible product/status copy is limited to: `MOMO Studio`, `Control`, `Studio`, `Library`, `Vision`, `Settings`, `Backend connected` or `Backend unavailable`, `DRY RUN`, and `Real motion disabled`.

The Control page may use: `Connection`, `Joint control`, `Cartesian control`, honest Stage 1 availability explanations, and `Stage 1 · Foundation`. Other routes may contain their route title and an honest foundation-stage explanation only. They must not present controls or fake state.

## Prohibited surface

No motion button or Real-mode enable operation; no robot/joint telemetry; no arm/fleet selector; no camera/image/video capture; no AI, voice, gesture, gripper, teach, community, or PyBullet entry; no fake metrics, charts, timelines, preview streams, or hardware render.

## Fidelity checklist

Final QA compares concept and implementation for: exact navigation/copy, full-frame composition, typography hierarchy, dark/white/cyan palette, flat separator-based content, status semantics, absence of invented controls, desktop proportions, mobile overflow, and route interaction.

## Stage 1 fidelity ledger

Compared on 2026-08-23 using the original concept and a fresh 1440 × 960 browser screenshot; both images were inspected at original detail.

| Comparison point | Concept evidence | Render evidence and disposition |
|---|---|---|
| Navigation and copy | Five-item left rail in the required order; Control selected | Exact order, labels and selected state match. Above-the-fold copy diff: none. |
| Frame and container model | 252 px dark rail, 72 px status header, open white workspace, dark footer | Same proportions and open separator-based workspace. At the shorter 960 px check viewport the workspace has a vertical scrollbar; no content is clipped and the footer remains fixed. |
| Typography | Large medium-weight Control title, 20 px slate body, deliberate shell labels | Hierarchy, line lengths, weights and control text are materially matched with a system sans stack. |
| Palette and states | Charcoal/navy shell, true white workspace, cyan selected route, green/amber/red status dots | Colors and semantic state order match; there are no gradients, glows or added overlays. |
| Placeholder anatomy | Three flat sections with restrained line icons and horizontal separators | Connection, Joint control and Cartesian control match; no cards, buttons, telemetry or fake controls were introduced. |
| Responsive behavior | Responsive-ready single-workspace hierarchy | Browser checks at 1440 × 960 and 390 × 844 found no horizontal document, navigation, status or workspace overflow. |
| Interaction and safety | Five route destinations and persistent safety status | All five navigation links, direct subroute refresh, backend-online state, safe fallback status, and status copy were exercised. |

No material visual mismatch remains. The generated concept is the only design artifact retained; temporary implementation screenshots are not repository assets.
