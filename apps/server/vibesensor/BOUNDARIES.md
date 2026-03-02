# Backend Boundaries (Local)

Use this when changing backend code without scanning the whole package.

## Analysis Pipeline
- All post-stop analysis lives in `analysis/`. See [docs/analysis_pipeline.md](../../../docs/analysis_pipeline.md).
- Single entrypoint: `summarize_run_data()` in `analysis/summary.py`.
- External code imports only from `analysis/__init__.py` (public API).
- `report/` is renderer-only and must not import from `analysis/`.
- Rule: no analysis helpers outside the analysis folder.

## Orchestration vs Computation
- `app.py`: orchestrates runtime loops, task startup/shutdown, payload assembly.
- FFT/metrics computation source of truth lives in `vibesensor_core`
	(`libs/core/python/vibesensor_core/vibration_strength.py` and
	`libs/core/python/vibesensor_core/strength_bands.py`).
- `processing.py` orchestrates calls into core computation.
- Rule: do not move algorithm details into `app.py`.

## Shared Utilities
- `json_utils.py`: single source of truth for numpy-aware JSON sanitisation.
  Both `ws_hub.py` and `history_db.py` delegate to it.  Also provides
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
- `report/pdf_layout.py`: aspect-ratio geometry helpers for PDF layout,
  separated from content rendering in `pdf_builder.py`.

## API Surface
- `api.py` is the HTTP boundary.
- Keep response keys stable.

## Persistence Surface
- `metrics_log.py` and `history_db.py` own session persistence semantics.
- Rule: logging flow should only ingest fresh client data.

## Device/Ops Surface
- `apps/server/scripts/hotspot_nmcli.sh`: offline AP bring-up first, optional uplink second.
- `apps/server/systemd/*.service`: startup behavior and boot-time guarantees.
