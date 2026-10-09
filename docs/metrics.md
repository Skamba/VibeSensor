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

### Peak local floor

Each peak in `top_peaks` also carries `local_floor_amp_g`: the median of the
floor bins (the spectrum without the bins within `PEAK_SEPARATION_HZ` of the
`top_n` strongest candidates) within `LOCAL_FLOOR_HALF_WIDTH_HZ` (5 Hz) of the
peak; where peaks crowd that whole neighbourhood, the median of every bin
there. It is what the peak stands out from where it sits, the reference an
ordered-statistic CFAR detector uses (Rohling, *IEEE Trans. AES* 19(4), 1983).
`vibration_strength_db` and the severity bands stay over the band's overall
floor; only the unexplained-vibration judgment uses the local floor.

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

- `location_amplitudes[].amplitude_mg`: the order's level at that location,
  read at its line in every window at the speeds it was heard
  (`Finding.sensor_levels[].level_g`, g × 1000; "Order-tracked reads" in
  `docs/order_tracking.md`). A sensor whose mean read does not stand two
  standard errors out of its reads' own scatter reads 0, so a sensor the
  order does not reach reads 0 whatever road noise it carries (the report
  then says the order is measurable only at the strongest sensor). A brake
  finding's level is read over the braking windows only.
  Without reads at every location that matched the order (no raw capture, or
  windows the replay could not rebuild), or with no location standing out, the
  median amplitude of the order's matched points at each location
  (`OrderMatchObservation.amp`); `None` where the order was not matched.
- `location_amplitudes[].db_above_floor`:
  `vibration_strength_db_scalar(peak_band_rms_amp_g=amplitude, floor_amp_g=floor)`,
  the floor being the mean power beside the order's line at that location
  (`sensor_levels[].floor_g`) with reads, else the median floor of that
  location's samples.
- `location_amplitudes[].ratio_to_strongest`: amplitude / strongest amplitude.
- With no diagnosed order (`amplitude_basis = "overall"`), each location reports
  the p95 of its dominant-peak amplitude (`strength_peak_amp_g`).
- `unexplained_vibration`: a no-fault run with no candidate where, at some
  location, the p95 over its windows of the window's most prominent peak
  reaches the elevated strength band (L3, 26 dB). A peak's prominence is its
  dB over its own `local_floor_amp_g` (see "Peak local floor"), not over the
  band's overall floor: on a real road a wheel sensor rings the wheel hop
  (about 12 Hz) as a hump 30-37 dB over the band's overall floor on every
  healthy car, and a hump is the background of the peaks on it, not a shake to
  explain. No checked order explains a flagged vibration, so the report and
  the UI say a vibration was found but not tied to a cause, never "No
  significant vibration found". Benchmark p95 prominences: about 10 dB on the
  idealised smooth road, 16 dB with a healthy car's residual wheel imbalance or
  a seat mode, 13-16 dB for a healthy car on a generated ISO 8608 road (33-37 dB
  over the overall floor); a 13 Hz body resonance (29 dB), an EV motor order
  with no ratio entered (37 dB) or fixed body resonances (38 dB) are above.
- `amplitude_vs_speed`: median order amplitude (mg) per 5 km/h speed bin and
  location; `spectrum.peaks`: median amplitude (mg) of peaks recurring in at
  least 20% of the strongest location's windows within ±5 km/h of the reference
  speed.

dB stays the strength metric for severity bands, live metrics, and every other
persisted field.

## Diagnosed order

The diagnosis names a source (wheel/tire, driveline, engine) and one of its
orders (T1/T2, P1/P2, E1 and the engine profile's firing order, e.g. E1.5,
E2, E3). Workshop advice depends on the order (balancing fixes T1, not T2), so
the label is the order that physically dominates, not the one that ranked
best: a harmonic often tracks a little more consistently than its louder
fundamental and outranks it, and two orders whose confidence both saturate
rank on a coin toss.

