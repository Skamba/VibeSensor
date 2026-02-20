# Design Language

This repo uses a **minimal, flat design system** with a purple accent for both:
- `apps/ui/` (web application) — auto light/dark via `prefers-color-scheme`
- `apps/server/vibesensor/report_pdf.py` (generated PDF reports) — light/print-friendly

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

Report tokens are defined in:
- `apps/server/vibesensor/report_theme.py`

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
- Location taxonomy: reuses report's canonical location codes from `apps/server/vibesensor/locations.py`.

## Do / Don't
- Do use existing tokens and classes.
- Do add new tokens only in theme/token files.
- Don't hardcode hex/rgba values inside feature logic.
- Don't introduce alternate visual systems per page.
- Don't compute strength metrics in client-side UI code (guardrail enforced by tests).

## PDF Report Layout

The generated PDF uses A4 landscape and is structured as a **workshop handout**:

### Page structure
1. **Workshop Summary** (page 1) — header bar, three status cards (Overall Status, Top Suspected Cause, Run Conditions), "What to check first" action table, and an "Evidence snapshot" mini-table.
2. **Evidence & Hotspots** (page 2) — left column: car hotspot heat-map diagram (42 % width); right column: two stacked adaptive charts (54 % width) with an interpretation note.
3. **Appendices** — sensor stats, speed-binned analysis tables, and full findings list.

### Primitives
| Primitive | File | Purpose |
|-----------|------|---------|
| `make_card(story, title, body, tone)` | `apps/server/vibesensor/report_pdf.py` | MD3 card with tone-based bg/border (`success`, `warn`, `error`, `neutral`) |
| `styled_table(data, col_widths, zebra)` | `apps/server/vibesensor/report_pdf.py` | Table with theme header and optional zebra-striped rows |
| `_confidence_pill_html(label, pct, tone)` | `apps/server/vibesensor/report_pdf.py` | Inline HTML pill for High / Medium / Low confidence |
| `line_plot(…, width, height)` | `apps/server/vibesensor/report_pdf.py` | Parameterised plot that accepts custom size |

### Card tone tokens (`report_theme.py`)
- `card_neutral_bg / _border` — informational
- `card_success_bg / _border` — good / ok status
- `card_warn_bg / _border` — attention needed
- `card_error_bg / _border` — critical issue

### Confidence pills (`report_theme.py`)
- `pill_high_bg / _text` (≥ 70 %)
- `pill_medium_bg / _text` (≥ 40 %)
- `pill_low_bg / _text` (< 40 %)

### Heat-map endpoints
`HEAT_LOW` → `HEAT_MID` → `HEAT_HIGH` define the gradient for the car hotspot diagram.

### Adaptive chart selection
- **Sweep mode** (variable speed): matched amplitude vs speed + frequency vs speed with predicted curve.
- **Steady mode** (constant speed): amplitude vs time + dominant frequency vs time.

### i18n
All user-visible strings go through `tr(lang, KEY)` in `report_i18n.py`. Add new keys there—never inline literals in `report_pdf.py`.

## Accessibility Notes
- Keep focus rings visible (`:focus-visible`).
- Maintain high text contrast on filled controls.
- Preserve keyboard usability in tab navigation and form controls.

