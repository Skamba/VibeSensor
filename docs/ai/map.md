# VibeSensor AI Entry-Point Map

## Start here

- `apps/server/vibesensor/app.py`: FastAPI app factory and CLI-facing startup.
- `apps/server/vibesensor/bootstrap.py`: subsystem builder orchestration before final runtime assembly.
- `apps/server/vibesensor/routes/__init__.py`: assembles the HTTP and WebSocket route groups.
- `apps/server/vibesensor/runtime/`: runtime subsystem builders and owners, processing loop, websocket broadcast state, route-service assembly, and lifecycle services.
- `apps/server/vibesensor/history_db/`: SQLite-backed history and settings persistence.
- `apps/server/vibesensor/report/pdf_engine.py`: public PDF renderer entrypoint and page orchestration.
- `apps/server/vibesensor/update/manager.py`: public wheel-based updater facade that composes the focused update modules.
- `apps/ui/src/main.ts`: top-level UI orchestration.
- `apps/ui/src/api.ts` and `apps/ui/src/ws.ts`: HTTP and WebSocket client surfaces.
- `apps/simulator/`: simulator CLI and websocket smoke tooling.

## Current backend boundaries

- Acquisition: `udp_data_rx.py`, `udp_control_tx.py`, `registry.py`, `protocol.py`.
- Analysis: `processing/`, `analysis/`, `live_diagnostics/`, `libs/core/python/vibesensor_core/`.
- Runtime coordination: `app.py`, `bootstrap.py`, `runtime/`.
- API delivery: `routes/`, `ws_hub.py`, `ws_models.py`.
- Persistence and exports: `metrics_log/`, `history_db/`, `history_runs.py`, `history_reports.py`, `history_exports.py`, `runlog.py`.
- Reports: `report/`, `report_i18n.py`.
- Updates and device ops: `update/`, `firmware_cache.py`, `esp_flash_manager.py`, `release_fetcher.py`, `apps/server/scripts/`, `apps/server/systemd/`.

## Hot spots

- `apps/server/vibesensor/runtime/composition.py`: runtime subsystem assembly and ownership boundaries.
- `apps/server/vibesensor/routes/__init__.py`: shared route assembly point.
- `apps/server/vibesensor/update/workflow.py`: long-running update flow with explicit validation, Wi-Fi, release, install, rollback, and restart orchestration.
- `apps/server/vibesensor/report/`: public report rendering surface. Start at `pdf_engine.py`, then follow the page modules plus shared drawing/layout helpers.
- `apps/ui/src/main.ts`: large UI coordinator.

## Safe starting points

- Small backend extractions inside the owning package instead of adding parallel modules elsewhere.
- Focused tests in `apps/server/tests/<area>/` plus adjacent integration or regression coverage when needed.
- `docs/ai/*`, `docs/testing.md`, and area READMEs when code movement changes the current source of truth.

## File-selection heuristic

1. Open the owning entry point for the area you are changing.
2. Read the nearest helper packages and tests for that ownership boundary.
3. Update the related docs or instructions in the same change set if paths, responsibilities, or workflows changed.
4. Avoid repo-wide scans until the local boundary is exhausted.
