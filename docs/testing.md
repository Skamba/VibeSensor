# Testing

## Key locations

- Server tests live under `apps/server/tests/`.
- UI validation lives under `apps/ui/` (Vite build/typecheck plus Playwright browser checks).
- Firmware build/flash guidance lives in `firmware/esp/README.md`.
- Pi-image build/validation guidance lives in `infra/pi-image/pi-gen/README.md`.
- `make format` is the canonical Python formatting command for backend and tooling files; no other Python formatter is supported in the repo workflow.
- Use `make test-ci-lite` (`python3 tools/tests/run_ci_parallel.py --ci-lite`) for the non-Docker blocking-CI subset.
- Use `make test-all` (`python3 tools/tests/run_ci_parallel.py`) for the broader local runner.
- Use `make benchmark-backend` for the explicit pytest-benchmark backend suite; pass `BENCHMARK_OPTS="--benchmark-save=<name>"` to save runs and `BACKEND_BENCHMARK_TARGETS=...` to focus one benchmark file. For direct `--benchmark-only` pytest runs, add `-o addopts=''` so the default xdist addopts do not disable benchmark mode.
- Use `make benchmark-compare-backend` to compare saved runs from `apps/server/.benchmarks/`.
- The full end-to-end verification runner is `make test-full-suite` (`python3 tools/tests/run_e2e_parallel.py --shards 1`), which starts an isolated direct server subprocess per shard from `apps/server/config.docker.yaml` with static UI serving disabled.
- `tools/tests/run_backend_parallel.py` shards `apps/server/tests` by whole test file, using cached JUnit timings from `~/.cache/vibesensor/backend-duration-cache.json` to keep the backend CI shards balanced over time. It also accepts `--xdist-workers` / `VIBESENSOR_BACKEND_XDIST_WORKERS` for controlled intra-shard xdist; CI pins that to `2` because the repo's five-shard local CI-parallel benchmark beat `-n 0` (48.6s wall time) and still edged out the higher `-n 3` setting (41.5s) with `-n 2` (41.1s) while keeping the same shard contents.
- `tools/tests/run_e2e_parallel.py` records observed shard test durations in `~/.cache/vibesensor/e2e-duration-cache.json` so later local or CI runs can rebalance without hand-maintained timing hints.
- Python test configuration lives in `apps/server/pyproject.toml`.
- Backend pytest runs through `pytest-randomly`, which randomizes test module, class, and function order on every run and prints the active seed in the header (e.g. `Using --randomly-seed=1234567890`). Reproduce a failing run with `pytest --randomly-seed=<seed> ...`, pinning to the reported value. Disable per run with `-p no:randomly` only when isolating a tooling issue, not to mask a real order-dependent failure.
- Use `pytest-httpx` for backend outbound HTTP boundary tests around `httpx` clients; prefer it over monkeypatching low-level request functions when the goal is to assert request URLs, methods, payloads, status codes, and transport failures.
- Use the shared MSW helpers under `apps/ui/tests/msw/` for frontend HTTP-boundary tests; they normalize relative `/api/...` requests onto the test origin and fail unhandled requests loudly by default.
- Use `cd apps/ui && npm run dev:mock` for the optional browser-worker MSW mode when you need to exercise the UI without a live backend HTTP stack. That mode keeps unmocked HTTP requests on bypass, does not mock WebSockets, and has a dedicated smoke entrypoint at `cd apps/ui && npm run test:smoke:mock`.
- Backend structural AST/import guards live in `tools/dev/verify_backend_static_guards.py`, and repo/frontend hygiene guards live in `tools/dev/check_hygiene.py`; both run via `make lint`.
- Oversized tracked test/spec files are guarded in `tools/dev/check_hygiene.py` with the allowlist at `tools/dev/oversized_test_allowlist.yml`. Files at or above the shared threshold must either be split or carry an explicit allowlist reason, and the hygiene output always prints the current largest tracked test/spec files.
- `make sync-contracts` is the authoritative contract/doc regeneration path; `make lint` and the `backend-contract-drift` CI job run it in `--check` mode.

### Frontend HTTP tests with MSW

Use MSW only for frontend tests that intentionally cross the real HTTP boundary.

- Install the shared lifecycle from `apps/ui/tests/msw/node.ts` for Playwright
  specs that call the real UI HTTP client. It rewrites relative `/api/...`
  requests onto the test origin and throws on unhandled requests so missing
  handlers fail loudly.
