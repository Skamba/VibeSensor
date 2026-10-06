# Run Lifecycle

Scope: recording orchestration, sample persistence, and the post-analysis
handoff after a run stops.

The recording lifecycle is intentionally split across focused helpers instead of
one big state-machine class:

- `RunLifecycleState` owns only the in-memory active-run gate and timing fields.
- `RunPersistenceWriter` owns history-run creation, sample append retries, and
  finalization.
- `RunRawCaptureWriter` owns the recorder-side raw UDP chunk handoff and
  artifact finalization for the active run.
- `RunRecordingSessionService` owns active-run context snapshots, sensor
  snapshots, run-start side effects, and ingest-drop baselines.
- `RawCaptureFinalizeRegistry` owns raw-capture finalize manifests/results and
  late-finalize replacement rules.
- `PostAnalysisWorker` owns the background queue and retry policy after a run
  stops.
- `CaptureReadinessTracker` owns the backend pre-record readiness checklist for
  idle/live states.
- `RunRecorder` coordinates those helpers without re-owning their internals.

## Owning components

| Component | File | Responsibility |
|-----------|------|----------------|
| `RunLifecycleState` | `recording/lifecycle_state.py` | Active run identity, start timing, frame-progress tracking, and auto-stop gating. |
| `SampleFlushOrchestrator` | `recording/sample_flush.py` | Build `SensorFrame` rows, refresh recent metrics, and decide when to flush or auto-stop. |
| `RunPersistenceWriter` | `recording/persistence_writer.py` | Create the persisted run, append sample rows with retries, and finalize the run metadata. |
| `RunRawCaptureWriter` | `recording/raw_capture_writer.py` | Buffer raw UDP chunks for the active run and finalize the raw artifact manifest into history. |
| `RunRecordingSessionService` | `recording/recording_session.py` | Active run context/sensor snapshots, start-run side effects, and ingest-drop baseline accounting. |
| `RawCaptureFinalizeRegistry` | `recording/raw_capture_finalize_registry.py` | Raw-capture finalize result/manifest bookkeeping and late timeout replacement. |
| `CaptureReadinessTracker` | `recording/capture_readiness.py` | Evaluate live-sensor readiness, reference freshness, steady-speed advice, and recent integrity quiet windows for the idle recording gate. |
| `RunRecorder` | `recording/recorder.py` | Start/stop entrypoint and coordinator for lifecycle, persistence, and post-analysis. |
| `PostAnalysisWorker` | `analysis/post_analysis.py` | Non-evicting queue and single daemon thread for completed runs. |
| `execute_post_analysis()` | `analysis/post_analysis_executor.py` | Load metadata/samples/raw capture, run the summary analysis, and store success or failure. |

## Lifecycle phases

These are architectural phases, not one exported enum. Only the first active
phase is stored directly on `RunLifecycleState`.

```text
idle
  -> recording active
  -> final flush + finalize
  -> queued for post-analysis
  -> analyzing
  -> complete / analysis error stored
```

### 1. Idle

No active run is recording:

- `RunLifecycleState.current_run is None`
- no active run ID is exposed
- `PostAnalysisWorker` may still be busy with an older run
- `RunRecorder.status()` includes a backend-owned `CaptureReadiness` checklist
  so `/api/recording/status` and the Live dashboard can explain whether
  a recording is ready to start. `reference_ready` needs only an active car
  and a working live speed (OBD-II also needs fresh RPM); a live 0 km/h counts,
  so a run can start while parked. Missing car references never block capture.
  `speed_stable` (20 km/h held for 8 s) is advice for the guided hold step: it
  warns but never blocks. `capabilities` reports, without
  blocking, which order families the run can test, mirroring the post-run
  source checks: `wheel` (`ok`/`missing_tire`), `driveline`
  (`ok`/`estimated_final_drive` for a weak library final drive/
  `missing_final_drive`/`missing_tire`) and `engine` (`measured` from fresh
  OBD-II RPM, `estimated_top_gear` from the ratios, `estimated_ratios` when the
  final drive or top gear is a weak library value, or what is missing:
  `missing_tire`, `missing_final_drive`, `missing_top_gear`, or
  `missing_ratios` for both; `not_applicable` for an EV, and
  `hybrid_estimated` instead of an estimate for a plug-in hybrid, whose engine
  may be off). An EV on OBD-II speed does not wait for RPM. A typed-in
  (manual) speed makes every family that has its references `manual_speed`.
  `capabilities` is `null` without an active car

