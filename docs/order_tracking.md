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

`build_order_bands()` emits the live band payloads with
`tolerance = tolerance_hz / center_hz`, so the UI draws
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
   the best speed band or dominant location.
4. Reject matches that do not follow the prediction. As speed changes, an
   order's peaks move one-for-one with its predicted frequency; a fixed
   resonance (body mode, engine idle) that the prediction sweeps past stays
   at one frequency, yet falls inside the tolerance band over a speed range.
   `frequency_tracking_slope()` (`domain/order_match.py`) takes the robust
   (Theil–Sen) slope of matched vs predicted Hz; below
   `MIN_ORDER_TRACKING_SLOPE` (0.5) the hypothesis produces no finding. On
   the simulator real orders score 0.8–1.3 and a 13 Hz body resonance crossed
   by T1 scores 0.0. It is only judged when the run's speed really changed
   (`trend_moves()`: the 2 s-median speed trend moves by at least 10 % and by
   more than twice the spread inside a 2 s bin). At a steady speed an order
   and a fixed tone look the same, and speed-reading noise would flatten the
   slope.
5. Score the surviving evidence with `score_order_finding()`. Location terms
   are source-aware: an engine/driveline order with no dominant corner is
   not penalised for it once its own evidence is established, unless it
   shares most of its peaks with a wheel order (see "Confidence levels" in
   `docs/metrics.md`).
6. Assemble a domain `Finding` with `assemble_order_finding()`.
7. Split multi-location wheel findings when two corners are both strong.
8. Apply `suppress_engine_aliases()` before returning the final ranked list.

If the effective match rate stays below the current threshold, the hypothesis
does not produce a finding.

Ranking decides the diagnosed source; it does not decide which of that
source's orders the diagnosis names. `TestRun.diagnosis_order_finding` labels
the source's louder order, comparing 1x and 2x amplitudes in the windows both
matched (see "Diagnosed order" in `docs/metrics.md`).

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
| `apps/server/vibesensor/analysis/orders/matching.py` | Match predicted order bands against stored sample peaks. |
| `apps/server/vibesensor/analysis/orders/scoring.py` | Convert matched evidence into confidence and ranking score. |
| `apps/server/vibesensor/analysis/orders/finding_builder.py` | Project scored evidence into domain `Finding` objects. |
| `apps/server/vibesensor/analysis/orders/pipeline.py` | Coordinate the full order-analysis pass. |
