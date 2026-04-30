# Order Tracking

Scope: shared order-reference math and the post-stop order-analysis flow.

VibeSensor uses the same vehicle-order reference model in two places:

- live telemetry, where the server precomputes order bands for spectrum views
- post-stop diagnostics, where stored samples are matched against those orders

The shared physics lives in `apps/server/vibesensor/domain/order_reference.py`
and `apps/server/vibesensor/shared/order_bands.py`. The post-stop finding flow
lives in `apps/server/vibesensor/use_cases/diagnostics/orders/`.

## Core concepts

| Concept | Owner | Purpose |
|---------|-------|---------|
| `OrderReferenceSpec` | `domain/order_reference.py` | Tire geometry, final-drive ratio, gear ratio, and uncertainty settings for order analysis. |
| `vehicle_orders_hz()` | `shared/order_bands.py` | Resolve wheel / driveshaft / engine reference frequencies for one speed sample. |
| `build_order_bands()` | `shared/order_bands.py` | Precompute live order-band payloads so the frontend does not duplicate tolerance math. |
| `OrderHypothesis` | `use_cases/diagnostics/orders/physics.py` | One named order candidate such as `wheel_1x` or `engine_2x`. |
| `OrderAnalysisSession` | `use_cases/diagnostics/orders/pipeline.py` | Run all eligible hypotheses across stored samples and return ranked findings. |

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

Order matching is not based on a single exact frequency bin. Each reference
order gets an uncertainty-aware tolerance band.

`OrderReferenceSpec` combines uncertainty in stages:

- wheel uncertainty = speed + tire diameter
- driveshaft uncertainty = wheel uncertainty + final-drive uncertainty
- engine uncertainty = driveshaft uncertainty + gear uncertainty

The shared helper `combined_relative_uncertainty()` uses
`sqrt(sum(part^2))`, so wider uncertainty produces wider matching bands.

`tolerance_for_order()` then turns the nominal order frequency plus uncertainty
into a half-bandwidth:

```text
base_half_rel = base_bandwidth_pct / 200
abs_floor     = min_abs_band_hz / order_hz
combined      = sqrt(base_half_rel^2 + uncertainty_pct^2)
tolerance     = min(max_half_rel, max(combined, abs_floor))
```

That tolerance means a match is accepted inside:

```text
[center_hz * (1 - tolerance), center_hz * (1 + tolerance)]
```

`build_order_bands()` uses those tolerances to emit the live band payloads:

- `wheel_1x`
- `wheel_2x`
- `driveshaft_1x` or merged `driveshaft_engine_1x`
- `engine_1x` when it does not overlap driveshaft
- `engine_2x`

The driveshaft and engine 1x bands collapse into `driveshaft_engine_1x` when
their centers are already inside the combined uncertainty envelope.

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

`OrderAnalysisSession.analyze()` coordinates the evidence flow:

1. Skip hypotheses that do not have enough reference data (`_should_test()`).
2. Use `match_samples_for_hypothesis()` to compare predicted order bands against
   the stored sample peaks.
3. Use `_compute_effective_match_rate()` to rescue or focus the evidence around
   the best speed band or dominant location.
4. Score the surviving evidence with `score_order_finding()`.
5. Assemble a domain `Finding` with `assemble_order_finding()`.
6. Split multi-location wheel findings when two corners are both strong.
7. Apply `suppress_engine_aliases()` before returning the final ranked list.

If the effective match rate stays below the current threshold, the hypothesis
does not produce a finding.

## Live vs post-stop reuse

The same reference math serves both runtime and diagnostics:

- live telemetry calls `vehicle_orders_hz()` and `build_order_bands()` so the
  UI can annotate the current spectrum without duplicating the formulas
- post-stop diagnostics uses the same order references, then asks whether peaks
  keep recurring in the predicted bands across the saved run

The saved per-sample peak/floor inputs consumed by order matching come from the
same canonical live-processing FFT/strength pipeline
(`apps/server/vibesensor/infra/processing/` plus `vibration_strength.py`), so
order analysis does not maintain a second independent DSP stack.

