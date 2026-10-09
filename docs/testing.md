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

- `apps/server/tests_e2e/conftest.py` starts one real server subprocess per pytest-xdist worker (session-scoped `e2e_server` fixture): a runtime dir under pytest's tmp dir with `config.docker.yaml` cloned and paths rewritten, seed data copied, and free loopback HTTP/UDP ports. The worker holds its HTTP and GPS ports for the whole session with a bound, never-listening `SO_REUSEPORT` socket: the server (Granian) and the simulator's GPS feed listen with `SO_REUSEPORT`, so a listener on a port another worker already holds would silently share it instead of failing. The server binds its UDP ports itself, so a start that loses one to another process is retried on fresh ports. The server is terminated at session end and also dies with its worker. Tests that need their own server use a function-scoped one: `capped_e2e_server` (recordings auto-stop early) or `power_cut`, whose `cut_and_restore()` SIGKILLs the server mid-run and starts it again on the same data, as a power cut and the next boot do.
- Tests drive it over HTTP and run `vibesensor.simulator.sim_sender` against it via the `e2e_env` fixture. Tests on one worker share that server sequentially, so each test restores the settings, clients, and runs it touches. Simulator sensor ids are deterministic per index (`sim_client_ids`), and sensor location assignments persist by sensor id, so tests that assign locations call `remove_all_clients` in their cleanup (removing a sensor releases its location).
- The simulator reports its speed as a GPS receiver (gpsd protocol) on the worker server's `gps.gpsd_port` (`run_simulator(gps_port=...)`, `vibesensor-sim --gps-port`), so recorded runs carry a measured speed; `gps_port=None` types the speed in as a manual speed instead. Each simulated sensor binds its own free control port and announces it in its HELLO; a sensor that cannot stream fails the simulator run.
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
- A drive that carries two real faults accepts either one as the diagnosis (`Case.second_fault`); whichever is named is checked against its own full expectation.
- The backend job runs one sensor-id seed per case. `make test-diagnostic-matrix` repeats each case over five more seeds and requires 4/5 passes; CI runs it as the `diagnosis-matrix` jobs when diagnosis-related paths change (it kills mutants the single seed misses). The 4/5 rule holds per case inside one test, so splitting cases across jobs keeps it.
- Network and clock conditions are part of the cases: a sensor losing frames, busy Wi-Fi delaying clock-sync replies, and a car start where recording begins before the sensor clocks sync (device timers within ~2 s of server time), optionally on congested Wi-Fi where the simulated firmware retransmits frames stop-and-wait (`Case.car_start`, `Case.wifi_retry_loss`). Each sensor's raw capture must stay on one continuous clock.
- Speed comes in measured: as gpsd TPV reports (3D fix) through the production GPS ingestion, or from a connected OBD adapter (`Case.speed_source`); the adapter can also report the engine RPM of the gear each phase drives in (`Case.obd_rpm`, `ScenarioPhase.gear_ratio`; idle at a standstill). A standstill drive must leave 0 km/h out of the per-speed breakdown.
- Cars are part of the cases (`Case.cars`): the default car, a hatchback, and an EV with and without its reduction ratio entered. A phase driven in a lower gear (`ScenarioPhase.gear_ratio`) moves only the simulated engine orders; without measured RPM the benchmark checks with its own gear math that a wheel or propshaft order the engine can match in some gear is never Strong and that the report says so. `run_sim_pipeline(max_recording_duration_s=...)` sets the server's recording cap, and the flush loop auto-stops at it as production does.
- Realistic drives are part of the cases: healthy cars with a residual imbalance on every corner, uneven mount coupling, road noise that grows with speed (`Profile.noise_speed_exponent`) and a body mode; an order whose level grows with speed and peaks in a resonant speed band (`order_speed_exponent`, `order_resonance_kmh`; `Expected.peak_speed_kmh` checks the reference speed lands there); town stop-and-go and motorway drives; GPS speed reported late and once a second (`Case.speed_lag_s`, `Case.speed_report_period_s`); a tone only while pulling; a sensor read through a stiffer mount; two tyres slightly apart; an OBD speed that reads high (`Case.obd_speed_over_read`). The simulated car's wheels turn from its own tire and slip model, not the analysis's order math (`simulator/wheel_kinematics.py`, see `docs/simulator_realism.md`), so every injected order sits a little off the entered-spec prediction, as on a real car; each seed's car has its own tire wear and pressures (`SimCar.in_service`). A wheel's or propshaft's unbalance shakes with the square of the speed (`UNBALANCE_SPEED_EXPONENT`). A run whose strong vibration no checked order explains (`Expected.unexplained_vibration`) must not read "No significant vibration found". With measured RPM the worksheet must list only orders the drive carried.
- First-drive confounders are part of the cases (`simulator/confounders.py`, sources in `docs/simulator_realism.md`): parking flat spots that fade over the first kilometres (`Case.flat_spots`), a sensor on a springy bracket or loose enough to rattle (`Case.fixings`), worn accessories at fixed or engine-locked frequencies (blower, alternator; `Case.accessories`), two faults at once, a non-uniform tyre, and traffic where the speed never holds still or never reaches the fault's strongest band. The ground truth adds a flat spot's level to the wheel orders and scales what a sensor reads by its mount's transmissibility.
- Road-excited structural modes are part of every simulated sensor signal (see "Simulated road resonances" below); a case can add a stronger mode near an order (`_with_mode`) to check that a healthy car with a boomy seat or soft tyres is not a fault and that a mild imbalance on that road still is.
- Every analysis rule should be justified by a case it changes for the better; a rule that changes no realistic case is a candidate for deletion. A miss is fixed at its root cause, not listed as an expected failure.
- New simulator scenarios need a ground-truth entry there; prefer adding a case over adding hand-built peak fixtures in `tests/analysis/`.

