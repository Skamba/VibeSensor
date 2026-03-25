# Testing

## Key locations

- Server tests live under `apps/server/tests/`.
- Use `make test-ci-lite` for the non-Docker blocking-CI subset.
- Use `make test-all` (`python3 tools/tests/run_ci_parallel.py`) for the broader local runner, including Docker-backed jobs when Docker is available.
- The full Docker-backed verification runner is `make test-full-suite` (`python3 tools/tests/run_e2e_parallel.py --shards 1`), which defaults to the lean backend-only `apps/server/Dockerfile.e2e` image path.
- `tools/tests/run_e2e_parallel.py` records observed shard test durations in `~/.cache/vibesensor/e2e-duration-cache.json` so later local or CI runs can rebalance without hand-maintained timing hints.
- Python test configuration lives in `apps/server/pyproject.toml`.
- Backend structural AST/import guards live in `tools/dev/verify_backend_static_guards.py` and run via `make lint` (or directly with `cd apps/server && python3 ../../tools/dev/verify_backend_static_guards.py`).

## Layout

The test tree is feature-based. Most directories mirror the backend package or module they cover.

```text
apps/server/tests/
├── _paths.py
├── conftest.py
├── test_support/
├── adapters/
├── app/
├── domain/
├── hygiene/
├── infra/
├── integration/
├── shared/
└── use_cases/
```

Older flat roots such as `analysis/`, `api/`, `config/`, `gps/`, `history/`,
`hotspot/`, `metrics_log/`, `processing/`, `protocol/`, `report/`, `update/`,
and `websocket/` were consolidated into the mirrored tree above. Do not create
new top-level flat roots; use the matching mirrored area unless the test is
intentionally cross-cutting.

## Where tests belong

| If you change... | Start with... |
|---|---|
| `vibesensor/adapters/http/*` | `apps/server/tests/adapters/http/` |
| `vibesensor/adapters/{hotspot,pdf,persistence,simulator,udp,websocket}/*` | the matching `apps/server/tests/adapters/.../` directory |
| `vibesensor/app/*` | `apps/server/tests/app/` |
| `vibesensor/domain/*` | `apps/server/tests/domain/` |
| `vibesensor/infra/{config,processing,runtime,workers}/*` | the matching `apps/server/tests/infra/.../` directory |
| `vibesensor/shared/boundaries/*`, `vibesensor/shared/types/sensor_frame.py`, shared helper utilities | `apps/server/tests/shared/` |
| Shared types and metadata contracts used across the domain boundary (`run_schema`, `car_config`, `sensor_config`, `speed_source_config`, `settings_snapshot`, `settings_types`) | `apps/server/tests/domain/` or `apps/server/tests/shared/` depending on the ownership boundary under test |
| `vibesensor/use_cases/{diagnostics,history,run,updates}/*` | the matching `apps/server/tests/use_cases/.../` directory |

Use cross-cutting directories when a test is intentionally broader than one package boundary:

- `apps/server/tests/integration/`: scenario, pipeline, multi-module behavior, and bug-fix regressions spanning multiple subsystems.
- `apps/server/tests/hygiene/`: architecture guards and repo hygiene.

Those two directories are the intentional flat exceptions to the mirrored tree.

Regression tests live alongside the feature they primarily test. Cross-cutting
regressions that span multiple subsystems go in `integration/`.

Prefer focused files grouped by behavior or maintenance boundary. Shared helpers live in `test_support/` — including `findings.py` (shared finding-payload factories), `report_helpers.py`, `scenario_ground_truth.py`, `sample_scenarios.py`, plus focused modules for synthetic data, assertions, and fault/perturbation scenarios. Per-directory helper modules (like `_report_pdf_test_helpers.py`, `_report_persistence_helpers.py`) stay local to their test directories.

If a guard needs AST or source-text inspection of production modules, put it in `tools/dev/verify_backend_static_guards.py` instead of pytest. Tests should exercise behavior, outputs, side effects, and errors through stable interfaces.

## Contract bridge tests

Contract bridge tests live in `apps/server/tests/integration/` and validate that data produced by one subsystem is accepted by the next. They catch schema drift at subsystem boundaries that unit tests miss.

