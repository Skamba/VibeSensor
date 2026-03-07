# Backend Boundaries (Local)

Use this when changing backend code without scanning the whole package.

## Analysis Pipeline
- All post-stop analysis lives in `analysis/`. See [docs/analysis_pipeline.md](../../../docs/analysis_pipeline.md).
- Single entrypoint: `summarize_run_data()` in `analysis/summary.py`.
- External code should prefer the public `vibesensor.analysis` package API.
- `report/` is renderer-only and must not import from `analysis/`.
- Rule: no analysis helpers outside the analysis folder.

## Orchestration vs Computation
- `app.py`: thin FastAPI wiring layer; delegates service construction to `bootstrap.py`.
- `bootstrap.py`: builds focused runtime service groups and hands them to runtime composition.
- `runtime/` package: explicit composition (`composition.py`), focused dependency groups
  (`dependencies.py`), thin coordinator (`_state.py`), lifecycle management (`lifecycle.py`),
  processing loop (`processing_loop.py`), WebSocket broadcast (`ws_broadcast.py`),
  settings sync (`settings_sync.py`), and rotational speed helpers (`rotational_speeds.py`).
- FFT/metrics computation source of truth lives in `vibesensor_core`
        (`libs/core/python/vibesensor_core/vibration_strength.py` and
        `libs/core/python/vibesensor_core/strength_bands.py`).
- `processing/` orchestrates calls into core computation.
- Rule: do not move algorithm details into `app.py` or `runtime/`.

## Shared Utilities
- `json_utils.py`: single source of truth for numpy-aware JSON sanitisation.
  Both `ws_hub.py` and the `history_db/` package delegate to it. Also provides
  `safe_json_dumps()` and `safe_json_loads()` for consistent
  serialisation/deserialisation with error handling.
- `constants.py`: single source of truth for physical and analysis constants
  (noise floors, resonance bands, corroboration bonuses, etc.).  Modules
  should import constants from here rather than defining them locally.
- `domain_models.py`: canonical `normalize_sensor_id()` for client/sensor
  ID normalisation — all other modules delegate to it.
- `runlog.py`: canonical `utc_now_iso()` helper — prefer over inline
  `datetime.now(UTC).isoformat()` everywhere.
- `report/report_data.py`: all report dataclasses expose `from_dict()`
  for dict→dataclass reconstruction; avoid manual field-by-field unpacking.
- `report/pdf_builder.py`: public PDF renderer facade.
- `report/pdf_engine.py`, `pdf_page1.py`, `pdf_page2.py`, `pdf_page*_sections.py`,
  `pdf_drawing.py`, `pdf_text.py`, and `pdf_page_layouts.py`: focused PDF page composition,
  drawing, layout, and text helpers behind the facade.
- `report/pdf_diagram.py` is a compatibility facade; diagram planning and drawing now live in
  `pdf_diagram_layout.py`, `pdf_diagram_models.py`, and `pdf_diagram_render.py`.

## API Surface
- `routes/` is the HTTP and WebSocket boundary, assembled by `routes/__init__.py`.
- Keep response keys stable.

## Persistence Surface
- `metrics_log/` owns recording-time persistence semantics.
- `history_db/` owns SQLite storage, schema, run/status lifecycle, settings, and client-name persistence.
- `history_runs.py`, `history_reports.py`, and `history_exports.py` are the read/export coordination layer above the DB package.
- Rule: logging flow should only ingest fresh client data.

## Device/Ops Surface
- `apps/server/scripts/hotspot_nmcli.sh`: offline AP bring-up first, optional uplink second.
- `apps/server/systemd/*.service`: startup behavior and boot-time guarantees.