### Simulated road resonances

The road shakes the car with broadband noise, and the car's structural modes
ring in it: a narrowband hump of noise about each mode's frequency, the same
at every speed, not a line. `simulator/profiles.py` gives every profile
`road_resonances` (`RoadResonance`: frequency, Q, RMS mg per axis at 100 km/h)
and a `road_roughness` scale; `SimClient` filters its own noise stream through
a band-pass biquad per mode and adds it in counts, whatever the scene's gains,
so every sensor feels it.

| Mode (default) | Hz | Q | mg (x, y, z) | Basis |
|----------------|----|---|--------------|-------|
| Wheel hop | 12 | 2.5 | 3, 2, 6 | unsprung mass on the tyre, 10-15 Hz, damping ratio about 0.2 (Gillespie, *Fundamentals of Vehicle Dynamics*, ch. 5) |
| Body bending/torsion | 24 | 8 | 1.5, 1, 2.5 | trimmed-body first global modes 20-35 Hz at 3-6 % damping |
| Steering column/mirror | 33 | 15 | 1, 1.5, 1 | column and mirror modes 30-40 Hz, lightly damped |

- Level grows with the square root of the speed: ISO 8608 road displacement
  roughness falls with the square of the spatial frequency, so the
  acceleration a fixed mode sees grows as `v^0.5`. Each rougher ISO 8608 class
  doubles it (`road_roughness` 2, 4, ...).
- The defaults are modest on purpose: a few mg per mode, against the 0.2-0.5
  m/s² (20-50 mg) frequency-weighted whole-body levels ISO 2631-1 surveys of
  cars on normal roads find at the seat (Paddan & Griffin, J. Sound Vib.
  253(1), 2002). The benchmark's strong modes (`_SEAT_MODE`, 15 Hz Q 6 at 40 mg
  vertical; `_WHEEL_HOP`, 13 Hz Q 3 at 60 mg near the suspension mounts) are a
  car whose one mode carries most of that.
