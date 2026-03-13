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
- `vibesensor/vibration_strength.py`, `vibesensor/strength_bands.py`: shared vibration math and unit logic (inlined from former `libs/core/`).
- `infra/pi-image/pi-gen/`: Raspberry Pi image build pipeline.
- `docs/`: human-facing docs plus AI repo maps and runbooks.

## Backend package layout

- `app.py`: app factory and CLI-facing startup.
- `routes/`: health, clients, settings, recording, history, websocket, updates (`/api/update/`, `/api/esp-flash/`), car library, and debug route groups; `/api/health` now surfaces startup readiness and managed-task failures in addition to processing degradation.
- `runtime/`: flat `RuntimeState` (`state.py`), service builders (`builders.py`), lifecycle management (`lifecycle.py`), processing loop (`processing_loop.py`), and websocket broadcast (`ws_broadcast.py`); `builders.py::build_runtime()` constructs the flat `RuntimeState` directly; routes receive `RuntimeState` (no intermediate route-service assembly); the websocket broadcaster reuses shared per-tick payload state and only layers in recipient-specific selection at the end.
- `processing/`, `analysis/`: signal processing and findings logic.
  `analysis/findings.py` and `analysis/top_cause_selection.py` delegate
  classification and ranking logic to the domain `Finding`.
- `domain/`: DDD-aligned domain model package.  Each primary domain object
  lives in its own dedicated file: `car.py` (Car), `sensor.py` (Sensor,
  SensorPlacement), `measurement.py` (Measurement/AccelerationSample,
  VibrationReading), `session.py` (Run/DiagnosticSession, SessionStatus),
  `speed_source.py` (SpeedSource), `analysis_window.py` (AnalysisWindow),
  `finding.py` (Finding), `report.py` (Report), `history_record.py`
  (HistoryRecord).  All are plain dataclasses with no external coupling.
  Domain objects own classification, ranking, actionability, surfacing,
  and query logic; pipeline adapters (OrderAssessment) in
  `analysis/` delegate to them.  See `docs/domain-model.md` for the full
  relationship map and modeling rules.
- `metrics_log/`: recording pipeline package; `logger.py` owns the `MetricsLogger` class which directly manages session state and persistence coordination (no private helper classes), enriching status/health payloads with sample counts and analysis results; `post_analysis.py` owns the background analysis queue with outcome tracking; `sample_builder.py` owns pure sample-building functions.
- `history_db/`: SQLite-backed history and settings persistence (3 files: `__init__.py` with `HistoryDB` class consolidating connection management, settings KV, client names, and all run reads/writes; `_schema.py` with DDL, `RunStatus`, and `ANALYSIS_SCHEMA_VERSION`; `_samples.py` for v2 sample serialization). Incompatible older schemas raise a clear error directing the user to delete the DB file.
- `history_services/`: focused history service layer (run query/delete, reports, exports, helpers) above `history_db/`.
- `hotspot/`: Wi-Fi AP monitoring, text parsing, and self-heal logic.
- `runlog.py`: JSONL run-file I/O and normalization.
- `report/`: PDF renderer and report-template builders.
- `update/`: public update manager facade (`manager.py`) with workflow orchestration, validation, and models (`models.py`); Wi-Fi control and diagnostics (`wifi.py`), release discovery (`releases.py`), ESP flash management, firmware cache, release validation, install and rollback, command execution, and status tracking with runtime detail collection (`status.py`); workflow validation and rollback snapshot creation must both succeed before a live install begins.
- `apps/ui/src/app/runtime/`: explicit UI runtime owners for shell/chrome state, live transport/payload application, and spectrum/chart orchestration beneath the `UiAppRuntime` composition root.

## Test layout

- `apps/server/tests/` is feature-based and mirrors backend ownership boundaries.
- Cross-cutting coverage lives in `integration/` and `hygiene/`.
- Regression tests live in the feature directory they primarily test, or in `integration/` for cross-cutting regressions.
- Shared test support lives at the test root (`conftest.py`, `_paths.py`, focused helper modules, and the `test_support/` package).
- Full map: `docs/testing.md`.

## Source-of-truth rule

When code movement changes this map, update `docs/ai/repo-map.md`, `.github/copilot-instructions.md`, and the affected README or instruction file in the same change set.
