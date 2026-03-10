# Chunk 2: Processing Pipeline & Runtime Simplification

## Mapped Findings

### F2.2: SignalProcessor Facade Re-Exposes Subsystem Internals
- **Validation**: CONFIRMED. `processor.py` L88–101 aliases 6 subsystem internals onto `self` immediately after building them (`_buffers`, `_lock`, `_fft_window`, `_fft_scale`, `_fft_cache`, `_fft_cache_lock`). Lines 107–128 are static/class method delegations. Lines 131–170 are internal forwarding methods (`_latest`, `_fft_params`, `_compute_fft_spectrum`, `_get_or_create`, `_resize_buffer`). Lines 226–260 are 1-line public delegations (6 to `_views`, 2 to `_store`).
- **Validated root cause**: Comment at L99: "Preserve the established internal surface used by tests/regressions." The split paid the cost of 3 collaborator classes without gaining encapsulation since all internals are re-aliased.
- **Counter-evidence**: `SignalProcessorViews` does have a distinct payload-shaping concern with no mutable state dependency on `SignalBufferStore`. Keeping it separate is arguably clean.
- **Refinement**: Merge `SignalBufferStore` and `SignalMetricsComputer` back into `SignalProcessor`. Keep `SignalProcessorViews` as a collaborator since it has genuine separation of concerns (read-only payload shaping).

### F1.3+F3.3: Per-Property RLock in Metrics Log (3 Nested Locks)
- **Validation**: CONFIRMED. `MetricsPersistenceCoordinator` has its own `RLock` with 8 individually-locked properties (persistence.py L64–103). `MetricsSessionState` has its own `RLock` with 9+ individually-locked properties (session_state.py L48–79). `MetricsLogger` has its own `RLock`. A single `status()` call acquires all 3 locks independently. The per-property locking does NOT provide compound-read atomicity.
- **Validated root cause**: Defensive boilerplate — each sub-object was given a lock for "standalone thread safety" even though both are exclusively owned by `MetricsLogger`.
- **Counter-evidence**: The per-property pattern is harmless from a correctness standpoint since RLock allows re-entrant acquisition. The overhead is noise, not a bug.
- **Refinement**: The primary win is code volume reduction (removing ~100 lines of property boilerplate) and making the locking contract honest. Remove nested locks, use the owner's lock for writes, and expose fields as plain attributes or snapshot methods.

### F8.3: MetricsLoggerConfig Value-Free Translation Layer
- **Validation**: CONFIRMED. `MetricsLoggerConfig` at logger.py L57–71 has 11 fields. 9 are 1:1 copies from `AppConfig`. `fft_window_type` and `peak_picker_method` are never user-configurable — always hardcoded at the call site (builders.py L143–144: `fft_window_type="hann"`, `peak_picker_method="canonical_strength_metrics_module"`). The default `peak_picker_method="max_peak_amp_across_axes"` at L67 is dead code.
- **Validated root cause**: Created for testability — to construct `MetricsLogger` in tests without a full `AppConfig`.
- **Counter-evidence**: Tests do use `MetricsLoggerConfig` directly. Removing it requires either passing `AppConfig` (more coupling) or keeping a minimal test config.
- **Refinement**: Keep a slimmed `MetricsLoggerConfig` with only the 4-5 fields that are actually variable. Make `fft_window_type` and `peak_picker_method` module-level constants. Remove dead default.

### F1.2: RuntimeXxxSubsystem One-Field Wrappers
- **Validation**: CONFIRMED. `RuntimeRecordingSubsystem` (subsystems.py L58) wraps exactly 1 field: `metrics_logger: MetricsLogger`. `RuntimeUpdateSubsystem` (L73) wraps 2 fields: `update_manager` + `esp_flash_manager`. All access is double-dot: `self._recording.metrics_logger`, `self._updates.update_manager`.
- **Counter-evidence**: `RuntimeSettingsSubsystem` has real methods (`apply_car_settings`, `apply_speed_source_settings`), so it's justified. `RuntimePersistenceSubsystem` groups 5 related objects coherently.
- **Refinement**: Flatten `RuntimeRecordingSubsystem` (1 field) and `RuntimeUpdateSubsystem` (2 fields, no methods) into `RuntimeState` directly. Keep `RuntimeSettingsSubsystem`, `RuntimePersistenceSubsystem`, `RuntimeProcessingSubsystem`, `RuntimeWebsocketSubsystem` as-is — they have enough fields or behavior to justify grouping.

### F3.2: Strength Metrics Triple Storage
- **Validation**: PARTIALLY CONFIRMED. Need to verify the exact storage locations. The subagent reported: (1) `combined_metrics["strength_metrics"]`, (2) root `metrics["strength_metrics"]`, (3) `buf.latest_strength_metrics`. The `extract_strength_data()` function in `sample_builder.py` navigates two paths defensively.
- **Counter-evidence**: The dual write may be intentional for different consumers (combined-axis context vs root shortcut). The `buf.latest_strength_metrics` is a fast-path for WS broadcast.
- **Refinement**: Validate by reading `compute.py` and `buffer_store.py` to confirm the triple storage. If confirmed, canonicalize on `buf.latest_strength_metrics` and remove the root-level duplicate.

## Root Complexity Drivers
1. Half-finished decomposition that added abstractions without removing the old surface
2. Defensive boilerplate applied uniformly regardless of ownership boundaries
3. Config objects that exist for test convenience but carry dead defaults
4. Subsystem wrappers applied uniformly even for 1-field cases

