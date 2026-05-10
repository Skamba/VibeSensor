# Whole-run post-analysis program

> **Status:** Active
> **Use:** Current source-of-truth architecture guidance for whole-run
> post-analysis. Follow this document for current owners, contracts, and design
> constraints.
> **Historical record:**
> `docs/designs/whole-run-post-analysis-history.md` keeps old issue plans,
> branch notes, and benchmark snapshots for reference only.

This document records the implemented architecture, the remaining debt, and the
shared contracts that must stay stable. Completed checklist items are kept only
as historical context; current execution status lives in the code paths named
below.

## Current state

### Live path

- Raw UDP samples enter through `apps/server/vibesensor/adapters/udp/udp_data_rx.py`.
- Live FFT/strength coordination lives in
  `apps/server/vibesensor/infra/processing/compute.py`.
- The canonical spectrum window is `FFT_N = 2048`; shared spectral primitives
  live in `apps/server/vibesensor/shared/fft_analysis.py` with DSP constants in
  `apps/server/vibesensor/shared/constants/dsp.py`.
- Live feature cadence is derived from `feature_interval_s`, which is currently
  written as `1 / metrics_log_hz` by
  `apps/server/vibesensor/use_cases/run/run_metadata_builder.py`.

### Run persistence and post-stop analysis

- `apps/server/vibesensor/use_cases/run/logger.py` finalizes a run and schedules
   `PostAnalysisWorker`.
- `apps/server/vibesensor/use_cases/run/post_analysis_loader.py` loads persisted
   samples for a run, caps compact analysis input at `_MAX_POST_ANALYSIS_SAMPLES =
   12_000`, and applies event-preserving sampling when needed. Compact summary
   replay may still use a full `RawRunCapture`; whole-run spectra do not.
- `apps/server/vibesensor/use_cases/run/raw_capture_replay.py` uses raw capture
   only to rebuild FFT-derived metrics for those already-persisted summary rows.
- `apps/server/vibesensor/use_cases/run/post_analysis_executor.py` is the
   canonical offline executor. `PostAnalysisExecutionRunner` owns the
   declarative top-level stage order, using `PostAnalysisExecutionConfig` for
   loader/runner/builder dependencies:
  `LoadRunStage`, `BuildPostAnalysisInputStage`,
  `BuildWholeRunSpectraStage`, `BuildWholeRunContextStage`,
  `BuildOrderTraceStage`, `BuildOrderTraceSummaryStage`,
  `BuildOrderFamilySummaryStage`, `BuildSpatialSummaryStage`,
  `PersistArtifactsStage`, `BuildReportFactsStage`, and
  `PersistAnalysisSummaryStage`.
- `apps/server/vibesensor/use_cases/diagnostics/run_analysis.py` and
  `analysis_pipeline.py` still provide the compact summary/report-facing
  analysis path over summary-style `SensorFrame` samples.

### Raw capture and dense sidecars

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
- Indexed raw range reads exist through
   `RunPersistence.aload_raw_capture_sensor_range(...)`.
- The current connected dense sidecar path is owned by
  `apps/server/vibesensor/use_cases/run/post_analysis_whole_run_builders.py` and
  the `whole_run_*` diagnostics modules:
  - `whole_run_spectra.py` builds deterministic whole-run spectral sidecars from
    `RawCaptureManifest` plus bounded raw range reads, emitting spectral
    grids/matrices plus per-window compact spectral summaries.
  - `whole_run_context.py` labels the same window grid with speed/RPM/reference
    context and persists compact context intervals in `analysis_json`.
  - `orders/whole_run_traces.py` builds dense order trace points from
    `spectral-summary:*` sidecars and context labels.
  - `orders/whole_run_scoring.py` collapses dense traces into compact lock and
    stability summaries.
  - `orders/whole_run_family_summaries.py` rolls scored harmonic traces up to
    family-level support intervals and phase summaries.
  - `whole_run_spatial_coherence.py` builds candidate-level spatial evidence
    windows and compact spatial summaries.
