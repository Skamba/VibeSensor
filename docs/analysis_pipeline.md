# Analysis Pipeline

Scope: architecture and data flow for the post-stop diagnostics pipeline in
`apps/server/vibesensor/use_cases/diagnostics/`.

## Architectural Rules

1. **Analysis runs only once** — after a recording is stopped.
   Report rendering and API endpoints use persisted results.
2. **Diagnostics-first package** — diagnostic orchestration, ranking, and
   post-stop reasoning live in `apps/server/vibesensor/use_cases/diagnostics/`.
   The shared vehicle-order frequency math used by both diagnostics and live
   telemetry lives in `apps/server/vibesensor/shared/order_bands.py`.
3. **Single diagnostics entrypoint** — `RunAnalysis(...).summarize()` is the
   diagnostics pipeline entrypoint. Boundary helpers such as
   `summarize_run_data()` / `summarize_log()` live in
   `apps/server/vibesensor/adapters/analysis_summary.py` and call the
   diagnostics entrypoint explicitly.
4. **Public API** — external app/domain code imports from
   `vibesensor.use_cases.diagnostics`: `RunAnalysis`, `AnalysisResult`,
   `build_findings_for_samples()`, `build_order_bands()`, `vehicle_orders_hz()`.
   Serialized `AnalysisSummary` helpers live outside the diagnostics package.
5. **Renderer-only report package** — `vibesensor.adapters.pdf` must not
   import from `vibesensor.use_cases.diagnostics` (enforced by tests).
6. **No circular coupling** — the live signal-processing layer
   (`apps/server/vibesensor/infra/processing/`) must not import from
   `use_cases/diagnostics/`.

## Live Processing vs Post-Stop Analysis

| | Live Processing (`apps/server/vibesensor/infra/processing/`) | Post-Stop Analysis (`use_cases/diagnostics/`) |
|-|----------------------------------------|------------------------------------------------|
| **When** | Continuously during recording (5–10 Hz) | Once, after recording stops |
| **Input** | Raw accelerometer frames from UDP | Stored sample records from history DB, plus optional raw-capture artifacts for replay |
| **Output** | Per-tick metrics: FFT spectrum, peaks, strength_db, RMS, P2P | Diagnostic findings, rankings, reports |
| **Purpose** | Data acquisition — transform raw signals into structured metrics | Diagnostic reasoning — classify, rank, and explain vibration causes |
| **Stateless?** | Yes — each tick processes the current rolling window | Yes — processes all stored samples in one pass |

Mathematical primitives (e.g. `compute_vibration_strength_db`,
`noise_floor_amp_p20_g`) live in
`apps/server/vibesensor/vibration_strength.py`; canonical windowing,
frequency-bin, and peak-detection steps live in
`apps/server/vibesensor/shared/fft_analysis.py`; and live snapshot/metric
coordination stays under `apps/server/vibesensor/infra/processing/`. Live
metrics use the `live_display` processing profile and a three-sample median
filter for operator-friendly display. Post-stop raw replay and dense whole-run
spectra use `diagnostic_raw` when raw capture is available; summary-only
fallbacks are marked `diagnostic_filtered`. Persisted analysis metadata records
the active profile, filter chains, and whether raw diagnostic evidence was
preserved.

Full-run dense analysis stages use
`use_cases/diagnostics/post_run_raw_windows.py` as the raw waveform access
boundary. It prepares a manifest-backed, deterministic window graph from run
metadata and raw-capture manifests, then reads each sensor/window through the
history raw range-read API. That keeps long runs streaming: downstream dense
stages consume bounded axis arrays per window instead of materializing the full
raw artifact bundle. Each emitted sensor window carries run ID, sensor ID,
location snapshot, mount orientation, start/end timing, sample rate, x/y/z
`int16` arrays, and data-quality flags such as partial windows, timestamp gaps,
missing samples, low sample count, invalid axis data, sample-rate mismatch,
sensor clipping, and missing sidecars.

