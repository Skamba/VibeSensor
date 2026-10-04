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

The implementation lives in `apps/server/vibesensor/dsp/vibration_strength.py`:

- `compute_vibration_strength_db()` — full pipeline (spectrum → peaks → dB metric)
- `vibration_strength_db_scalar()` — low-level scalar helper

No other module may re-implement this formula. Use `bucket_for_strength()` for severity
classification — never compare raw dB values against band thresholds inline.

For post-stop persisted analysis/report artifacts (`summarize_sensor_frames()` output,
persisted analysis envelopes, localized report-facing strength/intensity fields),
expose strength values in dB. Raw ingest/sample fields may still carry g-based
units.

## Diagnosis amplitude (mg)

Workshops compare vibration by amplitude per location (GM vibration worksheet,
PicoScope NVH), so the persisted `diagnosis` block reports amplitude at the
diagnosed order in **mg** (1 mg = 0.001 g), always with the dB above that
location's own noise floor next to it:

- `location_amplitudes[].amplitude_mg`: median amplitude of the order's matched
  points at that location (`OrderMatchObservation.amp`, g × 1000). `None` when
  the order was not detected there.
- `location_amplitudes[].db_above_floor`:
  `vibration_strength_db_scalar(peak_band_rms_amp_g=amplitude, floor_amp_g=median
  floor of that location's samples)`.
- `location_amplitudes[].ratio_to_strongest`: amplitude / strongest amplitude.
- With no diagnosed order (`amplitude_basis = "overall"`), each location reports
  the p95 of its dominant-peak amplitude (`strength_peak_amp_g`).
- `amplitude_vs_speed`: median order amplitude (mg) per 5 km/h speed bin and
  location; `spectrum.peaks`: median amplitude (mg) of peaks recurring in at
  least 20% of the strongest location's windows within ±5 km/h of the reference
  speed.

dB stays the strength metric for severity bands, live metrics, and every other
persisted field.

## Diagnosed order

The diagnosis names a source (wheel/tire, driveline, engine) and one of its
orders (T1/T2, P1/P2, E1/E2). Workshop advice depends on the order (balancing
fixes T1, not T2), so the label is the order that physically dominates, not the
one that ranked best: a harmonic often tracks a little more consistently than
its louder fundamental and outranks it.

`TestRun.diagnosis_order_finding` compares the source's 1st and 2nd order by
`Finding.level_over_db`: the median of `20·log10(amp_2 / amp_1)` over the
windows both orders matched (same sensor, same time), so both peaks come from
one spectrum and road-noise matches either order picked up elsewhere do not
count. Only the candidate's location counts when the two share at least 4
windows there; otherwise every location does.

- The 1st order is the label unless the 2nd is at least **3 dB** louder (1.4×
  the amplitude). A near-equal pair stays on the fundamental. On the
  simulator, a 4-cylinder engine's E2 sits about 9 dB above E1 and the 2nd
  order of a wheel or shaft imbalance 8–11 dB below its 1st, so both clear
  the margin by a wide gap.
- With fewer than 4 shared windows, or with no surfaced finding for the other
  order, the best-ranked order stays the label.
- The source and its confidence level stay those of the best-ranked order
  (the source's evidence); the amplitudes, frequency, and speeds shown are
  those of the labelled order.

## Confidence levels

Users see confidence only as one of three levels, defined by what to do
(`ConfidenceLevel` in `domain/finding_types.py`, derived by
`Finding.confidence_level` from the finding's internal 0–1 score):

| Level | Score | Meaning for the owner |
|-------|-------|-----------------------|
| Strong | ≥ 0.70 | Go fix it. |
| Moderate | ≥ 0.40 | Do the cheap confirming check first. |
| Weak | < 0.40 | Don't buy parts; record the test again. |

An order-tracked finding whose own amplitude is negligible (below
8 dB above the floor, i.e. road noise near an order) is capped just below
Moderate (0.39), after the corroboration and phase bonuses as well as before
them: a noise-level order is at most Weak, so on its own it reads as no fault,
and it cannot outrank a clearly louder order of another source. Only the
finding's own amplitude counts: the quiet sensors elsewhere on the car do not
cap a fault that is loud at its own corner. The score itself stays internal
(ranking); no percentage is shown in the UI or the PDF.

Where the vibration sits feeds the score of an order-tracked finding
(`analysis/orders/statistics.py::compute_order_confidence`), but how depends on
the source:

- **Wheel/tire** orders are diagnosed at a corner. Evidence spread evenly over
  the corners (no dominant corner) lowers the score: the localisation factor
  drops and the weak-separation penalty applies.
- **Engine and driveline** orders are diagnosed as a zone (engine bay, axle,
  centre tunnel), so the same order on the left and right is expected. When
  such an order shows no dominant corner and its own evidence is established,
  it scores like a wheel order at a clearly dominant corner, with no
  weak-separation penalty. Established means all of:
  - at least the moderate strength band (16 dB),
  - present in at least half of the possible windows,
  - a close frequency match (error score at least 0.5),
  - seen on at least two sensors,
  - and not an alias of a wheel order: fewer than half of its matched peaks
    were also matched by a wheel order.

  A faint or patchy engine/driveline match keeps the corner-dominance
  penalties. This is how a fault-free run's road noise near an engine order
  stays Weak (and so reads as no fault). The guards are tuned on the simulator.

Because wheel and engine scores follow different location rules, a score
comparison does not decide whether an engine order on a wheel harmonic belongs to
the wheel when its RPM is estimated; their amplitudes do (step 8 in
`docs/order_tracking.md`).

## Processing profiles

Filtering choices are explicit because live display smoothing must not silently
change report or forensic diagnostics.

| Profile | Owner | Filter chain | Use |
|---------|-------|--------------|-----|
| `live_display` | `apps/server/vibesensor/live/compute.py` | `median_3_sample_time_domain` | Operator-facing live metrics and spectra. |
| `diagnostic_raw` | post-run raw replay and dense raw-window stages | none | Report/post-run truth when raw capture is available. |
| `diagnostic_filtered` | persisted-summary fallback or optional comparisons | `median_3_sample_time_domain` | Clearly labeled fallback/comparison data, not raw truth. |

The shared identifiers live in
`apps/server/vibesensor/live/processing_profile.py`. Live combined
metrics carry `processing_profile = "live_display"` and their filter chain.
Persisted analysis metadata records the active diagnostic `processing_profile`,
available profile rows, the live filter chain, the diagnostic filter chain, and
whether raw diagnostic evidence was preserved.

Raw replay uses unfiltered raw windows for diagnostic
strength/spectrum computation. If no raw-backed replay is available, report
metadata marks the active profile as `diagnostic_filtered` so downstream report
code can treat summary-derived evidence as a fallback instead of raw evidence.

## Severity Bands (l1–l5)

Severity classification is performed solely by `bucket_for_strength(vibration_strength_db)` in
`apps/server/vibesensor/dsp/strength_bands.py`.

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

Runtime history stores sample metrics in SQLite `samples_v2` typed columns
with the `SensorFrame` field names. See `docs/history_db_schema.md` for the DB
schema. This section lists only metric fields, not the full persistence schema.

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

The following fields were removed to eliminate ambiguity. They are no longer written or read:

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
