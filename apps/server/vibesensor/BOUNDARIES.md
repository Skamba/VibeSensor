# Backend Boundaries (Local)

Use this when changing backend code without scanning the whole package.

## Domain Model
- Ten primary domain concepts live in dedicated files under `domain/` and are
  re-exported from `vibesensor.domain`:
  1. `Car` (`car.py`) – the vehicle under test.  Owns tire-circumference
     computation from aspect specs.
  2. `Sensor` (`sensor.py`) – a physical accelerometer node.
  3. `SensorPlacement` (`sensor.py`) – a sensor's mounting position on the
     vehicle.  Owns position category classification (wheel/drivetrain/body).
  4. `Run` (`session.py`) – one complete diagnostic measurement session
     (aggregate root).  Owns in-memory lifecycle (pending → running).
     The persisted lifecycle is tracked by `RunStatus` in `run_status.py`.
  5. `Measurement` (`measurement.py`) – a single multi-axis acceleration
     sample (value object).  `AccelerationSample` is a backward-compatibility
     alias.
  6. `SpeedSource` (`speed_source.py`) – how vehicle speed is obtained during
     a run.  Owns source-kind classification and effective-speed resolution.
  7. `AnalysisWindow` (`analysis_window.py`) – a contiguous aligned chunk of
     samples for analysis.  Owns phase classification (cruise/accel/idle),
     speed containment, and analyzability checks.
  8. `Finding` (`finding.py`) – one diagnostic conclusion or cause candidate.
     Owns classification (reference/informational/diagnostic),
     actionability, surfacing decisions, confidence normalisation,
     deterministic ranking, and phase-adjusted scoring.
  9. `Report` (`report.py`) – the assembled output of a diagnostic run.
     Owns finding accessors and primary-finding selection.
- Prefer these simple names in domain logic; use the narrower config/payload
  shapes (`CarConfig`, `SensorConfig`, `SpeedSourceConfig`, `RunMetadata`,
  `SensorFrame`, `ReportTemplateData`, `HistoryRunPayload`) at persistence,
  wire-format, and rendering boundaries.
- `OrderAssessment` (in `analysis/top_cause_selection.py`) delegates
  classification and ranking logic to the domain `Finding` and remains
  as a pipeline adapter for dict-based analysis workflows.
- See `docs/domain-model.md` for the full domain relationship map.

## Analysis Pipeline
- All post-stop analysis lives in `analysis/`. See [docs/analysis_pipeline.md](../../../docs/analysis_pipeline.md).
- Single entrypoint: `summarize_run_data()` in `analysis/summary_builder.py`.
- External code should prefer the public `vibesensor.analysis` package API.
- `report/` is renderer-only and must not import from `analysis/`.
- Rule: no analysis helpers outside the analysis folder.

## Orchestration vs Computation
- `app.py`: thin FastAPI wiring layer; delegates service construction to `runtime/builders.py`.
- `runtime/` package: flat `RuntimeState` (`state.py`), service builders (`builders.py`),
  lifecycle management (`lifecycle.py`), health tracking (`health_state.py`),
  processing loop (`processing_loop.py`), WebSocket broadcast (`ws_broadcast.py`),
  and rotational speed helpers (`rotational_speeds.py`).
- FFT/metrics computation source of truth lives in `vibesensor`
        (`vibesensor/vibration_strength.py` and
        `vibesensor/strength_bands.py`).
- `processing/` orchestrates calls into core computation.
- Rule: do not move algorithm details into `app.py` or `runtime/`.

## Shared Utilities
- `json_utils.py`: single source of truth for numpy-aware JSON sanitisation.
  Both `ws_hub.py` and the `history_db/` package delegate to it. Also provides
  `safe_json_dumps()` and `safe_json_loads()` for consistent
  serialisation/deserialisation with error handling.
- `constants.py`: single source of truth for physical and analysis constants
  (noise floors, resonance bands, confidence bounds, SNR divisors, etc.).  Modules
  should import constants from here rather than defining them locally.
- `exceptions.py`: domain exception hierarchy — `VibeSensorError` base with
  `ConfigurationError`, `PersistenceError`, `ProcessingError`, `ProtocolError`,
  `UpdateError`, `RunNotFoundError`, `AnalysisNotReadyError`, `DataCorruptError`.
  Subsystem exceptions (`settings_store.PersistenceError`,
  `runtime/processing_loop.ProcessingLoopError`) inherit from domain base classes.
- `protocol.py`: canonical `normalize_sensor_id()` for client/sensor
  ID normalisation — all other modules delegate to it.
- `runlog.py`: canonical `utc_now_iso()` helper — prefer over inline
  `datetime.now(UTC).isoformat()` everywhere.
- `report/report_data.py`: pure data-class definitions for the diagnostic PDF.
- `report/pdf_engine.py`: public PDF renderer entrypoint and pagination.
- `report/pdf_page1.py`, `pdf_page2.py`, `pdf_page*_sections.py`,
  `pdf_drawing.py`, `pdf_text.py`, and `pdf_page_layouts.py`: focused PDF page composition,
  drawing, layout, and text helpers.
- Diagram planning and drawing live in `pdf_diagram_layout.py`, `pdf_diagram_models.py`,
  and `pdf_diagram_render.py`.

## Settings Boundary
- `settings_store.py`: user-facing settings (cars, speed source, language, unit, sensors)
  persisted to HistoryDB.
- `analysis_settings.py`: in-memory-only analysis parameter store (tire_diameter,
  tire_aspect, etc.) recomputed from the active car's aspects.  Lives at package root
  (not inside `analysis/`) because `runtime/` and `metrics_log/` depend on it — moving
  it into `analysis/` would create a circular dependency.
- `history_db/`: `get_settings_snapshot()`/`set_settings_snapshot()` persist settings as a single JSON blob.
- `settings_store.py` owns semantic meaning; delegates persistence to `history_db`.

## API Surface
- `routes/` is the HTTP and WebSocket boundary, assembled by `routes/__init__.py`.
- Keep response keys stable.
- Rule: only `routes/` modules may import or raise `HTTPException`.
  Service modules in `history_services/` (`runs.py`, `reports.py`, `helpers.py`,
  `exports.py`) raise domain exceptions from `exceptions.py`.
  The `routes/_helpers.py::domain_errors_to_http()` context manager translates
  domain exceptions to HTTP status codes at the route boundary.

## Persistence Surface
- `metrics_log/` owns recording-time persistence semantics.
- `history_db/` owns SQLite storage, schema, run/status lifecycle, settings, and client-name persistence.
- `history_services/` is the read/export coordination layer above the DB package
  (`runs.py`, `reports.py`, `exports.py`, `helpers.py`).
- Rule: logging flow should only ingest fresh client data.

## Hotspot / Infrastructure Surface
- `hotspot/` owns Wi-Fi AP monitoring, parsing, and self-heal logic
  (`parsers.py` and `self_heal.py`).
- `apps/server/scripts/hotspot_nmcli.sh`: offline AP bring-up first, optional uplink second.
- `apps/server/systemd/*.service`: startup behavior and boot-time guarantees.