That shared ownership is why `shared/order_bands.py` exists outside
`use_cases/diagnostics/`.

## File map

| File | Responsibility |
|------|----------------|
| `apps/server/vibesensor/domain/order_reference.py` | Vehicle-physics reference model and frequency derivation helpers. |
| `apps/server/vibesensor/shared/order_bands.py` | Shared uncertainty, tolerance-band, and live band-payload helpers. |
| `apps/server/vibesensor/use_cases/diagnostics/orders/physics.py` | Fixed hypothesis catalog and per-sample predicted-Hz helpers. |
| `apps/server/vibesensor/use_cases/diagnostics/orders/matching.py` | Match predicted order bands against stored sample peaks. |
| `apps/server/vibesensor/use_cases/diagnostics/orders/scoring.py` | Convert matched evidence into confidence and ranking score. |
| `apps/server/vibesensor/use_cases/diagnostics/orders/finding_builder.py` | Project scored evidence into domain `Finding` objects. |
| `apps/server/vibesensor/use_cases/diagnostics/orders/pipeline.py` | Coordinate the full order-analysis pass. |
| `apps/server/vibesensor/use_cases/diagnostics/orders/whole_run_contracts.py` | Dense whole-run order-trace points plus compact summary/support contracts for later full-run work. |
| `apps/server/vibesensor/use_cases/diagnostics/orders/whole_run_traces.py` | Build deterministic dense whole-run order traces from spectral summaries plus context labels. |
| `apps/server/vibesensor/use_cases/diagnostics/orders/whole_run_scoring.py` | Collapse dense whole-run traces into deterministic lock/stability summaries for later persistence. |
| `apps/server/vibesensor/use_cases/diagnostics/orders/whole_run_family_summaries.py` | Collapse scored harmonic traces into family-level support intervals and phase summaries. |
| `apps/server/vibesensor/use_cases/run/post_analysis_executor.py` | Persist ranked compact whole-run order summaries into `analysis_json` while keeping dense traces sidecar-only. |

## Whole-run order trace contract split

Whole-run order work keeps one order model and changes only the sampling grid:

- dense sidecars use `OrderTracePoint` in
  `use_cases/diagnostics/orders/whole_run_contracts.py`, keyed by
  `(hypothesis_key, harmonic, window_index)` so later execution can join
  directly against the canonical whole-run window grid
- `use_cases/diagnostics/orders/whole_run_traces.py` now builds those dense
  points from `spectral-summary:*` sidecars plus `context-window-labels`, using
  the same `OrderHypothesis.predicted_hz(...)` math and `best_order_peak_match()`
  tolerance logic as the live sample-matching path
- `use_cases/diagnostics/orders/whole_run_scoring.py` now scores those dense
  traces into compact `OrderTraceSummary` rows plus harmonic evidence rows,
  explicitly carrying `reference_coverage_ratio`, `contiguous_support_ratio`,
  `drift_score`, and `lock_score` so partial context/RPM coverage degrades the
  result instead of silently inflating it
- `use_cases/diagnostics/orders/whole_run_family_summaries.py` now rolls those
  per-candidate summaries up into source-family summaries with deterministic
  `support_intervals`, `phase_support`, `stable_frequency_*_hz`, and
  `exemplar_interval_index` fields while keeping the dense traces sidecar-only
- `use_cases/run/post_analysis_executor.py` now projects those family summaries
  into a ranked persisted `whole_run_order_summaries` payload so history/report
  reload paths can consume compact whole-run order evidence without reading the
  dense sidecars back in
- compact persisted/report-facing projections use the summary shapes in
  `shared/types/history_analysis_contracts.py` and the report-side normalizer in
  `shared/boundaries/reporting/summary.py`
- the compact summary contract carries support intervals, phase support, and
  harmonic evidence rows, while the dense point contract keeps per-window
  predicted/matched frequency evidence

This keeps whole-run traces aligned with the existing `OrderHypothesis`,
`OrderMatchObservation`, and `FindingEvidence` concepts instead of creating a
second order-analysis vocabulary.
