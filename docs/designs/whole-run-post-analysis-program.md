# Whole-run post-analysis program

Scope: execution design for parent issues #3075, #3076, #3077, #3078, and
#3079, using the completed raw-capture work from #3065 as the foundation.

This document is a design and decomposition artifact, not an implementation
status log. It records the current architecture, the target architecture, the
shared contracts that must settle early, and the recommended execution order.

## Current state

### Live path

- Raw UDP samples enter through `apps/server/vibesensor/adapters/udp/udp_data_rx.py`.
- Live FFT/strength computation lives in `apps/server/vibesensor/infra/processing/`.
- The canonical spectrum window is `FFT_N = 2048` with a Hann window from
  `apps/server/vibesensor/shared/constants/dsp.py` and
  `apps/server/vibesensor/infra/processing/compute.py`.
- Live feature cadence is derived from `feature_interval_s`, which is currently
  written as `1 / metrics_log_hz` by
  `apps/server/vibesensor/use_cases/run/run_metadata_builder.py`.

### Run persistence and post-stop analysis

- `apps/server/vibesensor/use_cases/run/logger.py` finalizes a run and schedules
  `PostAnalysisWorker`.
- `apps/server/vibesensor/use_cases/run/post_analysis_loader.py` loads persisted
  samples for a run, but caps analysis input at `_MAX_POST_ANALYSIS_SAMPLES =
  12_000` and applies an upfront stride when the run is longer.
- `apps/server/vibesensor/use_cases/run/raw_capture_replay.py` uses raw capture
  only to rebuild FFT-derived metrics for those already-persisted summary rows.
- `apps/server/vibesensor/use_cases/diagnostics/run_analysis.py` and
  `analysis_pipeline.py` still operate on summary-style `SensorFrame` samples,
  not on a true full-run raw-window graph.

### Raw capture from #3065

- Raw artifacts are already stored separately from `samples_v2`.
- The canonical storage contract is
  `apps/server/vibesensor/shared/types/raw_capture.py`:
  - `RawCaptureManifest`
  - `RawCaptureSensorManifest`
  - `RawCaptureChunkIndex`
  - `RawRunCapture`
- Persistence uses `data/raw-runs/{run_id}/` with per-sensor
  `.raw.i16le` and `.index.jsonl` files via
  `apps/server/vibesensor/adapters/persistence/history_db/_raw_capture_store.py`.
- Whole-run foundations now include indexed raw range reads via
  `RunPersistence.aload_raw_capture_sensor_range(...)`, but there is still no
  canonical offline executor that walks the full run as a deterministic window
  graph.

### Persisted analysis and reporting

- `apps/server/vibesensor/shared/types/history_analysis_contracts.py` owns the
  outward persisted analysis/report payload shape.
- `apps/server/vibesensor/shared/types/persisted_analysis.py` wraps that JSON as
  `PersistedAnalysis`.
- Report preparation in `apps/server/vibesensor/shared/boundaries/reporting/`
  does not re-run diagnostics; it interprets persisted analysis only.
- `apps/server/vibesensor/use_cases/history/report_document/` composes the final
  `ReportDocument`, and `adapters/pdf` only renders it.

## Why the current path is insufficient

The current architecture already has strong raw capture and a stable
reporting boundary, but it still has four blocking limitations for whole-run
offline analysis:

1. **No full-run raw window engine.** Raw capture is only used to rehydrate the
   FFT-derived fields of summary rows, not to analyze the full run as a
   deterministic window graph.
2. **Long runs are sample-capped.** `post_analysis_loader.py` strides the input
   once a run exceeds 12k persisted rows, which is incompatible with
   whole-run trace continuity.
3. **Summary-shaped contracts dominate.** Orders, phases, and location proof are
   still derived from per-sample peak summaries and matched points instead of
   first-class whole-run artifacts.
4. **Persisted analysis JSON is the wrong place for heavy artifacts.** The
   report/history path should keep consuming compact summary objects, not
   tens of thousands of per-window spectra or traces.

## Target architecture