The first dense analysis consumer is
`use_cases/diagnostics/post_run_stft.py`. It consumes those POSTRUN-01 window
DTOs and produces in-memory STFT frames with per-axis spectra, combined spectra,
window timing, sensor metadata, per-axis RMS/P2P, dominant frequency, top peaks,
static-gravity-axis estimate, axis frame, and dB strength facts. Known mount
orientations are transformed into vehicle-relative axes at this boundary;
unknown orientations remain `sensor_local` so later stages can caveat or suppress
axis-specific conclusions while preserving combined-magnitude location evidence.
The STFT layer is deliberately post-run only: callers configure FFT size, window
function, frequency range, and partial-window behavior independently from the
live UI cadence, while still reusing the shared FFT/strength primitives.

`use_cases/diagnostics/post_run_window_features.py` is the next reduction layer.
It consumes POSTRUN-02 STFT frames and emits per-window/per-sensor feature DTOs:
dominant and top peaks, canonical `vibration_strength_db`, peak amplitude, noise
floor, strength bucket, axis dominance, RMS/P2P, axis frame, static gravity
axis, structured quality flags, and compact debug rows for synthetic runs.
Axis dominance is only emitted for vehicle-relative frames; sensor-local frames
carry a `sensor_orientation_unknown` quality flag instead. Frequency masks live
at this layer so later episode/order/finding logic can ignore unusable bands
without recomputing the dense spectra.

Shared per-window quality scoring detects repeated accelerometer rail hits,
flat-topped waveforms, high-frequency mounting/enclosure artifacts, and raw
capture timing integrity loss from timestamp gaps, overlaps/resets, late
packets, and queue drops. It exposes clipping counts/ratios, mounting-quality
scores, and timing-quality reasons in live/whole-run payloads and marks clipped,
suspect-mounted, or timing-compromised windows as limited/excluded evidence
rather than treating local sensor artifacts or corrupted sample timing as
trustworthy vibration strength.

`use_cases/diagnostics/post_run_vehicle_reference.py` normalizes speed, RPM, gear,
and final-drive references onto the same window grid. It uses conservative
interpolation only across short, same-source gaps; rejects ambiguous source,
gear, or final-drive changes; and records explicit unavailable reasons such as
missing speed/RPM/gear, stale samples, inconsistent sample rate, and missing
vehicle configuration. Wheel, driveshaft, and engine frequencies are derived via
the shared `OrderReferenceSpec` math instead of diagnostics-local formulas.

`use_cases/diagnostics/post_run_order_bands.py` consumes that vehicle-reference
timeline and emits per-window wheel, driveshaft, and engine order bands. It uses
the existing `tolerance_for_order()` math, the run's configured uncertainty and
bandwidth settings, optional harmonic lists, and an explicit output spectrum
clamp. Unavailable reference inputs become unavailable band rows with reasons
instead of being dropped or guessed.

Whole-run order traces score the same speed/RPM-synchronous hypotheses across
consecutive analysis windows. Summaries persist matched support intervals,
phase-level support, contiguous support, drift/error, and an order-lock score, so
fixed-frequency resonances during speed changes stay weak unless they follow the
expected wheel, driveshaft, or engine trajectory.

`use_cases/diagnostics/post_run_vibration_episodes.py` groups POSTRUN-03
window-feature peaks into deterministic, time-bounded episodes. Grouping is by
sensor/location, adjacent time windows, allowed per-step frequency drift, and a
minimum strength threshold. Defaults require at least three supporting windows
and 0.75 seconds of duration; isolated spikes are suppressed unless they exceed
the extreme-transient threshold and are marked as transient. Episode rows carry
frequency path, median/peak strength, median frequency, slope, dominant axis,
supporting window IDs, affected sensors, and explainable quality penalties for
dropout gaps, broad drift, noisy feature flags, short duration, and transient
extremes.

