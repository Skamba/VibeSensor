# Analysis Pipeline

This document describes the VibeSensor post-stop analysis pipeline:
its entrypoint, ordered steps, outputs, and architectural rules.

## Architectural Rules

1. **Analysis runs only once** — after a recording is stopped.
   Report rendering and API endpoints use persisted results.
2. **Single folder** — all analysis logic lives in
   `apps/server/vibesensor/analysis/`. No analysis helpers elsewhere.
3. **Single entrypoint** — `summarize_run_data()` is the primary
   pipeline function. All steps are called from there.
4. **Public API** — external code imports exclusively from
   `vibesensor.analysis` (the package `__init__.py`), never from
   sub-modules directly.
5. **Renderer-only report package** — `vibesensor.report` must not
   import from `vibesensor.analysis` (enforced by tests).
6. **No circular coupling** — the live signal-processing layer
   (`processing.py`) must not import from `analysis/`.

## Live Processing vs Post-Stop Analysis

The system has two distinct computational pipelines:

| | Live Processing (`processing.py`) | Post-Stop Analysis (`analysis/`) |
|-|-----------------------------------|----------------------------------|
| **When** | Continuously during recording (5–10 Hz) | Once, after recording stops |
| **Input** | Raw accelerometer frames from UDP | Stored sample records from history DB |
| **Output** | Per-tick metrics: FFT spectrum, peaks, strength_db, RMS, P2P | Diagnostic findings, rankings, reports |
| **Purpose** | Data acquisition — transform raw signals into structured metrics | Diagnostic reasoning — classify, rank, and explain vibration causes |
| **Stateless?** | Yes — each tick processes the current rolling window | Yes — processes all stored samples in one pass |

`processing.py` computes FFT spectra, peak detection, and vibration
strength metrics in real time.  These are **measurement steps** that
produce the sample records stored during recording.  The analysis
pipeline then reads those stored records and applies diagnostic
reasoning (pattern matching, order tracking, confidence scoring,
localisation) to produce findings and reports.

The mathematical primitives (e.g. `compute_vibration_strength_db`,
`noise_floor_amp_p20_g`) live in the shared `vibesensor_core` library
and are used by both layers — this is intentional code reuse, not
duplication.

### Live Diagnostics Preview

The `live_diagnostics.py` module calls `build_findings_for_samples()`
and `classify_sample_phase()` *during* recording to generate
real-time diagnostic feedback for the UI.  This is intentional code
reuse — the same analysis functions serve as a library for both
live preview and definitive post-stop analysis.

- **Live preview**: called every few seconds on a sliding window of
  recent samples.  Results are ephemeral (not persisted).
- **Definitive analysis**: called once after stop via
  `summarize_run_data()`.  Results are persisted and used for reports.

Only the definitive post-stop run produces the persisted analysis.
The live preview is a convenience feature that reuses analysis
functions but does not replace or duplicate the post-stop pipeline.

## Trigger Flow

```
stop_recording()                       # metrics_log.py
  └─ _schedule_post_analysis(run_id)   # enqueue to background thread
       └─ _analysis_worker_loop()      # daemon thread
            └─ _run_post_analysis(run_id)
                 ├─ read & downsample samples from history DB
                 ├─ summarize_run_data(…)   ← analysis entrypoint
                 ├─ map_summary(…)          ← build ReportTemplateData
                 └─ store_analysis(…)       ← persist results
```

## Pipeline Steps

`summarize_run_data()` in `analysis/summary.py` executes these steps
in order.  Each step runs exactly once per analysis invocation.

| # | Step | Key Function(s) | Purpose |
|---|------|-----------------|---------|
| 1 | Initialisation | `normalize_lang`, `_validate_required_strength_metrics` | Normalise language, validate that samples contain required strength metrics |
| 2 | Timing | `_compute_run_timing` | Extract run ID, start/end timestamps, duration |
| 3 | Speed statistics | `_speed_stats`, `_run_noise_baseline_g` | Compute speed distribution, noise baseline |
| 4 | Phase segmentation | `_segment_run_phases`, `_phase_summary`, `_speed_stats_by_phase` | Classify each sample into a driving phase (IDLE / ACCEL / CRUISE / DECEL / COAST_DOWN / SPEED_UNKNOWN) |
| 5 | Acceleration statistics | `_compute_accel_statistics` | Per-axis and magnitude accel stats, saturation detection |
| 6 | Speed breakdown | `_speed_breakdown`, `_phase_speed_breakdown` | Frequency binning by speed range and driving phase |
| 7 | Findings | `_build_findings` | Core diagnostic engine: order tracking, pattern matching, scoring, localisation |
| 8 | Origin & test plan | `_most_likely_origin_summary`, `_merge_test_plan`, `_build_phase_timeline` | Determine most likely vibration source, generate action plan, timeline |
| 9 | Reference completeness | (inline) | Check if tyre, engine, and sample-rate reference data are available |
| 10 | Top-cause selection | `select_top_causes` | Rank findings by phase-adjusted score, apply drop-off threshold |
| 11 | Run suitability | `_build_run_suitability_checks` | Data-quality and run-condition checks (steady speed, GPS, duration, etc.) |
| 12 | Sensor analysis | `_locations_connected_throughout_run`, `_sensor_intensity_by_location` | Per-location vibration intensity and connection stability |
| 13 | Summary construction | (inline dict) | Assemble all results into the summary dict |
| 14 | Plot generation | `_plot_data` | FFT aggregation, spectrogram, peak table |
| 15 | Peak annotation | `_annotate_peaks_with_order_labels` | Label peaks with human-readable order names |

## Persisted Outputs

After `summarize_run_data()` returns, the orchestrator in
`metrics_log.py`:

1. Adds `analysis_metadata` (sample count, stride info).
2. Calls `map_summary()` to convert the summary dict into a
   `ReportTemplateData` dataclass and embeds it as
   `_report_template_data`.
3. Stores the complete dict via `history_db.store_analysis()`.

Report endpoints read the persisted analysis and use
`_report_template_data` for PDF rendering without re-running analysis.

Persisted post-stop analysis strength/intensity outputs are dB-only. Raw ingest/sample
acceleration fields may still be expressed in g.

## Module Map

```
vibesensor/analysis/
├── __init__.py            Public API re-exports
├── summary.py             Pipeline entrypoint (summarize_run_data)
├── findings.py            Core findings engine, order tracking
├── order_analysis.py      Wheel/engine/driveshaft Hz helpers
├── phase_segmentation.py  Driving-phase classification
├── helpers.py             Constants, statistics, strength utils
├── strength_labels.py     dB → strength-band classification
├── test_plan.py           Action-plan generation
├── report_data_builder.py Summary dict → ReportTemplateData mapping
├── plot_data.py           FFT/spectrogram/peak-table payloads
└── pattern_parts.py       Pattern → likely-parts mapping
```

## Adding a New Analysis Step

1. Implement the step as a function in the appropriate analysis
   sub-module (or create a new one under `analysis/`).
2. Call it from `summarize_run_data()` at the correct point in the
   pipeline.  Each step should have clear inputs (prior step outputs
   or raw samples) and outputs (added to the summary dict).
3. If the new output is needed by the renderer, update
   `report_data_builder.py:map_summary()` and the
   `ReportTemplateData` dataclass.
4. Export any new public symbol from `analysis/__init__.py`.
5. Run `pytest apps/server/tests/test_analysis_architecture.py` to
   verify architectural guardrails still pass.
