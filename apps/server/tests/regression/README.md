# Regression tests

Regression tests are grouped by intent to make discovery predictable:

- `audits/`: coverage/report audits that verify known finding sets.
- `analysis/`: analysis/scoring/order-detection regression packs.
- `cross_cutting/`: broad regressions spanning multiple subsystems.
- `report/`: PDF/report-data rendering and formatting regressions.
- `runtime/`: runtime/storage/API guard regressions.

Each intent folder now keeps a single consolidated regression pack file:

- `analysis/test_analysis_regressions.py`
- `audits/test_audit_regressions.py`
- `cross_cutting/test_cross_cutting_regressions.py`
- `report/test_report_regressions.py`
- `runtime/test_runtime_regressions.py`

Naming convention:

- Prefer `test_<descriptive_scope>.py` (for example, `test_analysis_pipeline_guard_regressions.py`).
- Avoid ambiguous run labels when a feature-focused name is available.