`use_cases/diagnostics/post_run_dense_findings.py` fuses POSTRUN-06 episodes with
POSTRUN-05 order bands. It compares each episode frequency path against the
available wheel, driveshaft, and engine bands for the same `window_index`, ranks
source hypotheses by match ratio, reference completeness, persistence, support
density, and strength, then emits compact dense findings. Each finding carries
the likely origin, alternative hypotheses, confidence score/label, evidence
windows, supporting window count/duration, support density, and caveats for
ambiguity, missing references, quality penalties, weak persistence, intermittent
support, short/transient events, conflicting multi-sensor evidence, or strong
unmatched resonance. The DTO can project back to the existing domain `Finding`
shape for report/history compatibility without persisting dense spectra; that
projection carries evidence counts so report facts can show support duration from
the run feature interval.

## Related deep dives

- `docs/order_tracking.md` explains how `OrderReferenceSpec`, shared order-band
  math, and the order-matching pipeline fit together.
- `docs/intake_buffering.md` covers the live ingest path, snapshot -> compute ->
  store flow, FFT pipeline, and buffering/backpressure rules that feed the
  runtime metrics layer.
- `docs/run_lifecycle.md` documents the recording/persistence/post-analysis
  handoff around `RunRecorder`, `RunPersistenceWriter`, and
  `PostAnalysisWorker`.

## Trigger Flow

```
RunRecorder.stop_recording()            # use_cases/run/logger.py
  └─ schedule_post_analysis(run_id)
       └─ PostAnalysisWorker.schedule() # use_cases/run/post_analysis.py
            └─ _worker_loop()           # daemon thread, sequential queue
                 └─ _run_post_analysis(run_id)
                      ├─ load metadata + samples (+ raw capture when present) via injected RunPersistence
                      ├─ build_post_analysis_input(...)
                      │    └─ raw_capture_replay.py rebuilds FFT-derived strength fields from raw windows when possible
                      ├─ analysis_runner(...)
                      │    ← injected by RunRecorder
                      │      └─ RunAnalysis(metadata, samples, …).summarize()
                      └─ history_db.store_analysis()
                            ← persist results via injected RunPersistence
```

`PostAnalysisWorker` receives persistence access, the post-stop analysis
runner, and write-error callbacks via constructor injection from
`RunRecorder`. The worker now owns only queue/thread orchestration plus the
load/store boundary around the injected analysis dependency.

## Pipeline Steps

`RunAnalysis.summarize()` in `run_analysis.py` delegates to
`analysis_pipeline.py` and executes these steps
in order. Each step runs exactly once per analysis invocation.

