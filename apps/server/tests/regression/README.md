# Regression tests

Regression tests are grouped by intent to make discovery predictable:

- `audits/`: coverage/report audits that verify known finding sets.
- `bugfix_batches/`: PR or batch-level bug-fix packs.
- `analysis/`: analysis/scoring/order-detection regression packs.
- `report/`: PDF/report-data rendering and formatting regressions.
- `review_fixes/`: reviewer-driven fix packs.
- `runtime/`: runtime/storage/API guard regressions.

Naming convention:

- Prefer `test_<descriptive_scope>.py` (for example, `test_analysis_pipeline_fixes.py`).
- Avoid ambiguous run labels when a feature-focused name is available.
