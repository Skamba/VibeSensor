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
- `PostAnalysisWorker` owns the background queue and retry policy after a run
  stops.
- `post_run_raw_windows.py` owns post-stop raw artifact window access for dense
  diagnostics. It reads finalized raw sidecars by bounded ranges and emits
  structured window warnings instead of reusing live buffers or loading full
  runs into memory.
- `CaptureReadinessTracker` owns the backend pre-record readiness checklist for
  idle/live states.
- `RunRecorder` coordinates those helpers without re-owning their internals.

## Owning components

| Component | File | Responsibility |
|-----------|------|----------------|
| `RunLifecycleState` | `use_cases/run/lifecycle_state.py` | Active run identity, start timing, frame-progress tracking, and auto-stop gating. |
| `SampleFlushOrchestrator` | `use_cases/run/sample_flush.py` | Build `SensorFrame` rows, refresh recent metrics, and decide when to flush or auto-stop. |
| `RunPersistenceWriter` | `use_cases/run/persistence_writer.py` | Create the persisted run, append sample rows with retries, and finalize the run metadata. |
| `RunRawCaptureWriter` | `use_cases/run/raw_capture_writer.py` | Buffer raw UDP chunks for the active run and finalize the raw artifact manifest into history. |
| `CaptureReadinessTracker` | `use_cases/run/capture_readiness.py` | Evaluate live-sensor readiness, reference freshness, steady-speed dwell, and recent integrity quiet windows for the idle recording gate. |
| `RunRecorder` | `use_cases/run/logger.py` | Start/stop entrypoint and coordinator for lifecycle, persistence, and post-analysis. |
| `PostAnalysisWorker` | `use_cases/run/post_analysis.py` | Non-evicting queue and single daemon thread for completed runs. |
| `execute_post_analysis()` | `use_cases/run/post_analysis_executor.py` | Load metadata/samples, build the persisted analysis, and store success or failure. |

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
  steady-state capture is ready to start

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
- auto-stop is based on elapsed monotonic time since the last data progress, not
  on wall-clock timestamps

### 3. Final flush and finalize

`RunRecorder.stop_recording()` performs the stop handoff in this order:

1. capture one last pending flush if new data exists
2. finalize the raw artifact bundle and persist its compact manifest on the run
   row when raw chunks were captured
3. ask `RunPersistenceWriter.ready_for_analysis()` whether the run has both a
   created history row and at least one written sample
4. call `RunPersistenceWriter.finalize_run()`
5. call `RunLifecycleState.stop()` and clear the active run context
6. reset the persistence helper for the next live run
7. schedule post-analysis only when `ready_for_analysis()` returned the run ID

If `finalize_run()` fails, `RunRecorder` still schedules post-analysis when the
run was otherwise ready. The persistence layer handles that fallback path by
storing the later analysis result or analysis error explicitly.

## Canonical read-side lifecycle projection

History/report/UI read paths do not infer readiness from ad hoc combinations of
`run.status`, `analysis_started_at`, nullable analysis payloads, manifest
presence, and raw-capture finalize metadata anymore. The one read-side owner is
`RunArtifactLifecycle` in `apps/server/vibesensor/shared/types/run_lifecycle.py`.

That model is **derived**, not stored in a separate table or column. It projects
five fields:

- `stage`: `recording`, `post_analysis_pending`, `post_analysis_running`,
  `post_analysis_ready`, or `post_analysis_degraded`
- `raw_capture`: `not_recorded`, `pending`, `ready`, `degraded`, or `missing`
- `whole_run_artifacts`: `not_recorded`, `pending`, `ready`, `degraded`, or
  `missing`
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

History DB queries, history HTTP payloads, report loading, and history UI
presenters should consume that derived lifecycle object instead of rebuilding
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
- `execute_post_analysis()` loads the stored run, calls the injected analysis
  runner, and stores either analysis output or an analysis error record
- the loaded post-stop input can now include both persisted summary rows and the
  optional raw-capture bundle; the raw replay path rebuilds FFT-derived
  strength/peak fields from raw windows when the bundle exists and falls back to
  summary-only rows otherwise

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
  group and owns per-service cancel scopes for shutdown
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
| `apps/server/vibesensor/use_cases/run/lifecycle_state.py` | In-memory active-run gate and timeout fields. |
| `apps/server/vibesensor/use_cases/run/sample_flush.py` | Flush decisions, live metric refresh, and sample-row building. |
| `apps/server/vibesensor/use_cases/run/persistence_writer.py` | History-run creation, append retries, counters, and finalize flow. |
| `apps/server/vibesensor/use_cases/run/raw_capture_writer.py` | Recorder-side raw chunk queue and raw manifest finalization. |
| `apps/server/vibesensor/use_cases/run/logger.py` | Public recording start/stop entrypoint. |
| `apps/server/vibesensor/use_cases/run/post_analysis.py` | Queue, worker-thread, retry, and health behavior. |
| `apps/server/vibesensor/use_cases/run/post_analysis_executor.py` | Load -> analyze -> store execution path. |
| `apps/server/vibesensor/use_cases/run/raw_capture_replay.py` | Raw-window replay for post-stop strength/peak rebuilding before diagnostics. |
