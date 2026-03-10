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
	- `bootstrap.py`: focused subsystem-builder orchestration.
	- `routes/`: HTTP and WebSocket route groups; `/api/health` is the operator-facing readiness summary and now includes startup phase/error plus managed background-task failures.
	- `runtime/`: explicit runtime subsystem ownership, route-service assembly, lifecycle coordination, and websocket broadcast state; the broadcast path reuses shared per-tick payload state before applying per-recipient selected-client ids.
	- `processing/`, `analysis/`: signal and findings logic.
	- `metrics_log/`, `history_db/`, `history_*.py`, `runlog.py`: recording and persistence; within `metrics_log/`, `session_state.py` owns recording-session lifecycle, `persistence.py` owns history-run create/append/finalize bookkeeping, and `post_analysis.py` owns the background analysis queue while `logger.py` remains the façade. The runtime persistence subsystem owns the history query/delete/report/export services built around `HistoryDB`.
	- `report/`, `report_i18n.py`: report rendering and report strings.
	- `update/`: updater facade, workflow orchestration, and focused subsystems for Wi-Fi, releases, install and rollback, service control, status, and runtime reporting; validation and rollback snapshot creation are hard gates before live mutation.
- Frontend: `apps/ui/src/` provides the dashboard, settings, and history UI; `app/ui_app_runtime.ts` is the composition root over `app/runtime/` shell, transport, and spectrum owners plus the feature bundle.
- Tooling: `apps/simulator/`, `tools/tests/`, `tools/ci/`, `scripts/ai/`.
- Verification boundary: `tools/tests/run_release_smoke.py` is the canonical packaged-wheel smoke runner; Docker/e2e validation covers a different runtime path and should not be treated as a substitute for release-smoke.
- Pi image and infra: `infra/pi-image/pi-gen/`, `apps/server/systemd/`, `apps/server/scripts/`.

## Data flow boundaries

1. `udp_data_rx.py` parses sensor frames and feeds the registry and processing buffers.
2. `processing/` and `analysis/` compute spectra, vibration strength, and findings inputs.
3. `runtime/` assembles explicit ingress, settings, diagnostics, persistence, update, processing, websocket, and route-service subsystems, then coordinates their background work through lifecycle ownership.
4. `metrics_log/` owns recording orchestration through focused collaborators (`session_state.py`, `persistence.py`, `post_analysis.py`) while `history_db/` persists run data, analysis results, and settings through explicit read/write transactions and the runtime-owned history services.
5. `routes/` exposes the HTTP and WebSocket surface consumed by `apps/ui/src/`.
6. `report/` builds PDFs from saved run and analysis data.

## Where to change what

- UI behavior, copy, and state wiring: `apps/ui/src/`.
- HTTP or WebSocket surface: `apps/server/vibesensor/routes/` and `apps/ui/src/api.ts` or `apps/ui/src/ws.ts`.
- Runtime orchestration: `apps/server/vibesensor/runtime/`, `app.py`, `bootstrap.py`.
- Signal math and vibration logic: `apps/server/vibesensor/processing/`, `apps/server/vibesensor/analysis/`, `libs/core/python/vibesensor_core/`.
- History storage and exports: `apps/server/vibesensor/history_db/`, `history_services/`, `runlog.py`; route-facing history behavior is composed by the runtime persistence subsystem.
- Report rendering: `apps/server/vibesensor/report/`, `apps/server/data/report_i18n.json`.
- Updates and deployment: `apps/server/vibesensor/update/`, `apps/server/systemd/`, `apps/server/scripts/`, `infra/pi-image/pi-gen/`.
- Test ownership: `apps/server/tests/` by feature area, plus `integration/` and `regression/` for broader coverage.

## Must-not-break invariants

- Canonical vibration severity metric is `vibration_strength_db`; do not replace it with raw g-value proxies in persisted analysis outputs.
- Server, UI, and tests must move together when the API or websocket contract changes.
- When an intentional in-scope refactor changes function-level seams or helper boundaries, refactor the affected tests so they validate current behavior instead of preserving obsolete internals.
- The updater is wheel-first. Normal delivery must go through the `apps/server/vibesensor/update/` package, with `manager.py` as the public facade, not in-place edits on devices.
- Hotspot startup must remain offline-safe.
- `make test-all` is the local CI-parity verification path, including the packaged-wheel `release-smoke` gate.

## Documentation rule

If a code change moves files, changes ownership boundaries, or changes commands, update the corresponding README, `docs/testing.md`, `docs/ai/*.md`, and instruction files in the same change set.

## Minimal read set for most changes

1. `docs/ai/repo-map.md`
2. `docs/ai/context.md`
3. `docs/ai/map.md`
4. `docs/ai/runbooks.md`
5. The owning code and test directories for the area you are changing
