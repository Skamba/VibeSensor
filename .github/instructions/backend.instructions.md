---
applyTo: "pi/**"
---
Backend (python `pi/`)
- Entry points: `pi/vibesensor/app.py` for runtime, `pi/vibesensor/report_pdf.py` for PDF generation, and `pi/vibesensor/api.py` for http endpoints.
- Install: `python -m pip install -e "./pi[dev]"` (used by CI).
- Tests: add unit tests under `pi/tests/` and prefer `-m "not selenium"` for fast runs.
- i18n: Add/modify keys in `pi/vibesensor/report_i18n.py` when changing user-facing strings.
- Styling/lint: `ruff` is used in CI; follow existing `ruff` conventions.
