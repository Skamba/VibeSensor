# VibeSensor AI Context

## Purpose

VibeSensor is an offline vehicle vibration diagnostics system. A Raspberry Pi hosts a Wi-Fi AP, receives UDP accelerometer frames from ESP32 sensor nodes, runs vibration analysis, serves a browser UI, records run history, and generates PDF diagnostic reports.

## Primary user journeys

1. Live diagnostics: run the backend, connect sensors or the simulator, and inspect the live dashboard.
2. Recording and review: capture a run, stop it, then inspect history, findings, exports, and reports.
3. Device operations: update the Pi software and ESP firmware from release artifacts.
4. Deployment: build the Pi image or run the stack locally through Docker.

## Architecture overview

- Firmware: `firmware/esp/` sends UDP frames and receives control commands.
- Backend: `apps/server/vibesensor/`.
	- `app.py`: FastAPI app factory.
	- `bootstrap.py`: focused service-group construction.
	- `routes/`: HTTP and WebSocket route groups.
	- `runtime/`: explicit runtime composition, dependency groups, coordination, and websocket broadcast state.
	- `processing/`, `analysis/`, `live_diagnostics/`: signal and findings logic.
	- `metrics_log/`, `history_db/`, `history_*.py`, `runlog.py`: recording and persistence.
	- `report/`, `report_i18n.py`: report rendering and report strings.
	- `update/`: updater orchestration.
- Frontend: `apps/ui/src/` provides the dashboard, settings, and history UI.
- Tooling: `apps/simulator/`, `tools/tests/`, `tools/ci/`, `scripts/ai/`.
- Pi image and infra: `infra/pi-image/pi-gen/`, `apps/server/systemd/`, `apps/server/scripts/`.

## Data flow boundaries

1. `udp_data_rx.py` parses sensor frames and feeds the registry and processing buffers.
2. `processing/` and `analysis/` compute spectra, vibration strength, and findings inputs.
3. `runtime/` composes the processing loop, websocket broadcast, and lifecycle subsystems, then coordinates their background work.
4. `metrics_log/` and `history_db/` persist run data, analysis results, and settings.
5. `routes/` exposes the HTTP and WebSocket surface consumed by `apps/ui/src/`.
6. `report/` builds PDFs from saved run and analysis data.

## Where to change what

- UI behavior, copy, and state wiring: `apps/ui/src/`.
- HTTP or WebSocket surface: `apps/server/vibesensor/routes/` and `apps/ui/src/api.ts` or `apps/ui/src/ws.ts`.
- Runtime orchestration: `apps/server/vibesensor/runtime/`, `app.py`, `bootstrap.py`.
- Signal math and vibration logic: `apps/server/vibesensor/processing/`, `apps/server/vibesensor/analysis/`, `libs/core/python/vibesensor_core/`.
- History storage and exports: `apps/server/vibesensor/history_db/`, `history_runs.py`, `history_reports.py`, `history_exports.py`, `runlog.py`.
- Report rendering: `apps/server/vibesensor/report/`, `apps/server/data/report_i18n.json`.
- Updates and deployment: `apps/server/vibesensor/update/`, `apps/server/systemd/`, `apps/server/scripts/`, `infra/pi-image/pi-gen/`.
- Test ownership: `apps/server/tests/` by feature area, plus `integration/` and `regression/` for broader coverage.

## Must-not-break invariants

- Canonical vibration severity metric is `vibration_strength_db`; do not replace it with raw g-value proxies in persisted analysis outputs.
- Server, UI, and tests must move together when the API or websocket contract changes.
- The updater is wheel-first. Normal delivery must go through `apps/server/vibesensor/update/manager.py`, not in-place edits on devices.
- Hotspot startup must remain offline-safe.
- `make test-all` is the local CI-parity verification path.

## Documentation rule

If a code change moves files, changes ownership boundaries, or changes commands, update the corresponding README, `docs/testing.md`, `docs/ai/*.md`, and instruction files in the same change set.

## Minimal read set for most changes

1. `docs/ai/repo-map.md`
2. `docs/ai/context.md`
3. `docs/ai/map.md`
4. `docs/ai/runbooks.md`
5. The owning code and test directories for the area you are changing
