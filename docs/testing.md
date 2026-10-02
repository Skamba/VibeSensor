# Testing

High-traffic validation router. Keep this concise; use Makefile targets and scripts as the source of executable truth.

## Quick router

- Backend iteration: `make test` or targeted `pytest -q apps/server/tests/<module>/`.
- Before pushing: `make ci` runs lint, backend/UI type checks, backend tests, and UI unit tests.
- Docs/instruction-only changes need no local gate.
- Broad synthetic diagnostic matrices: `make test-diagnostic-matrix` (default backend CI excludes `diagnostic_matrix` cases).
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
make test-full-suite

pytest -q apps/server/tests/adapters/pdf/
pytest -q apps/server/tests/use_cases/history/
pytest -q apps/server/tests/use_cases/updates/
pytest -q apps/server/tests/integration/
```

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
cd apps/ui && npm run test:visual
cd apps/ui && npm run test:visual:audit
```

| Layer | Runner | Use for |
|---|---|---|
| Unit/integration | `npm run test:unit` | logic below browser boundary, payload decoders, runtime helpers, feature workflows, pure view helpers |
| Smoke | `npm run test:smoke` | critical boot/happy-path flows against a real Vite dev server |
| Browser regression | `npm run test:regression` | broader Playwright UI regressions moved out of smoke |
| Visual/snapshot | `npm run test:visual` | rendered-state regression baselines |

- `make ui-typecheck` runs format/lint/type gates. UI commands need only Node; the generated contract TypeScript is committed (regenerate with `make sync-contracts`).
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
./.venv/bin/python tools/tests/run_release_smoke.py
```

- Use `pio run -t upload` and `pio device monitor` only when hardware-backed firmware behavior needs confirmation.
- Use `BUILD_MODE=app` for packaged app artifacts, `BUILD_MODE=image` for image-stage logic, and `validate-image.sh` for existing artifacts. `BUILD_MODE=all` is only for changes spanning both layers.
- Do not use ACT for `.github/workflows/manual-pi-image-arm.yml` or `.github/workflows/weekly-pi-image.yml`; those require GitHub's `ubuntu-24.04-arm` runner label, intentionally not mapped in `.actrc`.
- `release-smoke` validates packaged server/UI artifacts; it complements, not replaces, Pi-image validation.

## Local CI with ACT

Use [act](https://github.com/nektos/act) only when you need GitHub workflow or Docker parity; `make ci` covers the usual gates faster.

```bash
act -l -W .github/workflows/ci.yml
act pull_request -W .github/workflows/ci.yml
act -j backend-tests -W .github/workflows/ci.yml
```

- No ACT secrets are currently required. If needed later, copy `.secrets.act.example` to `.secrets.act`; never commit it.

## CI job reference

Blocking jobs live in `.github/workflows/ci.yml`. The `changes` job uses `dorny/paths-filter` to decide which groups run:

- `backend` (`apps/server/`, `tools/`, `infra/pi-image/`, workflow files): backend lint, preflight, type check, tests, contract drift, release smoke, and e2e;
- `frontend` (`apps/ui/`, `tools/ui/`, `tools/config/`): frontend quality/type check, UI unit/smoke, contract drift, release smoke, and e2e;
- `firmware` (`firmware/`, `tools/firmware/`, the UDP protocol modules): firmware native tests;
- `shell` (shell scripts, hooks, `infra/pi-image/`): ShellCheck.

Docs-only changes run only the secret scan. Changes under `.github/` run everything.

## Coverage and characterization

```bash
make coverage
COV_OPTS="--cov-report=html --cov-report=term-missing:skip-covered" make coverage
cd apps/server && python -m pytest -q --cov=vibesensor --cov-report=term-missing:skip-covered tests
python3 -m vibesensor.cli.characterize_aliasing
```

Treat coverage as a risk-finding tool, not the only quality signal. High-risk backend areas (`diagnostics`, `infra/processing`, persistence history DB, updates) should stay above the repo baseline when practical.
