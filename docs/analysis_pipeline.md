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
4. **Public API** — external code should prefer `vibesensor.analysis`
   for stable entrypoints such as `summarize_run_data()`, `map_summary()`,
   and `build_findings_for_samples()`.
5. **Renderer-only report package** — `vibesensor.report` must not
   import from `vibesensor.analysis` (enforced by tests).
6. **No circular coupling** — the live signal-processing layer
   (`processing/`) must not import from `analysis/`.

## Live Processing vs Post-Stop Analysis

The system has two distinct computational pipelines:

| | Live Processing (`processing/`) | Post-Stop Analysis (`analysis/`) |
|-|-----------------------------------|----------------------------------|
| **When** | Continuously during recording (5–10 Hz) | Once, after recording stops |
| **Input** | Raw accelerometer frames from UDP | Stored sample records from history DB |
| **Output** | Per-tick metrics: FFT spectrum, peaks, strength_db, RMS, P2P | Diagnostic findings, rankings, reports |
| **Purpose** | Data acquisition — transform raw signals into structured metrics | Diagnostic reasoning — classify, rank, and explain vibration causes |
| **Stateless?** | Yes — each tick processes the current rolling window | Yes — processes all stored samples in one pass |

`processing/` computes FFT spectra, peak detection, and vibration
strength metrics in real time.  These are **measurement steps** that
produce the sample records stored during recording.  The analysis
pipeline then reads those stored records and applies diagnostic
reasoning (pattern matching, order tracking, confidence scoring,
localisation) to produce findings and reports.

The mathematical primitives (e.g. `compute_vibration_strength_db`,
`noise_floor_amp_p20_g`) live in the shared `vibesensor_core` library
and are used by both layers — this is intentional code reuse, not
duplication.

### Live Dashboard Scope

The live dashboard is intentionally limited to the blended spectrum and
RPM/order-band overlays needed to interpret the current FFT view while
recording. Live WebSocket updates carry spectrum data, sensor/client
status, speed, and rotational band metadata only.

Definitive diagnostic reasoning still happens only after stop via
`summarize_run_data()`. Those results are persisted and used for
history, findings, and reports. Post-run analysis remains the single
source of truth for diagnostic output.

## Trigger Flow

```
stop_recording()                       # metrics_log/
  └─ session_state.py                  # explicit recording-session state
  └─ persistence.py                    # finalize current run + gate analysis scheduling
  └─ _schedule_post_analysis(run_id)   # enqueue to background thread
       └─ _analysis_worker_loop()      # daemon thread
            └─ _run_post_analysis(run_id)
                 ├─ read & downsample samples from history DB
                 ├─ summarize_run_data(…)   ← analysis entrypoint
                 ├─ map_summary(…)          ← build ReportTemplateData
                 └─ store_analysis(…)       ← persist results
```

## Pipeline Steps

`summarize_run_data()` in `analysis/summary_builder.py` executes these steps
in order. Each step runs exactly once per analysis invocation.

| # | Step | Key Function(s) | Purpose |
|---|------|-----------------|---------|
| 1 | Initialisation | `normalize_lang`, `_validate_required_strength_metrics` | Normalise language, validate that samples contain required strength metrics |
| 2 | Run preparation | `prepare_run_data`, `_compute_run_timing`, `_run_noise_baseline_g` | Extract timing, speed statistics, phase segmentation, and speed-breakdown context once |
| 4 | Phase segmentation | `_segment_run_phases`, `_phase_summary`, `_speed_stats_by_phase` | Classify each sample into a driving phase (IDLE / ACCEL / CRUISE / DECEL / COAST_DOWN / SPEED_UNKNOWN) |
| 5 | Acceleration statistics | `_compute_accel_statistics` | Per-axis and magnitude accel stats, saturation detection |
| 6 | Speed breakdown | `_speed_breakdown`, `_phase_speed_breakdown` | Frequency binning by speed range and driving phase |
| 7 | Findings | `build_findings_bundle`, `_build_findings` | Core diagnostic engine: order tracking, pattern matching, scoring, localisation |
| 8 | Origin & test plan | `summarize_origin`, `_merge_test_plan`, `_build_phase_timeline` | Determine most likely vibration source, generate action plan, timeline |
| 9 | Run suitability | `build_run_suitability_bundle`, `_build_run_suitability_checks`, `compute_reference_completeness` | Check reference completeness plus data-quality and run-condition checks |
| 10 | Top-cause selection | `select_top_causes`, `group_findings_by_source` | Rank findings by phase-adjusted score, group by source, apply drop-off threshold |
| 11 | Sensor analysis | `build_sensor_bundle`, `_sensor_intensity_by_location` | Per-location vibration intensity and connection stability |
| 13 | Summary construction | `build_summary_payload` | Assemble the final summary dict |
| 14 | Plot generation | `_plot_data`, `plot_series.py`, `plot_spectrum.py`, `plot_peak_table.py` | Build time/speed series, FFT aggregation, spectrograms, and peak table |
| 15 | Peak annotation | `_annotate_peaks_with_order_labels` | Label peaks with human-readable order names |

## Persisted Outputs

After `summarize_run_data()` returns, the metrics pipeline coordinated by
`metrics_log/logger.py` and `metrics_log/post_analysis.py`:

1. Adds `analysis_metadata` (sample count, stride info).
2. Adds language-neutral trust warnings in `summary["warnings"]`
   when the captured run context was incomplete for confident
   order analysis.
3. Stores the summary via `history_db.store_analysis()` as a
   versioned persistence envelope.

History readers unwrap the envelope back to the canonical summary shape.
Report endpoints rebuild `ReportTemplateData` from that summary on demand,
then add presentation-time warnings if the current active vehicle profile no
longer matches the one captured with the run.

Persisted post-stop analysis strength/intensity outputs are dB-only. Raw ingest/sample
acceleration fields may still be expressed in g.

## Module Map

- `__init__.py`: package-level public API re-exports.
- Summary orchestration: `summary_builder.py`, `summary_models.py`, `summary_phases.py`, `summary_suitability.py`, `summary_payload.py`.
- Finding selection and ranking: `findings/`, `ranking.py`, `top_cause_selection.py`.
- Domain helpers: `order_analysis.py`, `phase_segmentation.py`, `helpers.py`, `strength_labels.py`, `test_plan.py`, `pattern_parts.py`.
- Report mapping: `diagnosis_candidates.py`, `report_mapping_common.py`, `report_mapping_context.py`, `report_mapping_models.py`, `report_mapping_pipeline.py`, `report_mapping_actions.py`, `report_mapping_peaks.py`, `report_mapping_systems.py`.
- Plot shaping: `plot_data.py`, `plot_series.py`, `plot_spectrum.py`, `plot_peak_table.py`.

## Adding a New Analysis Step

1. Implement the step as a function in the appropriate analysis
   sub-module (or create a new one under `analysis/`).
2. Call it from `summarize_run_data()` at the correct point in the
   pipeline.  Each step should have clear inputs (prior step outputs
   or raw samples) and outputs (added to the summary dict).
3. If the new output is needed by the renderer, update
   `report_mapping_pipeline.py:map_summary()` and the
   `ReportTemplateData` dataclass.
4. Export any new public symbol from `analysis/__init__.py`.
5. Run `pytest apps/server/tests/analysis/test_analysis_architecture.py` to
   verify architectural guardrails still pass.