| # | Step | Key Function(s) | Module | Purpose |
|---|------|-----------------|--------|---------|
| 1 | Validation | `_validate_required_strength_metrics` | `run_analysis.py` | Validate samples contain required strength metrics |
| 2 | Context decode | `build_diagnostics_context` | `_context_decode.py`, `_context.py` | Decode raw metadata once into the canonical typed `DiagnosticsContext` |
| 3 | Run preparation | `prepare_run_data`, `compute_run_timing`, `_run_noise_baseline_g` | run_data_preparation, statistics, `_sample_metrics.py` | Extract timing, speed stats, phase segmentation, and speed context |
| 4 | Phase segmentation | `segment_run_phases`, `_phase_summary`, `_speed_stats_by_phase` | phase_segmentation | Classify each sample into a driving phase (IDLE / ACCEL / CRUISE / DECEL / COAST_DOWN / SPEED_UNKNOWN) |
| 5 | Acceleration statistics | `compute_accel_statistics` | statistics | Per-axis and magnitude accel stats, saturation detection |
| 6 | Findings bundle | `build_findings_bundle` → `_build_findings` | `_summary_steps`, `_analysis_models.py`, findings, `peaks/findings.py`, `orders/pipeline.py` | Order tracking, pattern matching, scoring, localisation, and top-cause candidates via typed request/bundle contracts |
| 7 | Origin & test plan | `summarize_origin`, `build_phase_timeline` | `run_analysis.py`, run_data_preparation | Determine most likely vibration source, generate timeline |
| 8 | Top-cause selection | `select_top_causes`, `group_findings_by_source` | top_cause_selection | Rank findings by phase-adjusted score, group by source, apply drop-off threshold |
| 9 | Run suitability | `build_run_suitability_bundle`, `compute_reference_completeness` | `_summary_steps`, statistics | Check reference completeness plus data-quality and run-condition checks |
| 10 | Location analysis | `LocationAnalysisResult` | location_analysis | Per-location vibration intensity and spatial analysis |
| 11 | App-result construction | `build_analysis_result` | `_summary_result` | Assemble `AnalysisResult`, `TestRun`, `DiagnosticCase`, diagnostics-local artifacts, and the rehydrated metadata payload needed for later boundary serialization |
| 12 | Plot generation | `_plot_data`, `top_peaks_table_rows` | `_summary_result`, plots, `peaks/table.py` | Build time/speed series, FFT aggregation, spectrograms, and peak table rows as diagnostics-local value objects |
| 13 | Boundary serialization | `analysis_result_to_summary`, `summarize_run_data`, `summarize_log` | `shared/boundaries/analysis_payloads/summary.py`, `adapters/analysis_summary.py` | Convert the app-level `AnalysisResult` into the persisted `AnalysisSummary` payload only at explicit edges |

## Module Responsibilities

