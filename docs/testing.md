# Testing

High-traffic validation router. Keep this concise; use Makefile targets and scripts as the source of executable truth.

## Quick router

- Backend iteration: `make test` or targeted `pytest -q apps/server/tests/<module>/`.
- Before pushing: `make ci` runs lint, backend/UI type checks, backend tests, and UI unit tests.
- Docs/instruction-only changes need no local gate.
- Diagnosis accuracy across more sensor-id seeds: `make test-diagnostic-matrix` (CI runs it when diagnosis paths change).
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

pytest -q apps/server/tests/report/
pytest -q apps/server/tests/history/
pytest -q apps/server/tests/updates/
pytest -q apps/server/tests/integration/
```

## Process-backed e2e

```bash
.venv/bin/python -m pytest -q -m "e2e and not long_sim" -n 6 apps/server/tests_e2e   # = make test-e2e (CI)
.venv/bin/python -m pytest -q -m e2e -n 6 apps/server/tests_e2e                      # = make test-full-suite
```

- `apps/server/tests_e2e/conftest.py` starts one real server subprocess per pytest-xdist worker (session-scoped `e2e_server` fixture): a runtime dir under pytest's tmp dir with `config.docker.yaml` cloned and paths rewritten, seed data copied, and free loopback HTTP/UDP ports. The server is terminated at session end and also dies with its worker.
- Tests drive it over HTTP and run `vibesensor.simulator.sim_sender` against it via the `e2e_env` fixture. Tests on one worker share that server sequentially, so each test restores the settings, clients, and runs it touches. Simulator sensor ids are deterministic per index (`sim_client_ids`), and sensor location assignments persist by sensor id, so tests that assign locations call `remove_all_clients` in their cleanup (removing a sensor releases its location).
- Failing e2e tests append the server and app log tails to the pytest report.
- Simulated captures that must finish post-analysis need at least `ANALYZABLE_SIM_DURATION_S` (two FFT analysis windows); `_simulate()` defaults to it.
- `long_sim` marks longer simulated runs; the fast selection excludes them. Override the worker count with `make test-e2e E2E_WORKERS=<n>`.

Benchmarks are opt-in evidence, not default validation:

```bash
make benchmark-backend BENCHMARK_OPTS="--benchmark-save=baseline"
make benchmark-post-analysis-30min BENCHMARK_OPTS="--benchmark-save=post-analysis-30min"
make benchmark-compare-backend
```

Direct pytest benchmark runs need `-o addopts=''` so default xdist addopts do not disable benchmark mode.

## Diagnosis accuracy benchmark

`apps/server/tests/integration/test_diagnosis_accuracy_benchmark.py` is the accuracy oracle. It replays every simulator scenario plus a few benchmark drives, for the default car and for a car whose engine orders do not coincide with wheel orders, through the real pipeline (`test_support/sim_pipeline.py`: simulator sensor model -> UDP ingest and clock sync -> DSP -> recording with raw capture -> post-analysis -> diagnosis -> report view), in-process on a virtual clock (about 5 s per drive).

- Expectations come from what each scenario injects, never from analysis code: verdict, source, corner/zone, order label, confidence band, the order frequency and spectrum markers from the test's own tire/ratio math, MAC/name/location joins, the report's owner-page text, and the amplitude-vs-speed chart for swept faults. A few drives per report variant are also rendered to PDF in English and Dutch.
- Sensor layouts are part of the cases: one sensor, sensors in the cabin only, and a sensor on every mounting point (`Case.layout`).
- The backend job runs one sensor-id seed per case. `make test-diagnostic-matrix` repeats each case over five more seeds and requires 4/5 passes; CI runs it as the `diagnosis-matrix` job when diagnosis-related paths change (it kills mutants the single seed misses).
- Network and clock conditions are part of the cases: a sensor losing frames, busy Wi-Fi delaying clock-sync replies, and a car start where recording begins before the sensor clocks sync (device timers within ~2 s of server time), optionally on congested Wi-Fi where the simulated firmware retransmits frames stop-and-wait (`Case.car_start`, `Case.wifi_retry_loss`). Each sensor's raw capture must stay on one continuous clock.
- Every analysis rule should be justified by a case it changes for the better; a rule that changes no realistic case is a candidate for deletion. A miss is fixed at its root cause, not listed as an expected failure.
- New simulator scenarios need a ground-truth entry there; prefer adding a case over adding hand-built peak fixtures in `tests/analysis/`.

## Backend test placement

`apps/server/tests/` mirrors the backend package layout: a change to
`vibesensor/<package>/...` starts in `apps/server/tests/<package>/` (for example
`vibesensor/recording/recorder.py` -> `apps/server/tests/recording/`,
`vibesensor/report/pdf.py` -> `apps/server/tests/report/`,
`vibesensor/speed/obd/` -> `apps/server/tests/speed/obd/`).

- Cross-cutting regressions go in `apps/server/tests/integration/`.
- Repo/tooling tests go in `apps/server/tests/hygiene/`: run deploy/tooling scripts and assert their outputs, or guard real drift (for example sample column alignment). Do not pin source/config text, exception `__bases__`, or anything `make sync-contracts`, mypy, or import-linter already enforce; domain behaviour belongs in `apps/server/tests/domain/`. Import-direction rules belong in the `[tool.importlinter]` contracts in `apps/server/pyproject.toml`, not in tests.
- Test module basenames must be unique across `apps/server/tests/` (the tree has no `__init__.py` files).
- Shared helpers live in `apps/server/tests/test_support/`. The vehicle-library data validator the settings tests gate on lives in `tools/car_library/car_library_validation/` (on the pytest `pythonpath`).
- Do not create test roots that do not match a backend package (for example `api/`, `config/`, `gps/`, `metrics_log/`, `processing/`, `protocol/`, `update/`, or `websocket/`).
- Subsystem handoffs (ingest -> recording -> persistence -> analysis -> report) are checked end to end by the accuracy benchmark and the e2e suite; `tests/integration/` holds only cross-cutting cases they cannot reach.

## Backend test rules

- Python test config lives in `apps/server/pyproject.toml`.
- Backend pytest uses `pytest-randomly`; reproduce order failures with the printed `--randomly-seed=<seed>`. Disable it only to isolate tooling, not to hide order-dependence.
- Use `pytest-httpx` for backend outbound HTTP boundary tests.
- Import-direction rules are import-linter contracts in `apps/server/pyproject.toml`; `make lint` runs them. Tests must not parse or inspect production source (Ruff `TID251` bans `ast.parse` / `inspect.getsource` in tests).
- Temporary migration/absence tests must name the stable boundary they protect and be removed once positive current-behavior coverage exists.
- Use the `smoke`, `long_sim`, and `e2e` markers sparingly.
- `diagnostic_matrix` marks the accuracy benchmark's extra-seed repetitions; run them with `make test-diagnostic-matrix`. `make test` excludes them; the `diagnosis-matrix` CI job runs them.
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
| Unit | `npm run test:unit` | pure page models, payload decoders, poll/ws/live helpers, the spectrum renderer, `api/*` wrappers |
| Smoke | `npm run test:smoke` | per-page user journeys (`tests/smoke.<page>.spec.ts`) against a real Vite dev server |

- `make ui-typecheck` runs format/lint/type gates. UI commands need only Node; the generated contract TypeScript is committed (regenerate with `make sync-contracts`).
- UI unit tests cover pure logic (each page's model, poll/ws/live helpers, the spectrum renderer) and the `api/*` wrappers; the latter use `apps/ui/tests/fetch_stub.ts`, which fails unrouted requests loudly.
- Rendered behaviour belongs in the per-page Playwright journeys, which mock HTTP with `page.route` and the WebSocket with the fake socket in `tests/smoke.helpers.ts`.

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
| `diagnosis-matrix` | analysis, dsp, domain, ingest, recording, report, simulator, summary or benchmark paths | `make test-diagnostic-matrix` |
| `integration` | backend or frontend paths | `make sync-contracts && git diff --exit-code`, `make test-e2e`, `python tools/tests/run_release_smoke.py` |
| `firmware` | firmware paths | `python tools/firmware/generate_protocol_contract_fixtures.py --check`, `cd firmware/esp && pio test -e native`, `pio run -e m5stack_atom -e esp32-c3-devkitm-1` |

The `changes` job uses `dorny/paths-filter`: backend paths are `apps/server/`, `tools/`, `infra/pi-image/`, shell scripts/hooks, `docs/protocol.md`, and `.github/actions/`; frontend paths are `apps/ui/`, `tools/ui/`, `tools/config/`; firmware paths are `firmware/`, `tools/firmware/`, and the UDP protocol modules. Docs-only changes run only the secret scan; editing `ci.yml` runs everything.

Other workflows: `codeql.yml` (Python + JS/TS analysis), `main-release.yml` (wheel, Pi dependency wheelhouse, and firmware release after green CI on `main`), and `weekly-pi-image.yml` (scheduled Pi image release; manual runs build an artifact and publish only when the `publish` input is set).

## Coverage and characterization

```bash
make coverage
COV_OPTS="--cov-report=html --cov-report=term-missing:skip-covered" make coverage
cd apps/server && python -m pytest -q --cov=vibesensor --cov-report=term-missing:skip-covered tests
python3 -m vibesensor.cli.characterize_aliasing
```

Treat coverage as a risk-finding tool, not the only quality signal. High-risk backend areas (`analysis`, `live` processing, the `history` DB, `updates`) should stay above the repo baseline when practical.