The target shape keeps the current one-time post-stop analysis model, but adds
an internal whole-run artifact layer between raw capture and persisted
diagnosis/report summaries.

```text
raw capture manifest/files (#3065)
  -> indexed range/window reader
  -> deterministic window planner
  -> raw-window spectral executor
  -> context timeline + segment labels
  -> order traces / harmonic summaries
  -> multi-sensor coherence + spatial evidence
  -> evidence fusion + diagnosis ranking
  -> compact persisted analysis summary + report-facing facts
  -> history/report/PDF (no re-analysis)
```

### Layer responsibilities

| Layer | Owner area | Responsibility |
|---|---|---|
| Raw artifact access | `adapters/persistence/history_db/`, `shared/types/raw_capture.py` | Range reads and manifest-aware raw loading without changing the hot write path |
| Window planning | `use_cases/diagnostics/` | Derive a deterministic whole-run window grid from run metadata |
| Whole-run spectra | `use_cases/diagnostics/`, `shared/fft_analysis.py`, `infra/processing/` | Reuse canonical shared FFT/strength primitives to compute per-window spectral outputs without `use_cases -> infra` coupling |
| Context timeline | `use_cases/diagnostics/`, `shared/types/` | Normalize speed/RPM/context into per-window labels and segments |
| Order traces | `use_cases/diagnostics/orders/` | Track candidate orders across the full run and summarize harmonic stability |
| Spatial evidence | `use_cases/diagnostics/` | Measure cross-sensor agreement, coherence, and location separation |
| Fusion/report summary | `use_cases/diagnostics/`, `shared/boundaries/reporting/` | Convert whole-run evidence into ranked diagnoses and compact persisted facts |

## Early design decisions

### Raw artifact shape

Keep the #3065 raw artifact format as the canonical ingest-time storage model:

- `RawCaptureManifest` in the `runs` row
- `data/raw-runs/{run_id}/`
- per-sensor `.raw.i16le`
- per-sensor `.index.jsonl`

Do **not** introduce a second ingest format for whole-run analysis. Add an
indexed range/window reader on top of the current store instead.

### Canonical whole-run window policy

Whole-run analysis should default to the same spectral semantics the live path
already records in metadata:

- **window size** = `RunMetadata.fft_window_size_samples`
- **stride** = `RunMetadata.feature_interval_s * RunMetadata.raw_sample_rate_hz`
- **overlap** = `window_size - stride`
- **integrality rule** = `feature_interval_s * raw_sample_rate_hz` must resolve to
  an integral sample stride; reject non-integral stride metadata instead of
  silently drifting window alignment

With current defaults this means:

- `fft_window_size_samples = 2048`
- `feature_interval_s = 0.25`
- `raw_sample_rate_hz = 800`
- stride = `200` samples
- overlap = `1848` samples (~90.2%)

This preserves one canonical DSP interpretation and keeps whole-run outputs
aligned with existing summary rows and report timing expectations.

### What to persist vs recompute

Persist heavy whole-run artifacts outside `analysis_json`.

- **Persist in compact summary JSON (`PersistedAnalysis`)**
  - top diagnosis summaries
  - supporting-window counts and durations
  - stable frequency bands
  - phase/context summaries
  - order-trace summaries
  - spatial/coherence summaries
  - support/counterevidence factor keys
  - exemplar windows or intervals needed for reporting
- **Persist in sidecar artifact storage**
  - per-window spectral outputs
  - dense order traces
  - per-candidate cross-sensor matrices
  - any high-cardinality debug/trace data
- **Recompute from raw capture only when explicitly needed**
  - full spectra/spectrograms beyond persisted summaries
  - experimental diagnostics not part of the canonical report/history path

### Join strategy across windows, context, orders, and sensors

The canonical join key should be a deterministic run-level `window_index`
defined by the window planner. Every downstream artifact should be keyed by:

- `run_id`
- `window_index`
- `sensor_id` or sensor location when applicable

Each `window_index` should also carry:

- `sample_start`
- `sample_end`
- `center_sample`
- `start_t_s`
- `end_t_s`
- `center_t_s`

