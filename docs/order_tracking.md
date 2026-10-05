# Order Tracking

Scope: shared order-reference math and the post-stop order-analysis flow.

VibeSensor uses the same vehicle-order reference model in two places:

- live telemetry, where the server precomputes order bands for spectrum views
- post-stop diagnostics, where the summary analysis matches each run's sample
  peaks (recomputed from raw capture when it is available) against the
  predicted wheel / driveshaft / engine order bands

The shared physics lives in `apps/server/vibesensor/domain/order_reference.py`
and `apps/server/vibesensor/dsp/order_bands.py`. The post-stop finding flow
lives in `apps/server/vibesensor/analysis/orders/`.

## Core concepts

| Concept | Owner | Purpose |
|---------|-------|---------|
| `OrderReferenceSpec` | `domain/order_reference.py` | Tire geometry, final-drive ratio, gear ratio, and uncertainty settings for order analysis. |
| `vehicle_orders_hz()` | `dsp/order_bands.py` | Resolve wheel / driveshaft / engine reference frequencies for one speed sample. |
| `build_order_bands()` | `dsp/order_bands.py` | Precompute live order-band payloads so the frontend does not duplicate tolerance math. |
| `OrderHypothesis` | `analysis/orders/physics.py` | One named order candidate such as `wheel_1x` or `engine_2x`. |
| `OrderAnalysisSession` | `analysis/orders/pipeline.py` | Sample-peak order pass used by the summary analysis. |

## From speed to reference frequencies

`OrderReferenceSpec` turns vehicle speed plus car-reference data into rotational
frequencies:

```text
wheel_hz      = speed_mps / tire_circumference_m
driveshaft_hz = wheel_hz * final_drive_ratio
engine_hz     = driveshaft_hz * current_gear_ratio
```

The spec exposes capability checks before any of that math is used:

- `supports_wheel_reference`
- `supports_driveshaft_reference`
- `supports_engine_reference`

If the required tire or driveline data is missing, VibeSensor omits the order
reference instead of inventing one.

## Uncertainty and tolerance bands

Order matching is not based on a single exact frequency bin. Post-run
diagnostics and the live spectrum use one tolerance model,
`order_peak_tolerance_hz()` in `dsp/order_bands.py`, so a peak drawn inside a
live band is a peak the report counts as an order match:

```text
tolerance_hz = max(ORDER_TOLERANCE_MIN_HZ, predicted_hz * ORDER_TOLERANCE_REL * sqrt(path_compliance))
             = max(0.5 Hz, predicted_hz * 8% * sqrt(path_compliance))
```

`path_compliance` is 1.5 for wheel orders (tire, hub and bushings broaden the
peak, about ±9.8%) and 1.0 for driveshaft and engine orders (±8%).

Each order family needs only its own references: wheel orders need speed and
the tire size, driveshaft orders add the final drive, and engine orders come
from fresh measured OBD-II RPM or, without it, from the final drive and top gear
(an estimate that assumes top gear). A car reference has no default: a missing
one blanks only its own family live and makes that source "not testable" in the
diagnosis.

`build_order_bands()` emits the live band payloads for the families present,
with `tolerance = tolerance_hz / center_hz`, so the UI draws
`[center_hz * (1 - tolerance), center_hz * (1 + tolerance)]`:

- `wheel_1x`
- `wheel_2x`
- `driveshaft_1x` or merged `driveshaft_engine_1x`
- `engine_1x` when it does not overlap driveshaft
- `engine_2x`

`OrderReferenceSpec` still combines reference uncertainty in stages (wheel =
speed + tire diameter; driveshaft adds final drive; engine adds gear). That
combined uncertainty decides when the driveshaft and engine 1x bands collapse
into `driveshaft_engine_1x`; it no longer widens the bands.

## Post-stop hypothesis testing

Diagnostics does not search an open-ended order space. It evaluates a fixed
catalog of hypotheses from `orders/physics.py`:

- wheel 1x / 2x
- driveshaft 1x / 2x
- engine 1x / 2x

Each `OrderHypothesis` carries:

- a stable `key`
- the suspected `VibrationSource`
- the base order family (`wheel`, `driveshaft`, or `engine`)
- harmonic multiplier (`1` or `2`)
- `path_compliance`, which widens tolerance for softer transmission paths such
  as wheel/tire vibration traveling through suspension and bushings

For the compact summary compatibility path, `OrderAnalysisSession.analyze()`
coordinates the evidence flow:

1. Skip hypotheses that do not have enough reference data (`_should_test()`).
2. Use `match_samples_for_hypothesis()` to compare predicted order bands against
   the stored sample peaks.
3. Use `_compute_effective_match_rate()` to rescue or focus the evidence around
   the best speed band or dominant location. It starts from the match rate at
   the sensors that hear the order (see "Heard matches" below).
4. Reject matches that do not follow the prediction. As speed changes, an
   order's peaks move one-for-one with its predicted frequency; a fixed
   resonance (body mode, engine idle) that the prediction sweeps past stays
   at one frequency, yet falls inside the tolerance band over a speed range.
   `frequency_tracking_slope()` (`domain/order_match.py`) takes the robust
   (Theil–Sen) slope of matched vs predicted Hz over the heard matches; below
   `MIN_ORDER_TRACKING_SLOPE` (0.5) the hypothesis produces no finding. On
   the simulator real orders score 0.8–1.3 and a 13 Hz body resonance crossed
   by T1 scores 0.0. It is only judged when the run's speed really changed
   (`trend_moves()`: the 2 s-median speed trend moves by at least 10 % and by
   more than twice the spread inside a 2 s bin). At a steady speed an order
   and a fixed tone look the same, and speed-reading noise would flatten the
   slope.
5. Score the surviving evidence with `score_order_finding()`. The location
   comes from the 10 km/h speed bin whose matches carry the most order
   amplitude in total (mean amplitude × matches), so a short stretch at
   speeds the rest of the drive did not reach cannot outvote the bins that
   hold most of the evidence. Location terms are source-aware: an engine/driveline order with no dominant corner is
   not penalised for it once its own evidence is established, unless it
   shares most of its peaks with a wheel order (see "Confidence levels" in
   `docs/metrics.md`).
6. Assemble a domain `Finding` with `assemble_order_finding()`.
7. Split multi-location wheel findings when two corners are both strong.
8. Apply `suppress_engine_aliases()` before returning the final ranked list.
   An engine order that ranks below the best wheel order and is not clearly
   more confident than it is demoted as a likely alias. An engine order placed
   by RPM estimated from speed and gear that mostly lands on a wheel order's
   peaks has no frequency of its own: it is a fixed multiple of the wheel's
   (on a car whose top gear puts E1 on T2). When a wheel order is at least
   6 dB louder than it at the wheel's corner (median over the windows both
   matched there), it is that wheel's harmonic and is demoted whatever its
   confidence. An engine fault does not excite the wheel's own orders, and the
   wheel order it coincides with is as loud as it is. Confidence cannot settle
   this case, because the wheel order is penalised for spreading into the
   cabin and the engine zone is not. With measured RPM the engine order keeps
   its own frequency track and that rule does not apply.
   The same holds for an engine order with no dominant location, at any
   frequency: it is spared the spread penalty a wheel order takes, so it is
   compared with each wheel order that has a dominant corner by level. When
   that wheel order is at least 9 dB louder than it at the wheel's corner,
   the engine tone the whole car shares is demoted. The margin is wider than the 6 dB above because peak
   levels read on a speed sweep favour the slower-moving lower order by a few
   dB.

If the effective match rate stays below the current threshold, the hypothesis
does not produce a finding.

Ranking decides the diagnosed source; it does not decide which of that
source's orders the diagnosis names. `TestRun.diagnosis_order_finding` labels
the source's louder order, comparing 1x and 2x amplitudes in the windows both
matched (see "Diagnosed order" in `docs/metrics.md`).

## Heard matches

The matcher (`match_samples_for_hypothesis()`) takes the nearest peak in the
tolerance band whatever its level, so it also lands on floor-level road noise
at every sensor and in the windows an order is absent. It classifies each match
once, and every metric below reads that classification
(`OrderMatchObservation.heard`) instead of applying its own floor filter.

