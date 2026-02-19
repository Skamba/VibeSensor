# Backend Boundaries (Local)

Use this when changing backend code without scanning the whole package.

## Orchestration vs Computation
- `app.py`: orchestrates runtime loops, task startup/shutdown, payload assembly.
- FFT/metrics computation source of truth lives in `vibesensor_core`
	(`libs/core/python/vibesensor_core/vibration_strength.py` and
	`libs/core/python/vibesensor_core/strength_bands.py`).
- `processing.py` orchestrates calls into core computation.
- Rule: do not move algorithm details into `app.py`.

## API Surface
- `api.py` is the HTTP boundary.
- Keep response keys stable for UI compatibility.

## Persistence Surface
- `metrics_log.py` and `history_db.py` own session persistence semantics.
- Rule: logging flow should only ingest fresh client data.

## Device/Ops Surface
- `apps/server/scripts/hotspot_nmcli.sh`: offline AP bring-up first, optional uplink second.
- `apps/server/systemd/*.service`: startup behavior and boot-time guarantees.