`TestRun.diagnosis_order_finding` compares the candidate with the source's
best other order (a lower and a higher order) by `Finding.level_over_db`: the
median of `20·log10(amp_higher / amp_lower)` over the
windows both orders matched (same sensor, same time) and at least one of them
is heard (see "Heard matches" in `docs/order_tracking.md`), so both peaks come
from one spectrum, road-noise matches either order picked up elsewhere do not
count, and neither do windows that pair two floor-level noise peaks. Only the
candidate's location counts when the two share at least 4 such windows there;
otherwise every location does.

- The lower order is the label unless the higher is at least **3 dB** louder
  (1.4× the amplitude). A near-equal pair stays on the lower order. On the
  simulator, a 4-cylinder engine's E2 sits about 9 dB above E1, an inline-3's
  E1.5 about 8 dB above E1, and the 2nd order of a wheel or shaft imbalance
  8–11 dB below its 1st, so all clear the margin by a wide gap.
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
  on a second sensor, and is the product of five ramps:
  - how clearly a second sensor hears it (the graded corroboration count,
    `OrderMatchAccumulator.corroboration`): none while no other sensor is
    clear of the floor at least half as often as the clearest one (the bar
    for hearing it at all, see "Heard matches" in `docs/order_tracking.md`),
    full from 60 %. One sensor is a point, not a zone, so this stays a gate:
    the credit is 0 without a second hearing sensor,
  - how often it is heard (see "Heard matches" in `docs/order_tracking.md`):
    none at 40 % of the possible windows at the sensors that hear it, full
    at 50 %. Road noise that happens to sit on the order's frequency does
    not count; a measured speed predicts the order exactly in every window,
    so such chance matches are common on a rough road,
  - how closely it is on frequency: none at error score 0.5, full at 0.6,
  - that it is not an alias of a wheel order: full while under 40 % of its
    matched peaks were also matched by a wheel order, none from 50 %.
    For a driveline order, and an engine order placed by top-gear RPM, it
    also counts the wheel's 3rd to 6th orders where they sit at exact
    multiples of a heard T1 peak in the same spectrum (within the line width
    times the multiple plus one; `OrderAnalysisSession._wheel_harmonic_peaks`,
    `is_harmonic_of`): a parking flat spot or a non-uniform tyre shakes at the
    whole comb of wheel orders, and on a car whose E2 runs at about 4 per
    wheel turn and propshaft at about 3 these used to read as a Strong engine
    or Moderate driveline fault on a healthy car. A driveline or engine fault
    beside a wheel imbalance stays clear unless it sits on an exact harmonic.
    A driveline order with half or more of its peaks on the comb is dropped
    (`OrderAnalysisSession`): it turns locked to the wheel's rhythm, so
    nothing of it is its own. With the credit alone it stayed within 0.03 of
    the wheel order on the default car's flat-spot drives, and tyres a little
    apart in wear and pressure tipped it over.
    An engine order on measured RPM is not judged by the comb: it leaves it
    in any other gear, and a four-stroke's half order can turn once per
    wheel turn (E1 at twice the wheel's rhythm), so its own E0.5/E1/E2 would
    look like T1/T2/T4; the neutral coast-down decides there. T2 cannot stand
    in for T1 for the same reason, so below about 38 km/h, where T1 is under
    the lowest frequency analysed (5 Hz), the comb is not recognised: a
    town-only first drive on flat-spotted tyres can still read as a
    propshaft or engine fault on such a car (an open limit; the benchmark
    runs that drive only on a car whose orders miss the comb; the guided
    drive asks for a tire warm-up before recording for this reason,
    [user_journeys.md](user_journeys.md) §3.6),
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
| Run-wide heard match rate just over the minimum | the finding is at most Weak (0.39) | the next 0.15 of match rate (`_presence_cap`) |
| Second / third sensor's share of the clearest sensor's clear windows past 0.5 (the heard bar) | zone credit none → full; corroboration bonus ×1 → ×1.04 → ×1.08 | 0.5–0.6 per sensor (`_corroboration`) |
| A phase's match rate past the minimum match rate (with at least 3 matches) | phase bonus ×1 → ×1.03 → ×1.06 | the next 0.10 of match rate (`compute_phase_stats`) |

The presence cap reads the order's heard match rate over the whole run, not
the rate rescued to its best speed band or location
(`_compute_effective_match_rate`). An order under the minimum exists only
through that rescue; it is heard less often than "just often enough", so it
is at most Weak. Judged on the rescued rate, the score fell from Strong to
Weak as the run-wide rate rose past the minimum: on the benchmark matrix an
E3 order rescued to 0.80 from a run-wide 0.240 scored 0.86, and the same
order at 0.25 run-wide would have been capped at 0.39. Every rescued finding
the matrix scored Moderate or Strong was a secondary order that was not the
diagnosis.

The amplitude of an order under twice the MEMS noise floor (2 mg) no longer
caps its SNR term at 0.40: the floor is clamped at 1 mg, so such an order
reads at most 6 dB and the negligible cap above already holds it at Weak;
the separate cap moved the SNR term by at most 0.04 (0.008 of the score).

Some gates stay steps, because their input is a count or a categorical
judgement, or because no score depends on where they sit:

- Below the minimum match rate, or with a tracking slope under 0.5 (step 4
  in `docs/order_tracking.md`), there is no finding. The presence cap above
  bounds what passing the minimum match rate adds, or what a rescue to the
  best speed band or location adds below it (at most a Weak finding either
  way); the slope needs no cap, because an order that barely tracks speed is
  already off frequency and scores low on the frequency error.
- Counts: the number of connected sensors (`_few_sensor_scale`), at least 3
  matches for a phase to count (braking counts as one phase with
  deceleration), and which sensors hear an order at all (the heard bar
  itself, a classification every metric shares). The graded inputs built on
  them ramp (table above).
- Alias suppression (×0.6 for an engine order ranking below the best wheel
  order, `suppress_engine_aliases`): a choice between two explanations of the
  same peaks, so their ranking scores often tie to within a few per cent and
  the side of the tie is the evidence. On the benchmark matrix all 18 engine
  orders within 5 % of the tie in wheel-fault runs are suppressed, and 20 of
  27 in engine-fault runs are kept (the other 7 runs still diagnose the
  engine). A ramp there would leave the alias half-suppressed.
- The sample count saturates (×0.70 + 0.30 × matched/20) and is already
  continuous.
- Categorical outcomes on top of the score: whether a hotspot is weakly
  separated (the "spread across locations" reason, which keeps a wheel fault
  at most Moderate, and the faint wheel residual that reads as no fault),
  which zone or corner is named, a brake judder or fixed-tone verdict, a
  non-order peak's type (baseline noise, transient, persistent), and the
  weak reasons listed (intermittent under 50 % presence, a matched speed
  range under 10 km/h). Each is a statement shown to the owner, so it has
  one edge; the scores underneath them ramp, so on either side of such an
  edge the score differs by only a little and only the label or level cap
  changes.
- Score thresholds: the levels themselves (0.40, 0.70), surfacing (0.25),
  an order finding claiming its peaks from the non-order peak list (0.40),
  and the per-location split of a wheel finding with a second corner within
  2× dominance (the split-off corner scores the main finding ÷ dominance, at
  most half of it at the edge, far under the 15-point drop-off for a second
  top cause).

A non-order peak finding's caps ramp the same way (`_compute_peak_confidence`
in `analysis/peaks/scoring.py`): the cap for a peak spread over the sensors
(0.35 up to a spatial concentration of 0.35) lifts over 0.35–0.45, and the
negligible cap (0.40 under 8 dB) over 8–12 dB, as for orders.

