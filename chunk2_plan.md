# Chunk 2: Recording & Processing State Simplification

## Overview
The recording and signal processing subsystems (`metrics_log/`, `processing/`) have accumulated
unnecessary complexity through bloated facade classes, leaked private types, overlapping snapshot
methods, redundant locks, and configurable-in-name-only constants. This chunk collapses the
`SignalProcessor` facade, stops leaking private sub-objects from `MetricsLogger`, unifies the
`status()`/`health_snapshot()` parallel builders, simplifies the lock model, and demotes
`fft_window_type`/`peak_picker_method` from pseudo-config fields to constants.

## Mapped Findings

### Finding 1: SignalProcessor bloated facade (A2-1)
- **Original**: Subagent 2 finding 1
- **Validation result**: CONFIRMED. SignalProcessor has 25 methods (excluding `__init__`).
  11 are pure one-liner delegations (9 to `_store`, 2 to `_metrics`). 6 are thin lock-then-
  delegate wrappers. Only 6 have real logic: `compute_metrics`, `compute_all`, `debug_spectrum`,
  `intake_stats`, `time_alignment_info`, `_compute_all_serial`. Two private delegation methods
  (`_fft_params`, `_compute_fft_spectrum`) are accessed directly by tests, defeating the facade.
- **Validated root cause**: The original monolithic `SignalProcessor` was split into
  `SignalBufferStore` and `SignalMetricsComputer`, but all original method names were preserved
  as thin wrappers on the facade rather than being retired.

### Finding 2: Composites expose private sub-objects (A2-2)
- **Original**: Subagent 2 finding 2
- **Validation result**: CONFIRMED for two patterns:
  1. `MetricsLogger.persistence` property returns `_MetricsPersistenceCoordinator` (underscore-
     prefixed private class). `health.py:99-100` reaches through to read
     `.last_write_duration_s` and `.max_write_duration_s` directly.
  2. `SignalProcessor._compute_fft_spectrum` and `._fft_params` are private delegation methods
     accessed by tests at `test_analysis_pipeline_audit.py:58` and
     `test_api_history_processing_regressions.py:113`.
  3. `UpdateManager._collect_runtime_details` (logger.py:401) is a one-liner wrapper around
     `self._runtime_details.collect()` — marginal but unnecessary indirection.
- **Validated root cause**: When callers needed a sub-object's field that the facade hadn't
  exposed, the fix was to add a property forwarding the sub-object itself, or leave a private
  method that callers could reach.

### Finding 3: MetricsLogger overlapping snapshot layers (A3-2)
- **Original**: Subagent 3 finding 2
- **Validation result**: PARTIALLY CONFIRMED. There are 3 `RLock` instances (not 4 as
  originally claimed): `_MetricsSessionState._lock`, `_MetricsPersistenceCoordinator._lock`,
  and `MetricsLogger._lock`. The `PostAnalysisWorker` has its own locking in a separate file.
  The snapshot pattern is confirmed: `health.py` bypasses the snapshot by directly accessing
  `metrics_logger.persistence.last_write_duration_s`. The snapshot abstraction is already
  defeated by the direct field access.
- **Validated root cause**: Each inner class was split to avoid holding one lock while waiting
  on another (valid concern for DB writes). But the snapshot methods overlap, and the
  `persistence` property bypass undermines the isolation.

### Finding 4: MetricsLogger status()/health_snapshot() parallel builders (A5-3)
- **Original**: Subagent 5 finding 3
- **Validation result**: CONFIRMED. 6 fields are duplicated between `status()` and
  `health_snapshot()`: `write_error`, `analysis_in_progress`, `samples_written`,
  `samples_dropped`, `last_completed_run_id`, `last_completed_run_error`. Both methods
  independently call `self._persistence.status_snapshot()` and
  `self._post_analysis.snapshot()`.
- **Validated root cause**: `status()` (UI) and `health_snapshot()` (ops) were built as
  independent projections of the same state rather than composing.

### Finding 5: fft_window_type and peak_picker_method as config fields (A8-2)
- **Original**: Subagent 8 finding 2
- **Validation result**: CONFIRMED. Both are hardcoded string literals in `builders.py:138-139`.
  Neither is backed by YAML config. `MetricsLoggerConfig` has `peak_picker_method` defaulting
  to `"max_peak_amp_across_axes"` but `builders.py` always overrides it with
  `"canonical_strength_metrics_module"` — the dataclass default is misleading. Both travel
  through 6 files (builders → MetricsLoggerConfig → MetricsLogger → sample_builder →
  RunMetadata → JSONL) but are never used at runtime to select algorithms; they are purely
  metadata annotations in serialized run output.
