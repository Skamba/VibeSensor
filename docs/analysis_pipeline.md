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
   diagnostics pipeline entrypoint. Post-stop analysis
   (`apps/server/vibesensor/analysis/post_analysis_summary.py`) calls it and
   serializes the result with `analysis_result_to_summary()`.
4. **Public API** — external app/domain code imports from
   `vibesensor.analysis`: `RunAnalysis`, `AnalysisResult`,
   `build_order_bands()`, `vehicle_orders_hz()`.
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
| **Output** | Per-tick metrics: FFT spectrum, peaks, strength_db | Diagnostic findings, rankings, reports |
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
evidence.

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
                      ├─ load metadata, then a light pass over the summary rows picks ≤ 12,000 rows; only those are decoded
                      ├─ load raw manifest; replay memory-maps the raw waveform (read-only) via RawRunCapture
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
| 4 | Phase segmentation | `segment_run_phases`, `_phase_summary`, `_speed_stats_by_phase` | phase_segmentation | Classify each sample into a driving phase (IDLE / ACCEL / CRUISE / DECEL / BRAKING / COAST_DOWN / SPEED_UNKNOWN); see "Braking" below |
| 5 | Acceleration statistics | `compute_accel_statistics` | statistics | Per-axis and magnitude accel stats, saturation detection |
| 6 | Findings bundle | `build_findings_bundle` → `_build_findings` | `findings_bundle.py`, `_analysis_models.py`, findings, `peaks/findings.py`, `orders/pipeline.py` | Order tracking, pattern matching, scoring, localisation, and top-cause candidates via typed request/bundle contracts |
| 7 | Origin & test plan | `VibrationOrigin.from_ranked_findings`, `build_phase_timeline` | `findings_bundle.py`, run_data_preparation | Determine most likely vibration source, generate timeline |
| 8 | Top-cause selection | `select_top_causes`, `group_findings_by_source` | top_cause_selection | Rank findings by phase-adjusted score, group by source, apply drop-off threshold |
| 9 | Run suitability | `RunSuitability.evaluate` | `prepared_analysis_context.py`, `domain/run_suitability.py` | Check reference completeness plus data-quality and run-condition checks. The speed check passes only for a live speed that varied; a near-constant or typed-in speed warns. Post-analysis also warns frame integrity when the raw-capture replay coverage was incomplete (`with_incomplete_raw_replay`) |
| 10 | Location analysis | `LocationAnalysisResult` | location_analysis | Per-location vibration intensity and spatial analysis |
| 11 | App-result construction | `build_analysis_result` | `_analysis_result_builder.py`, `_analysis_result.py` | Assemble `AnalysisResult`, `TestRun`, `DiagnosticCase`, diagnostics-local artifacts, and the rehydrated metadata payload needed for later boundary serialization |
| 12 | Peak table | `top_peaks_table_rows`, `annotate_peak_rows_with_order_labels` | `peaks/table.py` | Rank persistent spectral peaks and label them with matched order findings; persisted as `plots.peaks_table` for the PDF report |
| 13 | Boundary serialization | `analysis_result_to_summary` | `analysis/summary_payload.py` | Convert the app-level `AnalysisResult` into the persisted `AnalysisSummary` payload only at explicit edges |

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
persistence-only; they never re-run diagnostics. Analyses stored under an
older persisted-analysis schema version are re-analysed on startup (see
`docs/history_db_schema.md`).
The core
history/report projection is derived from persisted run data plus the persisted
analysis summary only; any comparison against current mutable car settings is an
explicit advisory overlay at the history delivery boundary, not a hidden input
to the persisted projection or the default report cache path. The PDF report
translates the persisted summary (its `diagnosis` block) plus the run metadata
on demand (`report/view_model.py`, rendered by `report/pdf.py`; see
`docs/report_pipeline.md`).

Persisted post-stop analysis strength/intensity outputs are in dB. The one
exception is the `diagnosis` block (`analysis/diagnosis.py`), which reports
amplitude at the diagnosed order in mg next to its dB above the location's
noise floor (see `docs/metrics.md`). Raw ingest/sample acceleration fields may
still be expressed in g.

### Braking

`segment_run_phases()` reads the speed trend as a least-squares slope over the
speed readings within ±1.5 s of each sample on the time axis (one reading per
timestamp, so several sensors reporting the same moment do not count as a
flat stretch). A spell is **braking** when all of these hold:

