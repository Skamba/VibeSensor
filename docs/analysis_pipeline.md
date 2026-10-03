# Analysis Pipeline

Scope: architecture and data flow for the post-stop diagnostics pipeline in
`apps/server/vibesensor/analysis/`.

## Architectural Rules

1. **Analysis runs only once** — after a recording is stopped.
   Report rendering and API endpoints use persisted results.
2. **Diagnostics-first package** — diagnostic orchestration, ranking, and
   post-stop reasoning live in `apps/server/vibesensor/analysis/`.
   The shared vehicle-order frequency math used by both diagnostics and live
   telemetry lives in `apps/server/vibesensor/dsp/order_bands.py`.
3. **Single diagnostics entrypoint** — `RunAnalysis(...).summarize()` is the
   diagnostics pipeline entrypoint. Boundary helpers such as
   `summarize_run_data()` / `summarize_log()` live in
   `apps/server/vibesensor/analysis/summarize.py` and call the
   diagnostics entrypoint explicitly.
4. **Public API** — external app/domain code imports from
   `vibesensor.analysis`: `RunAnalysis`, `AnalysisResult`,
   `build_findings_for_samples()`, `build_order_bands()`, `vehicle_orders_hz()`.
   Serialized `AnalysisSummary` helpers live outside the diagnostics package.
5. **Renderer-only report package** — `vibesensor.report.pdf` must not
   import from `vibesensor.analysis` (enforced by tests).
6. **No circular coupling** — the live signal-processing layer
   (`apps/server/vibesensor/live/`) must not import from
   `analysis/`.

## Live Processing vs Post-Stop Analysis

| | Live Processing (`apps/server/vibesensor/live/`) | Post-Stop Analysis (`analysis/`) |
|-|----------------------------------------|------------------------------------------------|
| **When** | Continuously during recording (5–10 Hz) | Once, after recording stops |
| **Input** | Raw accelerometer frames from UDP | Stored sample records from history DB, plus optional raw-capture artifacts for replay |
| **Output** | Per-tick metrics: FFT spectrum, peaks, strength_db, RMS, P2P | Diagnostic findings, rankings, reports |
| **Purpose** | Data acquisition — transform raw signals into structured metrics | Diagnostic reasoning — classify, rank, and explain vibration causes |
| **Stateless?** | Yes — each tick processes the current rolling window | Yes — processes all stored samples in one pass |

Mathematical primitives (e.g. `compute_vibration_strength_db`,
`noise_floor_amp_p20_g`) live in
`apps/server/vibesensor/dsp/vibration_strength.py`; canonical windowing,
frequency-bin, and peak-detection steps live in
`apps/server/vibesensor/dsp/fft_analysis.py`; and live snapshot/metric
coordination stays under `apps/server/vibesensor/live/`. Live
metrics use the `live_display` processing profile and a three-sample median
filter for operator-friendly display. Post-stop raw replay uses
`diagnostic_raw` when raw capture is available; summary-only
fallbacks are marked `diagnostic_filtered`. Persisted analysis metadata records
the active profile, filter chains, and whether raw diagnostic evidence was
preserved.

When raw capture is available, `analysis/raw_capture_replay.py` recomputes each
summary row's FFT peaks and strength metrics from the raw window the row was
analysed over, so the summary analysis reasons over unfiltered diagnostic
evidence. Shared window-quality scoring marks clipped, suspect-mounted, or
timing-compromised windows as limited/excluded evidence rather than treating
local sensor artifacts or corrupted sample timing as trustworthy vibration
strength.

The summary analysis is the single diagnosis: the UI insights endpoint and the
PDF report both read its `findings`, `top_causes`, and `most_likely_origin`.

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
RunRecorder.stop_recording()            # recording/recorder.py
  └─ RunRecorder.post_analysis
       └─ PostAnalysisWorker.schedule() # analysis/post_analysis.py
            └─ _worker_loop()           # daemon thread, sequential queue
                 └─ _run_post_analysis(run_id)
                      ├─ load metadata + persisted summary rows via the injected HistoryDB
                      ├─ load raw manifest; compact replay may load full RawRunCapture
                      ├─ build_post_analysis_input(...)
                      │    └─ raw_capture_replay.py rebuilds FFT-derived strength fields from raw windows when possible
                      ├─ analysis_runner(...)
                      │    ← injected by RunRecorder
                      │      └─ RunAnalysis(metadata, samples, …).summarize()
                      └─ history_db.store_analysis()
                            ← persist the summary analysis via the injected HistoryDB
