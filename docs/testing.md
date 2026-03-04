# Test structure

## Directory layout

Tests live under `apps/server/tests/` in feature-based subdirectories
that mirror the source modules they cover:

```
tests/
├── conftest.py              # Shared fixtures (available to all subdirs)
├── builders.py              # Synthetic data generators for integration tests
├── _paths.py                # Stable path constants (SERVER_ROOT, REPO_ROOT)
│
├── analysis/                # vibesensor/analysis/* — findings, strength, phase
├── api/                     # vibesensor/routes/*, vibesensor/api.py
├── app/                     # vibesensor/app.py, runtime.py, worker_pool
├── car_library/             # Car profile/variant modules
├── config/                  # vibesensor/config.py, settings_store, constants
├── domain/                  # vibesensor/domain_models.py, json_utils, registry
├── e2e/                     # Selenium browser tests (marked @selenium)
├── gps/                     # vibesensor/gps_speed.py, speed parsing
├── history/                 # vibesensor/history_db.py, runlog
├── hygiene/                 # Architecture guards, repo hygiene, smoke tests
├── integration/             # Cross-cutting level tests, scenarios, multi-sensor
├── live_diagnostics/        # vibesensor/live_diagnostics/*
├── metrics_log/             # vibesensor/metrics_log/*
├── processing/              # vibesensor/processing/* — FFT, buffers, time-align
├── protocol/                # vibesensor/protocol.py, UDP tx/rx
├── regression/              # Bug-fix regressions grouped by intent:
│   ├── audits/              # Coverage and report audits
│   ├── bugfix_batches/      # PR/batch-level bug-fix packs
│   ├── cycle_fixes/         # Numbered cycle regression packs
│   └── review_fixes/        # Review-driven regression packs
├── report/                  # vibesensor/report/* — PDF, i18n, hotspots
├── update/                  # vibesensor/update/*, firmware_cache, esp_flash
└── websocket/               # vibesensor/ws_hub.py, ws_models, schema export
```

## Finding tests

### By source module

| If you change…                          | Tests live in…            |
|-----------------------------------------|---------------------------|
| `vibesensor/analysis/*`                 | `tests/analysis/`         |
| `vibesensor/report/*`                   | `tests/report/`           |
| `vibesensor/processing/*`              | `tests/processing/`       |
| `vibesensor/live_diagnostics/*`        | `tests/live_diagnostics/` |
| `vibesensor/routes/*`, `vibesensor/api.py` | `tests/api/`          |
| `vibesensor/ws_hub.py`, `ws_models.py` | `tests/websocket/`       |
| `vibesensor/config.py`, `settings_store.py` | `tests/config/`     |
| `vibesensor/gps_speed.py`              | `tests/gps/`             |
| `vibesensor/protocol.py`, `udp_*.py`  | `tests/protocol/`        |
| `vibesensor/metrics_log/*`             | `tests/metrics_log/`     |
| `vibesensor/update/*`, `firmware_cache.py` | `tests/update/`      |
| `vibesensor/history_db.py`, `runlog.py`| `tests/history/`         |
| `vibesensor/app.py`, `runtime.py`      | `tests/app/`             |
| `vibesensor/domain_models.py`          | `tests/domain/`          |
| Car library modules                     | `tests/car_library/`     |

### By feature

| Feature                    | Tests live in…                    |
|----------------------------|-----------------------------------|
| Recording & signal flow    | `tests/processing/`, `tests/protocol/` |
| Analysis & findings        | `tests/analysis/`                 |
| Report generation          | `tests/report/`                   |
| Live dashboard diagnostics | `tests/live_diagnostics/`         |
| GPS speed tracking         | `tests/gps/`                      |
| Settings & configuration   | `tests/config/`                   |
| Car profiles               | `tests/car_library/`              |
| OTA updates                | `tests/update/`                   |
| WebSocket API              | `tests/websocket/`                |
| REST API endpoints         | `tests/api/`                      |

### Cross-cutting tests

| Category          | Directory            | Description                                |
|-------------------|----------------------|--------------------------------------------|
| Integration       | `tests/integration/` | Multi-module scenarios, level tests        |
| Regression        | `tests/regression/`  | Bug-fix regressions grouped into `audits/`, `bugfix_batches/`, `cycle_fixes/`, `review_fixes/` |
| Architecture      | `tests/hygiene/`     | Repo hygiene, architecture guards, smoke   |
| End-to-end        | `tests/e2e/`         | Selenium browser tests                     |

## Running tests

```bash
# Full suite (excludes browser tests)
pytest -q -m "not selenium" apps/server/tests

# Single feature area
pytest -q apps/server/tests/analysis/
pytest -q apps/server/tests/report/
pytest -q apps/server/tests/processing/

# Integration tests only
pytest -q apps/server/tests/integration/

# Regression tests only
pytest -q apps/server/tests/regression/

# With live progress
python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" apps/server/tests

# CI-parity (all jobs in parallel)
make test-all
```

## Adding new tests

1. **Identify the source module** your test covers.
2. **Place the test** in the matching `tests/<module>/` subdirectory.
3. **Name the file** `test_<descriptive_name>.py`.
4. **Use fixtures** from `conftest.py` (available to all subdirs) and
   builders from `builders.py` (`from builders import …`).
5. **For path references**, import `SERVER_ROOT` / `REPO_ROOT` from
   `_paths` instead of using fragile `Path(__file__).parents[N]` chains.
6. **For cross-cutting tests** that span multiple modules, use
   `tests/integration/` (scenarios) or `tests/regression/` (bug fixes).
   Under regression, place files in the matching intent folder:
   `audits/`, `bugfix_batches/`, `cycle_fixes/`, or `review_fixes/`.

## Naming conventions

- **Test files**: `test_<feature_or_module>.py`
- **Regression file names**: prefer descriptive names (for example
  `test_analysis_pipeline_fixes.py`) over ad-hoc run labels.
- **Test classes**: `Test<FeatureName>` (group related tests)
- **Test functions**: `test_<behavior_under_test>`
- **Fixtures/builders**: in `conftest.py` (fixtures) or `builders.py` (data generators)
- **Path helpers**: in `_paths.py` (`SERVER_ROOT`, `REPO_ROOT`)

## Markers

| Marker     | Meaning                                    |
|------------|--------------------------------------------|
| `selenium` | Browser-based UI tests (skipped in CI)     |
| `e2e`      | Docker-based end-to-end tests              |
| `long_sim` | Longer simulated-run tests (>20s data)     |
| `smoke`    | Minimal critical path checks               |
