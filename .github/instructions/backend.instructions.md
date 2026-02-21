---
applyTo: "apps/server/**"
---
Backend (python `apps/server/`)
- Shared workflow/validation rules live in `.github/instructions/general.instructions.md`; this file only captures backend-specific deltas.
- Entry points: `apps/server/vibesensor/app.py` for runtime, `apps/server/vibesensor/report_pdf.py` for PDF generation, and `apps/server/vibesensor/api.py` for http endpoints.
- Install: `python -m pip install -e "./apps/server[dev]"` (used by CI).
- Tests: add unit tests under `apps/server/tests/` and prefer `-m "not selenium"` for fast runs.
- i18n: Add/modify keys in `apps/server/data/report_i18n.json` when changing user-facing strings.
- Styling/lint: `ruff` is used in CI; follow existing `ruff` conventions.