Context segments then refer to window index ranges, and order/spatial/fusion
layers join against the same key instead of ad hoc timestamp matching.

The canonical planner now lives in
`apps/server/vibesensor/use_cases/diagnostics/whole_run_windows.py` and uses an
explicit **drop incomplete trailing windows** policy. Runs shorter than one FFT
window produce an empty grid instead of padded or synthetic windows.

### Order-trace contract

Whole-run order tracking should separate dense trace points from persisted
summaries.

- **Dense trace point**
  - `candidate_key`
  - `window_index`
  - `sensor_id`
  - `predicted_hz`
  - `observed_hz`
  - `relative_error`
  - `amplitude_g` or derived dB
  - `snr_db`
  - `support_state`
  - `phase_key`
- **Persisted summary**
  - support ratio
  - contiguous support intervals
  - harmonic support counts
  - phase-specific support
  - stable frequency/order bounds
  - top supporting locations

### Spatial/coherence contract

Spatial evidence should not be just a whole-run `p95` intensity table. It
should explicitly separate:

- candidate-specific supporting windows
- per-window per-sensor support
- cross-sensor agreement/coherence summary
- location separation in dB
- ambiguity flags when the leading location is too close to the next best

The report path can still project compact location proof from these summaries,
but the source artifact should be candidate-aware and whole-run aware.

### Counterevidence model

Counterevidence should become a first-class persisted concept with stable keys,
not just renderer-time prose. Good initial keys fit the current
`confidence_facts.py` vocabulary:

- `summary_only`
- `sparse_support`
- `brief_support`
- `drifting_frequency`
- `loose_order_lock`
- `mixed_support_locations`
- `weak_spatial`
- `close_alternative`
- `incomplete_reference`
- `noisy_signal`

Whole-run fusion can add new stable keys, but should continue producing compact,
explainable factors that reporting can consume directly.

## Shared contracts to settle early

| Contract | Suggested owner | Notes |
|---|---|---|
| `WholeRunWindowPolicy` / `WholeRunWindowDescriptor` | `apps/server/vibesensor/shared/types/whole_run_analysis.py` | Canonical sample-space policy and deterministic window identity for every later whole-run stage |
| `WholeRunWindowPlan` / `plan_whole_run_windows(...)` | `apps/server/vibesensor/use_cases/diagnostics/whole_run_windows.py` | Deterministic window grid planner with explicit trailing-window policy |
| `WholeRunWindowSpectralSummary` | `use_cases/diagnostics/` with compact persisted projection | Per-window FFT/strength/top-peak outputs |
| `WholeRunArtifactManifest` | `apps/server/vibesensor/shared/types/whole_run_analysis.py` + `apps/server/vibesensor/adapters/persistence/history_db/_whole_run_artifact_store.py` | Sidecar manifest for dense whole-run artifacts; mirror the raw-capture pattern |
| `WholeRunContextInterval` / `WholeRunContextWindowLabel` | `apps/server/vibesensor/shared/types/whole_run_analysis.py` with compact report-facing projection in `shared/types/history_analysis_contracts.py` | Whole-run segments and per-window labels keyed to the canonical `window_index` grid |
| `OrderTracePoint` / `OrderTraceSummary` | `use_cases/diagnostics/orders/` with persisted summary projection | Dense trace vs compact report/history summary split |
| `SpatialEvidenceSummary` | `use_cases/diagnostics/` with persisted summary projection | Candidate-level coherence and location separation |
| `DiagnosisFactor` / `DiagnosisSummary` | diagnostics domain/use-case layer plus persisted projection | Explainable support and counterevidence for final ranking |

For the context track:

1. `WholeRunContextWindowLabel` is the dense internal join surface for later
   order, spatial, and fusion work. It carries explicit `context_coverage`,
   `speed_validity`, `rpm_validity`, `load_state`, and optional raw context
   values/source labels keyed by `window_index`.
2. `WholeRunContextInterval` is the compact segment summary surface. It uses
   `start_window_index` / `end_window_index` as the canonical range identity and
   can be projected later into persisted analysis/report payloads without
   forcing report consumers to load every window label.