### 2. Recording active

`RunRecorder.start_recording()` flushes per-client processor buffers, snapshots
the live run context, and calls `RunLifecycleState.start_new_run()`.

During recording:

- `current_run.is_recording` is true
- `SampleFlushOrchestrator` periodically builds `SensorFrame` rows from the
  registry, processor metrics, and resolved speed context
- raw UDP ingress also streams full-run `int16` chunks through
  `RunRawCaptureWriter`, which writes per-run artifacts under the history data
  directory without bloating `samples_v2`
- `refresh_data_progress()` / `mark_rows_written()` keep the no-data timeout
  clock moving
- auto-stop is based on monotonic time, not wall-clock timestamps: a run stops
  with reason `no_data_timeout` after `no_data_timeout_s` without data progress,
  and with reason `max_duration` when it reaches `MAX_RECORDING_DURATION_S`
  (30 minutes, `recording/lifecycle_state.py`; the `recording.max_duration_s`
  config default, which only isolated test runtimes shorten), which keeps
  post-analysis within the Pi's memory budget
- raw UDP chunks are only captured once their sensor is clock-synced (see
  `docs/time_alignment.md`); earlier chunks are dropped so raw replay aligns from
  each sensor's first synced chunk. A synced chunk from a sensor whose HELLO
  (which carries its sample rate) has not arrived yet is held, up to 20 per
  sensor, and written once the rate is known. This happens after a server
  restart, when DATA syncs the sensor before its next HELLO. Held chunks are
  counted as invalid only if the run ends before that HELLO.
- `GET /api/recording/status` reports `last_stop_reason` for the most recent run
  until the next run starts; the Live page shows a notice when it is
  `max_duration`
- status reports `elapsed_s`, the active run's time on the monotonic clock; the
  Live page's elapsed timer counts on from it with the browser clock, never
  from `start_time_utc`, which is wrong while the Pi clock is unset
- the optional guided test drive on the Live page posts each step to
  `POST /api/recording/guided-phase` (`sweep`, `hold`, `coast_down`, `brake`,
  or `null` to end the test). `RunRecordingSessionService` closes the open step and starts
  the next one at the current run time (seconds since the run's live start, the
  same clock as sample `t_s`); the steps are stored as `guided_phases` in the
  run metadata when the run is finalized. Markers outside a recording are
  ignored. Status reports the step in progress as `guided_phase` and the
  distinct steps finished so far as `guided_phases_completed`, so a Live page
  reloaded mid-run restores the guided panel (including a finished test). The
  step texts name their speeds in the UI's speed unit. While the `brake` step
  is open, each flush tick feeds the tick's stored speed to
  `GuidedBrakeStops` (`recording/guided_brake_stops.py`), which counts firm
  stops with the analysis's own `braking_intervals` (see "Braking" in
  [analysis_pipeline.md](analysis_pipeline.md)); status reports the count as
  `guided_brake_stops`. A stop counts about 3 s after it ends, once its last
  speed slopes are final.
- the Live page posts the browser clock (`POST /api/system/browser-clock`)
  before `POST /api/recording/start`, so an unset Pi clock is stepped first,
  and again after a successful `POST /api/recording/stop`, so a run the browser
  first saw mid-recording (the clock is never stepped under a recording) is
  re-dated once it stops; a report whose `runs_corrected` is above zero
  reloads History. A
  run that starts while the clock is not trusted (see
  `BrowserClockCorrector.clock_trusted`) still records, with
  `start_time_unverified: true` and its monotonic `start_clock` (boot id plus
  `time.monotonic()` at start) in its metadata; its end is start plus monotonic
  elapsed time. `RunTimeCorrector` (`vibesensor/clock/run_times.py`) re-dates
  such runs from the same boot once the clock is trusted (startup, browser
  report, after each post-analysis, and when its `clock-watch` task sees the
  clock become trusted, e.g. NTP with no browser open) and clears the flag;
  exports re-time such runs' sample rows as start plus `t_s`

