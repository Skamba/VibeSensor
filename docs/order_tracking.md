# Order Tracking

Scope: shared order-reference math and the post-stop order-analysis flow.

VibeSensor uses the same vehicle-order reference model in two places:

- live telemetry, where the server precomputes order bands for spectrum views
- post-stop diagnostics, where the active whole-run sidecar pipeline scores
  order traces against spectral summaries and context labels, and the legacy
  compact path still matches stored sample peaks when whole-run summaries are
  unavailable

The shared physics lives in `apps/server/vibesensor/domain/order_reference.py`
and `apps/server/vibesensor/shared/order_bands.py`. The post-stop finding flow
lives in `apps/server/vibesensor/use_cases/diagnostics/orders/`.

## Core concepts

| Concept | Owner | Purpose |
|---------|-------|---------|
| `OrderReferenceSpec` | `domain/order_reference.py` | Tire geometry, final-drive ratio, gear ratio, and uncertainty settings for order analysis. |
| `vehicle_orders_hz()` | `shared/order_bands.py` | Resolve wheel / driveshaft / engine reference frequencies for one speed sample. |
| `build_order_bands()` | `shared/order_bands.py` | Precompute live order-band payloads so the frontend does not duplicate tolerance math. |
| `build_whole_run_order_trace_artifact_bundle()` | `use_cases/diagnostics/orders/whole_run_traces.py` | Build dense whole-run order trace points from spectral summaries plus context labels. |
| `build_whole_run_order_trace_summary_artifact_bundle()` | `use_cases/diagnostics/orders/whole_run_scoring.py` | Collapse dense trace points into compact lock/stability summaries. |
| `build_whole_run_order_family_summary_artifact_bundle()` | `use_cases/diagnostics/orders/whole_run_family_summaries.py` | Roll harmonic summaries up to family-level support intervals and phase summaries. |
| `OrderHypothesis` | `use_cases/diagnostics/orders/physics.py` | One named order candidate such as `wheel_1x` or `engine_2x`. |
| `OrderAnalysisSession` | `use_cases/diagnostics/orders/pipeline.py` | Legacy/compatibility compact sample-peak order pass used by the summary analysis path. |

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

## Active whole-run order sidecar flow

The current connected dense order path is wired in
`apps/server/vibesensor/use_cases/run/post_analysis_executor.py` after
whole-run spectra and context sidecars are built:

1. `whole_run_spectra.py` writes per-sensor `spectral-summary:*` sidecars with
   compact per-window peaks, dB strength, and quality/coverage facts.
2. `whole_run_context.py` writes `context-window-labels` and compact
   `whole_run_context_intervals`, carrying speed/RPM/reference validity on the
   same window grid.
3. `orders/whole_run_traces.py` evaluates the fixed `OrderHypothesis` catalog
   against each window, using the same predicted-Hz and peak-match tolerance
   concepts as the compact sample path, and stores dense `order-trace-points`
   sidecars.
4. `orders/whole_run_scoring.py` scores those dense traces into compact
   `OrderTraceSummary` rows with reference coverage, contiguous support,
   drift/error, and lock score.
5. `orders/whole_run_family_summaries.py` rolls harmonic summaries up into
   source-family summaries with support intervals, phase support,
   stable-frequency fields, and exemplar interval IDs.
6. `post_analysis_executor.py` appends ranked
   `whole_run_order_summaries` and related metadata into `analysis_json` while
   keeping dense trace points sidecar-only.

This split lets history/report consumers use compact report-facing summaries
without loading dense sidecar artifacts during normal report generation.

## Compatibility per-window post-run references

The older `post_run_*` DTO path can still map vehicle context onto a
deterministic window grid with
`build_post_run_vehicle_reference_timeline()` in
`use_cases/diagnostics/post_run_vehicle_reference.py`.

The timeline keeps interpolation deliberately narrow:

- speed and RPM interpolate only across short gaps from the same source
- stale nearest samples remain unavailable instead of being stretched across long
  gaps
- gear and final-drive values are never interpolated across changed values
- source switches, missing speed/RPM/gear, inconsistent sample rates, and missing
  vehicle configuration are recorded as explicit unavailable reasons