| Module | LOC | Responsibility |
|--------|-----|---------------|
| `__init__.py` | ~5 | Package marker only; callers import canonical diagnostics owners directly |
| `_context.py` | ~150 | `DiagnosticsContext`: typed run context container with effective reference helpers |
| `_context_decode.py` | ~120 | Raw metadata → `DiagnosticsContext` decoding via `build_diagnostics_context()` |
| `_context_projection.py` | ~80 | Projection helpers that rehydrate metadata, car, symptom, and configuration snapshots from `DiagnosticsContext` |
| `_analysis_models.py` | ~80 | Typed request and bundle dataclasses shared across findings and result assembly |
| `_types.py` | ~150 | Diagnostics-local aliases and value objects (`AccelStatistics`, speed/phase breakdown rows, plot bundles, peak rows, spectrogram data) |
| `run_analysis.py` | ~130 | Public typed entrypoint: `RunAnalysis`, raw-boundary findings helper, and language normalization |
| `analysis_pipeline.py` | ~120 | Typed execution pipeline over already-prepared diagnostics inputs |
| `_summary_steps.py` | ~150 | Findings, sensor, and suitability step builders consumed by `RunAnalysis` |
| `_summary_result.py` | ~200 | `AnalysisResult` plus final `TestRun` / `DiagnosticCase` / diagnostics-local artifact assembly |
| `run_data_preparation.py` | ~200 | Shared run timing/speed/phase/sensor preparation: `PreparedRunData`, `prepare_run_data`, phase timeline helpers |
| `findings.py` | ~150 | Top-level finding orchestration and finalization around order + persistent-peak helpers |
| `_validation.py` | ~30 | Diagnostics input validation for required strength metrics |
| `_sample_metrics.py` | ~80 | Shared run/sample strength helpers, baseline-floor policy, and sensor-limit helpers |
| `_reference_resolution.py` | ~80 | Engine/tire/reference resolution helpers reused by order analysis |
| `_sensor_locations.py` | ~80 | Stable sensor-location labels and connected-throughout-run detection |
| `_run_loader.py` | ~20 | JSONL run loader used by analysis/report adapters |
| `post_run_raw_windows.py` | ~300 | Manifest-aware streaming raw waveform reader and configurable overlapping-window iterator for dense post-run stages |
| `post_run_stft.py` | ~350 | In-memory dense STFT engine over POSTRUN-01 raw-window DTOs |
| `post_run_window_features.py` | ~300 | Window-level feature extraction over POSTRUN-02 STFT frames |
| `post_run_vehicle_reference.py` | ~350 | Per-window vehicle speed/RPM/gear/final-drive reference normalization for dense order stages |
| `post_run_order_bands.py` | ~400 | Per-window wheel/driveshaft/engine order-band generation over POSTRUN-04 vehicle references |
| `post_run_vibration_episodes.py` | ~450 | Deterministic grouping of dense window peaks into persistent or intentional transient vibration episodes |
| `post_run_dense_findings.py` | ~500 | Dense episode classification into likely origins, alternatives, confidence, caveats, evidence windows, and domain-finding compatibility |
| `_counters.py` | ~20 | Shared `counter_delta()` helper used by diagnostics/runtime tests |
| `_reference_findings.py` | ~100 | Reference-gap checks and engine/wheel/sample-rate sufficiency helpers |
| `orders/pipeline.py` | ~250 | Order-finding orchestration: `OrderAnalysisSession`, `OrderAnalysisRequest`, multi-location split, and `_build_order_findings()` |
| `orders/matching.py` | ~200 | Order-tracking hypothesis/sample matching plus the stable `OrderMatchAccumulator` contract |
| `orders/match_rate.py` | ~50 | Focused speed-band and per-location match-rate rescue policy |
| `orders/scoring.py` | ~200 | Confidence/ranking assembly plus location-summary coordination for matched order hypotheses |
| `orders/finding_builder.py` | ~120 | Final `DomainFinding` construction and evidence projection for scored order findings |
| `orders/statistics.py` | ~260 | Order evidence aggregation plus typed confidence calibration settings |
| `orders/heuristics.py` | ~150 | Diffuse-excitation, localization-override, and engine-alias heuristics |
| `orders/settings.py` | ~80 | Typed frozen tuning collections used by order scoring and heuristics |
| `peaks/findings.py` | ~200 | Persistent-peak support: `PeakFindingAnalyzer`, phase filtering, and duplicate suppression |
| `peaks/accumulation.py` | ~100 | Raw peak-bin accumulation across samples |
| `peaks/classification.py` | ~60 | Peak classification policy backed by typed settings |
| `peaks/scoring.py` | ~180 | Peak-bin scoring, confidence, and ranking state |
| `peaks/finding_builder.py` | ~60 | Final `DomainFinding` projection for scored peak bins |
| `peaks/statistics.py` | ~90 | Shared peak distribution, uniformity, and persistence-score statistics |
| `peaks/settings.py` | ~80 | Typed frozen tuning collections for peak classification and confidence |
| `signal_aggregation.py` | ~250 | Speed/location aggregation helpers |
| `phase_segmentation.py` | ~300 | Driving-phase classification (IDLE → COAST_DOWN) |
| `location_analysis.py` | ~300 | Per-sensor-location vibration intensity and spatial analysis |
| `top_cause_selection.py` | ~80 | Phase-adjusted finding ranking and grouping |
| `shared/order_bands.py` | ~150 | Shared tire/driveline order-frequency band computation for diagnostics and live telemetry |
| `math_utils.py` | ~100 | Generic statistics and correlation helpers reused across diagnostics modules |
| `speed_profile_helpers.py` | ~150 | Speed-profile construction and phase/speed summary helpers |
| `plots.py` | ~300 | Chart data shaping orchestration over diagnostics-local value objects: time-series extraction plus FFT/spectrogram assembly |
| `adapters/analysis_summary.py` | ~60 | Edge-facing wrappers (`summarize_run_data()`, `summarize_log()`) that call diagnostics and then serialize the result |
| `shared/boundaries/analysis_payloads/summary.py` | ~120 | Pure boundary serializer from app-level `AnalysisResult` to persisted `AnalysisSummary` |
| `shared/boundaries/summary_serialization/` | ~350 | Low-level serialization seam package from domain/app diagnostics value objects to persisted `AnalysisSummary` payload fragments (`_contracts.py`, `_findings.py`, `_plots.py`, `_summary.py`) |

