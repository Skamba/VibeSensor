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

For post-stop persisted analysis/report artifacts (`analysis_result_to_summary()` output,
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
- `unexplained_vibration`: a no-fault run with no candidate where some
  location's p95 `db_above_floor` reaches the elevated strength band (L3,
  26 dB). No checked order explains that vibration, so the report and the UI
  say a vibration was found but not tied to a cause, never "No significant
  vibration found". The p95 of each window's strongest peak sits about 10 dB
  over the floor on a smooth road and around 20 dB with a healthy car's
  residual wheel imbalance (benchmark); a body resonance (37 dB) or an EV
  motor order with no ratio entered (36 dB) is well above.
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

An order-tracked finding's own amplitude bounds its score, by two ramps
(`_strength_cap`, `_light_strength_factor` in `analysis/orders/statistics.py`):

- Negligible (below 8 dB above the floor, i.e. road noise near an order): the
  score is capped just below Moderate (0.39), after the corroboration and
  phase bonuses as well as before them, so a noise-level order is at most
  Weak, reads as no fault on its own, and cannot outrank a clearly louder
  order of another source. The cap lifts linearly over 8–12 dB.
- Light (below 16 dB): the score is scaled by 0.8. The penalty eases out
  linearly over 16–19 dB.

Both ramps start at their band's edge, so under 8 dB an order stays at most
Weak and under 16 dB strength alone never makes it Strong, while half a dB
over an edge moves the score a few hundredths rather than doubling it. Only the
finding's own amplitude counts: the quiet sensors elsewhere on the car do not
cap a fault that is loud at its own corner. That amplitude is the mean of the
order's heard matches (see "Heard matches" in `docs/order_tracking.md`), not
an average with the floor-level noise the matcher picks up elsewhere. The score itself stays internal
(ranking); no percentage is shown in the UI or the PDF.

Where the vibration sits feeds the score of an order-tracked finding
(`analysis/orders/statistics.py::compute_order_confidence`), but how depends on
the source:

- **Wheel/tire** orders are diagnosed at a corner. Evidence spread evenly over
  the corners (no dominant corner) lowers the score: the localisation factor
  drops and the weak-separation penalty applies (×0.70 when the corners are
  even, dominance under 1.05; ×0.80 above; ×0.90 for a clear cabin hotspot,
  dominance 1.5 and up, when no wheel sensor is fitted). When the
  per-location match rates already pin the order to one corner
  (`apply_localization_override`), the hotspot counts as separated at any
  dominance and takes none of this penalty, so a clearer corner never scores
  lower.
- **Engine and driveline** orders are diagnosed as a zone (engine bay, axle,
  centre tunnel), so the same order on the left and right is expected. When
  such an order shows no dominant corner and its own evidence is established,
  it scores like a wheel order at a clearly dominant corner, with no
  weak-separation penalty. The credit (`_zone_credit`) needs the order heard
  on at least two sensors, and is then the product of four ramps:
  - how often it is heard (see "Heard matches" in `docs/order_tracking.md`):
    none at 40 % of the possible windows at the sensors that hear it, full
    at 50 %. Road noise that happens to sit on the order's frequency does
    not count; a measured speed predicts the order exactly in every window,
    so such chance matches are common on a rough road,
  - how closely it is on frequency: none at error score 0.5, full at 0.6,
  - that it is not an alias of a wheel order: full while under 40 % of its
    matched peaks were also matched by a wheel order, none from 50 %,
  - its strength: none at 13 dB, full at 19 dB, across the moderate band's
    edge (16 dB). Together with the light ramp this replaces a step at
    16 dB that more than doubled a faint engine tone's score (0.40 at
    15.9 dB, 0.91 at 16.0 dB on the faint-engine benchmark case; 0.55 and
    0.91 at 16 and 19 dB now).

  A faint, patchy, off-frequency or wheel-aliased engine/driveline match
  keeps the corner-dominance penalties. This is how a fault-free run's road
  noise near an engine order stays Weak (and so reads as no fault). The
  guards are tuned on the simulator.