- Keep reusable feature handlers in `apps/ui/tests/msw/handlers/` and cross-feature
  primitives in `apps/ui/tests/msw/http.ts`. Follow the existing naming pattern:
  `build<Feature>Handlers(...)`, `build<Feature><Scenario>Handlers(...)`, and
  `make<Feature><Thing>Payload(...)`.
- Prefer those shared scenario helpers over ad hoc `globalThis.fetch`
  replacement when multiple specs in the same feature area need the same HTTP
  behavior.
- Do not add MSW to tests that already inject transport ports or stay inside
  pure presenter/view/state seams. Those tests should remain network-free.
- WebSocket mocking is outside the MSW boundary here; keep using the dedicated
  fake WebSocket helpers for live-session flows.

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

If a guard needs AST or source-text inspection of production modules, put backend-specific checks in `tools/dev/verify_backend_static_guards.py` and repo/frontend boundary checks in `tools/dev/check_hygiene.py` instead of re-parsing source inside pytest. Hygiene tests should call those helpers through stable module interfaces rather than duplicating the source inspection logic. Oversized test/spec guardrails also belong in `tools/dev/check_hygiene.py`, with intentional exceptions documented in `tools/dev/oversized_test_allowlist.yml` rather than hidden in ad-hoc test code.

## Contract bridge tests

Contract bridge tests live in `apps/server/tests/integration/` and validate that data produced by one subsystem is accepted by the next. They catch schema drift at subsystem boundaries that unit tests miss.

| File | Boundary |
|---|---|
| `test_contract_analysis_report.py` | `summarize_run_data()` → `prepare_report_input()` → `build_report_document()` |
| `test_contract_persistence_analysis.py` | `HistoryDB` write → read → `summarize_run_data()` |

These tests are marked `smoke`, run in standard CI, use minimal synthetic data,
and complete in under 5 seconds.

## Running tests

Backend/local CI tiers: `make test-changed` for a fast changed-file heuristic, `make test` for backend iteration, `make test-ci-lite` for the non-Docker blocking-CI subset, `make test-all` for the broader local runner, and `act -W .github/workflows/ci.yml` (required before finalizing) to run the real GitHub workflow locally in Docker.

Main local tiers:

```bash
# Changed-file heuristic (current branch vs origin/main, fallback to main)
make test-changed

# Fast iteration — backend unit tests
make test

# Non-Docker blocking-CI subset
make test-ci-lite

# Full local runner
make test-all

# Explicit backend benchmarks
make benchmark-backend BENCHMARK_OPTS="--benchmark-save=baseline"
make benchmark-compare-backend

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

Explicit backend benchmark files stay out of default CI and normal pytest
discovery so the blocking lanes do not turn noisy or hardware-sensitive.
Run them on demand when you need regression evidence and save comparison data
for later runs with `make benchmark-backend` / `make benchmark-compare-backend`.

Focused CI job groups and full-stack validation:

```bash
python3 tools/tests/run_ci_parallel.py --ci-lite
python3 tools/tests/run_ci_parallel.py --job frontend-quality --job frontend-typecheck --job ui-smoke
python3 tools/tests/run_ci_parallel.py --job release-smoke
make test-full-suite
```

`release-smoke` is the packaged-artifact gate. It builds or reuses the server
wheel, validates packaged static assets, boots the packaged server, and checks
that `/api/health` reaches readiness. In GitHub CI it now consumes the
same-commit `release-smoke-ui-static` artifact built after `frontend-typecheck`
and runs `tools/tests/run_release_smoke.py --skip-ui-build` so the final smoke
job validates packaged assets without rebuilding the UI from source again. That
artifact build still runs `npm run sync:generated-contracts` to materialize the
UI-only derivative files on a fresh checkout, but it now switches to the
prevalidated-contracts build path instead of re-running the late
`check:contracts` gate already owned by `backend-contract-drift` and
`frontend-typecheck`. It is complementary to Docker/e2e validation, not a
duplicate of it.

## Frontend validation

Use the standard UI workflow for `apps/ui/**` changes:

```bash
make ui-typecheck
cd apps/ui && npm run test:unit
cd apps/ui && npm run build
cd apps/ui && npm run test:visual
cd apps/ui && npm run test:visual:audit   # optional broader visual sweep
python3 tools/tests/run_ci_parallel.py --job frontend-quality --job frontend-typecheck --job ui-unit --job ui-smoke
```

The UI has three test layers; pick the one that matches the seam under test:

| Layer | Runner | What it covers | Command |
|-------|--------|----------------|---------|
| Unit / integration | Vitest + `happy-dom` | Logic-heavy modules below the browser boundary (payload decoders, runtime helpers, feature workflows, signal-mounted islands, view-level pure helpers) | `npm run test:unit` |
| Smoke | Playwright (Chromium) | End-to-end flows against a real Vite dev/preview server; file pattern `tests/smoke*.spec.ts` | `npm run test:smoke` |
| Visual / snapshot | Playwright (Chromium) | Rendered-state regression baselines under `tests/snapshots/`; file pattern `tests/visual.spec.ts` | `npm run test:visual` |

- `npm run test:unit` is the canonical fast test lane. It auto-discovers
  `tests/**/*.spec.ts` and excludes the Playwright-owned browser/visual/smoke
  specs via [`apps/ui/vitest.config.ts`](../apps/ui/vitest.config.ts). Prefer it
  for anything that does not need a real browser.
- `npm run test:visual` is the rendered-state and snapshot gate; use
  `npm run test:visual:update` only for intentional baseline changes.
- `npm run test:visual:audit` is the opt-in four-project visual audit sweep
  when you need dark/tablet coverage on purpose instead of in the default lane.
- `frontend-quality` is the UI lint/tooling gate: it runs Biome,
  dependency-cruiser, and knip. `frontend-typecheck` is the generated-contract
  and TypeScript gate: it syncs generated contract artifacts, then runs
  `npm run typecheck`. `ui-unit` runs the Vitest suite and `ui-smoke` is the CI
  browser path. Use `act -j frontend-quality -W .github/workflows/ci.yml`,
  `act -j frontend-typecheck -W .github/workflows/ci.yml`,
  `act -j ui-unit -W .github/workflows/ci.yml`, or
  `act -j ui-smoke -W .github/workflows/ci.yml` when you need GitHub-workflow
  parity for those jobs.

## Firmware and Pi-image validation

Use the narrowest existing validation path that matches the layer you changed:

```bash
cd firmware/esp && pio run
BUILD_MODE=app ./infra/pi-image/pi-gen/build.sh
BUILD_MODE=image ./infra/pi-image/pi-gen/build.sh
./infra/pi-image/pi-gen/validate-image.sh
python3 tools/tests/run_ci_parallel.py --job release-smoke
```

- Use `pio run -t upload` and `pio device monitor` only when hardware-backed
  firmware behavior needs confirmation.
- Use `BUILD_MODE=app` for packaged app artifact changes, `BUILD_MODE=image` for
  image-stage logic, and `validate-image.sh` to rerun image validation without a
  rebuild. `BUILD_MODE=all` is only needed when both layers changed.
- `release-smoke` validates packaged server/UI artifacts; it complements the
  full Pi-image build rather than replacing it.

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
.venv/bin/python -m pip install -e "./apps/server[dev]"
```

`tools/dev/fuzz_processing_pipeline.py` covers upstream live-processing entry
points that sit before persisted diagnostics:

- `strength`: canonical vibration-strength math in `vibesensor.vibration_strength`
- `fft`: pure FFT spectrum assembly in `vibesensor.shared.fft_analysis`
- `processor`: live ingest / compute / debug payload paths in `SignalProcessor`

Both fuzzers default to 16 concurrent worker processes. Use `--processes` to
tune parallelism if you need to trade off CPU saturation against local
interactivity. `--threads` remains accepted as a compatibility alias.

## Characterization

Use `python3 -m vibesensor.cli.characterize_aliasing` to inspect which
out-of-band tones can fold into the current live-analysis band for the
configured sample rate and FFT setup:

```bash
python3 -m vibesensor.cli.characterize_aliasing
```