Because wheel and engine scores follow different location rules, a score
comparison does not decide whether an engine order on a wheel harmonic belongs to
the wheel when its RPM is estimated, or whether an engine tone spread over the
car outweighs a wheel order at a dominant corner; their amplitudes do (step 8 in
`docs/order_tracking.md`).

## Loose-mount check

`analysis/mount_tilt.py` warns when a sensor's reading of gravity turned on
its own during the drive: "The <location> sensor may be loosely mounted;
check its mount and record again" (run-quality warning `sensor_loose_mount`,
in the report, History and PDF). A firmly fixed sensor turns only with the
part it sits on, and so with the car; a sensor that sagged on loose ties or
tipped off a pad reads the same car turned by an angle of its own. It needs
the raw capture and three or more sensors.

1. Each replayed raw window's mean per axis is that window's 0 Hz reading:
   gravity plus the car's own acceleration (`RawReplayWindowCoverage.mean_xyz`).
   Windows below 25 km/h are left out: a car parking may steer its front
   wheels to full lock (about 35°), which tilts a front knuckle about 8.5°.
2. Each sensor's windows are averaged (as unit vectors) per 5 s stretch of the
   drive (longer on a drive over 20 minutes, so at most 240 stretches).
3. For every pair of stretches, each sensor's reading turned by some angle;
   the median of the other sensors' angles is how far the car's own reading
   turned. Only pairs where it turned 10° or less are compared: the car's
   acceleration changed by under tan 10° = 0.18 g (or the road's grade by
   under 18 %).
