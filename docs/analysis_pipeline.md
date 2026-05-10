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

The connected full-run dense path is the `whole_run_*` sidecar pipeline wired by
`use_cases/run/post_analysis_executor.py` through
`use_cases/run/post_analysis_whole_run_builders.py`. It currently receives the
full `RawRunCapture` loaded by `post_analysis_loader.py`, then builds and stores
dense sidecar artifacts before compact report-facing summaries are persisted.
The future streaming/range-read refactor should reuse the bounded range-read
boundary in `post_run_raw_windows.py`, but that boundary is not the active
executor input today.

Current whole-run sidecar stages:

1. `use_cases/diagnostics/whole_run_spectra.py` computes deterministic
   raw-window spectra from raw capture and emits `spectral-grid:*`,
   `spectral-matrix:*`, and `spectral-summary:*` sidecars. The summaries carry
   window timing, coverage/quality, top peaks, and dB strength facts without
   forcing reports to read the dense matrices.
2. `use_cases/diagnostics/whole_run_context.py` projects speed/RPM/reference
   context onto the same window grid and emits dense `context-window-labels`
   plus compact `whole_run_context_intervals` for `analysis_json`.
3. `use_cases/diagnostics/orders/whole_run_traces.py` joins spectral summaries
   with context labels and scores wheel/driveshaft/engine hypotheses per window,
   writing dense `order-trace-points` sidecars.
4. `use_cases/diagnostics/orders/whole_run_scoring.py` collapses trace points
   into compact lock/stability summaries with reference coverage, contiguous
   support, drift/error, and lock score.
5. `use_cases/diagnostics/orders/whole_run_family_summaries.py` rolls harmonic
   summaries up to family-level support intervals and phase summaries.
6. `use_cases/diagnostics/whole_run_spatial_coherence.py` builds candidate-level
   multi-sensor spatial evidence windows and compact spatial summaries.
7. `post_analysis_executor.py` persists dense artifacts through
   `RunPersistence.astore_whole_run_artifacts(...)`, appends compact whole-run
   metadata/summaries into `PersistedAnalysis`, and then stores the report-facing
   summary through `RunPersistence.astore_analysis(...)`.

The older `post_run_*` modules are compatibility/support/prototype components.
`post_run_raw_windows.py` is the manifest-aware range-read access boundary for
future streaming work; `post_run_stft.py`, `post_run_window_features.py`,
`post_run_vehicle_reference.py`, `post_run_order_bands.py`,
`post_run_vibration_episodes.py`, and `post_run_dense_findings.py` preserve
useful dense DTO and math seams, but the active sidecar pipeline is the
`whole_run_*` implementation above. Shared quality scoring still marks clipped,
suspect-mounted, or timing-compromised windows as limited/excluded evidence
rather than treating local sensor artifacts or corrupted sample timing as
trustworthy vibration strength.

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
                      ├─ load metadata + persisted summary rows via injected RunPersistence
                      ├─ load full RawRunCapture when a raw-capture manifest exists
                      ├─ build_post_analysis_input(...)
                      │    └─ raw_capture_replay.py rebuilds FFT-derived strength fields from raw windows when possible
                      ├─ whole_run_* sidecar stages (spectra, context, orders, spatial coherence)
                      ├─ analysis_runner(...)
                      │    ← injected by RunRecorder
                      │      └─ RunAnalysis(metadata, samples, …).summarize()
                      ├─ append compact whole-run summaries/metadata to PersistedAnalysis
                      ├─ history_db.astore_whole_run_artifacts()
                      └─ history_db.astore_analysis()
                            ← persist sidecars and report-facing summary via injected RunPersistence
