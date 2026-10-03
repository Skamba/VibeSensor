# Design Language

This repo uses a **minimal, flat design system** with a purple accent for both:
- `apps/ui/` (web application) — auto light/dark via `prefers-color-scheme`
- `apps/server/vibesensor/report/pdf.py` (generated PDF reports) — light/print-friendly

## Goals
- One visual system across live UI and exported reports.
- Modern, minimal, calm aesthetic suited for laptop/tablet-in-car use.
- Clear action hierarchy (primary vs neutral vs destructive).
- Stable, token-driven styling (no ad-hoc colors in feature code).

## Accent Color
Single accent: **purple** (`#7c3aed` light mode, `#a78bfa` dark mode).
Used for: primary actions, active tabs, focus rings, key highlights.

## Color Roles
Core token roles:
- `primary`: main actions and active navigation (purple)
- `surface` / `surface-container`: cards, backgrounds, panels
- `on-surface` / `on-surface-variant`: main and secondary text
- `outline` / `outline-variant`: borders and table separators
- `tertiary`: success/status positive feedback (green)
- `error`: destructive actions and critical status (red)

Web tokens are defined in:
- `apps/ui/src/styles/app.css` (`:root` + `@media (prefers-color-scheme: dark)`)

Report colors are defined at the top of:
- `apps/server/vibesensor/report/pdf.py`

## Theme
- **Auto theme**: default follows system preference (`prefers-color-scheme`).
- Light: `#f8f9fb` background, `#ffffff` surface, calm neutrals.
- Dark: `#0f1117` background, `#1a1d27` surface, muted borders.
- Both modes are intentionally designed (not just inverted).

## Drive Sizing Mode
Automatic on touch/coarse-pointer tablet-ish viewports (`pointer: coarse` + `max-width: 1024px`):
- 44px minimum touch targets
- Increased spacing and font sizes
- Optimized for glanceability and easy tapping

## Component Rules
- Buttons:
  - `btn--primary`: main action (purple)
  - Neutral buttons on Live view (no green/red for start/stop)
  - State communicated via status pill + clear text
  - Flat, no gradients
- Pills:
  - `pill--ok`, `pill--muted`, `pill--bad` map to status states
- Cards:
  - Subtle borders, no heavy shadows
  - Full-bleed page background (no boxed "app container" look)
- Tables:
  - Header row uses surface-container-high + strong text
  - Body uses subtle separators and optional zebra rows
- Charts:
  - Shared palette in `apps/ui/src/theme.ts` (purple as first series color)
  - Order bands and series colors come from shared theme constants

## Live View Car Map
- Top-down SVG car map positioned right of the spectrum chart (split layout).
- Heat coloring per location using report-consistent p95 intensity metric over a 10-second rolling window.
- Event pulse: glow ring + brief blink animation on new vibration events.
- Tapping the car map does nothing for now.
- Location taxonomy: reuses the report location codes from `apps/server/vibesensor/domain/locations.py`.

## Do / Don't
- Do use existing tokens and classes.
- Do add new tokens only in theme/token files.
- Don't hardcode hex/rgba values inside feature logic.
- Don't introduce alternate visual systems per page.
- Don't compute strength metrics in client-side UI code (guardrail enforced by tests).

## PDF Report Layout

A4 portrait, built-in Helvetica, light/print-friendly, drawn by
`apps/server/vibesensor/report/pdf.py` from the `ReportView` built in
`report/view_model.py` (see `docs/report_pipeline.md`):

1. **Owner page**: a header band, then the verdict box. The verdict box is
   tinted by verdict and level: green for no fault, amber for Moderate, red for
   Strong, grey for weak evidence. It holds one confidence chip (the level word
   and its action meaning) and one plain sentence. Below that, the next step,
   fallback step, and check-the-fix boxes, with the car diagram beside them.
2. **Workshop page**: test conditions grid, findings table (diagnosed row
   tinted), amplitude table, ruled-out list, spectrum and amplitude-vs-speed
   charts, and the shop-request box.
3. **Data quality page**: only when a check warns. Otherwise this information
   is one footer line on page 2.

Rules:

- Never show a confidence percentage.
- Speeds use an en dash (`50–118 km/h`). Units are kept with their number by a
  non-breaking space.
- Built-in Helvetica covers Latin-1 only. Avoid glyphs such as `≤`, `→`, and
  `≈` in report strings.
- Colors are module constants in `report/pdf.py`. The accent is the same purple
  as the UI.

### i18n
All user-visible strings go through `tr(lang, KEY)` in `report/i18n.py` with
English and Dutch text in `data/report_i18n.json`. The view model resolves them;
the renderer never holds literals.

## Accessibility Notes
- Keep focus rings visible (`:focus-visible`).
- Maintain high text contrast on filled controls.
- Preserve keyboard usability in tab navigation and form controls.