The tool characterizes the current **digital** chain only. It does not replace
hardware sweep tests of the physical sensor/front-end.

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
act -j backend-lint -W .github/workflows/ci.yml
act -j repo-hygiene -W .github/workflows/ci.yml
act -j backend-static-guards -W .github/workflows/ci.yml
act -j backend-preflight -W .github/workflows/ci.yml
act -j docs-lint -W .github/workflows/ci.yml
act -j backend-contract-drift -W .github/workflows/ci.yml
act -j backend-typecheck -W .github/workflows/ci.yml
act -j frontend-quality -W .github/workflows/ci.yml
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
./tools/tests/run_ci_with_act.sh -j backend-lint  # run one job
```

### Secrets

No secrets are currently required. If needed in the future, copy
`.secrets.act.example` to `.secrets.act`, fill in values, and the wrapper (or
`--secret-file .secrets.act`) will pick them up. Never commit `.secrets.act`.

### Known limitations under `act`

| Job | Status | Notes |
|---|---|---|
| `backend-lint` | ✅ Fully supported | — |
| `repo-hygiene` | ✅ Fully supported | — |
| `backend-static-guards` | ✅ Fully supported | — |
| `backend-preflight` | ✅ Fully supported | — |
| `docs-lint` | ✅ Fully supported | — |
| `backend-contract-drift` | ✅ Fully supported | — |
| `backend-typecheck` | ✅ Fully supported | — |
| `frontend-quality` | ✅ Fully supported | — |
| `frontend-typecheck` | ✅ Fully supported | — |
| `ui-smoke` | ✅ Fully supported | — |
| `release-smoke` | ✅ Fully supported | — |
| `backend-tests` | ⚠️ Mostly works | This matrix job emits the `Backend tests (shard 1/5)` through `Backend tests (shard 5/5)` checks. The same 5 update-module tests that depend on system-level features (sudo, network interfaces) may fail inside the `act` container. All other tests pass. |
| `e2e` | ✅ Fully supported | Runs isolated server subprocess shards directly; no Docker-in-Docker dependency. |

### Relationship to `run_ci_parallel.py`

`tools/tests/run_ci_parallel.py` (`make test-all`) remains available as a fast
local convenience runner. Its job surface is derived from
`.github/workflows/ci.yml`, while `act` remains the primary CI-parity mechanism
because it runs the actual GitHub workflow file. Use `run_ci_parallel.py` when
you want a faster non-containerized local run without Docker. The workflow’s raw
job id is `backend-tests` because GitHub expands it as a matrix, while
`run_ci_parallel.py` expands that same matrix source back into logical local
jobs `backend-tests-1` through `backend-tests-5` so you can run individual
backend shards directly. The path-planning `ci-scope` job stays workflow-only;
it feeds GitHub job gating but is intentionally excluded from the local
manifest-backed runner surface.

### Path-aware CI gating

Changed-path gating lives in `tools/tests/ci_path_rules.py` and is applied by
the workflow’s `ci-scope` job via `tools/tests/ci_changed_scope.py`. Keep those
rules explicit, documented, and test-backed.

The current gating contract is:

- docs-only markdown changes run `docs-lint` without the backend, frontend, release, firmware, or e2e stacks
- frontend-only changes run `repo-hygiene`, `frontend-quality`, `frontend-typecheck`, `ui-unit`, `ui-smoke`, and `release-smoke`
- backend-only changes run the split backend quality gates, `backend-typecheck`, `backend-tests`, `release-smoke`, and `e2e`
- firmware-only changes run `firmware-native-tests`
- workflow / CI meta changes such as `.github/workflows/ci.yml`, `Makefile`, version pins, Dockerfiles, and workflow-manifest tooling fall back to the full stack

When you change these rules, update both the workflow wiring and the focused
hygiene tests so path scope does not silently drift.

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

The default CI-parity suite now derives these blocking GitHub checks from the
workflow-backed CI manifest:

- `backend-lint`: Ruff lint and formatter drift checks for backend and tooling Python code.
- `repo-hygiene`: line endings plus repo/path/runtime/CI hygiene checks.
- `backend-static-guards`: import-linter backend architecture contracts plus the
  remaining repo-specific backend static guards.
- `backend-preflight`: `pip check`, backend `deptry` dependency-declaration
  validation, and config preflight validation for dev, docker, and pi configs.
- `docs-lint`: docs misuse and markdown-link validation.
- `backend-contract-drift`: WS schema and HTTP API contract drift checks.
- `backend-typecheck`: mypy on the `vibesensor` backend package; package discovery keeps new backend files checked by default without an internal module denylist.
- `frontend-quality`: `npm run lint`, `npm run lint:deps`, and `npm run lint:unused` in `apps/ui/`.
- `frontend-typecheck`: `npm run sync:generated-contracts` and `npm run typecheck` in `apps/ui/`.
- `release-smoke`: builds packaged UI and a server wheel, then runs the release smoke validator against the built artifact.
- `ui-smoke`, `backend-tests` (matrix job emitting shard `1/5` through `5/5` checks), `e2e`: required test jobs.

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
| `e2e` | End-to-end tests |
| `long_sim` | Longer simulated-run tests |
| `smoke` | Minimal critical-path checks |

Use markers sparingly:

- `@pytest.mark.smoke`: fast, deterministic, high-signal checks for critical
  paths such as schema/contract bridges or minimal end-to-end behavior.
- `@pytest.mark.long_sim`: slower simulated-run tests that intentionally trade
  speed for more scenario coverage.
- `@pytest.mark.e2e`: end-to-end tests.

Do not mark every fast unit test as `smoke`; keep it a compact slice that is
useful for quick feedback.
