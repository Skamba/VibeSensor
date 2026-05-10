# Repo map

This file is the repo map, not a workflow or policy guide. On-demand navigation help: do not read it by default; use `rg`, file names, imports, and tests first, and open this only when ownership is unclear. Workflow and policy rules live in `.github/copilot-instructions.md` and `.github/instructions/*.instructions.md`.

## Primary entry points

- Backend app/runtime: `apps/server/vibesensor/app/bootstrap.py`, `apps/server/vibesensor/app/container.py`
- Backend HTTP assembly: `apps/server/vibesensor/adapters/http/router.py`, `apps/server/vibesensor/adapters/http/route_bundles.py`
- Backend CLIs: `apps/server/vibesensor/cli/`
- UI app/runtime: `apps/ui/src/main.ts`, `apps/ui/src/app/ui_app_runtime.ts`, `apps/ui/src/app/runtime/`
- Simulator: `apps/server/vibesensor/adapters/simulator/`
- Firmware: `firmware/esp/src/main.cpp`, `firmware/esp/src/runtime_*.{h,cpp}`
- Pi image: `infra/pi-image/pi-gen/build.sh`, `infra/pi-image/pi-gen/lib/`, `infra/pi-image/pi-gen/templates/`, `infra/pi-image/pi-gen/validate-image.sh`
- Local stack: `docker-compose.yml`

## Top-level ownership

- `apps/server/`: Python backend package, configs, tests, simulator, static UI assets, systemd units, and backend tooling.
- `apps/ui/`: TypeScript/Vite dashboard and Playwright/Vitest tests.
- `firmware/esp/`: ESP32 firmware; keep `main.cpp` thin and subsystem logic in `runtime_*`.
- `infra/pi-image/`: Raspberry Pi image build, templates, validation, and image docs.
- `docs/`: human-facing docs plus this navigation index.
- `.github/instructions/`: path-scoped AI instructions.

## Backend package ownership

- `vibesensor/app/`: startup, dependency wiring, runtime state, config loading.
- `vibesensor/domain/`: domain behavior; see `docs/domain-model.md`.
- `vibesensor/shared/`: stable contracts, ports, codecs, constants, JSON helpers, and boundary serializers.
- `vibesensor/use_cases/`: application workflows (`diagnostics`, `history`, `run`, `updates`).
- `vibesensor/infra/`: runtime lifecycle/health, signal processing, config storage, workers.
- `vibesensor/adapters/http/`: route groups, HTTP dependencies, Pydantic models.
- `vibesensor/adapters/{persistence,pdf,udp,gps,simulator,hotspot,websocket}/`: persistence, rendering, device, simulator, and transport adapters.
- Report flow details: `docs/report_pipeline.md`.
- Analysis/run/live ingest details: `docs/analysis_pipeline.md`, `docs/run_lifecycle.md`, `docs/intake_buffering.md`, `docs/order_tracking.md`.

## Backend layer DAG

Enforced by `apps/server/pyproject.toml` import-linter config and `tools/dev/verify_backend_static_guards.py`.

| Layer | May import |
|---|---|
| `domain` | no project layers |
| `shared` | `domain` |
| `use_cases` | `domain`, `shared` |
| `infra` | `domain`, `shared` |
| `adapters` | `domain`, `shared`, `infra`, `use_cases` |
| `app` | all backend layers |

`shared -> domain` and `infra -> domain` are intentional. Fix inward leakage such as `use_cases -> adapters` or `domain -> outer layers`.

## UI ownership

- `apps/ui/src/app/runtime/`: app-wide composition, long-lived controllers, live transport, spectrum lifecycle.
- `apps/ui/src/app/features/`: feature workflows, API calls, polling, app-state mutations.
- `apps/ui/src/app/views/`: DOM rendering, HTML helpers, event-target decoding.
- `apps/ui/src/api/http.ts`, `apps/ui/src/ws.ts`, generated contracts, validators: canonical transport/contract seams.
- Contract sync details: `apps/ui/README.md`.

## Firmware and Pi image

- Firmware protocol contract: `docs/protocol.md`.
- Firmware local guidance: `firmware/esp/AGENTS.md`, `.github/instructions/firmware.instructions.md`.
- Pi image build/defaults: `infra/pi-image/pi-gen/README.md`.
- Pi local guidance: `infra/pi-image/AGENTS.md`, `.github/instructions/pi-image.instructions.md`.

## Tests and validation

- Backend tests mirror package ownership under `apps/server/tests/{adapters,app,domain,infra,shared,use_cases}/`.
- Cross-cutting regressions go in `apps/server/tests/integration/`; guards go in `apps/server/tests/hygiene/`.
- Shared backend test helpers live in `apps/server/tests/test_support/`.
- Full test placement and command router: `docs/testing.md`.
