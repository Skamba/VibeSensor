# Design Language

This repo uses a **minimal, flat design system** with a purple accent for both:
- `apps/ui/` (web application) — auto light/dark via `prefers-color-scheme`
- `apps/server/vibesensor/adapters/pdf/` (generated PDF reports) — light/print-friendly

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
- `apps/server/vibesensor/adapters/pdf/pdf_style.py`

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
- Location taxonomy: reuses the report location codes from `apps/server/vibesensor/shared/locations.py`.

## Do / Don't
- Do use existing tokens and classes.
- Do add new tokens only in theme/token files.
- Don't hardcode hex/rgba values inside feature logic.
- Don't introduce alternate visual systems per page.
- Don't compute strength metrics in client-side UI code (guardrail enforced by tests).

## PDF Report Layout

The generated PDF uses A4 portrait and starts with a **one-glance verdict page**:

### Page structure
1. **Verdict page** (page 1) — compact date/car/run metadata, primary source,
   inspect-first target, short reason, a compact decision path, concise proof
   rows, ranked source-comparison bars, and the first action plus
   confirm/clean/parts-gate outcomes. Page 1 intentionally omits the run
   timeline and support-duration phrasing that can be confused with elapsed
   runtime. The action preview must not truncate the instruction, the lower
   layout should use the available vertical space for useful proof/inspection
   facts, and fallback wording should be operational (for example, "If the
   primary path is clean: inspect the fallback path") rather than vague caveat
   language.
2. **Appendix / evidence pages** — Appendix-B style location proof and hotspot
   diagrams, Appendix-C diagnosis proof packs, worksheet/action-matrix guidance,
   and diagnostic peak/evidence tables are rendered from the canonical
   `ReportDocument`, not by re-running diagnostics in the PDF adapter.
3. **Inspection path** — full action-card detail, alternatives,
   confirm/falsify guidance, and longer evidence/context that does not belong on
   the glanceable verdict page.

### Primitives
| Primitive | File | Purpose |
|-----------|------|---------|
| `parts_for_pattern(system, order)` | `apps/server/vibesensor/use_cases/history/report_document/pattern_parts.py` | Centralized pattern-to-parts mapping |
| `strength_text(db_value, lang)` | `apps/server/vibesensor/shared/report_presentation.py` | Natural-language strength label with dB |
| `ConfidenceAssessment.tier` | `apps/server/vibesensor/domain/confidence_assessment.py` | Report layout tier (A/B/C) for section visibility |

### Card tone tokens (`apps/server/vibesensor/adapters/pdf/pdf_style.py`)
- `brand_surface_soft` — low-emphasis metadata strip background
- `card_neutral_bg / _border` — informational
- `card_success_bg / _border` — good / ok status
- `card_warn_bg / _border` — attention needed
- `card_error_bg / _border` — critical issue

### Heat-map gradient
The car hotspot diagram uses a severity gradient defined in
`apps/server/vibesensor/adapters/pdf/pdf_style.py` and is planned/rendered
through the report-document and PDF adapter modules under
`apps/server/vibesensor/use_cases/history/report_document/` and
`apps/server/vibesensor/adapters/pdf/`.

### i18n
All user-visible strings go through `tr(lang, KEY)` in `report_i18n.py`. Add new keys there instead of introducing new inline literals across the PDF renderer modules.

## Accessibility Notes
- Keep focus rings visible (`:focus-visible`).
- Maintain high text contrast on filled controls.
- Preserve keyboard usability in tab navigation and form controls.
