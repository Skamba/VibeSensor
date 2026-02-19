---
applyTo: "apps/server/**"
---
Backend (python `apps/server/`)
- Entry points: `apps/server/vibesensor/app.py` for runtime, `apps/server/vibesensor/report/pdf.py` for PDF generation, and `apps/server/vibesensor/api.py` for http endpoints.
- Install: `python -m pip install -e "./apps/server[dev]"` (used by CI).
- Tests: add unit tests under `apps/server/tests/` and prefer `-m "not selenium"` for fast runs.
- i18n: Add/modify keys in `apps/server/data/report_i18n.json` when changing user-facing strings.
- Styling/lint: `ruff` is used in CI; follow existing `ruff` conventions.
- After backend changes, always rebuild and test via the Docker container (`docker compose build --pull && docker compose up -d`) rather than only running unit tests. Use the simulator to verify end-to-end behaviour.
