# Regression tests

Regression tests are grouped by intent first, then by narrower scope:

- `audits/`: coverage and pipeline audits (`coverage/`, `pipeline/`).
- `analysis/`: analysis regressions (`pipeline/`, `scoring/`, `signal/`).
- `cross_cutting/`: broad regressions (`contracts/`, `delivery/`, `domains/`, `review/`).
- `report/`: report regressions (`rendering/`, `signal/`).
- `runtime/`: runtime regressions (`api/`, `concurrency/`, `guards/`, `metrics/`, `quality/`, `queues/`, `signal/`).

Within each scope folder, tests are split into **class/function-scoped files**:

- file pattern: `<legacy_pack_name>__<class_or_group_slug>.py`
- each file contains one regression class (or one module-level regression-function group)
- this keeps individual regression intent explicit while preserving the intent/scope directory layout

Naming convention:

- Prefer `test_<descriptive_scope>.py` (for example, `test_runtime_validation_and_schema.py`).
- Avoid ambiguous run labels when a feature-focused name is available.