4. A sensor whose angle exceeds the others' median by 8° or more in some pair
   is flagged.

The threshold sits over what a firm sensor reads anyway, between two
stretches the check compares:

| Unshared turn | Worst case | Basis |
|---------------|------------|-------|
| Body against wheel carrier | 1.2° | roll 6.6°/g (or pitch 3°/g) × 0.18 g (`docs/simulator_realism.md`, "Body attitude") |
| A front carrier steered at 25 km/h or more | 1.5° | at 0.18 g and 25 km/h the bend's radius is 27 m: 6° of steer plus understeer about a steering axis 14° from vertical tilts the carrier 6.2° × sin 14° |
| Offset drift as the sensor warms by 40 °C | 1.9° | ADXL345 0 g offset drift ±0.4 mg/°C (x, y) and ±1.2 mg/°C (z) (ADI PCN 10_0327, Rev. B die); the part across gravity at a 30° mounting is about 33 mg |
| The other sensors' median off by its own errors | 1.9° | the same drift on the others |
| Sum | 5.5° | |

8° is about 1.5 times that sum. A sensor that tipped 14° (an adhesive pad
letting go at one corner, `bench-*-pad-lets-go-*`) reads 14°; on every healthy
bench drive (bends, firm stops, 8 % hills, city) no sensor reads over 1°.
Rows thinned by the post-analysis loader still count: each stretch needs two
windows per sensor.

The diagnosis treats a cause felt strongest at a flagged sensor as resting on
that sensor (weak reason `loose_mount`): never Strong, as for a cause spread
over the locations.

Not covered: engine torque roll of a sensor on the engine or gearbox (a few
degrees on soft mounts under full load in top gear) is not modelled; a drive
with fewer than three sensors, or without raw capture, gets no check. The
check costs 1-4 ms per bench drive on x86 (5-12 sensors, 400-2600 rows) and
about 60 ms for an hour's 12,000 rows; each window's mean adds about 1 % to
the raw replay's spectrum work.

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
| `top_peaks` | list | Up to 8 combined-spectrum peaks: `[{hz, amp, vibration_strength_db, strength_bucket, local_floor_amp_g}]` (`local_floor_amp_g` absent in runs recorded before it existed); `hz` is the vertex of a parabola through the log amplitudes of the peak bin and its neighbours, within a few hundredths of a bin of a steady tone under the Hann window |
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