- **Validated root cause**: Designed as configurable metadata fields for forensic value, but
  the "configurable" framing was never backed by actual config surface.

## Root Causes Behind These Findings
1. Facade preservation after internal splits
2. Property exposure as a shortcut for encapsulation
3. Independent (non-composing) view methods for the same state
4. Metadata fields disguised as configuration

## Relevant Code Paths and Components

### SignalProcessor simplification
- `apps/server/vibesensor/processing/processor.py` — main facade class
- `apps/server/vibesensor/processing/buffer_store.py` — SignalBufferStore
- `apps/server/vibesensor/processing/compute.py` — SignalMetricsComputer
- Callers: `runtime/processing_loop.py`, `routes/`, `metrics_log/logger.py`
- Tests: `tests/regression/analysis/test_analysis_pipeline_audit.py`,
  `tests/regression/runtime/test_api_history_processing_regressions.py`

### MetricsLogger state simplification
- `apps/server/vibesensor/metrics_log/logger.py` — MetricsLogger, inner classes
- `apps/server/vibesensor/routes/health.py` — health route (bypasses snapshot)
- `apps/server/vibesensor/routes/recording.py` — recording route (calls status())
- Tests: `tests/metrics_log/`, `tests/api/`, `tests/regression/runtime/`

### Config field demotion
- `apps/server/vibesensor/runtime/builders.py` — literal strings
- `apps/server/vibesensor/metrics_log/logger.py` — MetricsLoggerConfig fields
- `apps/server/vibesensor/metrics_log/sample_builder.py` — forwarded to run metadata
- `apps/server/vibesensor/domain_models.py` — RunMetadata fields
- `apps/server/vibesensor/runlog.py` — build_run_metadata() parameters

## Simplification Approach

### Step 1: Collapse SignalProcessor pure-delegation methods
1. Remove the 9 pure one-liner delegations to `_store` (flush_client_buffer, ingest,
   latest_sample_xyz, latest_sample_rate_hz, latest_metrics, all_latest_metrics,
   raw_samples, clients_with_recent_data, evict_clients)