- Real-drive recordings are needed to calibrate the levels and Q per car; the
  numbers above are literature ranges, not measurements.

`run_sim_pipeline(road=...)` gives the sensors a road (`SimClient.road`): the
road's vibration through a quarter car at each sensor's mount and the ADXL345
front end, instead of white noise; its physics and sources are in
`docs/simulator_realism.md`. A benchmark `Case(iso8608_road=True)` drives on
`generated_road(seed)`; the `*-iso8608-road` cases are the healthy motorway,
the healthy sweep and the engine sweep on that road. The rest of the
benchmark still runs on the idealised floor (see "Benchmark on the realistic
road" in `docs/simulator_realism.md`).

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
- `diagnostic_matrix` marks the accuracy benchmark's extra-seed repetitions; run them with `make test-diagnostic-matrix`. `make test` excludes them; the `diagnosis-matrix` CI jobs run them.
- `--shard=INDEX/COUNT` (defined in `apps/server/tests/conftest.py`) keeps every COUNT-th selected test in node-id order; CI passes it through `PYTEST_ADDOPTS` to split `make test` and `make test-diagnostic-matrix` across parallel jobs, e.g. `PYTEST_ADDOPTS=--shard=2/8 make test-diagnostic-matrix`.
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

- `make ui-typecheck` runs format/lint/type gates. UI commands need only Node; the generated contract TypeScript is committed (regenerate with `make sync-contracts`). Its output depends on the installed Pydantic version, so when a Pydantic release changes it, regenerate and raise the `pydantic` floor in `apps/server/pyproject.toml` to that release; the floor bump also refreshes CI's cached venv, which is keyed on that file. If `make sync-contracts` rewrites files on a clean checkout, rerun `make setup`.
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
| `backend` | backend paths | `pip check`, `make lint` (Ruff, ShellCheck, deptry, import layers, config preflight), `make typecheck-backend` |
| `backend-tests` (2 shards) | backend paths | `make test` |
| `frontend` | frontend paths | `make ui-typecheck`, `make ui-test` |
| `ui-smoke` | frontend paths | `cd apps/ui && npm run test:smoke` |
| `diagnosis-matrix` (8 shards) | analysis, dsp, domain, ingest, recording, report, simulator, summary or benchmark paths | `make test-diagnostic-matrix` |
| `integration` | backend or frontend paths | `make sync-contracts && git diff --exit-code`, `make test-e2e`, `python tools/tests/run_release_smoke.py` |
| `firmware` | firmware paths | `python tools/firmware/generate_protocol_contract_fixtures.py --check`, `cd firmware/esp && pio test -e native`, `pio run -e m5stack_atom -e esp32-c3-devkitm-1` |

The `changes` job uses `dorny/paths-filter`: backend paths are `apps/server/`, `tools/`, `infra/pi-image/`, shell scripts/hooks, `docs/protocol.md`, and `.github/actions/`; frontend paths are `apps/ui/`, `tools/ui/`, `tools/config/`; firmware paths are `firmware/`, `tools/firmware/`, and the UDP protocol modules. Docs-only changes run only the secret scan; editing `ci.yml` runs everything.

Other workflows: `codeql.yml` (Python + JS/TS analysis), `main-release.yml` (wheel, Pi dependency wheelhouse, and firmware release after green CI on `main`), and `weekly-pi-image.yml` (scheduled Pi image release; manual runs build an artifact and publish only when the `publish` input is set).

## Coverage and characterization

```bash
make coverage
COV_OPTS="--cov-report=html --cov-report=term-missing:skip-covered" make coverage
cd apps/server && python -m pytest -q --cov=vibesensor --cov-report=term-missing:skip-covered tests
.venv/bin/python tools/dev/characterize_aliasing.py
```

Treat coverage as a risk-finding tool, not the only quality signal. High-risk backend areas (`analysis`, `live` processing, the `history` DB, `updates`) should stay above the repo baseline when practical.