Every graded input of the score ramps over a short band past its old step
edge instead of switching a penalty fully on or off there, so a small change
of the input moves the score a few hundredths. Each ramp starts at the old
edge on the cautious side: the old penalty region keeps its full penalty and
the penalty eases out beyond it.

| Input | Penalty or limit | Eases out over |
|-------|------------------|----------------|
| Dominance past the weak-separation threshold (1.2 × (1 + 0.1 × (locations − 2))) | the spread penalty above | the next 0.15 of dominance (`_spatial_weakness`) |
| Dominance past 1.05 (even corners) | ×0.70 → ×0.80 | 1.05–1.15 |
| Dominance past 1.5 without wheel sensors | ×0.80 → ×0.90 | 1.5–1.65 |
| Speed stddev / range past the steady limits (2 km/h, 8 km/h) | ×0.82 | 2–3 km/h stddev, 8–12 km/h range (`speed_steadiness`) |
| Speed stddev past the constant limit (0.5 km/h) | ×0.75, tracking correlation not counted, minimum match rate 0.55 instead of 0.25 | 0.5–1.0 km/h (`speed_constancy`, `order_min_match_rate`) |
| Diffuse excitation (wheel orders: similar match rates and amplitudes at every sensor) | ×0.85 − 0.04 per sensor, at least ×0.65 | amplitude ratio 2–3, match-rate range 0.15–0.30, mean match rate 0.15 down to 0.05 (`detect_diffuse_excitation`) |
| Localisation claimed with one or two sensors | ×0.85 / ×0.92 from localisation 0.30 | eases in from the 0.05 floor (`_few_sensor_scale`) |
| Effective match rate just over the minimum | the finding is at most Weak (0.39) | the next 0.15 of match rate (`_presence_cap`) |

Some gates stay steps, because their input is a count or a categorical
judgement, or because no score depends on where they sit:

- Below the minimum match rate, or with a tracking slope under 0.5 (step 4
  in `docs/order_tracking.md`), there is no finding. The presence cap above
  bounds what passing the minimum match rate adds (at most a Weak finding);
  the slope needs no cap, because an order that barely tracks speed is
  already off frequency and scores low on the frequency error.
- Sensor counts: the zone credit's two heard sensors, the corroboration
  bonus (×1.04 at two sensors, ×1.08 at three) and the phase bonus (×1.03,
  ×1.06; braking counts as one phase with deceleration). One heard sensor is a point, not a zone; on the benchmark matrix
  no zone-source order heard at one sensor has evidence that would earn
  credit, so the step never acts there. The bonuses move a score by at most
  0.04 per count.
- Alias suppression (×0.6 for an engine order ranking below the best wheel
  order, `suppress_engine_aliases`): a choice between two explanations of the
  same peaks, so their ranking scores often tie to within a few per cent and
  the side of the tie is the evidence. On the benchmark matrix all 18 engine
  orders within 5 % of the tie in wheel-fault runs are suppressed, and 20 of
  27 in engine-fault runs are kept (the other 7 runs still diagnose the
  engine). A ramp there would leave the alias half-suppressed.
- The sample count saturates (×0.70 + 0.30 × matched/20) and is already
  continuous.

Because wheel and engine scores follow different location rules, a score
comparison does not decide whether an engine order on a wheel harmonic belongs to
the wheel when its RPM is estimated, or whether an engine tone spread over the
car outweighs a wheel order at a dominant corner; their amplitudes do (step 8 in
`docs/order_tracking.md`).

## One spectrum definition

The live tick (`apps/server/vibesensor/live/compute.py`) and the post-stop raw
replay compute a block's spectrum the same way: no time-domain filter, the
per-axis mean removed, a Hann window, then the shared strength and noise-floor
metrics. A run's rows mix the two (a sensor that lost frames keeps its stored
live rows where the replay has no complete window), so a filter on one path
only would put that sensor's floor apart from the others'. A 3-sample median
filter on the live path once did: it lowered a lossy sensor's floor by about
2 dB and raised its strength above floor as much.

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