| File | Boundary |
|---|---|
| `test_contract_analysis_report.py` | `summarize_run_data()` → `prepare_report_input()` → `map_summary()` |
| `test_contract_persistence_analysis.py` | `HistoryDB` write → read → `summarize_run_data()` |

These tests are marked `smoke`, run in standard CI, use minimal synthetic data,
and complete in under 5 seconds.

## Running tests

Four tiers: `make test-changed` for a fast changed-file heuristic, `make test` for backend iteration, `make test-ci-lite` for the non-Docker blocking-CI subset, `make test-all` for the broader local runner, and `act -W .github/workflows/ci.yml` (required before finalizing) to run the real GitHub workflow locally in Docker.

Main local tiers:

```bash
# Changed-file heuristic (current branch vs origin/main, fallback to main)
make test-changed

# Fast iteration — backend unit tests
make test

# Non-Docker blocking-CI subset
make test-ci-lite

# Full local runner — includes Docker-backed jobs when Docker is available
make test-all

# Required pre-finalization gate — real GitHub workflow via act (requires Docker)
act -W .github/workflows/ci.yml
```

Focused feature-area and fuzzing runs:

```bash
pytest -q apps/server/tests/adapters/pdf/
pytest -q apps/server/tests/use_cases/history/
pytest -q apps/server/tests/use_cases/updates/
pytest -q apps/server/tests/integration/
python3 tools/dev/fuzz_analysis_engine.py --duration-s 60 --batch-examples 100 --processes 16
```

Focused CI job groups and full-stack validation:

```bash
python3 tools/tests/run_ci_parallel.py --job backend-quality --job backend-typecheck --job backend-tests
python3 tools/tests/run_ci_parallel.py --job frontend-typecheck --job ui-smoke
python3 tools/tests/run_ci_parallel.py --job release-smoke
make test-full-suite
```

`release-smoke` is the packaged-artifact gate. It builds or reuses the server
wheel, validates packaged static assets, boots the packaged server, and checks
that `/api/health` reaches readiness. It is complementary to Docker/e2e
validation, not a duplicate of it.

## Fuzzing

Use `tools/dev/fuzz_analysis_engine.py` for randomized diagnostics coverage
against the real `summarize_run_data()` analysis entrypoint. The harness uses
Hypothesis, validates the produced summary against the typed analysis contract,
and writes a minimized reproduction artifact under `artifacts/fuzz/` when it
finds a failure.

```bash
python3 tools/dev/fuzz_analysis_engine.py
python3 tools/dev/fuzz_analysis_engine.py --duration-s 60 --batch-examples 100 --processes 16
python3 tools/dev/fuzz_processing_pipeline.py
python3 tools/dev/fuzz_processing_pipeline.py --target fft --duration-s 60 --processes 16
```

The script expects the backend package plus dev dependencies to be installed,
for example via:

```bash
python3 -m pip install -e "./apps/server[dev]"
```

`tools/dev/fuzz_processing_pipeline.py` covers upstream live-processing entry
points that sit before persisted diagnostics:

- `strength`: canonical vibration-strength math in `vibesensor.vibration_strength`
- `fft`: pure FFT spectrum assembly in `vibesensor.infra.processing.fft`
- `processor`: live ingest / compute / debug payload paths in `SignalProcessor`

Both fuzzers default to 16 concurrent worker processes. Use `--processes` to
tune parallelism if you need to trade off CPU saturation against local
interactivity. `--threads` remains accepted as a compatibility alias.

## Local CI with `act`

