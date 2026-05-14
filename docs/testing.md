# Testing

High-traffic validation router. Keep this concise; use Makefile targets and scripts as the source of executable truth.

## Quick router

- Start with `make plan-validation` to turn the current diff into a CI-backed plan.
- Run planned non-Docker jobs with `./.venv/bin/python tools/tests/plan_validation.py --run`.
- Use `./.venv/bin/python tools/tests/plan_validation.py --act` or `./tools/tests/run_ci_with_act.sh` only when GitHub workflow/Docker parity is needed.
- Docs/instruction-only changes: `make docs-lint` plus `make plan-validation`.
- Fast broad gate: `make test-ci-fast` for lint, docs, static guards, and type checks without heavy suites.
- Larger non-Docker gate: `make test-ci-lite` for workflow jobs except e2e.
- Backend iteration: `make test` or targeted `pytest -q apps/server/tests/<module>/`.
- Broad synthetic diagnostic matrices: `make test-diagnostic-matrix` (default backend CI excludes `diagnostic_matrix` cases).
- UI validation: `make ui-typecheck`; add UI test/build commands below when the changed seam requires them.
- Firmware and Pi image validation: use the narrow commands below; avoid hardware/full image builds unless required.
- Local `shell-lint` parity needs host `shellcheck`; `make doctor` reports prerequisites. Use ACT for the workflow-managed install path.

## Command tiers

```bash
make plan-validation
./.venv/bin/python tools/tests/plan_validation.py --run
./.venv/bin/python tools/tests/plan_validation.py --act

make docs-lint
make test-changed
make test-diagnostic-matrix
make test-ci-fast
make test-ci-lite
make test-all
make test-full-suite

pytest -q apps/server/tests/adapters/pdf/
pytest -q apps/server/tests/use_cases/history/
pytest -q apps/server/tests/use_cases/updates/
pytest -q apps/server/tests/integration/
```

Benchmarks and fuzzers are opt-in evidence, not default validation:

```bash
make benchmark-backend BENCHMARK_OPTS="--benchmark-save=baseline"
make benchmark-golden-replay BENCHMARK_OPTS="--benchmark-save=golden-replay"
make benchmark-compare-backend
make test-golden-replay
python3 tools/dev/fuzz_analysis_engine.py --duration-s 60 --batch-examples 100 --processes 16
python3 tools/dev/fuzz_processing_pipeline.py --target fft --duration-s 60 --processes 16
```

Direct pytest benchmark runs need `-o addopts=''` so default xdist addopts do not disable benchmark mode.

## Backend test placement

`apps/server/tests/` mirrors backend package ownership:

| Production change | Test start |
|---|---|
| `vibesensor/adapters/http/*` | `apps/server/tests/adapters/http/` |
| `vibesensor/adapters/{hotspot,pdf,persistence,simulator,udp,websocket}/*` | matching `apps/server/tests/adapters/.../` |
| `vibesensor/app/*` | `apps/server/tests/app/` |
| `vibesensor/domain/*` | `apps/server/tests/domain/` |
| `vibesensor/infra/{config,processing,runtime,workers}/*` | matching `apps/server/tests/infra/.../` |
| `vibesensor/shared/*` | `apps/server/tests/shared/` or `domain/` when testing domain-owned contracts |
| `vibesensor/use_cases/{diagnostics,history,run,updates}/*` | matching `apps/server/tests/use_cases/.../` |

- Cross-cutting regressions go in `apps/server/tests/integration/`.
- Architecture/repo guards go in `apps/server/tests/hygiene/` or the owning guard script.
- Shared helpers live in `apps/server/tests/test_support/`.
- Do not create old flat roots such as `analysis/`, `api/`, `config/`, `gps/`, `history/`, `hotspot/`, `metrics_log/`, `processing/`, `protocol/`, `report/`, `update/`, or `websocket/`.
- Contract bridge tests live in `apps/server/tests/integration/` and validate subsystem handoffs such as analysis -> report and persistence -> analysis.

## Backend test rules

- Python test config lives in `apps/server/pyproject.toml`.
- Backend pytest uses `pytest-randomly`; reproduce order failures with the printed `--randomly-seed=<seed>`. Disable it only to isolate tooling, not to hide order-dependence.
- Use `pytest-httpx` for backend outbound HTTP boundary tests.
- Put AST/import guards in `tools/dev/verify_backend_static_guards.py`; repo/frontend hygiene guards live in `tools/dev/check_hygiene.py`. Both run via `make lint`.
- Temporary migration/absence tests must name the stable boundary they protect and be removed once positive current-behavior coverage exists.
- New test-looking files must map to a runner or be explicitly allowed in `tools/dev/test_inventory_allowlist.yml`.
- Marker policy lives in `tools/dev/test_marker_policy_allowlist.yml`. Use `smoke`, `long_sim`, and `e2e` sparingly.
- `diagnostic_matrix` marks broad synthetic axis matrices; run them with `make test-diagnostic-matrix` or `tools/tests/run_backend_parallel.py --include-diagnostic-matrix`.
- Oversized test/spec guardrails live in `tools/dev/check_hygiene.py`; intentional exceptions require a reason in `tools/dev/oversized_test_allowlist.yml`.
- For cached helpers, clear caches in tests that monkeypatch underlying files, paths, or cached state.

## Frontend validation

```bash
make ui-typecheck
cd apps/ui && npm run test:unit
cd apps/ui && npm run build
cd apps/ui && npm run test:visual
cd apps/ui && npm run test:visual:audit
./.venv/bin/python tools/tests/run_ci_parallel.py --job frontend-quality --job frontend-typecheck --job ui-unit --job ui-smoke
```