3. Report-facing persisted summaries should keep only compact segment fields and
   coarse completeness signals. Dense per-window labels remain sidecar/internal
   artifacts unless a future consumer proves otherwise.

## Persistence strategy

The current `runs.analysis_json` payload should stay compact and report-facing.

Current foundation:

1. `apps/server/vibesensor/adapters/persistence/history_db/_whole_run_artifact_store.py`
   mirrors `HistoryRawCaptureStore` with a deterministic
   `data/whole-run-artifacts/{run_id}/` sidecar layout.
2. The `runs` row now carries `whole_run_artifact_manifest_json`, and
   `StoredHistoryRun` exposes that manifest as
   `whole_run_artifact_manifest`.

Recommended follow-on behavior:

1. Keep `PersistedAnalysis` as the stable history/report summary boundary.
2. Store only compact summaries and exemplars in `PersistedAnalysis`.
3. Use the whole-run sidecar only for dense artifacts such as spectra, traces,
   matrices, and debug payloads.

This keeps legacy report loading cheap and avoids turning the history DB blob
into a large binary transport.

## Performance and determinism

### Likely hot spots

- **I/O-bound**
  - reading raw capture windows
  - writing dense whole-run artifact sidecars
- **CPU-bound**
  - per-window FFT/strength computation
  - order-trace evaluation
  - multi-sensor coherence scoring
  - fusion across many candidates
- **Memory-bound**
  - any design that loads full raw arrays for long multi-sensor runs
  - retaining dense spectra for all windows in memory at once

### Deterministic rules

Whole-run execution should guarantee:

1. the same raw input yields the same window grid
2. reducers persist artifacts in stable sort order
3. parallel workers never decide ordering implicitly
4. tie-breaking is explicit by stable keys (candidate key, location, window index)
5. floating-point reductions are gathered in a deterministic order before
   persistence

### Parallelization guidance

Use existing bounded concurrency infrastructure from
`apps/server/vibesensor/infra/workers/worker_pool.py` where it fits.

Safe parallel boundaries:

- per-sensor raw range reads
- per-chunk spectral computation after window planning is fixed
- per-candidate order trace scoring after spectral artifacts and context labels exist
- per-candidate spatial scoring after aligned multi-sensor artifacts exist
- per-diagnosis fusion after upstream summaries are stable

Keep these sequential:

- raw manifest finalization
- global window planning
- final persisted artifact ordering and serialization

## Test strategy

### Reuse existing seams

- `apps/server/tests/adapters/persistence/history_db/test_history_db_raw_capture.py`
- `apps/server/tests/use_cases/run/test_post_analysis_loader.py`
- `apps/server/tests/use_cases/diagnostics/test_phase_segmentation.py`
- `apps/server/tests/use_cases/diagnostics/test_analysis_pipeline_integration_regressions.py`
- `apps/server/tests/use_cases/history/test_report_confidence_facts.py`
- report separation guardrails in the PDF/history test suites

### Add new coverage

- raw range-reader unit tests over chunk boundaries
- deterministic window-planner tests
- whole-run spectral executor regression tests
- context timeline tests with missing speed/RPM spans
- order-trace synthetic scenarios with speed variation and harmonic changes
- spatial/coherence scenarios for clear hotspot vs ambiguous location
- fusion scenarios for clear, mixed, summary-only, and counterevidence-heavy runs

## Benchmark strategy

Reuse the existing explicit benchmark style:

- `apps/server/tests/infra/workers/benchmark_compute_all.py`
- `apps/server/tests/infra/processing/benchmark_rfft_backend.py`
- `apps/server/tests/use_cases/diagnostics/benchmark_whole_run_spectra.py`

Add opt-in benchmarks for:

- raw range-reader throughput
- whole-run spectral executor throughput by sensor count and run length
- worker-pool scaling vs sequential execution on Pi-sized datasets
- order-trace evaluation cost by candidate family count
- spatial/coherence cost by sensor count
- end-to-end whole-run analysis memory peak on long runs

Current #3085 baseline:

- `benchmark_whole_run_spectra.py` uses a 5-minute, 4-sensor, 800 Hz raw-capture fixture with `FFT_N=2048` and `feature_interval_s=1.0`.
- The validated `make benchmark-backend` sweep showed the executor fastest in sequential mode with `max_workers=1` and `chunk_window_count=32` (mean ~547 ms) versus slower 4-worker runs at chunk sizes 64 (~586 ms), 32 (~622 ms), and 16 (~668 ms).
- The raw range-reader baseline for one full window sweep over one sensor was ~371 ms.
- Keep the default executor settings at `max_workers=1`, `chunk_window_count=32`, and rerun the explicit benchmark on target hardware before raising worker count.

## Summary-only and legacy fallback policy

- If raw capture is absent, preserve the current summary-only diagnostics/report
  path.
- If raw capture exists but whole-run artifacts do not, continue to support the
  current raw-backed replay behavior instead of failing the run.
- Legacy persisted analyses must remain readable by history/report code.
- New whole-run report facts should degrade to existing summary-only language and
  confidence caveats where necessary.

## Recommended implementation order

1. Settle whole-run window contracts and sidecar artifact persistence.
2. Add indexed raw range reads and the deterministic window planner.
3. Build the raw-window spectral executor and benchmark it.
4. Build the context timeline and segment labeling on the same window grid.
5. Build order tracking and spatial/coherence in parallel on top of the shared
   spectral/context artifacts.
6. Build fusion, counterevidence, persisted diagnosis summaries, and report
   wiring last.

## Planned sub-issue breakdown

### Parent #3075 — whole-run engine

1. #3080 Define deterministic whole-run window contracts and artifact manifest
2. #3081 Add indexed raw-capture range reads for offline window analysis
3. #3082 Build the canonical whole-run window planner from run metadata
4. #3083 Add a file-backed whole-run analysis artifact store and manifest plumbing
5. #3084 Implement the raw-window spectral executor with deterministic chunk scheduling
   - Landed locally on branch `issue-3084-spectral-executor`: deterministic chunk ordering, shared FFT primitive extraction into `vibesensor.shared.fft_analysis`, per-sensor `.npy` grid/matrix artifacts, per-window `.jsonl` summaries with explicit coverage states, and post-analysis manifest persistence plumbing.
6. #3085 Benchmark the whole-run engine on Pi-sized runs

### Parent #3076 — phase segmentation and context timelines

1. #3086 Define whole-run context timeline and segment contracts
2. #3087 Normalize full-run speed and RPM context onto the window grid
3. #3088 Implement whole-run phase segmentation over normalized timelines
4. #3089 Persist segment timelines and per-window context labels
5. #3090 Surface context completeness and fallback signals to history and report consumers

### Parent #3077 — order tracking and harmonic stability

1. #3091 Define whole-run order-trace and harmonic evidence contracts
2. #3092 Build per-candidate order traces from window spectra and context labels
3. #3093 Add harmonic stability and order-lock scoring across the full run
4. #3094 Summarize order traces by source family, phase, and support intervals
5. #3095 Persist ranked order-trace summaries and exemplars for downstream fusion

### Parent #3078 — multi-sensor coherence and spatial evidence

1. #3096 Define multi-sensor coherence and spatial evidence contracts
2. #3097 Join aligned per-window sensor outputs with coverage and missing-data rules
3. #3098 Implement candidate-level coherence and cross-sensor agreement metrics
4. #3099 Implement spatial separation and supporting-window hotspot summaries
5. #3100 Persist spatial evidence and proof-basis summaries for downstream fusion

### Parent #3079 — fusion, counterevidence, and diagnosis ranking

1. #3101 Define persisted whole-run evidence fusion and diagnosis summary contracts
2. #3102 Model support factors and counterevidence factors with stable keys
3. #3103 Implement the diagnosis ranker over context, order, and spatial evidence
4. #3104 Add summary-only and partial-artifact fallback scoring for legacy runs
5. #3105 Expose fused diagnosis evidence through history and report preparation and PDF surfaces
6. #3106 Add cross-scenario regression coverage for clear, mixed, and ambiguous whole-run diagnoses
