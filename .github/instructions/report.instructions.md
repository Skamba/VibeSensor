---
applyTo: "apps/server/vibesensor/report/**/*.py,apps/server/vibesensor/report_*.py,apps/server/vibesensor/report_pdf.py,apps/server/data/report_i18n.json"
---
Report generation and diagnostics
- Shared workflow/validation rules live in `.github/instructions/general.instructions.md`; this file only captures report-specific deltas.
- Preserve persistence-aware diagnostics and ranking behavior; do not regress report ranking to max-only peak selection.
- Keep transient/impact events visible in report output, but not promoted above likely persistent faults by default.
- Validate report-facing output (rendered/report API/PDF text and ordering), not just internal helper outputs.
- Preserve parsing compatibility for old recorded runs/report data unless the task explicitly waives it.
- When user-facing report text changes, update `apps/server/data/report_i18n.json`.
