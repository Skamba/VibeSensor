# VibeSensor Metrics Reference

## Canonical Vibration Strength

**`vibration_strength_db`** (dB) — the single authoritative "how strong is the vibration" metric.

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

### Source of truth

The canonical implementation lives in `libs/core/python/vibesensor_core/vibration_strength.py`:

- `compute_vibration_strength_db()` — full pipeline (spectrum → peaks → dB metric)
- `_vibration_strength_db_scalar()` — low-level scalar helper (private)

No other module may re-implement this formula. Use `bucket_for_strength()` for severity
classification — never compare raw dB values against band thresholds inline.

## Severity Bands (l1–l5)

Severity classification is performed solely by `bucket_for_strength(vibration_strength_db)` in
`libs/core/python/vibesensor_core/strength_bands.py`.

| Band | Minimum dB |
|------|-----------|
| l1   | 10.0      |
| l2   | 16.0      |
| l3   | 22.0      |
| l4   | 28.0      |
| l5   | 34.0      |

`bucket_for_strength()` returns the highest band whose `min_db` threshold is met, or `None` if
below all thresholds.

Hysteresis and persistence logic is handled in `diagnostics_shared.severity_from_peak()`:

- `HYSTERESIS_DB = 2.0` — dB subtracted from active band threshold on decay check
- `PERSISTENCE_TICKS = 3` — ticks a new band must be seen before promotion
- `DECAY_TICKS = 5` — ticks below threshold before demotion

## JSONL Run Log Fields

The canonical field written to `.jsonl` run files is `vibration_strength_db` (dB).

### Current fields (v2 schema)

| Field | Type | Description |
|-------|------|-------------|
| `vibration_strength_db` | float | Canonical vibration strength (dB above noise floor) |
| `strength_bucket` | str \| null | Severity band key (`l1`–`l5`) or `null` |
| `top_peaks` | list | Top peaks: `[{hz, amp, vibration_strength_db, strength_bucket}]` |
| `dominant_freq_hz` | float | Frequency of dominant peak (Hz) |

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

The `spectrum_payload` and `selected_payload` endpoints include:

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

Live diagnostic events include:

```json
{
  "vibration_strength_db": 22.3,
  "key": "l3",
  "client_id": "001122334455"
}
```
