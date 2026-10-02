# Testing

High-traffic validation router. Keep this concise; use Makefile targets and scripts as the source of executable truth.

## Quick router

- Backend iteration: `make test` or targeted `pytest -q apps/server/tests/<module>/`.
- Before pushing: `make ci` runs lint, backend/UI type checks, backend tests, and UI unit tests.
- Docs/instruction-only changes need no local gate.
- Broad synthetic diagnostic matrices: `make test-diagnostic-matrix` (default backend CI excludes `diagnostic_matrix` cases).
- Simulator, UDP ingest, recording, post-analysis, or persistence changes: also run the process-backed e2e suite (`make test-e2e`); `make ci` does not run it.
- UI validation: `make ui-typecheck`; add UI test/build commands below when the changed seam requires them.
- Firmware and Pi image validation: use the narrow commands below; avoid hardware/full image builds unless required.
- Local `shell-lint` needs host `shellcheck`; `make doctor` reports prerequisites.

## Command tiers

```bash
make test
make lint
make typecheck
make ci
make test-diagnostic-matrix
make test-e2e
make test-full-suite

pytest -q apps/server/tests/adapters/pdf/
pytest -q apps/server/tests/use_cases/history/
pytest -q apps/server/tests/use_cases/updates/
pytest -q apps/server/tests/integration/
```

## Process-backed e2e

```bash
.venv/bin/python -m pytest -q -m "e2e and not long_sim" -n 6 apps/server/tests_e2e   # = make test-e2e (CI)
.venv/bin/python -m pytest -q -m e2e -n 6 apps/server/tests_e2e                      # = make test-full-suite
```

- `apps/server/tests_e2e/conftest.py` starts one real server subprocess per pytest-xdist worker (session-scoped `e2e_server` fixture): a runtime dir under pytest's tmp dir with `config.docker.yaml` cloned and paths rewritten, seed data copied, and free loopback HTTP/UDP ports. The server is terminated at session end and also dies with its worker.
- Tests drive it over HTTP and run `vibesensor.adapters.simulator.sim_sender` against it via the `e2e_env` fixture. Tests on one worker share that server sequentially, so each test restores the settings, clients, and runs it touches.
- Failing e2e tests append the server and app log tails to the pytest report.
- Simulated captures that must finish post-analysis need at least `ANALYZABLE_SIM_DURATION_S` (two FFT analysis windows); `_simulate()` defaults to it.
- `long_sim` marks longer simulated runs; the fast selection excludes them. Override the worker count with `make test-e2e E2E_WORKERS=<n>`.

Benchmarks are opt-in evidence, not default validation:

```bash
make benchmark-backend BENCHMARK_OPTS="--benchmark-save=baseline"
make benchmark-golden-replay BENCHMARK_OPTS="--benchmark-save=golden-replay"
make benchmark-compare-backend
make test-golden-replay
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
- Repo/tooling tests go in `apps/server/tests/hygiene/`. Import-direction rules belong in the `[tool.importlinter]` contracts in `apps/server/pyproject.toml`, not in tests.
- Shared helpers live in `apps/server/tests/test_support/`.
- Do not create old flat roots such as `analysis/`, `api/`, `config/`, `gps/`, `history/`, `hotspot/`, `metrics_log/`, `processing/`, `protocol/`, `report/`, `update/`, or `websocket/`.
- Contract bridge tests live in `apps/server/tests/integration/` and validate subsystem handoffs such as analysis -> report and persistence -> analysis.

## Backend test rules

- Python test config lives in `apps/server/pyproject.toml`.
- Backend pytest uses `pytest-randomly`; reproduce order failures with the printed `--randomly-seed=<seed>`. Disable it only to isolate tooling, not to hide order-dependence.
- Use `pytest-httpx` for backend outbound HTTP boundary tests.
- Import-direction rules are import-linter contracts in `apps/server/pyproject.toml`; `make lint` runs them. Tests must not parse or inspect production source (Ruff `TID251` bans `ast.parse` / `inspect.getsource` in tests).
- Temporary migration/absence tests must name the stable boundary they protect and be removed once positive current-behavior coverage exists.
- Use the `smoke`, `long_sim`, and `e2e` markers sparingly.
- `diagnostic_matrix` marks broad synthetic axis matrices; run them with `make test-diagnostic-matrix`. `make test` and CI exclude them.
- For cached helpers, clear caches in tests that monkeypatch underlying files, paths, or cached state.

## Frontend validation

```bash
make ui-typecheck
cd apps/ui && npm run test:unit
cd apps/ui && npm run build
cd apps/ui && npm run test:smoke
```

| Layer | Runner | Use for |
|---|---|---|
| Unit/integration | `npm run test:unit` | logic below browser boundary, payload decoders, runtime helpers, feature workflows, pure view helpers |
| Smoke | `npm run test:smoke` | critical boot/happy-path flows against a real Vite dev server |

- `make ui-typecheck` runs format/lint/type gates. UI commands need only Node; the generated contract TypeScript is committed (regenerate with `make sync-contracts`).
- Use shared MSW helpers under `apps/ui/tests/msw/` for frontend tests that intentionally cross the real HTTP boundary. They normalize relative `/api/...` requests and fail unhandled requests loudly.
- Do not add MSW to tests that inject transport ports or stay inside presenter/view/state seams. Keep WebSocket mocking on the dedicated fake WebSocket helpers.

## Firmware and Pi image validation

```bash
cd firmware/esp && pio run
python tools/firmware/generate_protocol_contract_fixtures.py --check
cd firmware/esp && pio test -e native

