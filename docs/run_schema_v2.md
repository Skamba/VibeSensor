# Legacy Run Schema v2 (`.jsonl`)

This document describes the legacy/CLI JSONL run boundary used by
`shared/types/run_schema.py` constants and tools such as `vibesensor-report`.
The current server runtime persists run history in SQLite (`history.db`) plus
raw-capture and whole-run sidecar directories; see `docs/history_db_schema.md`
and `docs/analysis_pipeline.md` for the active storage model.

When a JSONL run file is read or written at this boundary, it has:

1. `run_metadata` record (first line)
2. many `sample` records (time series)
3. optional `run_end` record

## Record Types

### `run_metadata` (run-level, required)

Required fields:

- `run_id`
- `start_time_utc`
- `end_time_utc` (may be `null` while active)
- `sensor_model`
- `firmware_version` (optional)
- `strength_algorithm_version` (optional)
- `peak_detector_version` (optional)
- `calibration_profile_id` (optional)
- `vehicle_baseline_profile_id` (optional)
- `raw_sample_rate_hz`
- `configured_raw_sample_rate_hz` (optional)
- `feature_interval_s` (used by time-aware order-evidence gating to convert logged match samples into durations)
- `fft_window_size_samples`
- `fft_window_type`
- `peak_picker_method`
- `accel_scale_g_per_lsb` (`null` if unknown / not converted)

If key references are missing, set:

- `incomplete_for_order_analysis: true`

Optional but recommended:

- `analysis_settings` (active run-attached analysis settings snapshot)
- `car` (run-attached car identity and order-reference status)
- `sensor_snapshots` (per-run sensor identity/location/orientation/sample-rate snapshots)
- `raw_capture_finalize` (raw-capture finalize status when the runtime writes a DB-backed run)
- `finalization_stages` (structured recorder finalization stage results)
- `case_id`, `sensor_mac`, `symptom`, `report_date`, `language`
- `wheel_circumference_m` (legacy wheel-reference fallback)
- `recorded_utc_offset_seconds`

### `sample` (per timestamp)

Required columns (must exist per record):

- `t_s` (monotonic seconds)
- `speed_kmh` (required for speed/order analysis; can be `null`)
- `gps_speed_kmh`
- `speed_source`
- `engine_rpm`
- `engine_rpm_source`
- `gear`
- `final_drive_ratio`
- `accel_x_g`
- `accel_y_g`
- `accel_z_g`
- `analysis_window_start_us` (optional raw-analysis window start)
- `analysis_window_end_us` (optional raw-analysis window end)
- `analysis_window_synced` (optional raw-window sync flag)

Recommended:

- `client_id`
- `client_name`
- `location`
- `sample_rate_hz`
- `frames_dropped_total`
- `queue_overflow_drops`

Common derived fields:

- `dominant_freq_hz`
- `vibration_strength_db` (vibration severity metric in dB — see `docs/metrics.md`)
- `strength_bucket` (severity band key: `l1`–`l5` or `null`)
- `top_peaks` (up to 8 entries of `{hz, amp, vibration_strength_db, strength_bucket}` from combined spectrum)

### `run_end`

Contains:

- `run_id`
- `end_time_utc`

## Missing Reference Behavior

The report pipeline does not infer orders without references.

- Wheel order requires speed plus tire/order-reference settings.
- Driveshaft order requires wheel reference plus final-drive data.
- Engine order requires RPM or aligned speed/final-drive/gear reference data.

When missing, report findings include explicit `reference missing` entries and
order-specific claims are skipped.

The current whole-run sidecar path scores order traces against the dense window
grid and persists compact summaries. The legacy JSONL/summary path still uses
per-sample predicted order frequencies and matches against `top_peaks` within
tolerance, so wheel/driveline/engine findings can remain valid when speed
changes during the run.

## Commands

Generate PDF from run file:

```bash
vibesensor-report path/to/metrics_20260215_120000.jsonl
```

Legacy CSV files are intentionally not supported in this lab setup. For current
runtime history, use the SQLite history DB and sidecar artifacts rather than
treating JSONL files as the primary run store.

## Removed Fields (schema history)

The following fields were present in earlier runs and are no longer written or read.

| Removed field | Replacement |
|---------------|-------------|
| `vib_mag_rms_g` | (removed — use `vibration_strength_db`) |
| `vib_mag_p2p_g` | (removed) |
| `noise_floor_amp_p20_g` | (removed — internal intermediate) |
| `strength_floor_amp_g` | (removed — internal intermediate) |
| `strength_peak_band_rms_amp_g` | `top_peaks[0].amp` |
| `strength_db` | `vibration_strength_db` |
| `top_strength_peaks` | `top_peaks` |
