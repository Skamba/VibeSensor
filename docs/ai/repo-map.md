# Repo map

## Primary entry points

- Backend app: `apps/server/vibesensor/app.py`
- Backend service wiring: `apps/server/vibesensor/runtime/builders.py`
- Backend route assembly: `apps/server/vibesensor/routes/__init__.py`
- UI app entry: `apps/ui/src/main.ts`
- UI runtime/composition root: `apps/ui/src/app/ui_app_runtime.ts`
- UI runtime owners: `apps/ui/src/app/runtime/`
- Simulator CLI: `apps/server/vibesensor/simulator/sim_sender.py`
- Firmware app: `firmware/esp/src/main.cpp`
- Pi image build: `infra/pi-image/pi-gen/build.sh`
- Local stack entry point: `docker-compose.yml`

## Top-level layout

- `apps/server/`: backend package, configs, tests, scripts, systemd units, public UI assets, simulator, and config tooling.
- `apps/ui/`: TypeScript/Vite dashboard and Playwright tests.
- `firmware/esp/`: ESP32 firmware.
- `vibesensor/core/`: shared vibration math and unit logic (inlined from former `libs/core/`).
- `infra/pi-image/pi-gen/`: Raspberry Pi image build pipeline.
- `docs/`: human-facing docs plus AI repo maps and runbooks.

## Backend package layout

- `app.py`: app factory and CLI-facing startup.
- `routes/`: health, clients, settings, recording, history, websocket, updates, car library, and debug route groups; `/api/health` now surfaces startup readiness and managed-task failures in addition to processing degradation.
- `runtime/`: flat `RuntimeState` (`state.py`), service builders (`builders.py`), lifecycle management (`lifecycle.py`), processing loop (`processing_loop.py`), and websocket broadcast (`ws_broadcast.py`); `builders.py::build_runtime()` constructs the flat `RuntimeState` directly; routes receive `RuntimeState` (no intermediate route-service assembly); the websocket broadcaster reuses shared per-tick payload state and only layers in recipient-specific selection at the end.
- `processing/`, `analysis/`: signal processing and findings logic.
- `metrics_log/`: recording pipeline package; `session_state.py` owns recording-session lifecycle, `persistence.py` owns history-run create/append/finalize bookkeeping with drop counting and retry-with-cooldown for transient DB failures, `post_analysis.py` owns the background analysis queue with outcome tracking, and `logger.py` is the coordinating façade that enriches status/health payloads with sample counts and analysis results.
- `history_db/`: SQLite-backed history and settings persistence (3 files: `__init__.py` with `HistoryDB` class consolidating connection management, settings KV, client names, and all run reads/writes; `_schema.py` with DDL, `RunStatus`, and `ANALYSIS_SCHEMA_VERSION`; `_samples.py` for v2 sample serialization). Incompatible older schemas raise a clear error directing the user to delete the DB file.
- `history_services/`: focused history service layer (run query/delete, reports, exports, helpers) above `history_db/`.
- `hotspot/`: Wi-Fi AP monitoring, text parsing, and self-heal logic.
- `runlog.py`: JSONL run-file I/O and normalization.
- `report/`: PDF renderer and report-template builders.
- `update/`: public update manager facade plus focused modules for workflow orchestration and validation (`workflow.py`), Wi-Fi control and diagnostics (`wifi.py`), release discovery, install and rollback, service control, command execution, and status tracking with runtime detail collection (`status.py`); workflow validation and rollback snapshot creation must both succeed before a live install begins.
- `apps/ui/src/app/runtime/`: explicit UI runtime owners for shell/chrome state, live transport/payload application, and spectrum/chart orchestration beneath the `UiAppRuntime` composition root.

## Test layout

- `apps/server/tests/` is feature-based and mirrors backend ownership boundaries.
- Cross-cutting coverage lives in `integration/`, `regression/`, `hygiene/`, and `e2e/`.
- `regression/` is further split by intent: `analysis/`, `audits/`, `cross_cutting/`, `report/`, `runtime/`.
- Shared test support lives at the test root (`conftest.py`, `_paths.py`, focused helper modules, and the `test_support/` package).
- Full map: `docs/testing.md`.

## Source-of-truth rule

When code movement changes this map, update `docs/ai/repo-map.md`, `.github/copilot-instructions.md`, and the affected README or instruction file in the same change set.