A match is **heard** when both hold:

- its peak is at least 6 dB (2×, `heard_peak_over_floor`) over the floor of
  the window it was read from (`strength_floor_amp_g`, the same spectrum), and
- it is at a sensor that hears the order: one where the order's peak clears
  that bar at least half as often (`heard_location_min_share`) as at the
  sensor where it clears it most often (`OrderMatchAccumulator.heard_locations`).
  A vibration fades with distance from its source, so an engine tone only the
  front sensors hear is not diluted by the rear ones.

An order heard nowhere keeps all its matches as evidence (`evidence`,
`heard_match_rate`), so a faint order is judged on what there is rather than
dropped. The persisted `matched_points[].heard` carries the flag to the
diagnosis.

| Consumer | Reads |
|----------|-------|
| Match rate the effective rate starts from (`pipeline.py`) | matches / possible windows at the heard sensors (`heard_match_rate`) |
| Score strength, frequency error, tracking correlation, sample count (`scoring.py`, `compute_amplitude_and_error_stats()`) | heard matches only (`evidence`) |
| Corroborating sensors (`scoring.py`) | the heard sensors |
| Zone evidence rate (`_zone_evidence_established()`) | effective match rate × the share of matches at the heard sensors that are heard (`heard_share`) |
| Tracking slope (step 4) | heard matches |
| `presence_ratio`, per-location `presence` (`analysis/diagnosis.py`) | heard matches over the moving samples |
| Coast-down `speed_dependence`: the order's main location and the matches counted during and outside the coast-down | heard matches |
| Matched speed range (`speed_min_kmh` / `speed_max_kmh`) | heard matches (all, when none is heard) |

Why 6 dB over the window's floor: on the full benchmark matrix (40 cases, both
cars, seeds 1–6, and the healthy cases on seeds 7–26) this one rule gives the
same verdicts as the per-metric filters it replaced, which were 6 dB over the
window floor for the score and 8 dB over the run's median floor for presence and
the coast-down. Raising the shared bar to 8 dB over the window floor turned the
every-mount healthy sweep into a Moderate wheel fault on two seeds. The window
floor is measured on the same spectrum as the peak, so it follows road and
speed changes the run median does not. The 8 dB negligible cap in
`docs/metrics.md` is a different role: it caps a finding whose heard level is
noise-like, not which matches count.

## Live vs post-stop reuse

The same reference math serves both runtime and diagnostics:

- live telemetry calls `vehicle_orders_hz()` and `build_order_bands()` so the
  UI can annotate the current spectrum without duplicating the formulas
- the post-stop summary analysis asks whether the run's sample peaks keep
  recurring in the predicted wheel/driveshaft/engine bands

The saved per-sample peak/floor inputs consumed by order matching come from the
same canonical live-processing FFT/strength pipeline
(`apps/server/vibesensor/live/compute.py`,
`apps/server/vibesensor/dsp/fft_analysis.py`, and
`apps/server/vibesensor/dsp/vibration_strength.py`), so order analysis does not
maintain a second independent DSP stack.

That shared ownership is why `dsp/order_bands.py` exists outside
`analysis/`.

## File map

| File | Responsibility |
|------|----------------|
| `apps/server/vibesensor/domain/order_reference.py` | Vehicle-physics reference model and frequency derivation helpers. |
| `apps/server/vibesensor/dsp/order_bands.py` | Shared order-match tolerance and live band-payload helpers. |
| `apps/server/vibesensor/analysis/orders/physics.py` | Fixed hypothesis catalog and per-sample predicted-Hz helpers. |
| `apps/server/vibesensor/analysis/orders/matching.py` | Match predicted order bands against stored sample peaks and classify each match as heard. |
| `apps/server/vibesensor/analysis/orders/scoring.py` | Convert matched evidence into confidence and ranking score. |
| `apps/server/vibesensor/analysis/orders/finding_builder.py` | Project scored evidence into domain `Finding` objects. |
| `apps/server/vibesensor/analysis/orders/pipeline.py` | Coordinate the full order-analysis pass. |