## Relevant Code Paths
- `apps/server/vibesensor/processing/processor.py` (278 LOC)
- `apps/server/vibesensor/processing/buffer_store.py`
- `apps/server/vibesensor/processing/compute.py`
- `apps/server/vibesensor/processing/views.py`
- `apps/server/vibesensor/metrics_log/logger.py` (483 LOC)
- `apps/server/vibesensor/metrics_log/persistence.py` (289 LOC)
- `apps/server/vibesensor/metrics_log/session_state.py` (233 LOC)
- `apps/server/vibesensor/runtime/subsystems.py` (88 LOC)

## Simplification Approach

### Step 1: Merge SignalBufferStore and SignalMetricsComputer back into SignalProcessor
- Inline `SignalBufferStore` fields and methods into `SignalProcessor`
- Inline `SignalMetricsComputer` fields and methods into `SignalProcessor`
- Remove the 6 private aliases (`_buffers`, `_lock`, etc.) — they become real attributes again
- Remove the 5 internal delegation methods (`_latest`, `_fft_params`, etc.)
- Remove the 6 static/class method delegations
- Keep `SignalProcessorViews` as a collaborator — pass `self` instead of `self._store` and `self._metrics`
- Delete `buffer_store.py` and `compute.py`
- Update `views.py` to access processor directly

### Step 2: Remove nested locks from MetricsPersistenceCoordinator
- Remove `self._lock = RLock()` from `MetricsPersistenceCoordinator`
- Convert all 8 `@property` with lock acquisition to plain attributes
- Add a `snapshot()` method (or keep existing if present) for thread-safe multi-field reads under the caller's lock
- Add docstring noting that callers must hold `MetricsLogger._lock` for write operations

### Step 3: Remove nested locks from MetricsSessionState
- Remove `self._lock = RLock()` from `MetricsSessionState`
- Convert individually-locked properties to plain attributes
- Keep `snapshot()` method but remove its internal locking — caller provides lock
- Document the locking contract: `MetricsLogger._lock` serializes all access

### Step 4: Slim MetricsLoggerConfig
- Remove `fft_window_type` and `peak_picker_method` from `MetricsLoggerConfig`
- Make them module-level constants in `sample_builder.py` or `logger.py`
- Remove dead default `"max_peak_amp_across_axes"`
- Update `builders.py` to not pass these fields
- Keep the remaining ~9 fields that are genuinely variable

### Step 5: Flatten one-field RuntimeSubsystem wrappers
- Remove `RuntimeRecordingSubsystem` — add `metrics_logger: MetricsLogger` directly to `RuntimeState`
- Remove `RuntimeUpdateSubsystem` — add `update_manager: UpdateManager` and `esp_flash_manager: EspFlashManager` directly to `RuntimeState`
- Update all double-dot access patterns: `self._recording.metrics_logger` → `self._metrics_logger`
- Update `_state.py`, `lifecycle.py`, `builders.py`, `routes/__init__.py`

### Step 6: Validate and fix strength_metrics storage (if triple storage confirmed)
- Read `compute.py` to verify dual write
- If confirmed, remove root-level `metrics["strength_metrics"]` duplicate
- Simplify `extract_strength_data()` to read from single location

## Dependencies on Other Chunks
- Chunk 1 changes `RuntimeUpdateSubsystem` by moving `esp_flash_manager.py` → so do Step 5 after Chunk 1 or coordinate the import paths.

## Risks and Tradeoffs
- **Merging buffer_store + compute into processor**: `processor.py` will grow from ~278 to ~500+ lines. This is still manageable for one class.
- **Lock removal**: Must verify no code outside `MetricsLogger` directly accesses `MetricsPersistenceCoordinator` or `MetricsSessionState` concurrently. Initial scan shows they're exclusively owned.
- **Test breakage**: Tests that access `processor._buffers` or `processor._store` will need updates.

## Validation Steps
1. `pytest -q apps/server/tests/processing/`
2. `pytest -q apps/server/tests/metrics_log/`
3. `make lint && make typecheck-backend`
4. Verify no `RLock` in persistence.py or session_state.py
5. Verify `RuntimeRecordingSubsystem` and `RuntimeUpdateSubsystem` no longer exist

## Required Documentation Updates
- `docs/ai/repo-map.md`: Update processing/ and runtime/ descriptions
- `.github/copilot-instructions.md`: Update RuntimeState field count

## Required AI Instruction Updates
- Add guidance: "Do not add internal locks to objects that are exclusively owned by a single parent — use the parent's lock instead"
- Add guidance: "Do not create facade classes that re-alias all internals of their collaborators"

## Required Test Updates
- Update tests accessing `processor._store` or `processor._metrics` directly
- Update tests constructing `MetricsLoggerConfig` with `fft_window_type` or `peak_picker_method`
- Update tests referencing `RuntimeRecordingSubsystem` or `RuntimeUpdateSubsystem`

## Simplification Crosswalk

| Finding | Validation | Root Cause | Steps | Verify |
|---------|-----------|------------|-------|--------|
| F2.2: SignalProcessor facade | Confirmed: 6 aliases, 5+6 delegations | Half-finished decomposition | Step 1 | grep for _store/_metrics in processor.py |
| F1.3+F3.3: Per-property RLock | Confirmed: 3 nested locks, 17+ locked properties | Defensive boilerplate | Steps 2,3 | grep for RLock in persistence/session_state |
| F8.3: MetricsLoggerConfig | Confirmed: 2 dead fields, 9 pass-through | Test convenience | Step 4 | grep for fft_window_type/peak_picker_method |
| F1.2: One-field subsystem wrappers | Confirmed: Recording=1 field, Update=2 fields | Uniform pattern | Step 5 | RuntimeRecordingSubsystem gone |
| F3.2: Triple strength_metrics | Partially confirmed | Convenience shortcuts | Step 6 | single storage location |