BUILD_MODE=app ./infra/pi-image/pi-gen/build.sh
BUILD_MODE=image ./infra/pi-image/pi-gen/build.sh
./infra/pi-image/pi-gen/validate-image.sh [artifact]
./.venv/bin/python tools/tests/run_release_smoke.py
```

- Use `pio run -t upload` and `pio device monitor` only when hardware-backed firmware behavior needs confirmation.
- Use `BUILD_MODE=app` for packaged app artifacts, `BUILD_MODE=image` for image-stage logic, and `validate-image.sh` for existing artifacts. `BUILD_MODE=all` is only for changes spanning both layers.
- Do not use ACT for `.github/workflows/weekly-pi-image.yml`; it requires GitHub's `ubuntu-24.04-arm` runner label, intentionally not mapped in `.actrc`. Run it manually with `publish` off to get an image as a workflow artifact only.
- Release smoke (`tools/tests/run_release_smoke.py`) validates packaged server/UI artifacts; it complements, not replaces, Pi-image validation.

## Local CI with ACT

Use [act](https://github.com/nektos/act) only when you need GitHub workflow or Docker parity; `make ci` covers the usual gates faster.

```bash
act -l -W .github/workflows/ci.yml
act pull_request -W .github/workflows/ci.yml
act -j backend -W .github/workflows/ci.yml
```

- No ACT secrets are currently required. If needed later, copy `.secrets.act.example` to `.secrets.act`; never commit it.

## CI job reference

Blocking jobs live in `.github/workflows/ci.yml`; each reuses the local make targets:

| Job | Runs when | Local equivalent |
|---|---|---|
| `secret-scan` | always | gitleaks |
| `backend` | backend paths | `pip check`, `make lint` (Ruff, ShellCheck, deptry, import layers, config preflight), `make typecheck-backend`, `make test` |
| `frontend` | frontend paths | `make ui-typecheck`, `make ui-test` |
| `ui-smoke` | frontend paths | `cd apps/ui && npm run test:smoke` |
| `integration` | backend or frontend paths | `make sync-contracts && git diff --exit-code`, `make test-e2e`, `python tools/tests/run_release_smoke.py` |
| `firmware` | firmware paths | `python tools/firmware/generate_protocol_contract_fixtures.py --check`, `cd firmware/esp && pio test -e native` |

The `changes` job uses `dorny/paths-filter`: backend paths are `apps/server/`, `tools/`, `infra/pi-image/`, shell scripts/hooks, `docs/protocol.md`, and `.github/actions/`; frontend paths are `apps/ui/`, `tools/ui/`, `tools/config/`; firmware paths are `firmware/`, `tools/firmware/`, and the UDP protocol modules. Docs-only changes run only the secret scan; editing `ci.yml` runs everything.

Other workflows: `codeql.yml` (Python + JS/TS analysis), `main-release.yml` (wheel/firmware release after green CI on `main`), and `weekly-pi-image.yml` (scheduled Pi image release; manual runs build an artifact and publish only when the `publish` input is set).

## Coverage and characterization

```bash
make coverage
COV_OPTS="--cov-report=html --cov-report=term-missing:skip-covered" make coverage
cd apps/server && python -m pytest -q --cov=vibesensor --cov-report=term-missing:skip-covered tests
python3 -m vibesensor.cli.characterize_aliasing
```

Treat coverage as a risk-finding tool, not the only quality signal. High-risk backend areas (`diagnostics`, `infra/processing`, persistence history DB, updates) should stay above the repo baseline when practical.
