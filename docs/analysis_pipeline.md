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
3. **Single entrypoint** — `RunAnalysis(...).summarize()` (or the procedural
   wrapper `summarize_run_data()`) is the pipeline entrypoint.
4. **Public API** — external code imports from `vibesensor.use_cases.diagnostics`:
   `summarize_run_data()`, `build_findings_for_samples()`, `summarize_log()`,
   `RunAnalysis`, `AnalysisResult`, `build_order_bands()`, `vehicle_orders_hz()`.
   The diagnostics package re-exports the order-band helpers from
   `vibesensor.shared.order_bands`.
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
                      ├─ RunAnalysis(metadata, samples, …).summarize()
                      │     ← current diagnostics entrypoint
                      └─ history_db.store_analysis()
                           ← persist results via injected RunPersistence
```

`PostAnalysisWorker` already receives persistence access and write-error
callbacks via constructor injection from `RunRecorder`. The remaining direct
coupling in this path is the diagnostics analysis entrypoint that
`_run_post_analysis()` still resolves locally.

## Pipeline Steps

`RunAnalysis.summarize()` in `summary_builder.py` executes these steps
in order. Each step runs exactly once per analysis invocation.

| # | Step | Key Function(s) | Module | Purpose |
|---|------|-----------------|--------|---------|
| 1 | Validation | `_validate_required_strength_metrics` | summary_builder | Validate samples contain required strength metrics |
| 2 | Run preparation | `prepare_run_data`, `_compute_run_timing`, `_run_noise_baseline_g` | summary_builder | Extract timing, speed stats, phase segmentation, and speed context |
| 3 | Phase segmentation | `segment_run_phases`, `_phase_summary`, `_speed_stats_by_phase` | phase_segmentation | Classify each sample into a driving phase (IDLE / ACCEL / CRUISE / DECEL / COAST_DOWN / SPEED_UNKNOWN) |
| 4 | Acceleration statistics | `_compute_accel_statistics` | summary_builder | Per-axis and magnitude accel stats, saturation detection |
| 5 | Findings bundle | `build_findings_bundle` → `_build_findings` | summary_builder, findings | Order tracking, pattern matching, scoring, localisation via `PeakFindingAnalyzer` and `OrderAnalysisSession` |
| 6 | Origin & test plan | `summarize_origin`, `_build_phase_timeline` | summary_builder | Determine most likely vibration source, generate timeline |
| 7 | Top-cause selection | `select_top_causes`, `group_findings_by_source` | top_cause_selection | Rank findings by phase-adjusted score, group by source, apply drop-off threshold |
| 8 | Run suitability | `build_run_suitability_bundle`, `compute_reference_completeness` | summary_builder | Check reference completeness plus data-quality and run-condition checks |
| 9 | Location analysis | `LocationAnalysisResult` | location_analysis | Per-location vibration intensity and spatial analysis |
| 10 | Summary construction | `build_summary_payload` | summary_builder | Assemble the final `AnalysisSummary` dict |
| 11 | Plot generation | `_plot_data`, `top_peaks_table_rows` | summary_builder, plots, peak_table | Build time/speed series, FFT aggregation, spectrograms, and peak table rows |
| 12 | Peak annotation | `_annotate_peaks_with_order_labels` | summary_builder | Label peaks with human-readable order names |

## Module Responsibilities

| Module | LOC | Responsibility |
|--------|-----|---------------|
| `__init__.py` | ~50 | Public API re-exports, including shared order-band helpers |
| `_types.py` | ~50 | Local type aliases (`PhaseEvidence`, `FindingPayload`, `AnalysisSummary`) |
| `summary_builder.py` | ~1100 | Top-level pipeline orchestration: `RunAnalysis`, `PreparedRunData`, `AnalysisResult`, `build_summary_payload` |
| `findings.py` | ~400 | Finding construction and enrichment: `PeakFindingAnalyzer`, `finalize_findings`, `build_reference_findings`, `prepare_analysis_samples` |
| `order_analysis.py` | ~500 | Order-tracking core: hypothesis matching, confidence scoring, and finding assembly primitives |
| `order_pipeline.py` | ~250 | Order-finding orchestration: `OrderAnalysisSession`, multi-location split, and `_build_order_findings()` |
| `order_heuristics.py` | ~150 | Heuristic filters and tuning constants for diffuse excitation, localization overrides, and engine-alias suppression |
| `peak_binning.py` | ~450 | Peak accumulation and scoring across samples |
| `signal_aggregation.py` | ~250 | Speed/location aggregation helpers |
| `phase_segmentation.py` | ~300 | Driving-phase classification (IDLE → COAST_DOWN) |
| `location_analysis.py` | ~300 | Per-sensor-location vibration intensity and spatial analysis |
| `top_cause_selection.py` | ~80 | Phase-adjusted finding ranking and grouping |
| `shared/order_bands.py` | ~150 | Shared tire/driveline order-frequency band computation for diagnostics and live telemetry |
| `helpers.py` | ~300 | Diagnostics-specific run/sample extraction, metadata/reference helpers, and formatting utilities |
| `math_utils.py` | ~100 | Generic statistics and correlation helpers reused across diagnostics modules |
| `speed_profile_helpers.py` | ~150 | Speed-profile construction and phase/speed summary helpers |
| `plots.py` | ~700 | Chart data shaping orchestration: time-series extraction plus FFT/spectrogram assembly |
| `peak_table.py` | ~200 | Peak-table row ranking and persistence-weighted statistics |

## Data Flow

```
Input: samples (list[JsonObject]) + metadata (JsonObject)
  │
  ├─ prepare_run_data() → PreparedRunData
  │    ├─ timing, speed stats, noise baseline
  │    └─ phase_segmentation → phases + phase summaries
  │
  ├─ build_findings_bundle()
  │    ├─ PeakFindingAnalyzer → peak-based findings
  │    ├─ OrderAnalysisSession → order-matched findings
  │    ├─ finalize_findings() → enriched domain Finding objects
  │    └─ select_top_causes() → ranked top causes
  │
  ├─ build_summary_payload() → AnalysisSummary dict
  │    ├─ findings, top causes, origin, test plan, suitability
  │    └─ accel stats, speed breakdown, phase timeline
  │
  └─ plots + peak_table + peak annotation → chart data + labeled peak table
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

History readers unwrap the envelope back to the canonical summary shape.
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
