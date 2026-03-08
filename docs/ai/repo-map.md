# Repo map

## Primary entry points

- Backend app: `apps/server/vibesensor/app.py`
- Backend service wiring: `apps/server/vibesensor/bootstrap.py`
- Backend route assembly: `apps/server/vibesensor/routes/__init__.py`
- UI app: `apps/ui/src/main.ts`
- Simulator CLI: `apps/simulator/vibesensor_simulator/sim_sender.py`
- Firmware app: `firmware/esp/src/main.cpp`
- Pi image build: `infra/pi-image/pi-gen/build.sh`
- Local stack entry point: `docker-compose.yml`

## Top-level layout

- `apps/server/`: backend package, configs, tests, scripts, systemd units, public UI assets.
- `apps/ui/`: TypeScript/Vite dashboard and Playwright tests.
- `apps/simulator/`: simulator package and websocket smoke tooling.
- `firmware/esp/`: ESP32 firmware.
- `libs/core/python/vibesensor_core/`: shared vibration math and unit logic.
- `libs/shared/`: shared contracts and generated assets used across server and UI.
- `infra/pi-image/pi-gen/`: Raspberry Pi image build pipeline.
- `docs/`: human-facing docs plus AI repo maps and runbooks.

## Backend package layout

- `app.py`: app factory and CLI-facing startup.
- `bootstrap.py`: orchestrates focused runtime subsystem builders.
- `routes/`: health, clients, settings, recording, history, websocket, updates, car library, and debug route groups; `/api/health` now surfaces startup readiness and managed-task failures in addition to processing degradation.
- `runtime/`: subsystem builders, explicit runtime owners, lifecycle, processing loop, websocket broadcast, settings sync, and route-service assembly; the websocket broadcaster reuses shared per-tick payload state and only layers in recipient-specific selection at the end.
- `processing/`, `analysis/`, `live_diagnostics/`: signal processing and findings logic.
- `metrics_log/`: recording, post-analysis hooks, and the focused live-analysis snapshot window used by runtime websocket diagnostics.
- `history_db/`: SQLite-backed history and settings persistence, including explicit read/write transaction helpers for run lifecycle updates.
- `history_runs.py`, `history_reports.py`, `history_exports.py`, `history_helpers.py`, `runlog.py`: focused history services and helpers now owned by the runtime persistence subsystem instead of being composed inside routes.
- `report/`: PDF renderer and report-template builders.
- `update/`: public update manager facade plus focused modules for status tracking, Wi-Fi control, release discovery, install and rollback, service control, command execution, and state storage; workflow validation and rollback snapshot creation must both succeed before a live install begins.

## Test layout

- `apps/server/tests/` is feature-based and mirrors backend ownership boundaries.
- Cross-cutting coverage lives in `integration/`, `regression/`, `hygiene/`, and `e2e/`.
- `regression/` is further split by intent: `analysis/`, `audits/`, `cross_cutting/`, `report/`, `runtime/`.
- Shared test support lives at the test root (`conftest.py`, `_paths.py`, focused helper modules, and the `test_support/` package).
- Full map: `docs/testing.md`.

## Source-of-truth rule

When code movement changes this map, update `docs/ai/repo-map.md`, `docs/ai/map.md`, `docs/ai/context.md`, `docs/ai/runbooks.md`, and the affected README or instruction file in the same change set.