2. Make `_store` a public attribute `store` (it's already effectively public through its methods)
3. Update all callers to use `processor.store.X` instead of `processor.X`
4. Remove the 2 private delegations to `_metrics` (`_fft_params`, `_compute_fft_spectrum`)
5. Update the 2 regression tests to call `SignalMetricsComputer` directly
6. Keep the 6 lock-then-delegate methods since they add real value (thread safety)
7. Keep the 6 real-logic methods unchanged

### Step 2: Stop leaking MetricsLogger private types
1. Expose `last_write_duration_s` and `max_write_duration_s` directly on `MetricsLogger`
   as properties (or include in `health_snapshot()` dict)
2. Remove the `persistence` property that returns `_MetricsPersistenceCoordinator`
3. Update `health.py` to read from MetricsLogger directly instead of reaching through
4. Inline `UpdateManager._collect_runtime_details()` at its callsites

### Step 3: Unify status() and health_snapshot()
1. Make `health_snapshot()` call `status()` for the shared 6 fields, then extend with
   ops-only fields
2. Or: make `status()` a projection of `health_snapshot()` (return subset of fields)
3. One method builds the state, the other selects from it
4. Remove duplicate `_persistence.status_snapshot()` calls

### Step 4: Demote fft_window_type and peak_picker_method
1. Define `_FFT_WINDOW_TYPE = "hann"` and `_PEAK_PICKER_METHOD = "canonical_strength_metrics_module"`
   as module-level constants in `metrics_log/sample_builder.py`
2. Remove from `MetricsLoggerConfig` dataclass
3. Remove from `MetricsLogger.__init__` instance variables
4. Remove from `build_run_metadata()` signature — use constants directly inside
5. Keep the fields in `RunMetadata` and `RunMetadata.from_dict()` for backward compatibility
   with historical run data
6. Remove from `builders.py` constructor call

## Dependencies on Earlier/Later Chunks
- No dependencies on Chunk 1
- Chunk 3 (Persistence) is independent
- Chunk 4 (Config) is independent

## Risks and Tradeoffs
- **SignalProcessor caller updates**: Making `_store` public as `store` and updating callers
  is a mechanical but broad change. Callers include processing loop, routes, and tests.
  The risk is missing a callsite, caught by tests.
- **MetricsLogger lock structure**: We are NOT collapsing the 3 locks to 1. The separate locks
  for session and persistence have a valid justification (avoiding holding a lock during DB
  writes). We are only fixing the leaky abstraction, not restructuring the lock model.
- **status()/health_snapshot()**: Making one compose the other is low-risk and reduces
  duplication without behavioral change.
- **Config field demotion**: Removing from MetricsLoggerConfig changes the constructor
  signature. All callers (just `builders.py`) must be updated. Historical RunMetadata records
  in the DB still contain these fields, so `from_dict()` keeps reading them.

## Validation Steps
1. `ruff check apps/server/` — lint passes
2. `make typecheck-backend` — type checking passes
3. `pytest -q apps/server/tests/processing/` — processing tests pass
4. `pytest -q apps/server/tests/metrics_log/` — metrics log tests pass
5. `pytest -q apps/server/tests/api/` — API tests pass
6. `pytest -q apps/server/tests/regression/` — regression tests pass
7. Grep for `processor.flush_client_buffer` — should show `processor.store.flush_client_buffer`
8. Grep for `metrics_logger.persistence.` — zero matches
9. Grep for `fft_window_type` in builders.py — zero matches

## Required Documentation Updates
- `docs/ai/repo-map.md` — update processing description re: public `store` attribute
- No user-facing docs affected

## Required AI Instruction Updates
- Add guidance to prevent facade methods that are pure one-liner delegations
- Add guidance against exposing private sub-objects via properties
- Add guidance against disguising constants as config fields

## Required Test Updates
- Update `test_analysis_pipeline_audit.py` to construct `SignalMetricsComputer` directly
- Update `test_api_history_processing_regressions.py` to use compute module directly
- Update any tests that use `metrics_logger.persistence.*` to use new direct properties
- Update any tests that pass `fft_window_type`/`peak_picker_method` to MetricsLoggerConfig

## Simplification Crosswalk

### A2-1 → Collapse SignalProcessor facade
- Validation: CONFIRMED (11 pure delegations, 6 lock wrappers, 6 real methods)
- Root cause: Facade preservation after internal split
- Steps: Remove 11 delegations, make _store public, update callers
- Code areas: processor.py, all callers of delegation methods
- What can be removed: 11 forwarding methods (~50 lines)
- Verification: All processing + regression tests pass

### A2-2 → Stop leaking private types
- Validation: CONFIRMED (persistence property, _compute_fft_spectrum in tests)
- Root cause: Property shortcuts for encapsulation
- Steps: Expose needed fields directly, remove persistence property, update health.py
- Code areas: logger.py, health.py, processor.py (tests), manager.py
- What can be removed: persistence property, _collect_runtime_details wrapper
- Verification: health tests pass, no direct .persistence. access in routes

### A3-2 → Simplify MetricsLogger state access (SCOPED DOWN)
- Validation: PARTIALLY CONFIRMED (3 locks, not 4; snapshot bypass confirmed)
- Root cause: Overlapping snapshot methods with direct field bypass
- Steps: Fix the bypass in health.py, unify snapshot access
- Code areas: logger.py, health.py
- NOT doing: lock consolidation (justified by DB write isolation needs)
- Verification: health endpoint returns same data, tests pass

### A5-3 → Unify status()/health_snapshot()
- Validation: CONFIRMED (6 duplicated fields)
- Root cause: Independent projections of same state
- Steps: Make health_snapshot() compose status(), eliminate parallel building
- Code areas: logger.py
- What can be removed: Duplicate persistence.status_snapshot() call path
- Verification: Both endpoints return same data as before, tests pass

### A8-2 → Demote config-disguised constants
- Validation: CONFIRMED (hardcoded in builders.py, misleading default in MetricsLoggerConfig)
- Root cause: Speculative configurability
- Steps: Define as constants, remove from MetricsLoggerConfig and build_run_metadata signature
- Code areas: builders.py, logger.py, sample_builder.py, runlog.py, domain_models.py
- What can be removed: 2 fields from MetricsLoggerConfig, 2 params from build_run_metadata
- Verification: JSONL run metadata still contains the fields (from constants), tests pass
