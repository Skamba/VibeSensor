# VibeSensor Metrics Reference

## Vibration Strength

**`vibration_strength_db`** (dB) — the repo-wide "how strong is the vibration" metric.

### Formula

```
vibration_strength_db = 20 * log10((peak_band_rms_amp_g + eps) / (floor_amp_g + eps))
```

where:

- `peak_band_rms_amp_g` — RMS amplitude of the dominant peak within ±`PEAK_BANDWIDTH_HZ` (1.2 Hz)
- `floor_amp_g` — median amplitude of the spectrum excluding peaks (noise floor estimate)
- `eps = max(STRENGTH_EPSILON_MIN_G, floor_amp_g * STRENGTH_EPSILON_FLOOR_RATIO)`
  - `STRENGTH_EPSILON_MIN_G = 1e-9`
  - `STRENGTH_EPSILON_FLOOR_RATIO = 0.05`

This formula measures how far the dominant peak stands above the noise floor, expressed in dB.
A value of 0 dB means the peak is at the noise floor level; positive values indicate vibration
above the floor.

### Implementation

The implementation lives in `apps/server/vibesensor/vibration_strength.py`:

- `compute_vibration_strength_db()` — full pipeline (spectrum → peaks → dB metric)
- `vibration_strength_db_scalar()` — low-level scalar helper

No other module may re-implement this formula. Use `bucket_for_strength()` for severity
classification — never compare raw dB values against band thresholds inline.

For post-stop persisted analysis/report artifacts (`summarize_run_data()` output,
persisted analysis envelopes, localized report-facing strength/intensity fields),
expose dB-only strength values. Raw ingest/sample fields may still carry g-based
units.

## Processing profiles

Filtering choices are explicit because live display smoothing must not silently
change report or forensic diagnostics.

| Profile | Owner | Filter chain | Use |
|---------|-------|--------------|-----|
| `live_display` | `apps/server/vibesensor/infra/processing/compute.py` | `median_3_sample_time_domain` | Operator-facing live metrics and spectra. |
| `diagnostic_raw` | post-run raw replay and dense raw-window stages | none | Report/post-run truth when raw capture is available. |
| `diagnostic_filtered` | persisted-summary fallback or optional comparisons | `median_3_sample_time_domain` | Clearly labeled fallback/comparison data, not raw truth. |

The shared identifiers live in
`apps/server/vibesensor/shared/types/processing_profile.py`. Live combined
metrics carry `processing_profile = "live_display"` and their filter chain.
Persisted analysis metadata records the active diagnostic `processing_profile`,
available profile rows, the live filter chain, the diagnostic filter chain, and
whether raw diagnostic evidence was preserved.

Raw replay and whole-run spectra use unfiltered raw windows for diagnostic
strength/spectrum computation. If no raw-backed replay is available, report
metadata marks the active profile as `diagnostic_filtered` so downstream report
code can treat summary-derived evidence as a fallback instead of raw evidence.

## Severity Bands (l1–l5)

Severity classification is performed solely by `bucket_for_strength(vibration_strength_db)` in
`apps/server/vibesensor/strength_bands.py`.

| Band | Minimum dB |
|------|-----------|
| l1   | 10.0      |
| l2   | 16.0      |
| l3   | 22.0      |
| l4   | 28.0      |
| l5   | 34.0      |

`bucket_for_strength()` returns the highest band whose `min_db` threshold is met, or `None` if
below all thresholds.

Hysteresis and persistence logic is handled in `severity.severity_from_peak()`:

- `HYSTERESIS_DB = 2.0` — dB subtracted from active band threshold on decay check
- `PERSISTENCE_TICKS = 3` — ticks a new band must be seen before promotion
- `DECAY_TICKS = 5` — ticks below threshold before demotion

## Run persistence fields

Current runtime history stores sample metrics in SQLite `samples_v2` typed
columns; the legacy/CLI JSONL boundary uses the same `SensorFrame` field names.
See `docs/history_db_schema.md` for the current DB schema and
`docs/run_schema_v2.md` for the legacy JSONL boundary. This section lists only
metric fields, not the full persistence schema.

### Metric fields

| Field | Type | Description |
|-------|------|-------------|
| `vibration_strength_db` | float | Vibration strength (dB above noise floor) |
| `strength_bucket` | str \| null | Severity band key (`l1`–`l5`) or `null` |
| `top_peaks` | list | Up to 8 combined-spectrum peaks: `[{hz, amp, vibration_strength_db, strength_bucket}]` |
| `dominant_freq_hz` | float | Frequency of dominant peak (Hz) |
| `strength_peak_amp_g` | float | Peak amplitude used to compute dB strength |
| `strength_floor_amp_g` | float | Noise-floor amplitude used to compute dB strength |

### Removed fields (previously present, now deleted)

The following fields were removed to eliminate ambiguity. They are no longer written and will
be stripped from old records by `normalize_sample_record()`:

- `vib_mag_rms_g` — removed; was RMS of 3-axis combined magnitude
- `vib_mag_p2p_g` — removed; was peak-to-peak of 3-axis combined magnitude
- `noise_floor_amp_p20_g` — removed; internal intermediate, use `vibration_strength_db`
- `strength_floor_amp_g` — removed; internal intermediate
- `strength_peak_band_rms_amp_g` — removed; use `top_peaks[0].amp`
- `strength_db` — renamed to `vibration_strength_db`
- `combined_spectrum_db_above_floor` — removed from API/WebSocket; use `combined_spectrum_amp_g`
- `severity_db` — renamed to `vibration_strength_db` in live event payloads
- `top_strength_peaks` — renamed to `top_peaks`

## WebSocket / API Payloads

The `spectrum_payload` endpoint includes:

```json
{
  "combined_spectrum_amp_g": [...],
  "strength_metrics": {
    "vibration_strength_db": 22.3,
    "strength_bucket": "l3",
    "top_peaks": [
      {"hz": 32.5, "amp": 0.041, "vibration_strength_db": 22.3, "strength_bucket": "l3"}
    ]
  }
}
```