```

`PostAnalysisWorker` receives persistence access, the post-stop analysis
runner, and write-error callbacks via constructor injection from
`RunRecorder`. The worker now owns only queue/thread orchestration plus the
load/store boundary around the injected analysis dependency.

## Pipeline Steps

`RunAnalysis.summarize()` in `run_analysis.py` runs the compact
summary/report-facing analysis over summary-style samples:
`prepare_analysis_context()` → `build_findings_bundle()` →
`build_analysis_result()`. `execute_post_analysis()` stores the result as the
run's persisted analysis.

| # | Step | Key Function(s) | Module | Purpose |
|---|------|-----------------|--------|---------|
| 1 | Validation | `_validate_required_strength_metrics` | `run_analysis.py` | Validate samples contain required strength metrics |
| 2 | Context preparation | `prepare_analysis_context` | `prepared_analysis_context.py` | Assemble the canonical typed `PreparedAnalysisContext` (sensor analysis, run suitability) from run metadata and prepared run data |
| 3 | Run preparation | `prepare_run_data`, `compute_run_timing`, `_run_noise_baseline_g` | run_data_preparation, statistics, `_sample_metrics.py` | Extract timing, speed stats, phase segmentation, and speed context |
| 4 | Phase segmentation | `segment_run_phases`, `_phase_summary`, `_speed_stats_by_phase` | phase_segmentation | Classify each sample into a driving phase (IDLE / ACCEL / CRUISE / DECEL / COAST_DOWN / SPEED_UNKNOWN) |
| 5 | Acceleration statistics | `compute_accel_statistics` | statistics | Per-axis and magnitude accel stats, saturation detection |
| 6 | Findings bundle | `build_findings_bundle` → `_build_findings` | `findings_bundle.py`, `_analysis_models.py`, findings, `peaks/findings.py`, `orders/pipeline.py` | Order tracking, pattern matching, scoring, localisation, and top-cause candidates via typed request/bundle contracts |
| 7 | Origin & test plan | `summarize_origin`, `build_phase_timeline` | `run_analysis.py`, run_data_preparation | Determine most likely vibration source, generate timeline |
| 8 | Top-cause selection | `select_top_causes`, `group_findings_by_source` | top_cause_selection | Rank findings by phase-adjusted score, group by source, apply drop-off threshold |
| 9 | Run suitability | `RunSuitability.evaluate` | `prepared_analysis_context.py`, `domain/run_suitability.py` | Check reference completeness plus data-quality and run-condition checks |
| 10 | Location analysis | `LocationAnalysisResult` | location_analysis | Per-location vibration intensity and spatial analysis |
| 11 | App-result construction | `build_analysis_result` | `_analysis_result_builder.py`, `_analysis_result.py` | Assemble `AnalysisResult`, `TestRun`, `DiagnosticCase`, diagnostics-local artifacts, and the rehydrated metadata payload needed for later boundary serialization |
| 12 | Peak table | `top_peaks_table_rows`, `annotate_peak_rows_with_order_labels` | `peaks/table.py` | Rank persistent spectral peaks and label them with matched order findings; persisted as `plots.peaks_table` for the PDF report |
| 13 | Boundary serialization | `analysis_result_to_summary`, `summarize_run_data`, `summarize_log` | `analysis/summary_payload.py`, `analysis/summarize.py` | Convert the app-level `AnalysisResult` into the persisted `AnalysisSummary` payload only at explicit edges |

## Data Flow

Summary analysis flow:

```text
Input: PostAnalysisRunInput (summary rows, FFT peaks recomputed from raw capture when available)
  │
  ├─ _run_input.build_diagnostics_run_input() → typed metadata + samples
  │
  ├─ run_data_preparation.prepare_run_data() → PreparedRunData
  │    ├─ timing, speed stats, noise baseline
  │    └─ phase_segmentation → phases + phase summaries
  │
  ├─ prepared_analysis_context.prepare_analysis_context() → PreparedAnalysisContext
  │
  ├─ findings_bundle.build_findings_bundle()
  │    ├─ FindingsBuildRequest / FindingsBundle → typed orchestration contracts
  │    ├─ peaks.findings.PeakFindingAnalyzer → peak-based findings
  │    ├─ orders.pipeline.OrderAnalysisSession → order-matched findings
  │    ├─ _reference_findings.build_reference_findings() → reference sufficiency findings
  │    ├─ finalize_findings() → enriched domain Finding objects
  │    └─ select_top_causes() → ranked top causes
  │
  ├─ _analysis_result_builder.build_analysis_result() → AnalysisResult/TestRun/DiagnosticCase
  │
  ├─ peaks.table.top_peaks_table_rows() → labeled peak table rows
  │    └─ serialize_peak_table() → persisted `plots.peaks_table`
  │
  └─ history_db.store_analysis() → PersistedAnalysis/report-facing summary
```

## Persisted Outputs

During `execute_post_analysis()`, `PostAnalysisWorker`:

1. Runs the summary analysis and adds `analysis_metadata` (sample count,
   sampling method, processing profile, raw-replay coverage, and fallback
   reasons).
2. Adds language-neutral trust warnings when the captured run context was
   incomplete for confident order analysis.
3. Stores the summary via `history_db.store_analysis()` as a versioned
   persistence envelope.

History readers unwrap the envelope back to the summary shape and stay
persistence-only; they never re-run diagnostics. Analyses stored by older
versions may still carry retired `whole_run_*` fields; the storage decoder
(`summary/persisted_codec.py`) drops them on load.
The core
history/report projection is derived from persisted run data plus the persisted
analysis summary only; any comparison against current mutable car settings is an
explicit advisory overlay at the history delivery boundary, not a hidden input
to the persisted projection or the default report cache path. Report endpoints
rebuild a `ReportDocument` from the persisted summary on demand via
`report/preparation.py:prepare_report_input()`, which
reconstructs the domain aggregate and assembles the prepared report handoff,
and `report/document/builder.py:build_report_document()`,
which performs the final document assembly before adapter-local PDF render
planning.

Persisted post-stop analysis strength/intensity outputs are dB-only.
Raw ingest/sample acceleration fields may still be expressed in g.

## Adding a New Analysis Step

1. Implement the step as a function in the appropriate module
   (or create a new one under `analysis/`).
2. Call it from `RunAnalysis.summarize()` at the correct point in the
   pipeline.
3. If the new output is needed by the renderer, persist it through the
   `summary/` contract, add any report-facing shaping in `report/` or
   `report/document/`, then update
   `build_report_document()` and `ReportDocument`. Keep semantic
   interpretation on the reporting-boundary side rather than in
   `report/pdf/*`.
4. Run `pytest apps/server/tests/` to verify tests still pass.