- the speed falls at **0.2 g or more** (7.1 km/h/s; the detector's
  `BRAKING_MIN_DECEL_G` is 0.19 g, see below). Physical basis: a car
  coasting in gear slows at about 0.05–0.1 g (rolling resistance, aero drag
  and engine braking; up to about 0.15 g in a low gear at high speed), while
  an ordinary stop on the brakes is 0.2–0.4 g. Below 0.2 g the run cannot
  tell light braking from coasting, so it counts as `DECEL`. The detector
  itself accepts from 0.19 g, so a stop at exactly 0.2 g is not lost to the
  slope fit over a GPS staircase or a speed rounded to whole km/h. A 1 Hz GPS
  staircase read by sensors on staggered timestamps still makes the fitted
  slope wobble by up to about 12 %, so there a stop needs about 0.22 g to
  count;
- it lasts at least 2.5 s (`BRAKING_MIN_DURATION_S`, about one spectrum
  window), with gaps of at most 1 s;
- the speed reading drops at least twice inside it, so one GPS jump or glitch
  is not braking;
- the speed is at least 15 km/h; below that the sample is `COAST_DOWN` or
  `IDLE` as before.

The same rule applies to OBD speed: OBD-II has no standard brake-pedal PID,
so braking is inferred from the speed trend whatever the speed source. A
typed-in speed never brakes.

The guided test drive's last step asks for three firm stops from about 100 to
40 km/h (4–7 s each at 0.25–0.4 g), and the Live page counts them with the
same `braking_intervals` ([run_lifecycle.md](run_lifecycle.md)), so a drive
that completes the step has braking spectra to judge.

### Brake judder

Brake judder (disc thickness variation or runout) shakes the car at the
wheel's own order, mainly 1x and sometimes 2x, but only while the brakes are
on. `analysis/orders/brake_attribution.py` relabels a wheel/tire order finding
as `brakes` when, at the sensors that hear it:

- it is heard in at least half of at least 8 braking spectra, counting only
  the stops that show it (heard within 12 dB of the loudest stop's level in
  at least a quarter of the stop's spectra; an EV or PHEV may have made the
  others on regeneration alone), and
- at least 8 spectra clear of braking (not within half an analysis window of a
  braking sample, so spectra that straddle the start or end of a stop count
  for neither side) fall in the speed band the car braked through, and at
  most 10 % of them hear the order within 12 dB of its median braking level.

An unbalanced or out-of-round wheel fails the second test: it is there at the
same speeds without braking. The brake finding keeps only its braking matched
points, with `dominant_phase` `braking`. Its `presence_ratio` and per-location
`presence` count braking samples only, `speed_dependence` is `null`, and its
`zone` is the axle (`front_axle` / `rear_axle`) of its corner: front discs
are felt in the steering wheel, rear discs in the seat and pedal. Without an
axle it is reported unlocated.

### The diagnosis block

`analysis/diagnosis.py:build_diagnosis()` runs once per run, after findings and
top causes exist, and is persisted as `summary["diagnosis"]`
(`summary/diagnosis_contracts.py`). It is the single verdict the History UI and
the PDF both show:

- `verdict`: `fault` (Strong/Moderate candidate), `weak_evidence` (Weak
  candidate), or `no_fault` (no candidate, or a Weak candidate fainter than the
  moderate strength band, or a wheel/tire candidate fainter than that band that
  no corner stands out in: every wheel keeps some imbalance after balancing,
  and a healthy car feels that residual about evenly at every corner). The candidate is `TestRun.diagnosis_candidate`: the
  first surfaced, actionable top cause that is not baseline noise or a
  transient.
- `confidence_level`: the action-defined level (see `docs/metrics.md`); no
  percentage is exposed anywhere. A candidate with the weak reason `faint`
  (under the 16 dB moderate strength band) or `spread_across_locations` (a
  wheel/tire or brake cause felt about as strongly at several sensors) is
  Moderate at most: a vibration that faint may be a healthy car's residual
  imbalance, and a spread one is not pinned to the part a Strong level tells
  the owner to fix.
