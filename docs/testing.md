# Testing

## Source of truth

- Server tests live under `apps/server/tests/`.
- The canonical local verification entry point is `python3 tools/tests/run_verification.py`.
- The default CI-parity runner is `make test-all` (`python3 tools/tests/run_verification.py --suite ci-parity`).
- The full Docker-backed verification runner is `make test-full-suite` (`python3 tools/tests/run_verification.py --suite full-stack`).
- Python test configuration lives in `apps/server/pyproject.toml`.

## Layout

The test tree is feature-based. Most directories mirror the backend package or module they cover.

```text
apps/server/tests/
├── conftest.py
├── _paths.py
├── _*.py helper modules
├── test_support/
├── analysis/
├── api/
├── app/
├── car_library/
├── config/
├── domain/
├── e2e/
├── gps/
├── history/
├── hygiene/
├── integration/
├── live_diagnostics/
├── metrics_log/
├── processing/
├── protocol/
├── regression/
│   └── {analysis,audits,cross_cutting,report,runtime}/
├── report/
├── test_support/
├── update/
└── websocket/
```

## Where tests belong

| If you change... | Start with... |
|---|---|
| `vibesensor/analysis/*` | `apps/server/tests/analysis/` |
| `vibesensor/report/*`, `report_i18n.py` | `apps/server/tests/report/` |
| `vibesensor/routes/*` | `apps/server/tests/api/` |
| `vibesensor/app.py`, `bootstrap.py`, `runtime/*`, `worker_pool.py` | `apps/server/tests/app/` |
| `vibesensor/history_db/*`, `history_*.py`, `runlog.py` | `apps/server/tests/history/` |
| `vibesensor/update/*`, `firmware_cache.py`, `esp_flash_manager.py`, `release_fetcher.py` | `apps/server/tests/update/` |
| `vibesensor/processing/*` | `apps/server/tests/processing/` |
| `vibesensor/live_diagnostics/*` | `apps/server/tests/live_diagnostics/` |
| `vibesensor/ws_hub.py`, `ws_models.py`, `ws_schema_export.py` | `apps/server/tests/websocket/` |
| `vibesensor/config.py`, `settings_store.py`, `constants.py` | `apps/server/tests/config/` |
| `vibesensor/domain_models.py`, `json_utils.py`, `registry.py` | `apps/server/tests/domain/` |
| `vibesensor/gps_speed.py` | `apps/server/tests/gps/` |
| `vibesensor/protocol.py`, `udp_*.py` | `apps/server/tests/protocol/` |
| `vibesensor/metrics_log/*` | `apps/server/tests/metrics_log/` |
| `vibesensor/car_library.py` and related data | `apps/server/tests/car_library/` |

Use cross-cutting directories when a test is intentionally broader than one package boundary:

- `apps/server/tests/integration/`: scenario, pipeline, and multi-module behavior.
- `apps/server/tests/regression/`: bug-fix regressions grouped by intent.
- `apps/server/tests/hygiene/`: architecture guards and repo hygiene.
- `apps/server/tests/e2e/`: browser and Docker-backed end-to-end coverage.

## Regression layout

Regression coverage is grouped by intent:

- `regression/analysis/`: scoring, ranking, signal-selection, and analysis pipeline guardrails.
- `regression/audits/`: audit-style tests that verify known findings or coverage gaps.
- `regression/cross_cutting/`: failures that span multiple subsystems.
- `regression/report/`: report rendering and report-data regressions.
- `regression/runtime/`: runtime, history, API, queueing, and update-adjacent regressions.

Prefer focused files grouped by behavior or maintenance boundary. Recent high-churn suites in `api/`, `report/`, `update/`, `analysis/`, and `apps/ui/tests/` are intentionally split into smaller behavior-focused files plus local helper modules such as `_history_endpoint_helpers.py`, `_report_persistence_helpers.py`, `_report_pdf_test_helpers.py`, `_update_manager_test_helpers.py`, `_diagnosis_robustness_helpers.py`, `_phased_scenario_helpers.py`, and `smoke.helpers.ts` so failures stay easy to diagnose without centralizing unrelated assertions in one mega-file.

## Running tests

```bash
# Canonical verification entry points
python3 tools/tests/run_verification.py --suite ci-parity
python3 tools/tests/run_verification.py --suite full-stack

# Full backend suite (excludes selenium)
pytest -q -m "not selenium" apps/server/tests

# Single feature area
pytest -q apps/server/tests/report/
pytest -q apps/server/tests/history/
pytest -q apps/server/tests/update/

# Cross-cutting scopes
pytest -q apps/server/tests/integration/
pytest -q apps/server/tests/regression/report/

# Progress output for a faster local loop
python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" apps/server/tests

# CI-parity job groups
make test-all
python3 tools/tests/run_verification.py --suite ci-parity --job backend-quality --job backend-typecheck --job backend-tests
python3 tools/tests/run_verification.py --suite ci-parity --job frontend-typecheck --job ui-smoke
python3 tools/tests/run_verification.py --suite ci-parity --job release-smoke
```

`release-smoke` is the packaged-artifact gate. It builds or reuses the server
wheel, validates packaged static assets, boots the packaged server, and checks
that `/api/health` reaches readiness. It is complementary to Docker/e2e
validation, not a duplicate of it.

## Coverage reporting

Use coverage runs to expose untested paths before they become release risk.

```bash
make coverage
make coverage-html
make coverage-strict
```

For direct control over thresholds and output:

```bash
python3 tools/tests/run_coverage.py --min-coverage 75
python3 tools/tests/run_coverage.py --html --fail-under --min-coverage 85
```

Coverage guidance:

- Treat coverage as a risk-finding tool, not the only quality signal.
- Default coverage runs exclude `selenium` tests to match the fast local path.
- High-risk backend areas such as `analysis/`, `processing/`, `history_db/`, and `update/` should stay above the repo-wide baseline whenever practical.

The default CI-parity suite now mirrors these blocking GitHub checks:

- `backend-quality`: Ruff, line endings, config preflight, path-indirection guard, docs lint, WS schema sync, and HTTP API schema sync.
- `backend-typecheck`: mypy on the enforced backend slice covering app/bootstrap, runtime/routes, and the high-risk `analysis/`, `processing/`, `history_db/`, and `update/` packages.
- `frontend-typecheck`: `npm run typecheck` in `apps/ui/`.
- `release-smoke`: builds packaged UI and a server wheel, then runs the release smoke validator against the built artifact.
- `ui-smoke`, `backend-tests`, `e2e`: required test jobs.

## Adding or moving tests

1. Put the test in the narrowest directory that matches the production ownership boundary.
2. Keep files focused on one behavior, scenario family, or maintenance boundary.
3. Reuse shared helpers only when multiple files need the same setup or assertions.
4. Import `SERVER_ROOT` and `REPO_ROOT` from `_paths.py` instead of using fragile parent traversals.
5. If a refactor changes test placement or ownership boundaries, update this file in the same change set.

## Markers

| Marker | Meaning |
|---|---|
| `selenium` | Browser-based UI tests |
| `e2e` | Docker-based end-to-end tests |
| `long_sim` | Longer simulated-run tests |
| `smoke` | Minimal critical-path checks |