- `apps/server/vibesensor/adapters/persistence/history_db/_whole_run_artifact_store.py`
  persists dense sidecar artifacts under `data/whole-run-artifacts/{run_id}/`.
- The older `post_run_*` modules remain useful support/prototype code for legacy
   dense DTOs and alternate bounded-window iteration, but they are not the
   currently connected sidecar pipeline in `execute_post_analysis()`.

### Persisted analysis and reporting

- `apps/server/vibesensor/shared/types/history_analysis_contracts.py` owns the
  outward persisted analysis/report payload shape.
- `apps/server/vibesensor/shared/types/persisted_analysis.py` wraps that JSON as
  `PersistedAnalysis`.
- Report preparation in `apps/server/vibesensor/shared/boundaries/reporting/`
  does not re-run diagnostics; it interprets persisted analysis only.
- `apps/server/vibesensor/use_cases/history/report_document/` composes the final
  `ReportDocument`, and `adapters/pdf` only renders it.

## Remaining debt

The current architecture has raw capture, a canonical executor, dense sidecar
persistence, whole-run spectra/context/order/spatial stages, and compact
report-facing summaries. Remaining debt is narrower:

1. **Summary-era compatibility remains.** The compact `RunAnalysis` path over
   summary rows still builds the report-facing baseline. Whole-run summaries are
   projected into that persisted analysis, but legacy `Finding` narratives remain
   a fallback when fused whole-run diagnosis summaries are absent.
2. **Compact raw replay still materializes raw capture.** Summary-row replay may
   still use the optional full `RawRunCapture`; keep it separate from the
   bounded range-read whole-run sidecar executor.
3. **Dense sidecars are write-mostly.** History/report consumers intentionally
   read compact summaries and manifests. Sidecar readback is limited to explicit
   internal needs; adding new report surfaces should still project compact
   summaries first instead of loading dense matrices during render.
4. **Fusion should stay compact.** Future diagnosis/fusion refinements must keep
   `PersistedAnalysis` report-facing and store any dense evidence as sidecars.

## Implemented architecture and current direction

The implemented shape keeps the one-time post-stop analysis model and adds an
internal whole-run artifact layer between raw capture and persisted
diagnosis/report summaries.