```

`PostAnalysisWorker` receives persistence access, the post-stop analysis
runner, and write-error callbacks via constructor injection from
`RunRecorder`. The worker now owns only queue/thread orchestration plus the
load/store boundary around the injected analysis dependency.

## Pipeline Steps

`RunAnalysis.summarize()` in `run_analysis.py` delegates to
`analysis_pipeline.py` for the compact summary/report-facing analysis over
summary-style samples. `execute_post_analysis()` runs the whole-run sidecar
stages before this compact summary is stored, then appends whole-run metadata and
summaries to the persisted analysis.

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
| `post_run_raw_windows.py` | ~300 | Compatibility/future-streaming manifest-aware raw waveform range reader and configurable overlapping-window iterator |
| `post_run_stft.py` | ~350 | Support/prototype in-memory dense STFT engine over range-read raw-window DTOs |
| `post_run_window_features.py` | ~300 | Support/prototype window-level feature extraction over dense STFT frames |
| `post_run_vehicle_reference.py` | ~350 | Support/prototype per-window vehicle speed/RPM/gear/final-drive reference normalization |
| `post_run_order_bands.py` | ~400 | Support/prototype per-window wheel/driveshaft/engine order-band generation |
| `post_run_vibration_episodes.py` | ~450 | Support/prototype deterministic grouping of dense window peaks into episodes |
| `post_run_dense_findings.py` | ~500 | Support/prototype dense episode classification and domain-finding projection |
| `whole_run_spectra.py` | ~900 | Active sidecar spectral executor over loaded raw capture; emits dense spectra and compact spectral summaries |
| `whole_run_context.py` | ~400 | Active sidecar context timeline and compact context intervals on the whole-run window grid |
| `whole_run_spatial_coherence.py` | ~450 | Active candidate-level spatial evidence sidecars and compact spatial summaries |
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
| `orders/whole_run_traces.py` | ~350 | Active dense order-trace sidecar generation from spectral summaries plus context labels |
| `orders/whole_run_scoring.py` | ~600 | Active compact lock/stability scoring over dense order traces |
| `orders/whole_run_family_summaries.py` | ~600 | Active family-level support intervals and phase summaries from scored order traces |
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

Whole-run sidecar flow:

```
Input: persisted summary samples + metadata (+ optional raw-capture manifest/files)
  │
  ├─ post_analysis_loader.load_post_analysis_run()
  │    ├─ loads persisted summary rows and caps compact-analysis input
  │    └─ loads full RawRunCapture when raw capture is available
  │
  ├─ post_analysis_whole_run_builders.build_whole_run_artifacts()
  │    ├─ whole_run_spectra.py → dense spectral sidecars + spectral summaries
  │    ├─ whole_run_context.py → context-window-labels sidecar + compact intervals
  │    ├─ orders/whole_run_traces.py → dense order-trace sidecar
  │    ├─ orders/whole_run_scoring.py → compact trace summaries
  │    ├─ orders/whole_run_family_summaries.py → compact family summaries
  │    └─ whole_run_spatial_coherence.py → spatial sidecar + compact summaries
  │
  ├─ history_db.astore_whole_run_artifacts() → dense sidecar artifacts
  │
  └─ compact-analysis/report summary flow
```

Compact-analysis/report summary flow:

```text
Input: PostAnalysisRunInput + optional whole-run stage output
  │
  ├─ _context_decode.build_diagnostics_context() → typed diagnostics context
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
  ├─ _summary_result.build_analysis_result() → AnalysisResult/TestRun/DiagnosticCase
  │
  ├─ _summary_result._plot_data() → diagnostics-local PlotDataResultData
  │    └─ serialize_plot_data() → persisted chart payload + labeled peak table
  │
  ├─ post_analysis_executor.append_whole_run_*() → compact persisted summaries
  │
  └─ history_db.astore_analysis() → PersistedAnalysis/report-facing summary
```

## Persisted Outputs

During `execute_post_analysis()`, `PostAnalysisWorker`:

1. Builds and stores dense whole-run sidecar artifacts when raw capture is
   available and prerequisites pass.
2. Runs the compact summary analysis path and adds `analysis_metadata` (sample
   count, sampling method, profile info, raw/whole-run availability, artifact
   manifest pointers, and stage/fallback details).
3. Adds compact whole-run context/order/spatial/diagnosis summaries when those
   stages produced them.
4. Adds language-neutral trust warnings when the captured run context was
   incomplete for confident order analysis.
5. Stores the summary via `history_db.astore_analysis()` as a versioned
   persistence envelope.

History readers unwrap the envelope back to the summary shape. When a run has
raw capture and whole-run sidecars, the persisted analysis summary already
contains compact report-facing summaries plus sidecar manifest metadata;
report/history readers still stay persistence-only and never re-run diagnostics.
The core
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