## Data Flow

```
Input: raw samples (list[JsonObject]) + metadata (JsonObject)
  │
  ├─ _context_decode.build_diagnostics_context() → typed diagnostics context
  │    ├─ RunMetadataSnapshot
  │    ├─ RunContextSnapshot
  │    └─ diagnostics-local context conveniences / boundary metadata rehydration
  │
  ├─ _types.normalize_analysis_samples() → raw rows + typed AnalysisSample objects
  │
  ├─ run_data_preparation.prepare_run_data() → PreparedRunData
  │    ├─ timing, speed stats, noise baseline
  │    └─ phase_segmentation → phases + phase summaries
  │
  ├─ _summary_steps.build_findings_bundle()
  │    ├─ FindingsBuildRequest / FindingsBundle → typed orchestration contracts
  │    ├─ peaks.findings.PeakFindingAnalyzer → peak-based findings
  │    ├─ orders.pipeline.OrderAnalysisSession → order-matched findings
  │    ├─ _reference_findings.build_reference_findings() → reference sufficiency findings
  │    ├─ finalize_findings() → enriched domain Finding objects
  │    └─ select_top_causes() → ranked top causes
  │
  ├─ _summary_result.build_analysis_result()
  │    ├─ AnalysisResult
  │    ├─ TestRun / DiagnosticCase
  │    └─ rehydrated metadata dict for later boundary serialization
  │
  └─ _summary_result._plot_data() → diagnostics-local PlotDataResultData
       └─ serialize_plot_data() → persisted chart payload + labeled peak table
  │
Output: AnalysisResult (TestRun, DiagnosticCase, diagnostics-local artifacts)
```

## Persisted Outputs

After `RunAnalysis.summarize()` returns, `PostAnalysisWorker`:

1. Adds `analysis_metadata` (sample count, stride info, and whether raw-backed
   replay was used).
2. Adds language-neutral trust warnings when the captured run context
   was incomplete for confident order analysis.
3. Stores the summary via `history_db.store_analysis()` as a
   versioned persistence envelope.

History readers unwrap the envelope back to the summary shape. When a run has a
raw capture bundle, the persisted analysis summary already reflects raw-backed
strength/peak metrics from post-stop replay; report/history readers still stay
persistence-only and never re-run diagnostics. The core
history/report projection is derived from persisted run data plus the persisted
analysis summary only; any comparison against current mutable car settings is an
explicit advisory overlay at the history delivery boundary, not a hidden input
to the persisted projection or the default report cache path. Report endpoints
rebuild a `ReportDocument` from the persisted summary on demand via
`shared/boundaries/reporting/preparation.py:prepare_report_input()`, which
reconstructs the domain aggregate and assembles the prepared report handoff,
and `use_cases/history/report_document/builder.py:build_report_document()`,
which performs the final document assembly before adapter-local PDF render
planning.

Persisted post-stop analysis strength/intensity outputs are dB-only.
Raw ingest/sample acceleration fields may still be expressed in g.

## Adding a New Analysis Step

1. Implement the step as a function in the appropriate module
   (or create a new one under `use_cases/diagnostics/`).
2. Call it from `RunAnalysis.summarize()` at the correct point in the
   pipeline.
3. If the new output is needed by the renderer, add any report-facing shaping
   in `shared/boundaries/reporting/` or
   `use_cases/history/report_document/`, then update
   `build_report_document()` and `ReportDocument`. Keep semantic
   interpretation on the reporting-boundary side rather than in
   `adapters/pdf/*`.
4. Export any new public symbol from `use_cases/diagnostics/__init__.py`.
5. Run `pytest apps/server/tests/` to verify tests still pass.
