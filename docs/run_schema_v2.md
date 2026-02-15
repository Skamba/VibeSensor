# Run Schema v2 (`.jsonl`)

VibeSensor writes run logs as JSONL (`*.jsonl`).

Each run file has:

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
- `raw_sample_rate_hz`
- `feature_interval_s`
- `fft_window_size_samples`
- `fft_window_type`
- `peak_picker_method`
- `units`
- `amplitude_definitions`

If key references are missing, set:

- `incomplete_for_order_analysis: true`

Optional but recommended:

- `tire_circumference_m` (required for wheel-order labeling)

### `sample` (per timestamp)

Required columns (must exist per record):

- `t_s` (monotonic seconds)
- `speed_kmh` (required for speed/order analysis; can be `null`)
- `accel_x_g`
- `accel_y_g`
- `accel_z_g`

Recommended:

- `engine_rpm`
- `gear`
- `gps_speed_kmh`

Common derived fields:

- `dominant_freq_hz`
- `dominant_peak_amp_g`
- `accel_magnitude_rms_g`
- `accel_magnitude_p2p_g`

### `run_end`

Contains:

- `run_id`
- `end_time_utc`

## Missing Reference Behavior

The report pipeline does not infer orders without references.

- Wheel order requires `speed_kmh` + `tire_circumference_m` (or wheel speed sensor).
- Engine order requires `engine_rpm`.

When missing, report findings include explicit `reference missing` entries and
order-specific claims are skipped.

## Commands

Generate PDF from run file:

```bash
vibesensor-report path/to/metrics_20260215_120000.jsonl
```

Legacy CSV files are intentionally not supported in this lab setup.
