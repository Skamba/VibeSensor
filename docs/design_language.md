# Design Language

This repo uses **Material Design 3** as its single design language for both:
- `ui/` (web application)
- `pi/vibesensor/report_pdf.py` (generated PDF reports)

## Goals
- One visual system across live UI and exported reports.
- Clear action hierarchy (primary vs secondary vs destructive).
- Stable, token-driven styling (no ad-hoc colors in feature code).

## Color Roles
Core Material-style roles used in this project:
- `primary`: main actions and active navigation
- `surface` / `surface-container`: cards, backgrounds, panels
- `on-surface` / `on-surface-variant`: main and secondary text
- `outline` / `outline-variant`: borders and table separators
- `tertiary`: success/status positive feedback
- `error`: destructive actions and critical status

Web tokens are defined in:
- `ui/src/styles/app.css` (`:root` `--md-sys-color-*` tokens)

Report tokens are defined in:
- `pi/vibesensor/report_theme.py`

## Component Rules
- Buttons:
  - `btn--primary`: main action in a section
  - `btn--success`: positive/run actions
  - `btn--danger`: destructive/stop/delete actions
- Pills:
  - `pill--ok`, `pill--muted`, `pill--bad` map to status states
- Tables:
  - Header row uses surface-container-high + strong text
  - Body uses subtle separators and striped rows
- Charts:
  - Shared palette is defined in `ui/src/theme.ts`
  - Order bands and series colors come from shared theme constants, not inline literals

## Do / Don't
- Do use existing tokens and classes.
- Do add new tokens only in theme/token files.
- Don't hardcode hex/rgba values inside feature logic.
- Don't introduce alternate visual systems per page.

## PDF Report Layout

The generated PDF uses A4 landscape and is structured as a **workshop handout**:

### Page structure
1. **Workshop Summary** (page 1) — header bar, three status cards (Overall Status, Top Suspected Cause, Run Conditions), "What to check first" action table, and an "Evidence snapshot" mini-table.
2. **Evidence & Hotspots** (page 2) — left column: car hotspot heat-map diagram (42 % width); right column: two stacked adaptive charts (54 % width) with an interpretation note.
3. **Appendices** — sensor stats, speed-binned analysis tables, and full findings list.

### Primitives
| Primitive | File | Purpose |
|-----------|------|---------|
| `make_card(story, title, body, tone)` | `report_pdf.py` | MD3 card with tone-based bg/border (`success`, `warn`, `error`, `neutral`) |
| `styled_table(data, col_widths, zebra)` | `report_pdf.py` | Table with theme header and optional zebra-striped rows |
| `_confidence_pill_html(label, pct, tone)` | `report_pdf.py` | Inline HTML pill for High / Medium / Low confidence |
| `line_plot(…, width, height)` | `report_pdf.py` | Parameterised plot that accepts custom size |

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

