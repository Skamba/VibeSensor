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

## Accessibility Notes
- Keep focus rings visible (`:focus-visible`).
- Maintain high text contrast on filled controls.
- Preserve keyboard usability in tab navigation and form controls.