| Layer | Runner | Use for |
|---|---|---|
| Unit/integration | `npm run test:unit` | logic below browser boundary, payload decoders, runtime helpers, feature workflows, pure view helpers |
| Smoke | `npm run test:smoke` | critical boot/happy-path flows against a real Vite dev server |
| Browser regression | `npm run test:regression` | broader Playwright UI regressions moved out of smoke |
| Visual/snapshot | `npm run test:visual` | rendered-state regression baselines |

- `make ui-typecheck` materializes generated UI contracts, then runs format/lint/type gates.
- Use `npm run test:visual:update` only for intentional baseline changes.
- Use shared MSW helpers under `apps/ui/tests/msw/` for frontend tests that intentionally cross the real HTTP boundary. They normalize relative `/api/...` requests and fail unhandled requests loudly.
- Do not add MSW to tests that inject transport ports or stay inside presenter/view/state seams. Keep WebSocket mocking on the dedicated fake WebSocket helpers.
- Optional browser-worker MSW mode: `cd apps/ui && npm run dev:mock`; smoke entrypoint `cd apps/ui && npm run test:smoke:mock`.

## Firmware and Pi image validation

```bash
cd firmware/esp && pio run
python tools/firmware/generate_protocol_contract_fixtures.py --check
cd firmware/esp && pio test -e native

BUILD_MODE=app ./infra/pi-image/pi-gen/build.sh
BUILD_MODE=image ./infra/pi-image/pi-gen/build.sh
./infra/pi-image/pi-gen/validate-image.sh [artifact]
./.venv/bin/python tools/tests/run_ci_parallel.py --job release-smoke
```

- Use `pio run -t upload` and `pio device monitor` only when hardware-backed firmware behavior needs confirmation.
- Use `BUILD_MODE=app` for packaged app artifacts, `BUILD_MODE=image` for image-stage logic, and `validate-image.sh` for existing artifacts. `BUILD_MODE=all` is only for changes spanning both layers.
- Do not use ACT for `.github/workflows/manual-pi-image-arm.yml` or `.github/workflows/weekly-pi-image.yml`; those require GitHub's `ubuntu-24.04-arm` runner label, intentionally not mapped in `.actrc`.
- `release-smoke` validates packaged server/UI artifacts; it complements, not replaces, Pi-image validation.

## Local CI with ACT

Use the wrapper unless raw ACT flags are necessary. The default wrapper mode is a changed-scope ACT run as a `pull_request` event; `--full-stack` forces a forced full-stack ACT run.

```bash
./tools/tests/run_ci_with_act.sh -l
./tools/tests/run_ci_with_act.sh
./tools/tests/run_ci_with_act.sh --full-stack
./tools/tests/run_ci_with_act.sh -j backend-lint
./tools/tests/run_ci_with_act.sh -j backend-tests
./tools/tests/run_ci_with_act.sh --base-ref main -j backend-lint
```

Raw equivalents:

```bash
act -l -W .github/workflows/ci.yml
python3 tools/tests/act_event.py --output /tmp/vibesensor-act-event.json
act pull_request -W .github/workflows/ci.yml -e /tmp/vibesensor-act-event.json
act pull_request -W .github/workflows/ci.yml -e /tmp/vibesensor-act-event.json --env VIBESENSOR_CI_FORCE_FULL_STACK=1
act -j backend-lint -W .github/workflows/ci.yml
act -j backend-tests -W .github/workflows/ci.yml
```

- ACT `-j` uses raw workflow job IDs such as `backend-tests`, not local shard IDs like `backend-tests-1`.
- No ACT secrets are currently required. If needed later, copy `.secrets.act.example` to `.secrets.act`; never commit it.
- `run_ci_parallel.py` is a faster non-container local runner. It respects selected GitHub `needs`, reports omitted prerequisites, and expands backend matrix shards as `backend-tests-1` through `backend-tests-5`.
- Changed-path gating lives in `tools/tests/ci_path_rules.py` and `tools/tests/ci_changed_scope.py`; update workflow wiring and focused hygiene tests together.

## CI job reference

Blocking job names come from `.github/workflows/ci.yml`. Common local job selectors:

```bash
./.venv/bin/python tools/tests/run_ci_parallel.py --ci-lite
./.venv/bin/python tools/tests/run_ci_parallel.py --job backend-lint --job repo-hygiene --job backend-static-guards --job backend-preflight --job docs-lint --job backend-contract-drift --job backend-typecheck
./.venv/bin/python tools/tests/run_ci_parallel.py --job frontend-quality --job frontend-typecheck --job ui-unit --job ui-smoke
./.venv/bin/python tools/tests/run_ci_parallel.py --job release-smoke
```

Path-aware CI intent:

- docs-only markdown changes run `docs-lint`;
- frontend-only changes run repo hygiene, frontend quality/typecheck, UI unit/smoke, and release smoke;
- backend-only changes run backend quality/typecheck/tests plus release smoke and e2e;
- firmware-only changes run firmware native tests;
- workflow/CI meta changes fall back to full stack.

## Coverage and characterization

```bash
make coverage
COV_OPTS="--cov-report=html --cov-report=term-missing:skip-covered" make coverage
cd apps/server && python -m pytest -q --cov=vibesensor --cov-report=term-missing:skip-covered tests
python3 -m vibesensor.cli.characterize_aliasing
```

Treat coverage as a risk-finding tool, not the only quality signal. High-risk backend areas (`diagnostics`, `infra/processing`, persistence history DB, updates) should stay above the repo baseline when practical.