When inputs are valid, wheel/driveshaft/engine Hz are derived through
`OrderReferenceSpec`; diagnostics does not duplicate the tire or driveline
formulas. Missing RPM can still produce an engine reference only when speed,
final drive, and gear ratio are available from aligned samples or settings, and
the missing-RPM reason remains visible to downstream coverage scoring.

## Compatibility per-window dense order bands

`build_post_run_order_band_timeline()` consumes the compatibility
`VehicleReferenceTimeline` and the run's `OrderReferenceSpec`. For each window it
emits deterministic `OrderBand` rows for configured harmonics:

- default wheel bands: `wheel_1x`, `wheel_2x`
- default driveshaft bands: `driveshaft_1x`, `driveshaft_2x`
- default engine bands: `engine_1x`, `engine_2x`

Each row carries `label`, `source`, `harmonic`, `center_hz`, `min_hz`, `max_hz`,
`uncertainty_pct`, `tolerance`, optional `reference_source`, and optional
`unavailable_reason`. The band half-width is computed with the same
`tolerance_for_order()` helper used by live order-band payloads:

```text
center_hz = base_reference_hz * harmonic
min_hz    = max(config.min_frequency_hz, center_hz * (1 - tolerance))
max_hz    = min(config.max_frequency_hz, center_hz * (1 + tolerance))
```

If the configured spectrum range does not overlap a band, the row stays present
with `unavailable_reason = "outside_spectrum"`. Missing speed, tire,
final-drive, gear, RPM, or whole order-reference settings also stay explicit on
the affected rows. Engine bands can remain available from RPM even when
speed-derived wheel/driveshaft bands are unavailable.

## Compatibility dense episode classification

`use_cases/diagnostics/post_run_dense_findings.py` consumes compatibility
`VibrationEpisode` rows and the compatibility `PostRunOrderBandTimeline`. For each
episode it checks the episode frequency at each supporting `window_index` against
available order bands for wheel, driveshaft, and engine. A source hypothesis is
scored from:

- match ratio across eligible windows
- reference completeness across all episode support windows
- episode persistence and duration
- peak vibration strength
- sensor localization quality

The highest-ranked source becomes the likely origin only when its match ratio
meets the classifier threshold. Otherwise strong persistent episodes stay
reportable as `unknown_resonance` instead of being forced into a weak mechanical
order. Close competing scores add an `ambiguous_origin` caveat and reduce
confidence. Missing bands/reference data, episode quality penalties, short
usable duration, transient-only evidence, and conflicting multi-sensor evidence
are also carried as caveats.

Dense findings keep compact evidence windows plus alternatives and can project
to the existing domain `Finding` model. This remains support/prototype logic;
the active sidecar path persists compact whole-run order summaries from
`orders/whole_run_family_summaries.py`.

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

For the compact summary compatibility path, `OrderAnalysisSession.analyze()`
coordinates the evidence flow:

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
- the active whole-run sidecar path uses the same order references and scores
  whether peak support follows the expected wheel/driveshaft/engine trajectory
  across the saved run
- the compact compatibility path still asks whether stored summary peaks keep
  recurring in the predicted bands

The saved per-sample peak/floor inputs consumed by order matching come from the
same canonical live-processing FFT/strength pipeline
(`apps/server/vibesensor/infra/processing/compute.py`,
`apps/server/vibesensor/shared/fft_analysis.py`, and
`apps/server/vibesensor/vibration_strength.py`), so order analysis does not
maintain a second independent DSP stack.

That shared ownership is why `shared/order_bands.py` exists outside
`use_cases/diagnostics/`.

## File map

| File | Responsibility |
|------|----------------|
| `apps/server/vibesensor/domain/order_reference.py` | Vehicle-physics reference model and frequency derivation helpers. |
| `apps/server/vibesensor/shared/order_bands.py` | Shared uncertainty, tolerance-band, and live band-payload helpers. |
| `apps/server/vibesensor/use_cases/diagnostics/post_run_vehicle_reference.py` | Compatibility/prototype per-window vehicle reference normalization and debug fixtures. |
| `apps/server/vibesensor/use_cases/diagnostics/post_run_order_bands.py` | Compatibility/prototype per-window order-band DTOs, clamping, unavailable reasons, and serializer rows. |
| `apps/server/vibesensor/use_cases/diagnostics/post_run_dense_findings.py` | Compatibility/prototype dense vibration episode classification and domain `Finding` projection. |
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