```text
raw capture manifest/files (#3065)
  -> bounded raw range reads for whole-run spectra
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
| Window planning | `use_cases/diagnostics/` | Derive a deterministic whole-run window grid from run metadata; `whole_run_spectra.py` resolves each window to bounded raw range reads |
| Whole-run spectra/features | `apps/server/vibesensor/use_cases/diagnostics/`, `apps/server/vibesensor/shared/fft_analysis.py`, `apps/server/vibesensor/vibration_strength.py` | Reuse canonical shared FFT/strength primitives to compute per-window spectral outputs without `use_cases -> infra` coupling; `post_run_stft.py`, `post_run_window_features.py`, and `post_run_vibration_episodes.py` remain support/prototype seams |
| Context timeline | `use_cases/diagnostics/`, `shared/types/` | Normalize speed/RPM/context into per-window labels and segments; `post_run_vehicle_reference.py` owns the conservative vehicle-reference timeline for dense stages |
| Order traces | `use_cases/diagnostics/orders/` | Track candidate orders across the full run and summarize harmonic stability; `post_run_order_bands.py` owns the pre-classification per-window expected band grid |
| Spatial evidence | `use_cases/diagnostics/` | Measure cross-sensor agreement, coherence, and location separation |
| Fusion/report summary | `use_cases/diagnostics/`, `shared/boundaries/reporting/` | Convert whole-run evidence into ranked diagnoses and compact persisted facts; `post_run_dense_findings.py` owns the first compact episode/order fusion DTO and compatibility projection |

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
  - `hypothesis_key`
  - `harmonic`
  - `window_index`
  - `eligible` / `matched`
  - `predicted_hz`
  - `matched_hz`
  - `relative_error`
  - `peak_intensity_db`
  - `vibration_strength_db`
  - `ref_source`
  - `strongest_location`
- **Persisted summary**
  - support ratio
  - reference coverage ratio
  - contiguous support ratio
  - drift score and lock score
  - contiguous support intervals
  - harmonic support counts
  - phase-specific support
  - stable frequency/order bounds
  - top supporting locations

The dense generation owner now lives in
`apps/server/vibesensor/use_cases/diagnostics/orders/whole_run_traces.py`. It
reuses `OrderHypothesis.predicted_hz(...)` from `orders/physics.py` and the
shared `best_order_peak_match()` tolerance logic from `orders/matching.py`, so
whole-run traces stay aligned with the current live/sample order model.

The current scoring owner is
`apps/server/vibesensor/use_cases/diagnostics/orders/whole_run_scoring.py`. It
derives deterministic per-candidate `OrderTraceSummary` rows from the dense
trace points, keeps `support_intervals` and `phase_support` empty until the
later summarization issue lands, and already projects the compact stability
fields that later ranking and persistence work need:

- `reference_coverage_ratio`
- `contiguous_support_ratio`
- `relative_error_stddev`
- `drift_score`
- `lock_score`

The current family-summary owner is
`apps/server/vibesensor/use_cases/diagnostics/orders/whole_run_family_summaries.py`.
It consumes the dense trace points plus the per-candidate scored summaries from
`whole_run_scoring.py`, then emits compact source-family summaries with:

- deterministic `support_intervals`
- per-phase `phase_support`
- `stable_frequency_min_hz` / `stable_frequency_max_hz`
- `exemplar_interval_index`

Those family summaries now feed a ranked persisted
`whole_run_order_summaries` payload in `PersistedAnalysis`, while the dense
trace and intermediate summary layers stay sidecar-only. History/report reload
paths should consume that compact persisted payload without requiring dense trace
loads.

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

The current contract owner is
`apps/server/vibesensor/use_cases/diagnostics/spatial_evidence_contracts.py`.
It now settles:

- dense `SpatialEvidenceWindow` rows keyed by
  `(candidate_key, window_index, sensor_id)` for later aligned sensor joins
- compact `SpatialLocationSummary` rows for dominant / runner-up location proof
- compact `SpatialEvidenceSummary` rows for persisted/report-facing proof with
  `proof_basis`, `location_separation_db`, `dominance_ratio`,
  `ambiguous_location`, and `weak_spatial_separation`

`shared/types/history_analysis_contracts.py` now owns the future persisted
response shapes for those compact summaries, and
`shared/boundaries/reporting/sensor_facts.py` uses the same
`LocationProofBasis` literal set so later report wiring does not invent a
second proof-basis vocabulary.

The aligned multi-sensor join owner now lives in
`apps/server/vibesensor/use_cases/diagnostics/whole_run_spatial_alignment.py`.
It builds deterministic `window_index`-ordered joins from persisted
`spectral-summary:*` sidecars plus `WholeRunContextWindowLabel` rows, keeps
sensor ordering canonical by `sensor_id`, and exposes explicit
`full` / `partial` / `empty` / `missing` coverage counts per window so later
coherence and hotspot scoring stages do not have to infer missing-data rules
ad hoc.

Candidate-level coherence now builds on that aligned matrix plus the existing
whole-run order trace catalog in
`apps/server/vibesensor/use_cases/diagnostics/whole_run_spatial_coherence.py`.
That stage reuses `OrderTracePoint.hypothesis_key` as the candidate identity,
scores cross-sensor agreement with the same order tolerance logic already used
by `orders/matching.py`, emits dense `SpatialEvidenceWindow` rows to a
`spatial-coherence-windows` sidecar, and now also builds compact
`SpatialLocationSummary` / `SpatialEvidenceSummary` hotspot outputs with
dominant location, runner-up, location separation, and weak/ambiguous flags
derived from supporting-window evidence.

### Counterevidence and support factor model

Support and counterevidence now use one shared persisted vocabulary instead of
renderer-only prose. The canonical owner is the combination of:

- `apps/server/vibesensor/use_cases/diagnostics/whole_run_diagnosis_contracts.py`
  for compact persisted diagnosis rows
- `apps/server/vibesensor/shared/types/history_analysis_contracts.py` for the
  outward history/report/schema contract
- `apps/server/vibesensor/shared/boundaries/reporting/confidence_facts.py` for
  the projection from the existing report-confidence thresholds and score deltas
  into stable factor rows

The current stable support keys are:

- `raw_backed`
- `repeated_support`
- `sustained_support`
- `stable_frequency`
- `tight_order_lock`
- `localized_support`
- `clean_signal`

The current stable counterevidence keys are:

- `summary_only`
- `legacy_context`
- `speed_context_gaps`
- `rpm_context_gaps`
- `sparse_support`
- `brief_support`
- `drifting_frequency`
- `loose_order_lock`
- `mixed_support_locations`
- `noisy_signal`
- `weak_spatial`
- `close_alternative`
- `incomplete_reference`

Each factor row carries stable key, polarity, severity, numeric weight, and a
typed details payload so later fusion/report work can explain why a diagnosis
ranked where it did without reparsing report prose.

The contract owner for the fused output should now live in
`apps/server/vibesensor/use_cases/diagnostics/whole_run_diagnosis_contracts.py`.
That layer should settle:

- compact `WholeRunDiagnosisSummary` rows persisted as
  `whole_run_diagnosis_summaries`
- structured `DiagnosisExemplarReference` links back to compact order support
  intervals, spatial hotspot rows, and context intervals already persisted
  elsewhere
- explicit top-level ambiguity, suspicious-case, and fallback markers that later
  report/history consumers can project without inventing a second diagnosis
  wrapper
- typed `support_factors` and `counterevidence_factors` rows built from the same
  thresholds and score deltas already used by `ReportConfidenceFacts`, so the
  fused whole-run path does not drift from current report confidence semantics

The actual ranker should live alongside that contract in
`apps/server/vibesensor/use_cases/diagnostics/whole_run_diagnosis_ranking.py`.
Its first job is to join persisted `OrderTraceSummary`,
`SpatialEvidenceSummary`, and `WholeRunContextInterval` rows by candidate key
and segment context, then feed normalized signal inputs through the shared
non-fallback scorer in
`apps/server/vibesensor/shared/boundaries/reporting/confidence_facts.py`. That
keeps whole-run ranking and the current report-confidence caveat language on one
scoring path instead of creating a second threshold table.

## Shared contracts to settle early

| Contract | Suggested owner | Notes |
|---|---|---|
| `WholeRunWindowPolicy` / `WholeRunWindowDescriptor` | `apps/server/vibesensor/shared/types/whole_run_analysis.py` | Canonical sample-space policy and deterministic window identity for every later whole-run stage |
| `WholeRunWindowPlan` / `plan_whole_run_windows(...)` | `apps/server/vibesensor/use_cases/diagnostics/whole_run_windows.py` | Deterministic window grid planner with explicit trailing-window policy |
| `WholeRunWindowSpectralSummary` | `use_cases/diagnostics/` with compact persisted projection | Per-window FFT/strength/top-peak outputs |
| `WholeRunArtifactManifest` | `apps/server/vibesensor/shared/types/whole_run_analysis.py` + `apps/server/vibesensor/adapters/persistence/history_db/_whole_run_artifact_store.py` | Sidecar manifest for dense whole-run artifacts; mirror the raw-capture pattern |
| `WholeRunContextInterval` / `WholeRunContextWindowLabel` | `apps/server/vibesensor/shared/types/whole_run_analysis.py` with compact report-facing projection in `shared/types/history_analysis_contracts.py` | Whole-run segments and per-window labels keyed to the canonical `window_index` grid |
| `OrderTracePoint` / `OrderTraceSummary` | `apps/server/vibesensor/use_cases/diagnostics/orders/whole_run_contracts.py` with persisted summary projection in `shared/types/history_analysis_contracts.py` | Dense trace vs compact report/history summary split |
| `SpatialEvidenceSummary` | `apps/server/vibesensor/use_cases/diagnostics/spatial_evidence_contracts.py` with persisted summary projection in `shared/types/history_analysis_contracts.py` | Candidate-level coherence, location separation, ambiguity flags, and proof basis |
| `WholeRunSpatialAlignmentMatrix` / `AlignedSpatialWindow` | `apps/server/vibesensor/use_cases/diagnostics/whole_run_spatial_alignment.py` | Deterministic per-window sensor joins with explicit coverage-state semantics for later spatial scoring |
| `DiagnosisExemplarReference` / `WholeRunDiagnosisSummary` | `apps/server/vibesensor/use_cases/diagnostics/whole_run_diagnosis_contracts.py` with persisted projection in `shared/types/history_analysis_contracts.py` | Fused diagnosis shell, exemplar links to compact order/spatial/context summaries, and explicit ambiguity/fallback markers for later ranking/report wiring |

For the context track:

1. `WholeRunContextWindowLabel` is the dense internal join surface for later
   order, spatial, and fusion work. It carries explicit `context_coverage`,
   `speed_validity`, `rpm_validity`, `speed_is_stale`, `rpm_is_stale`,
   `load_state`, and optional raw context values/source labels keyed by
   `window_index`.
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

Current persistence guidance:

1. Keep `PersistedAnalysis` as the stable history/report summary boundary.
2. Store only compact summaries and exemplars in `PersistedAnalysis`.
3. Use the whole-run sidecar only for dense artifacts such as spectra, traces,
   matrices, and debug payloads.
4. For the context track specifically, persist
   `whole_run_context_intervals` in `analysis_json`, keep
   `analysis_metadata.whole_run_context_*` as cheap presence/count pointers, and
   store dense `WholeRunContextWindowLabel` rows as the canonical
   `context-window-labels` JSONL sidecar artifact.

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

## Summary-only and legacy fallback policy

- If raw capture is absent, preserve the current summary-only diagnostics/report
  path.
- If raw capture exists but whole-run artifacts do not, continue to support the
  current raw-backed replay behavior instead of failing the run.
- Legacy persisted analyses must remain readable by history/report code.
- New whole-run report facts should degrade to existing summary-only language and
  confidence caveats where necessary.
- When persisted `whole_run_diagnosis_summaries` are absent, the report-prep
  boundary should synthesize exactly one fallback diagnosis row from the current
  summary-era primary candidate plus report confidence/evidence facts instead of
  pretending full whole-run fusion ran. The owner for that synthesis should stay
  in `apps/server/vibesensor/shared/boundaries/reporting/facts.py`, reusing
  `confidence_facts.py` and carrying an explicit `fallback_reason` that
  distinguishes summary-only legacy replay from raw-backed partial-artifact
  replay.
- When persisted `whole_run_diagnosis_summaries` are present, report/history/PDF
  consumers should treat them as the canonical fused proof surface for primary
  source ordering, dominant/runner-up location, proof basis, support-window
  counts, stable-frequency text, and counterevidence rows. Legacy domain
  `Finding` objects remain the fallback narrative source only when fused rows are
  absent or when a surface still needs text that the fused row does not carry.
- Persisted `analysis_metadata` should carry whole-run context completeness counts
  (full/partial/missing plus speed/RPM gap counts) so history/report preparation
  can project caveats without loading dense sidecar labels during report render.

## Historical/completed implementation checklist

These items describe the completed implementation order and should not be read
as current blockers:

1. Whole-run window contracts and sidecar artifact persistence were added.
2. Indexed raw range reads and deterministic window planning were added.
3. The raw-window spectral executor and benchmarks were added.
4. Context timelines and segment labels were added on the shared window grid.
5. Whole-run order traces, order scoring, family summaries, and spatial
   coherence were added on top of spectral/context artifacts.
6. Compact whole-run summaries and report-facing fallback/fused-summary wiring
   were added while keeping dense artifacts sidecar-only.