- `order_code` (T1/T2 tire, P1/P2 driveshaft: propshaft or gearbox output, E1/E2 engine), `frequency_hz` at
  `reference_speed_kmh`, the matched speed range, presence ratio, and
  `weak_reasons` codes (at most two shown); `order_findings` repeats those facts once per surfaced
  order (its best-ranked finding; diagnosed one first) as workshop worksheet rows.
  The candidate names the source and the confidence level; the order shown
  (label, amplitudes, frequency, speeds) is that source's dominant order,
  `TestRun.diagnosis_order_finding` (see "Diagnosed order" in
  `docs/metrics.md`). `reference_speed_kmh` is the median matched speed in
  the order's strongest speed band: the 10 km/h bin where its matched
  amplitude is highest on average (phase-weighted: a cruise match ×3, one
  while accelerating, slowing down, braking or coasting down ×0.3), among
  bins with at least 3 matched points. A mean, not a total, so a long cruise
  at one speed does not make that speed the strongest. The diagnosed row carries the diagnosis level. Rows are
  listed from Moderate up, plus the diagnosed source's other order once even
  when it is Weak on its own.
- `zone`: a corner for wheel/tire faults: the finding's location when the
  order analysis found a dominant corner, otherwise from the per-location
  amplitudes (an axle when two corners on one axle are within 1.5×,
  `all_wheels` when three or more are). The amplitudes are medians over the
  whole drive, so they understate a fault that was there for only part of
  it. `engine_bay` for
  engine orders, and an axle or `driveshaft_tunnel` for driveline orders
  (on an engined car without a propshaft, the final drive's axle instead of
  the tunnel when no axle dominates). An axle for brakes (see "Brake
  judder" above).
- `driveline_parts`: for a driveline fault on an engined car with a known
  drive layout, the parts to check, likelier first: `["front_drive"]`
  without a propshaft, `["propshaft_rear"]` for RWD, and both for AWD with
  the front first when the zone is the front axle. The order turns at wheel
  speed x final drive, so `front_drive` alone is the gearbox output shaft,
  final-drive pinion and differential bearings (drive shafts and CV joints
  turn at wheel speed and show at the wheel order); next to `propshaft_rear`
  it is the AWD car's front propshaft (if fitted) and front differential
  pinion. Empty for an EV, without
  a layout, or for another source (`_driveline_parts` in `diagnosis.py`).
- `unexplained_vibration`: a `no_fault` run with no candidate where a sensor
  still felt a vibration in the elevated strength band (see `docs/metrics.md`).
  The report and the UI then say a vibration was found that no checked cause
  explains, not that none was found.
- `location_amplitudes` (mg + dB above floor + ratio to the strongest),
  `amplitude_vs_speed` (5 km/h bins), a recurring-peak `spectrum` at the
  strongest location with order markers, `source_checks`, and the reference
  `conditions` (speed source, RPM `measured` / `estimated_top_gear` / `none`,
  tire circumference, ratios, each reference's provenance, the car's
  `fuel_type`, `drive_layout`, `final_drive_axle` and `propshaft`; the last
  three are absent on runs analysed before the layout existed, read as not
  given).
- `source_checks` give each order family (wheel/tire, driveline, engine,
  brakes) a status and reason:
  - `candidate`: the diagnosed source.
  - `not_testable`: its reference is missing (`no_tire_reference`,
    `no_drive_reference`, `no_engine_reference`), or the speed was typed in
    by hand (`manual_speed`; every sample carries the set value, even on a
    desk), or, for the engine, `same_rhythm_as_candidate` (see "Engine
    alias" below).
  - `ruled_out_estimated`: no match, but the check rests on an estimate. The
    reason is `estimated_final_drive` or `estimated_top_gear` for a
    car-library ratio with `family_default` / `unverified` confidence, else
    `engine_may_be_off` for a plug-in hybrid (`fuel_type` `PHEV`) whose engine
    RPM was estimated, else `top_gear_assumed` for engine RPM estimated from
    speed. For the brakes it is `regen_braking` (see below).
  - `not_applicable` (`electric_car`): the engine of an EV (`fuel_type`
    `EV`). An EV's motor turns at the driveline order (wheel speed ×
    reduction ratio), so the driveline check is its motor check; no E1/E2
    markers are drawn and `speed_dependence` stays `null` (no neutral
    decouples the motor).
  - On a plug-in hybrid, a measured 0 rpm sample means the engine was off: it
    is not replaced by an estimate. If the engine ran in fewer than 35 % of
    the measured samples, the engine is `not_testable` with
    `engine_not_running`. A combustion engine does not stop while the car
    moves, so on any other car a 0 rpm reading is a bad one (an OBD glitch or
    ignition-off data): the RPM is estimated from speed as when none was
    measured, and the engine check is hedged the same way.
  - `ruled_out` (`no_matching_order`): no match on references the user gave
    or the library verified, and for the engine only with measured RPM.
  - Brakes are `not_testable` with `no_tire_reference` or `manual_speed` as
    for the wheels, else `no_braking` when the run had less than 2.5 s of
    braking (see "Braking"), else `ruled_out` (`no_matching_order`); on an EV
    or PHEV `ruled_out_estimated` (`regen_braking`), because regenerative
    braking slows it at up to about 0.3 g, often without the discs, so its
    firm stops need not have tested them. When
    brakes are the candidate, the wheel/tire check is `ruled_out` with
    `only_while_braking`: the same order was absent while driving at the same
    speeds.
  - Provenance is the car's recorded field confidence, `user_confirmed` when
    none was recorded, or `missing`. A manual speed also adds the weak reason
    `manual_speed` to a found cause.
- `guided_phases` (the guided test-drive steps the driver marked: `sweep`,
  `hold`, `coast_down`, `brake`) and
  `speed_dependence`: after a guided neutral coast-down, `vehicle_speed` when
  the diagnosed order stayed present while coasting (wheels or driveline) and
  `engine_speed` when it disappeared (engine). The first 3 s of the coast-down
  are skipped while the revs drop and the spectrum window clears. Presence at
  the order's main location inside the coast-down is compared with presence
  during the rest of the run (≥ 60 % of it: road speed, ≤ 30 %: engine,
  otherwise unknown). The main location and both presences count heard
  matches only (see "Heard matches" in `docs/order_tracking.md`): once an
  engine tone is gone, road noise at the floor still lands near its predicted
  frequency in some windows. Coast-down matches that stay at one frequency while the
  prediction falls (an idle tone the order's path crosses) do not count as the
  order (`frequency_tracking_slope`, judged when the coast-down speed really
  fell; see `docs/order_tracking.md`). With a manual speed `speed_dependence` is
  `null`: a typed-in speed does not fall while coasting. The coast-down rules out the other side in
  `source_checks` (`stayed_in_neutral` / `stopped_in_neutral`) even without an
  order reference. When it contradicts the order match (an engine order that
  stays in neutral, a wheel or driveline order that stops), the verdict drops
  to `weak_evidence` with the weak reason `coast_test_contradicts`.
- Engine alias: RPM estimated from speed assumes top gear, but the drive may
  have been in any gear. In gear `g` the engine's `m`-th order (m = 1, 2)
  repeats `m × g × final drive` times per wheel turn, so a wheel or propshaft
  order sits on an engine order whenever that gives a ratio at or above the
  top gear's (within the 8 % order tolerance): P1/P2 always do in a direct
  1:1 gear, and T2 does on a car whose top gear is about 2 / final drive.
  For such a diagnosed order the engine check is `not_testable` with
  `same_rhythm_as_candidate` (unless a coast-down ruled it out), and no such
  order, diagnosed or listed in `order_findings`, is Strong: Moderate at most
  unless the coast-down showed `vehicle_speed`. When the coast-down shows
  `engine_speed` instead, the diagnosis names the engine: the candidate and
  the same source's orders that fit that gear become the engine orders they
  are there (P2 → E2 and P1 → E1 in a direct gear, T2 → E1 in top gear), so
  the verdict is an engine fault, not `coast_test_contradicts`. Measured RPM
  and EVs (no gears) never alias.

## Adding a New Analysis Step

1. Implement the step as a function in the appropriate module
   (or create a new one under `analysis/`).
2. Call it from `RunAnalysis.summarize()` at the correct point in the
   pipeline.
3. If the report needs the new output, persist it through the `summary/`
   contract (usually the `diagnosis` block), then translate it in
   `report/view_model.py` and draw it in `report/pdf.py`. The report never
   re-derives analysis facts.
4. Run `pytest apps/server/tests/` to verify tests still pass.
