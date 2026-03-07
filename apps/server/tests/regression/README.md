# Regression tests

Regression tests are grouped by intent to make discovery predictable:

- `audits/`: coverage/report audits that verify known finding sets.
- `analysis/`: analysis/scoring/order-detection regression packs.
- `cross_cutting/`: broad regressions spanning multiple subsystems.
- `report/`: PDF/report-data rendering and formatting regressions.
- `runtime/`: runtime/storage/API guard regressions.

Each intent folder now keeps focused regression files grouped by behavior or maintenance boundary rather than a single dumping-ground suite.

Quick smoke-style entry points:

- `analysis/test_analysis_pipeline_guard_regressions.py`
- `audits/test_analysis_pipeline_audit.py`
- `cross_cutting/test_multi_domain_regressions.py`
- `report/test_report_rendering_regressions.py`
- `runtime/test_api_history_processing_regressions.py`

The `report/` folder is split by maintenance boundary:

- `test_report_rendering_regressions.py` covers PDF/report-data rendering and formatting guardrails.
- `test_report_signal_filtering_regressions.py` covers signal filtering and buffer-shape regressions that feed report generation.

Naming convention:

- Prefer `test_<descriptive_scope>.py` (for example, `test_analysis_pipeline_guard_regressions.py`).
- Keep helper functions local to a focused file unless they materially reduce duplication across multiple files.