### 3. Final flush and finalize

`RunRecorder.stop_recording()` performs the stop handoff in this order:

1. capture one last pending flush if new data exists
2. finalize the raw artifact bundle and persist its compact manifest on the run
   row when raw chunks were captured
3. call `RunPersistenceWriter.finalize_run()`, which first creates the history
   row if no sample ever did
4. ask `RunPersistenceWriter.ready_for_analysis()` whether the run has a
   created history row
5. call `RunLifecycleState.stop()` and clear the active run context; the
   stopped run's ID stays in status as `last_run_id` until the next run starts
6. end the persistence helper's run (`end_run()`): write state is cleared but
   `samples_written`/`samples_dropped` stay in status until the next run, so
   the Live page names the run and its sample count while it is analysed
7. schedule post-analysis only when `ready_for_analysis()` returned the run ID

A run that collected no samples is still analysed: post-analysis stores it in
History with the error "No samples collected during run", so it never vanishes.

If `finalize_run()` fails, `RunRecorder` still schedules post-analysis when the
run was otherwise ready. The persistence layer handles that fallback path by
storing the later analysis result or analysis error explicitly.

## Canonical read-side lifecycle projection

History/report/UI read paths do not infer readiness from ad hoc combinations of
`run.status`, `analysis_started_at`, nullable analysis payloads, manifest
presence, and raw-capture finalize metadata anymore. The one read-side owner is
`RunArtifactLifecycle` in `apps/server/vibesensor/history/run_lifecycle.py`.

That model is **derived**, not stored in a separate table or column. It projects
four fields:

- `stage`: `recording`, `post_analysis_pending`, `post_analysis_running`,
  `post_analysis_ready`, or `post_analysis_degraded`
- `raw_capture`: `not_recorded`, `pending`, `ready`, `degraded`, or `missing`
- `post_analysis`: `pending`, `running`, `ready`, or `degraded`
- `report`: `pending`, `ready`, or `degraded`

Transition ownership stays split by subsystem, but projection ownership is now
centralized:

| Lifecycle fact | Source of truth | Transition owner |
|----------------|-----------------|------------------|
| recording vs stopped | in-memory `RunLifecycleState` while live; persisted `RunStatus` after handoff | `RunRecorder` + `RunPersistenceWriter` |
| raw capture ready/degraded/missing | raw manifest/files plus `RunMetadata.raw_capture_finalize` | `RunRawCaptureWriter` + history raw-capture store |
| post-analysis pending/ready/degraded | persisted `RunStatus` plus stored analysis/corruption state | `PostAnalysisWorker` + `execute_post_analysis()` + history DB lifecycle writes |
| report ready/degraded | derived directly from post-analysis readiness | `RunArtifactLifecycle` projection only |

History DB queries, history HTTP payloads, report loading, and the History
page should consume that derived lifecycle object instead of rebuilding
their own readiness heuristics.

## Persistence and retry rules

`RunPersistenceWriter.ensure_history_run()` creates the persisted run record
before sample rows are appended.

- history-run creation allows up to `5` failures before entering a retry
  cooldown
- the cooldown grows from the `2.0s` base up to `10.0s`
- while the history run is still missing, incoming sample rows are dropped and
  counted as dropped samples instead of being queued forever

`append_rows()` has a separate retry budget:

- up to `3` append attempts total
- retry delays come from `_APPEND_RETRY_DELAYS_S = (0.1, 0.3)`
- if all attempts fail, the rows are counted as dropped and the last write error
  is updated

`finalize_run()` only touches the persisted run when the history row was
actually created. If no history row exists, finalize returns success immediately
because there is nothing persistent to close.

## Post-analysis queue semantics

`PostAnalysisWorker` owns the background phase after recording stops.

- `schedule(run_id)` ignores duplicates for runs that are already queued or
  active
- the queue is FIFO and processed by one daemon thread
- `_run_post_analysis()` retries transient failures with
  `_RETRY_DELAYS_S = (0.5, 1.0, 2.0)`
- `execute_post_analysis()` loads the stored run, recomputes the summary rows'
  FFT peaks from raw capture when it is available, calls the injected summary
  analysis runner, and stores either analysis output or an analysis error
  record
