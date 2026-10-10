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
location's own noise floor next to it.

**One scale: the peak of a tone.** Every mg in the `diagnosis` block (the
location amplitudes, amplitude vs speed, the spectrum's peaks and floor, the
felt levels and the workshop limits) is the peak amplitude of a steady tone,
the three axes' peaks as a vector `sqrt(x^2 + y^2 + z^2)`: what a vibration
analyser reads, and the scale workshop limits and the simulator's injected
levels are on. The analysis reads levels on the combined spectrum (the three
axes' amplitudes averaged in power), as the RMS over a peak's band
(`PEAK_BANDWIDTH_HZ` either side). A Hann window puts a tone's power into its
equivalent noise bandwidth of 1.5 bins (Harris 1978), so a tone of vector peak
`A` reads there `A * sqrt(1.5 / (3 * 7))`, about `0.267 A`, at 800 Hz / 2048
samples (7 bins in the band). The mg shown is the level over that factor,
`level_g / tone_line_level_g(1, bin_hz) * 1000` (`_tone_mg` in
`analysis/diagnosis.py`; `tone_line_level_g` in `dsp/window_spectrum.py`,
checked against a synthesised tone in `tests/dsp/test_window_spectrum.py`: a
30 mg tone on one axis reads a level of 8 mg, and shows as 30 mg). A tone on
one axis shows its own peak; the same peak on every axis shows `sqrt(3)`
times it. dB above the floor and ratios between locations do not depend on
the scale. A broadband floor has no peak: the spectrum's floor line is put on
the same scale so the peaks stand out of it as on the spectrum.


- `location_amplitudes[].amplitude_mg`: the order's level at that location,
  read at its line in every window at the speeds it was heard
  (`Finding.sensor_levels[].level_g`; "Order-tracked reads" in
  `docs/order_tracking.md`): the median read while the order is there. A
  sensor whose median read does not stand three standard errors out of the
  floor's scatter beside its line reads 0, so a sensor the order does not
  reach reads 0 whatever road noise it carries (the report then says the
  order is measurable only at the strongest sensor); a sensor with under two
  independent reads over the drive has no row. A brake finding's level is
  read over the braking windows only.
  Without reads at every location that matched the order (no raw capture, or
  windows the replay could not rebuild), or with no location standing out, the
  median amplitude of the order's matched points at each location
  (`OrderMatchObservation.amp`); `None` where the order was not matched.
- `location_amplitudes[].db_above_floor`:
  `vibration_strength_db_scalar(peak_band_rms_amp_g=amplitude, floor_amp_g=floor)`,
  the floor being the median power beside the order's line at that location
  (`sensor_levels[].floor_g`) with reads, else the median floor of that
  location's samples.
- `location_amplitudes[].ratio_to_strongest`: amplitude / strongest amplitude.
- Rows run strongest first, except that the diagnosis's `location` leads when
  the strongest is less than `NEAR_TIE_DOMINANCE_THRESHOLD` (1.15x) above it:
  location scoring calls that a tie and names its own winner, so the findings,
  the amplitude table and the car diagram name the same location.
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

## What the driver feels

Nobody records a drive unless they feel a vibration, so the top causes are
ranked by what each one shakes where the occupants sit, and each is judged
against the levels workshops act on (`analysis/felt_ranking.py`, persisted as
`diagnosis.felt`).

**Felt reference.** The first of these sensor locations the run has order
levels at: driver seat, front passenger seat, rear left/centre/right seat,
trunk, propshaft tunnel. Workshops measure on the driver's seat track; the
trunk and tunnel are on the body behind and under the occupants. Wheel,
subframe, engine-bay and gearbox sensors sit on the source side of the
bushings and mounts that keep a vibration out of the body, so they are never
the reference. Without one (`fallback = "no_cabin_sensor"`), or without order
levels (`"no_order_levels"`: no raw capture to read them from), the ranking by
evidence stays.

**A cause's level there.** Each order's own level at the reference
(`Finding.sensor_levels[].level_g`, "Order-tracked reads" in
`docs/order_tracking.md`), counted only where its line carries at least the
power of the floor beside it (`level_g >= floor_g`, 3 dB); below, it is part
of the road's rumble there, or a body mode the line sweeps over reads as it.
On the benchmark (CI configuration, seeds 1-6) an order injected at a cabin
or trunk sensor reads 0.6-51x its floor there (19 in 20 over 3.2x), and a
line nothing was injected at there, where the reads hear it at all (a seat
mode or road hump under the line), 0.5-0.9x, 7 times in 1344 runs, never
over the bar (main: 1.2-23x and 2.3x; 0.4-1.5x, 44 times, 3 over the bar). The reference cannot tell one wheel from another, so a source
is one cause there: its orders (T1 and T2; a second corner's T1 is the same
line) add in power, `sqrt(sum level^2)`, since different frequencies do not
interfere over a window. Its best-ranked top cause stands for it.

**Share.** A cause's power over the summed power of the distinct order lines
of every measured cause heard at overlapping speeds (`heard_speed_range`). A
cause heard at 100-120 km/h and one at 40-60 km/h each explain all of what is
felt at their speeds.

**The causes the diagnosis keeps** (`diagnosis.felt`, `FeltAttribution`). The
felt block follows the diagnosis's attribution, so page 2 never weighs a cause
page 1 rules out:
- a source the diagnosis rules out (`source_checks` `ruled_out`: the neutral
  coast-down) is no felt cause;
- an order the coast-down put on another source counts as that source's (its
  findings are the diagnosis's);
- without measured RPM an engine order that turns with a wheel or propshaft
  order in top gear (`_road_alike`: E1 on T2 on the default car) is one
  spectral line read twice. It counts once, for the diagnosed source when it
  is one of the two, else for the cause ranked first by evidence; a cause left
  with no line of its own is not listed.
The ranking of the top causes (below) does not use this: it runs before the
diagnosis.

**Ranking.** With a reference, `TestRun.top_causes` are ordered by their
source's level there, strongest first; causes the reference does not measure
follow in their ranking by evidence; a Weak cause stays after every Strong or
Moderate one. Detection is unchanged: the same findings with the same
confidence levels. The diagnosed cause is the first actionable top cause, so
a cause the occupants feel more is named over one with better evidence that
they feel less.

**Workshop scale.** Workshop limits are peak readings on one axis of a
vibration analyser on the driver's seat track. `level_mg` is on the tone-peak
scale of every diagnosis mg (see "Diagnosis amplitude (mg)"): the vector sum
of the three axes' peaks, the most any one axis can carry at that level.
Comparing it with a one-axis limit is an ISO 2631-1 style vector sum against
that limit, and errs towards "workshop level" when the vibration is spread
over the axes. A source's `level_mg` adds its orders (T1 and T2) in power, so
it reads a little over the diagnosed order's `amplitude_mg` at the same
sensor.

**Workshop limits** (`WORKSHOP_LEVELS`; a starting point, to be calibrated on
real drives):

| Source | Workshop acts from | Normal up to | Basis |
|---|---|---|---|
| wheel/tire | 25 mg | - | GM bulletins 19-NA-240 and 20-NA-192 (NHTSA MC-10168200, MC-10181717): driver's seat track, 80-129 km/h after a 10 min warm-up; T1 on the Y axis consistently over 25 mg, service all wheel and tire assemblies (balance; road force under 30 lb front, 45 lb rear); under 25 mg, look elsewhere |
| driveline, brakes | 25 mg | - | No published limit: the wheel limit, an assumption |
| engine | 12 mg | 2 mg | GM rough-idle diagnosis: an engine order at the seat track of 12 mg or more points to the engine mounts, about 2 mg or less is normal; measured at idle, applied while driving as an assumption |

`severity`: `workshop` from the limit up, `normal` up to the normal level,
`below_workshop` in between; `null` where the reference does not measure the
cause.

**In the report.** Page 1 ("What you feel", also in History) says, for the
diagnosed cause, how much of what the test measured at the reference it
explains (nearly all from 90 %, most from 60 %, about half from 40 %, else
part) at its speeds, and
whether a workshop acts on that level; below the wheel limit it adds that a
workshop may find the wheels in balance and to ask for a road-force check. A
trunk or tunnel reference adds that it is not the seat workshops measure at.
A cause the reference does not measure "may not be what you feel"; without a
reference the report says it cannot tell. Page 2 lists every cause with its
`level_mg`, share, severity and limit. A no-fault run says nothing about it.
The wheel shop lines pair the limit with what a workshop then checks:
residual imbalance under 5 g per wheel, 3 g preferred (tire-shop practice;
balancers round to 5 g steps unless set to their fine mode), and road force
(GM: at most 18 lb on passenger P-metric tires; Volvo: at most 65 N / 15 lb
for a car with a vibration complaint, against 120 N in production).

To check on real drives: whether the GM limits are peak or RMS readings (the
bulletins do not say; peak is assumed); how the trunk relates to the seat
track (they are not the same point: a seat-mounted and a trunk sensor on the
same drive give the ratio); the driveline, brake and driving-engine limits.

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
the rate rescued to its best speed band, driving phase or location
(`_compute_effective_match_rate`); for an order whose tracked reads hear it
only while braking, the whole run is its braking windows at the sensors that
hear it where they hear it more often there (`heard_match_rate`, "What the
reads decide" in `docs/order_tracking.md`): brake judder has no windows
between stops to be heard in. An order under the minimum exists only
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
the raw capture and three or more sensors. A run where it found a loose
sensor also gets a warning row "Sensor mounting" in the run-suitability
checks (`SUITABILITY_CHECK_SENSOR_MOUNTS`, `loose_sensors`), so the quality
table never reads all OK above the warning. A run where it found none gets no
row: it may not have been checked. A run with no fault also names the loose
sensor in its page-1 verdict (report, History and PDF): "…; check its mount
and record again, because a loose sensor can hide a fault." Its verdict box is
amber, not green. A fault strongest
at a loose sensor is capped at Moderate and says so in its description instead.

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

## The live view and the report

The live view shows the same numbers the report gives, on the same scales,
but over the last few seconds instead of the whole drive:

- **mg.** Each sensor's spectrum carries `peak_mg`, its dominant peak's band
  RMS on the report's scale (`peak_amp_g / tone_line_level_g(1, bin_hz) *
  1000`, `build_spectrum_payload` in `apps/server/vibesensor/live/payload.py`):
  a steady tone reads its vector peak live as in the report (checked in
  `tests/live/test_processing_extended.py`). The chart draws each bin's
  amplitude times `sqrt(3)` (`AXES_AS_VECTOR` in `apps/ui/src/spectrum.ts`), so
  a tone's peak on the chart and its hover read the same mg; a broad hump
  reads lower on the chart than in `peak_mg`, whose band RMS spans it.
- **Strongest signal.** The overview ranks connected sensors by mg, the
  report's ranking, not by dB above each sensor's own floor (a quiet cabin
  sensor has a low floor and once read strongest on a healthy car while the
  report put it at 0.07x the wheels). It averages each sensor's mg in power
  over the last 5 s (`STRONGEST_AVERAGE_MS` in
  `apps/ui/src/pages/dashboard/dashboard_model.ts`) and, when the next sensor
  is within `NEAR_TIE_DOMINANCE_THRESHOLD` (1.15x, generated into
  `apps/ui/src/constants.ts`), says "About equal at n sensors" rather than
  naming one, as the report's location scoring calls that a tie. On simulated
  drives on a generated road a healthy car ties in 36-37 of 38 frames at 50,
  100 and 130 km/h, and a front-left wheel imbalance at 80-120 km/h names the
  front-left wheel in every frame; ranked per frame by dB, the strongest
  sensor changed from one frame to the next.
- **Order labels.** Each live order band carries the report's workshop label
  (`code`: T1, T2, P1, E1, E1.5, or `P1/E1` for the merged band;
  `workshop_order_code` in `apps/server/vibesensor/domain/finding.py`), and the
  spectrum shows it first ("T1 · Wheel 1x").
- **dB.** The live dB is the dominant peak over the band's overall P20 floor,
  as the report's no-fault amplitude table gives it. A fault's table reads the
  order's line over the floor beside it, so a wheel imbalance that reads
  34 dB live can read 6 dB there; compare the mg, not the dB.

What the live view cannot say: which order a peak belongs to. A healthy
wheel's wheel-hop hump (about 12 Hz) is the strongest peak on a real road and
falls inside the Wheel 1x or Wheel 2x band at some speeds, so a peak in a band
is not a finding; the report reads each order at its line across the drive
(see "Order-tracked reads" in `docs/order_tracking.md`).

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
  },
  "peak_mg": 153.6
}
```