[`act`](https://nektosact.com/) runs the real `.github/workflows/ci.yml` locally
inside Docker containers. It is the primary path for CI-parity validation.

Prerequisites: Docker and [`act`](https://nektosact.com/installation/index.html).

### Raw `act` commands (primary interface)

```bash
# List available CI jobs
act -l -W .github/workflows/ci.yml

# Run all CI jobs (push event)
act -W .github/workflows/ci.yml

# Run a single job
act -j backend-quality -W .github/workflows/ci.yml
act -j backend-typecheck -W .github/workflows/ci.yml
act -j frontend-typecheck -W .github/workflows/ci.yml
act -j backend-tests -W .github/workflows/ci.yml
act -j ui-smoke -W .github/workflows/ci.yml
act -j release-smoke -W .github/workflows/ci.yml

# Run with pull_request event (uses the included event payload)
act pull_request -W .github/workflows/ci.yml -e tools/tests/act-event.json
```

### Optional wrapper (convenience only)

A thin shell wrapper is provided at `tools/tests/run_ci_with_act.sh`. It checks
prerequisites and passes arguments through to `act`:

```bash
./tools/tests/run_ci_with_act.sh -l               # list jobs
./tools/tests/run_ci_with_act.sh                   # run all CI jobs
./tools/tests/run_ci_with_act.sh -j backend-quality  # run one job
```

### Secrets

No secrets are currently required. If needed in the future, copy
`.secrets.act.example` to `.secrets.act`, fill in values, and the wrapper (or
`--secret-file .secrets.act`) will pick them up. Never commit `.secrets.act`.

### Known limitations under `act`

| Job | Status | Notes |
|---|---|---|
| `backend-quality` | ✅ Fully supported | — |
| `backend-typecheck` | ✅ Fully supported | — |
| `frontend-typecheck` | ✅ Fully supported | — |
| `ui-smoke` | ✅ Fully supported | — |
| `release-smoke` | ✅ Fully supported | — |
| `backend-tests` | ⚠️ Mostly works | 5 update-module tests that depend on system-level features (sudo, network interfaces) may fail inside the `act` container. All other tests pass. |
| `e2e` | ❌ Not supported | Requires Docker-in-Docker. Run `make test-full-suite` or use GitHub CI instead. |

### Relationship to `run_ci_parallel.py`

`tools/tests/run_ci_parallel.py` (`make test-all`) remains available as a fast
local convenience runner. `act` is the primary CI-parity mechanism — it runs the
actual GitHub workflow file. Use `run_ci_parallel.py` when you want a faster
non-containerized local run without Docker.

## Coverage reporting

Use coverage runs to expose untested paths before they become release risk.

```bash
make coverage
make coverage-html
make coverage-strict
```

For direct control over thresholds and output:

```bash
cd apps/server && python -m pytest -q --cov=vibesensor --cov-report=term-missing:skip-covered tests
```

Coverage guidance:

- Treat coverage as a risk-finding tool, not the only quality signal.
- High-risk backend areas such as `use_cases/diagnostics/`,
  `infra/processing/`, `adapters/persistence/history_db/`, and
  `use_cases/updates/` should stay above the repo-wide baseline whenever
  practical.

The default CI-parity suite now mirrors these blocking GitHub checks:

- `backend-quality`: Ruff, line endings, config preflight, path-indirection guard, backend static guards, docs lint, WS schema sync, and HTTP API schema sync.
- `backend-typecheck`: mypy on the `vibesensor` backend package; package discovery keeps new backend files checked by default without an internal module denylist.
- `frontend-typecheck`: `npm run typecheck` in `apps/ui/`.
- `release-smoke`: builds packaged UI and a server wheel, then runs the release smoke validator against the built artifact.
- `ui-smoke`, `backend-tests`, `e2e`: required test jobs.

## Adding or moving tests

1. Put the test in the narrowest directory that matches the production ownership boundary.
2. Keep files focused on one behavior, scenario family, or maintenance boundary.
3. Reuse shared helpers only when multiple files need the same setup or assertions.
4. Import `SERVER_ROOT` and `REPO_ROOT` from `_paths.py` instead of using fragile parent traversals.

Cached helpers such as `@lru_cache` are acceptable when they memoize immutable
test data. If a test monkeypatches the underlying file, path, or other cached
state, clear the cache in that test before asserting on the changed behavior.

## Markers

| Marker | Meaning |
|---|---|
| `e2e` | Docker-based end-to-end tests |
| `long_sim` | Longer simulated-run tests |
| `smoke` | Minimal critical-path checks |

Use markers sparingly:

- `@pytest.mark.smoke`: fast, deterministic, high-signal checks for critical
  paths such as schema/contract bridges or minimal end-to-end behavior.
- `@pytest.mark.long_sim`: slower simulated-run tests that intentionally trade
  speed for more scenario coverage.
- `@pytest.mark.e2e`: Docker-backed end-to-end tests.

Do not mark every fast unit test as `smoke`; keep it a compact slice that is
useful for quick feedback.