- each analysis start is counted in the `analysis_attempts` table before any
  work, and the count is cleared when a result or error is stored. A count left
  behind means the server stopped mid-analysis (most likely out of memory on the
  Pi). After `MAX_UNFINISHED_ANALYSIS_ATTEMPTS = 2` such attempts the worker does
  not try again: it stores the run as `error` with "Analysis did not finish in 2
  attempts: … Record a shorter run.", which the history UI shows, instead of
  crashing the restarted server again
- to stay within the Pi's memory, loading reads only `id`, `t_s` and the
  loudness columns of every summary row first, picks the rows to analyse (at most
  12,000: evenly spaced plus the loudest of each stretch) and decodes only those;
  the raw waveform is memory-mapped read-only rather than copied, and both are
  released once the analysis input is built

The worker also exposes `PostAnalysisHealthSnapshot`, which is what the health
surface uses for queue depth, active run ID, and the most recent completion
status.

## Shutdown behavior

Shutdown does not start new work:

- `schedule()` ignores new runs once shutdown has started
- `shutdown()` sets the shutdown event, clears queued-but-not-started runs, and
  then waits briefly for the worker to exit
- an in-flight analysis attempt is allowed to finish its current call path; the
  worker checks the shutdown flag before starting the next queued item or retry

## Runtime concurrency ownership

The run lifecycle is coordinated inside the backend runtime, but concurrency
ownership now stays in one AnyIO-based path instead of split `asyncio`
task/timeout helpers:

- `LifecycleManager` opens one runtime-scoped AnyIO task group before startup
  phases begin
- `BackgroundTaskCoordinator` starts named runtime services inside that task
  group and owns per-service cancel scopes for shutdown; a service is tracked
  and cancellable as soon as `start()` returns, so shutdown right after startup
  never waits on a service body that has not been scheduled yet
- `TaskSupervisor` owns restart/backoff for long-lived runtime services such as
  `processing-loop`, `ws-broadcast`, `gps-speed`, `obd-speed`, and the UDP data
  consumer while still recording terminal failures into health state
- runtime shutdown closes ingress first, cancels those service scopes with a
  bounded wait, then drains `RunRecorder.shutdown_report()` and closes the
  worker pool / history DB
- WebSocket tick timing, send timeouts, and thread offloads in the runtime path
  use AnyIO scheduling/timeouts (`sleep`, `fail_after`, `to_thread.run_sync`)
  so startup/shutdown behavior stays on the same cancellation model

## Key invariants

- At most one live recording run is active at a time.
- Post-analysis never starts until recording has stopped and persistence says
  the run is ready for analysis.
- The live recording path and the post-analysis path are decoupled; once a run
  is queued, diagnostics work happens off the recording loop.
- Duplicate post-analysis schedules are no-ops.
- Retry budgets are explicit and bounded for history creation, sample appends,
  and post-analysis retries.

## File map

| File | Responsibility |
|------|----------------|
| `apps/server/vibesensor/recording/lifecycle_state.py` | In-memory active-run gate and timeout fields. |
| `apps/server/vibesensor/recording/sample_flush.py` | Flush decisions, live metric refresh, and sample-row building. |
| `apps/server/vibesensor/recording/persistence_writer.py` | History-run creation, append retries, counters, and finalize flow. |
| `apps/server/vibesensor/recording/raw_capture_writer.py` | Recorder-side raw chunk queue and raw manifest finalization. |
| `apps/server/vibesensor/recording/recording_session.py` | Active run context/sensor snapshots, run-start side effects, and ingest-drop baselines. |
| `apps/server/vibesensor/recording/raw_capture_finalize_registry.py` | Raw-capture finalize result/manifest bookkeeping and late timeout replacement. |
| `apps/server/vibesensor/recording/recorder.py` | Public recording start/stop entrypoint. |
| `apps/server/vibesensor/analysis/post_analysis.py` | Queue, worker-thread, retry, and health behavior. |
| `apps/server/vibesensor/analysis/post_analysis_executor.py` | Load -> build input (raw replay) -> analyze -> store execution path, written as straight-line steps (one `post_analysis_step` log line each). |
| `apps/server/vibesensor/analysis/raw_capture_replay.py` | Raw-window replay for post-stop strength/peak rebuilding before diagnostics. |
