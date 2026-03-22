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
   (`infra/processing/`) must not import from `use_cases/diagnostics/`.

## Live Processing vs Post-Stop Analysis

| | Live Processing (`infra/processing/`) | Post-Stop Analysis (`use_cases/diagnostics/`) |
|-|----------------------------------------|------------------------------------------------|
| **When** | Continuously during recording (5–10 Hz) | Once, after recording stops |
| **Input** | Raw accelerometer frames from UDP | Stored sample records from history DB |
| **Output** | Per-tick metrics: FFT spectrum, peaks, strength_db, RMS, P2P | Diagnostic findings, rankings, reports |
| **Purpose** | Data acquisition — transform raw signals into structured metrics | Diagnostic reasoning — classify, rank, and explain vibration causes |
| **Stateless?** | Yes — each tick processes the current rolling window | Yes — processes all stored samples in one pass |

Mathematical primitives (e.g. `compute_vibration_strength_db`,
`noise_floor_amp_p20_g`) live in the `vibesensor` top-level package
and are shared by both layers.

## Trigger Flow

```
RunRecorder.stop_recording()            # use_cases/run/logger.py
  └─ schedule_post_analysis(run_id)
       └─ PostAnalysisWorker.schedule() # use_cases/run/post_analysis.py
            └─ _worker_loop()           # daemon thread, sequential queue
                 └─ _run_post_analysis(run_id)
                      ├─ load metadata + samples via injected RunPersistence
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

`RunAnalysis.summarize()` in `summary_builder.py` executes these steps
in order. Each step runs exactly once per analysis invocation.

| # | Step | Key Function(s) | Module | Purpose |
|---|------|-----------------|--------|---------|
| 1 | Validation | `_validate_required_strength_metrics` | summary_builder | Validate samples contain required strength metrics |
| 2 | Run preparation | `prepare_run_data`, `compute_run_timing`, `_run_noise_baseline_g` | run_data_preparation, statistics, helpers | Extract timing, speed stats, phase segmentation, and speed context |
| 3 | Phase segmentation | `segment_run_phases`, `_phase_summary`, `_speed_stats_by_phase` | phase_segmentation | Classify each sample into a driving phase (IDLE / ACCEL / CRUISE / DECEL / COAST_DOWN / SPEED_UNKNOWN) |
| 4 | Acceleration statistics | `compute_accel_statistics` | statistics | Per-axis and magnitude accel stats, saturation detection |
| 5 | Findings bundle | `build_findings_bundle` → `_build_findings` | `_summary_steps`, findings, `_peak_findings` | Order tracking, pattern matching, scoring, localisation via `PeakFindingAnalyzer` and `OrderAnalysisSession` |
| 6 | Origin & test plan | `summarize_origin`, `build_phase_timeline` | summary_builder, run_data_preparation | Determine most likely vibration source, generate timeline |
| 7 | Top-cause selection | `select_top_causes`, `group_findings_by_source` | top_cause_selection | Rank findings by phase-adjusted score, group by source, apply drop-off threshold |
| 8 | Run suitability | `build_run_suitability_bundle`, `compute_reference_completeness` | `_summary_steps`, statistics | Check reference completeness plus data-quality and run-condition checks |
| 9 | Location analysis | `LocationAnalysisResult` | location_analysis | Per-location vibration intensity and spatial analysis |
| 10 | App-result construction | `build_analysis_result` | `_summary_result` | Assemble `AnalysisResult`, `TestRun`, `DiagnosticCase`, and diagnostics-local artifacts needed for later boundary serialization |
| 11 | Plot generation | `_plot_data`, `top_peaks_table_rows` | `_summary_result`, plots, peak_table | Build time/speed series, FFT aggregation, spectrograms, and peak table rows as diagnostics-local value objects |
| 12 | Boundary serialization | `analysis_result_to_summary`, `summarize_run_data`, `summarize_log` | `shared/boundaries/analysis_summary.py`, `adapters/analysis_summary.py` | Convert the app-level `AnalysisResult` into the persisted `AnalysisSummary` payload only at explicit edges |

## Module Responsibilities

| Module | LOC | Responsibility |
|--------|-----|---------------|
| `__init__.py` | ~50 | Diagnostics public API re-exports, including shared order-band helpers |
| `_types.py` | ~150 | Diagnostics-local aliases and value objects (`AccelStatistics`, speed/phase breakdown rows, plot bundles, peak rows, spectrogram data) |
| `summary_builder.py` | ~250 | Top-level pipeline orchestration: `RunAnalysis`, `summarize_origin`, and findings entrypoints |
| `_summary_steps.py` | ~150 | Findings, sensor, and suitability step builders consumed by `RunAnalysis` |
| `_summary_result.py` | ~200 | `AnalysisResult` plus final `TestRun` / `DiagnosticCase` / diagnostics-local artifact assembly |
| `run_data_preparation.py` | ~200 | Shared run timing/speed/phase/sensor preparation: `PreparedRunData`, `prepare_run_data`, phase timeline helpers |
| `findings.py` | ~150 | Top-level finding orchestration and finalization around order + persistent-peak helpers |
| `_peak_findings.py` | ~200 | Persistent-peak support: `PeakFindingAnalyzer`, phase filtering, and duplicate-suppression helpers |
| `_reference_findings.py` | ~100 | Reference-gap checks and engine/wheel/sample-rate sufficiency helpers |
| `order_matching.py` | ~200 | Order-tracking hypothesis/sample matching plus the stable `OrderMatchAccumulator` contract |
| `order_match_rate.py` | ~50 | Focused speed-band and per-location match-rate rescue policy |
| `order_scoring.py` | ~200 | Confidence/ranking assembly plus location-summary coordination for matched order hypotheses |
| `order_finding_builder.py` | ~120 | Final `DomainFinding` construction and evidence projection for scored order findings |
| `order_pipeline.py` | ~250 | Order-finding orchestration: `OrderAnalysisSession`, multi-location split, and `_build_order_findings()` |
| `order_heuristics.py` | ~150 | Heuristic filters and tuning constants for diffuse excitation, localization overrides, and engine-alias suppression |
| `peak_accumulation.py` | ~100 | Raw peak-bin accumulation across samples |
| `peak_classification.py` | ~60 | Peak classification thresholds and policy |
| `peak_scoring.py` | ~180 | Peak-bin scoring, confidence, and ranking state |
| `peak_finding_builder.py` | ~60 | Final `DomainFinding` projection for scored peak bins |
| `signal_aggregation.py` | ~250 | Speed/location aggregation helpers |
| `phase_segmentation.py` | ~300 | Driving-phase classification (IDLE → COAST_DOWN) |
| `location_analysis.py` | ~300 | Per-sensor-location vibration intensity and spatial analysis |
| `top_cause_selection.py` | ~80 | Phase-adjusted finding ranking and grouping |
| `shared/order_bands.py` | ~150 | Shared tire/driveline order-frequency band computation for diagnostics and live telemetry |
| `helpers.py` | ~300 | Diagnostics-specific run/sample extraction, metadata/reference helpers, and formatting utilities |
| `math_utils.py` | ~100 | Generic statistics and correlation helpers reused across diagnostics modules |
| `speed_profile_helpers.py` | ~150 | Speed-profile construction and phase/speed summary helpers |
| `plots.py` | ~300 | Chart data shaping orchestration over diagnostics-local value objects: time-series extraction plus FFT/spectrogram assembly |
| `peak_table.py` | ~250 | Peak-table row ranking, persistence-weighted statistics, and internal order-label annotation |
| `adapters/analysis_summary.py` | ~60 | Edge-facing wrappers (`summarize_run_data()`, `summarize_log()`) that call diagnostics and then serialize the result |
| `shared/boundaries/analysis_summary.py` | ~120 | Pure boundary serializer from app-level `AnalysisResult` to persisted `AnalysisSummary` |
| `shared/boundaries/summary_serialization/` | ~350 | Low-level serialization seam package from domain/app diagnostics value objects to persisted `AnalysisSummary` payload fragments (`_contracts.py`, `_findings.py`, `_plots.py`, `_summary.py`) |

## Data Flow

```
Input: samples (list[JsonObject]) + metadata (JsonObject)
  │
  ├─ run_data_preparation.prepare_run_data() → PreparedRunData
  │    ├─ timing, speed stats, noise baseline
  │    └─ phase_segmentation → phases + phase summaries
  │
  ├─ _summary_steps.build_findings_bundle()
  │    ├─ _peak_findings.PeakFindingAnalyzer → peak-based findings
  │    ├─ OrderAnalysisSession → order-matched findings
  │    ├─ _reference_findings.build_reference_findings() → reference sufficiency findings
  │    ├─ finalize_findings() → enriched domain Finding objects
  │    └─ select_top_causes() → ranked top causes
  │
  ├─ _summary_result.build_analysis_result()
  │    └─ shared.boundaries.summary_serialization.build_summary_payload() → AnalysisSummary dict
  │    ├─ findings/top causes serialized from domain Finding
  │    ├─ speed + phase breakdown rows serialized from diagnostics-local value objects
  │    └─ origin, test plan, suitability, accel stats, phase timeline
  │
  └─ _summary_result._plot_data() → diagnostics-local PlotDataResultData
       └─ serialize_plot_data() → persisted chart payload + labeled peak table
  │
Output: AnalysisResult (TestRun, DiagnosticCase, AnalysisSummary)
```

## Persisted Outputs

After `RunAnalysis.summarize()` returns, `PostAnalysisWorker`:

1. Adds `analysis_metadata` (sample count, stride info).
2. Adds language-neutral trust warnings when the captured run context
   was incomplete for confident order analysis.
3. Stores the summary via `history_db.store_analysis()` as a
   versioned persistence envelope.

History readers unwrap the envelope back to the summary shape.
Report endpoints rebuild `ReportTemplateData` from that summary on demand
via `adapters/pdf/mapping.py:map_summary()`.

Persisted post-stop analysis strength/intensity outputs are dB-only.
Raw ingest/sample acceleration fields may still be expressed in g.

## Adding a New Analysis Step

1. Implement the step as a function in the appropriate module
   (or create a new one under `use_cases/diagnostics/`).
2. Call it from `RunAnalysis.summarize()` at the correct point in the
   pipeline.
3. If the new output is needed by the renderer, update
   `adapters/pdf/mapping.py:map_summary()` and `ReportTemplateData`.
4. Export any new public symbol from `use_cases/diagnostics/__init__.py`.
5. Run `pytest apps/server/tests/` to verify tests still pass.
