# Regression tests

Regression tests are grouped by intent to make discovery predictable:

- `audits/`: coverage/report audits that verify known finding sets.
- `bugfix_batches/`: PR or batch-level bug-fix packs.
- `cycle_fixes/`: cycle-based fix packs (kept in numeric order).
- `review_fixes/`: reviewer-driven fix packs.

Naming convention:

- Prefer `test_<descriptive_scope>.py` (for example, `test_analysis_pipeline_fixes.py`).
- Avoid ambiguous run labels when a feature-focused name is available.
