# Chunk 3: Internal Architecture & Abstraction

## Mapped Findings

- [1.1] LifecycleManager mirrors RuntimeState constructor (9 mirrored args)
- [1.2] SignalProcessor proxies internal decomposition via 6 aliases + forwarding methods
- [1.3] report/mapping/ is an 8-file sub-package for a single export
- [2.1] OrderHypothesisLike Protocol with a single private implementor
- [2.2] UpdateWorkflow dataclass assembled and discarded per invocation
- [2.3] Two private Protocols in rotational_speeds.py with vacuous union types
- [10.1] analysis/findings/ double-nesting at 4-segment import depth

## Validation Outcomes

### [1.1] CONFIRMED (HIGH confidence)
`RuntimeState` has 10 fields; `LifecycleManager.__init__` receives 9 of the same (all except `lifecycle` itself). `bootstrap.py` passes the identical 9 keyword arguments to both constructors. LifecycleManager stores each as a private slot. Verified in bootstrap.py, runtime/lifecycle.py, runtime/_state.py.

### [1.2] CONFIRMED (MEDIUM-HIGH confidence)
After constructing `_store`, `_metrics`, `_views`, `SignalProcessor.__init__` creates 6 attribute aliases (3 from store, 3 from metrics) and has ~12 forwarding methods. The comment "Preserve the established internal surface used by tests/regressions" explicitly documents the compatibility shim nature. However, the 3 internal classes do have genuine separation of concern (buffer management, FFT computation, payload views). **Revised scope**: Don't collapse all 3 files back into processor.py. Instead: remove the 6 aliases and update test references to use the proper dot-path (`processor._store.buffers` instead of `processor._buffers`). This preserves the valid decomposition while removing the compatibility shim.

### [1.3] CONFIRMED (MEDIUM confidence)
8 files in `report/mapping/`, single public export `map_summary`. Only consumer: `history_services/reports.py`. Internal-only `models.py` (2 dataclasses) exists only to break a circular import within the sub-package.

**Revised scope**: The sub-package files are ~100-200 lines each with meaningfully distinct responsibilities (context extraction, peak rows, system cards, actions). Collapsing to a single ~500-line module is defensible but trades directory navigation complexity for scrolling complexity. **Decision**: Collapse to a single module. The functions remain private module-scope functions, the 2 `models.py` dataclasses become module-level. The caller import `from ..report.mapping import map_summary` stays the same.

### [2.1] CONFIRMED (HIGH confidence)
`OrderHypothesisLike` is a Protocol in `order_models.py` with 5 properties + 1 method. Exactly one private concrete implementor: `_OrderHypothesis` frozen dataclass. Used in 3 consumer modules. No test doubles, no substitution.

### [2.2] CONFIRMED (MEDIUM confidence)
`UpdateWorkflow` is create-once-run-once-discard. `_build_workflow()` constructs it, immediately calls `.run()`. The `_snapshot_for_rollback()` and `_rollback()` paths bypass the workflow and build their own `UpdateInstaller` separately.

**Revised scope**: The workflow logic is ~100 lines and non-trivial. Rather than inlining ALL of it into `UpdateManager`, the better fix is: (a) remove the `UpdateWorkflow` **dataclass wrapper**, and (b) make `UpdateWorkflow.run()` a private method on `UpdateManager` that accepts the required sub-objects as direct parameters. This eliminates the per-invocation dataclass without creating a 400-line method.

### [2.3] CONFIRMED (MEDIUM confidence)
Two private Protocols in `rotational_speeds.py`: `_SpeedSourceSettingsStore` (1 method) and `_GpsMonitorState` (2 properties). Used in vacuous union types. The concrete types already satisfy the protocol structurally.

### [10.1] CONFIRMED (HIGH confidence)
`analysis/` has 20 files. `analysis/findings/` has 14 files nested inside. Import paths are 4 segments deep: `vibesensor.analysis.findings.order_findings`. Related code is split across levels: `order_analysis.py` (top) and `order_findings.py` (sub-package).

## Root Complexity Drivers

1. **Mirrored constructor pattern**: LifecycleManager was extracted from RuntimeState but not given a reference back to it. Each subsystem is passed individually to both.

2. **Compatibility-shim decomposition**: SignalProcessor was decomposed into internal classes but old access patterns were preserved via aliases. The decomposition was done without updating consumers.

3. **Premature sub-packaging**: `report/mapping/` and `analysis/findings/` were given sub-package treatment when flat modules would suffice. The sub-package overhead (directories, `__init__.py`, internal imports) adds cognitive cost.

4. **Protocol overuse**: Protocols were added for type narrowing where only one concrete type exists. The Protocols provide fictional substitutability that is never exercised.

5. **Per-invocation wrappers**: `UpdateWorkflow` wraps constructor arguments into a dataclass that lives for one method call. The pattern obscures ownership.

## Simplification Strategy

### Step 1: Fix LifecycleManager to accept RuntimeState

**Implementation:**
1. Modify `LifecycleManager.__init__` to accept a single `runtime: RuntimeState` parameter
2. Store `self._runtime = runtime` and access subsystems via `self._runtime.ingress`, `self._runtime.settings`, etc.
3. Handle the circular construction issue: In `bootstrap.py`, construct `RuntimeState` first (with `lifecycle=None` or a sentinel), then construct `LifecycleManager(runtime)` and assign `runtime.lifecycle = lifecycle_manager`
4. Alternatively, use a factory pattern: `lifecycle = LifecycleManager.__new__(LifecycleManager)`, assign to RuntimeState, then call `lifecycle._init(runtime)`. But this is over-engineered — the `lifecycle=None` then assign pattern is simpler.
5. Update `RuntimeState` to allow `lifecycle` to be set after construction (remove `frozen=True` for that field, or make it a property with a setter, or use `object.__setattr__`)
6. Delete the 9 individual parameter slots from `LifecycleManager.__init__`

**Key consideration**: `RuntimeState` is a dataclass. If it's frozen, we need to handle post-construction assignment of `lifecycle`. Check whether it's frozen.

### Step 2: Remove SignalProcessor compatibility aliases

**Implementation:**
1. Remove the 6 attribute aliases from `SignalProcessor.__init__`:
   - `self._buffers`, `self._lock`, `self._fft_window`, `self._fft_scale`, `self._fft_cache`, `self._fft_cache_lock`
2. Update any test code that accesses these aliased attributes to use the proper path:
   - `processor._buffers` → `processor._store.buffers`
   - `processor._lock` → `processor._store.lock`
   - `processor._fft_cache` → `processor._metrics.fft_cache`
   etc.
3. Keep the 3 internal classes (`SignalBufferStore`, `SignalMetricsComputer`, `SignalProcessorViews`) — they have genuine separation of concern
4. Remove the comment about "Preserve the established internal surface"

### Step 3: Collapse report/mapping/ sub-package into single module

**Implementation:**
1. Create `apps/server/vibesensor/report/mapping.py` (new file)
2. Concatenate the contents of `pipeline.py`, `context.py`, `systems.py`, `peaks.py`, `actions.py`, `common.py`, `models.py` into the single file
3. Order: models/dataclasses first, then common helpers, then context, systems, peaks, actions, then the pipeline entry point `map_summary()`
4. Make all functions that were previously module-scope but internal into `_private` functions
5. Delete `report/mapping/` directory (7 files + __init__.py)
6. The caller import `from ..report.mapping import map_summary` stays unchanged since Python allows `report/mapping.py` module import via the same path
7. Update any test imports that referenced sub-modules inside `report/mapping/`

### Step 4: Remove OrderHypothesisLike Protocol and export concrete class

**Implementation:**
1. Rename `_OrderHypothesis` to `OrderHypothesis` in `analysis/order_analysis.py` (remove underscore prefix)
2. Export it from `order_analysis.py` — add to `__all__` or make publicly importable
3. In `order_models.py`, delete the `OrderHypothesisLike` Protocol definition
4. In `order_assembly.py`, `order_matching.py`, `order_findings.py`: replace `OrderHypothesisLike` with `OrderHypothesis` in all type annotations
5. Update imports in consumer modules: `from ..order_analysis import OrderHypothesis`
6. If `order_models.py` becomes empty (only had the Protocol + `OrderMatchAccumulator`), keep `OrderMatchAccumulator` in it or move it

### Step 5: Inline UpdateWorkflow into UpdateManager

**Implementation:**
1. Move the `run()` method logic from `UpdateWorkflow` into a private method on `UpdateManager` (e.g., `_execute_update_workflow()`)
2. Instead of constructing `UpdateWorkflow(tracker, validator, ...)`, the method directly creates local variables: `validator = UpdatePrerequisiteValidator(self._validation_config)`, etc.
3. This aligns the main update path with `_snapshot_for_rollback()` and `_rollback()`, which already construct their sub-objects inline
4. Delete the `UpdateWorkflow` dataclass from `workflow.py`
5. Delete `_build_workflow()` from `manager.py`
6. Keep the rest of `workflow.py` (validation config, prerequisite validator, etc.) — only the wrapper dataclass is removed

### Step 6: Remove private Protocols in rotational_speeds.py

**Implementation:**
1. Delete `_SpeedSourceSettingsStore` Protocol definition
2. Delete `_GpsMonitorState` Protocol definition
3. Replace union types in function signatures:
   - `SettingsStore | _SpeedSourceSettingsStore` → `SettingsStore`
   - `GPSSpeedMonitor | _GpsMonitorState` → `GPSSpeedMonitor`
4. Remove unused Protocol import

### Step 7: Flatten analysis/findings/ into analysis/

**Implementation:**
1. Move all 14 files from `analysis/findings/` to `analysis/` with prefix naming:
   - `findings/__init__.py` → delete (re-export file)
   - `findings/builder.py` → `analysis/findings_builder.py`
   - `findings/builder_support.py` → `analysis/findings_builder_support.py`
   - `findings/intensity.py` → `analysis/findings_intensity.py`
   - `findings/order_findings.py` → `analysis/findings_order.py`
   - `findings/order_matching.py` → `analysis/findings_order_matching.py`
   - `findings/order_assembly.py` → `analysis/findings_order_assembly.py`
   - `findings/order_models.py` → `analysis/findings_order_models.py` (or merged after step 4)
   - `findings/transient.py` → `analysis/findings_transient.py`
   - `findings/severity.py` → `analysis/findings_severity.py` (check for collision with existing analysis/severity.py)
   - `findings/_constants.py` → `analysis/findings_constants.py`
   - etc.
2. Update all imports from `vibesensor.analysis.findings.X` to `vibesensor.analysis.findings_X`
3. Delete `analysis/findings/` directory
4. Update test imports that reference `analysis.findings.*`

**Key concern**: Check for filename collisions between `analysis/` and `findings/` files. For example, both might have a `severity.py`. Use the `findings_` prefix to avoid collisions systematically.

## Dependencies on Other Chunks

- **Chunk 1** must complete first (it changes import paths for simulator, which might affect some test files)
- **Chunk 4** builds on this chunk's type cleanup — the TypedDict removal in chunk 4 pairs well with the Protocol removal here
- Step 4 (OrderHypothesisLike) and Step 7 (flatten findings/) interact: do the Protocol removal first (step 4 prepares the ground), then the flatten (step 7 moves the files)

## Risks and Tradeoffs

- **LifecycleManager circular construction**: The biggest risk is the circular dependency between RuntimeState (needs lifecycle) and LifecycleManager (needs runtime). Mitigation: use a two-phase construction with `lifecycle=None` initially.
- **SignalProcessor alias removal**: Tests that access `processor._buffers` directly will need updates. These are private API tests — the risk is moderate but the changes are mechanical.
- **report/mapping/ collapse**: A 500-line file is harder to navigate than 8 smaller files. But one file is easier to understand holistically for a single-consumer function.
- **analysis/findings/ flatten**: This is the largest rename operation, touching ~14 files and potentially many import sites. Risk is mechanical but blast radius is large.

## Validation Steps

1. `pytest -q apps/server/tests/` — full test suite
2. `make lint` — ruff passes
3. `make typecheck-backend` — mypy passes with all changes
4. `pytest -q apps/server/tests/integration/` — integration tests work
5. Verify no `from vibesensor.analysis.findings.` imports remain (should be `findings_`)
6. Verify `report/mapping/` directory no longer exists (only `report/mapping.py`)
7. Verify `UpdateWorkflow` class no longer exists

## Required Documentation Updates

- `docs/ai/repo-map.md`: Update references to `report/mapping/` sub-package and `analysis/findings/` sub-package
- `docs/report_pipeline.md`: Update if it references mapping sub-package structure

## Required AI Instruction Updates

- `.github/instructions/general.instructions.md`: Add guidance:
  - Do not create sub-packages for single-consumer, single-export modules
  - Do not create Protocol types for classes with only one implementor
  - Do not add compatibility aliases/shims when refactoring — update consumers directly
  - Prefer direct constructor parameters over wrapper dataclasses for one-shot operations
- `.github/instructions/backend.instructions.md`: Update references to analysis/findings/ structure

## Required Test Updates

- Update tests accessing `processor._buffers` etc. to use `processor._store.buffers`
- Update imports from `vibesensor.analysis.findings.X` to `vibesensor.analysis.findings_X`
- Update imports from `vibesensor.report.mapping.X` if any tests import sub-modules

## Simplification Crosswalk

### [1.1] LifecycleManager mirrors RuntimeState
- **Validation**: CONFIRMED
- **Root cause**: Per-field constructor mirroring
- **Steps**: Accept RuntimeState reference, remove 9 individual params
- **Code areas**: bootstrap.py, lifecycle.py, _state.py
- **What can be removed**: ~25 lines of duplicated constructor args
- **Verification**: Tests pass, lifecycle start/stop works

### [1.2] SignalProcessor aliases
- **Validation**: CONFIRMED (revised: keep decomposition, remove aliases only)
- **Root cause**: Compatibility shim over internal refactor
- **Steps**: Remove 6 aliases, update test references
- **Code areas**: processing/processor.py, test files
- **What can be removed**: 6 alias lines, compatibility comment
- **Verification**: Tests pass with updated references

### [1.3] report/mapping/ sub-package
- **Validation**: CONFIRMED
- **Root cause**: Sub-package for single-consumer function
- **Steps**: Concatenate 7 implementation files into mapping.py, delete directory
- **Code areas**: report/mapping/, history_services/reports.py
- **What can be removed**: 7 files, directory, internal circular-import workaround
- **Verification**: map_summary() import works, report tests pass

### [2.1] OrderHypothesisLike Protocol
- **Validation**: CONFIRMED
- **Root cause**: Protocol for single private implementor
- **Steps**: Export concrete class, delete Protocol, update 3 consumer imports
- **Code areas**: analysis/findings/order_models.py, order_analysis.py, 3 consumer modules
- **What can be removed**: Protocol definition (~20 lines)
- **Verification**: mypy passes, analysis tests pass

### [2.2] UpdateWorkflow dataclass
- **Validation**: CONFIRMED (revised: inline orchestration, not full method body)
- **Root cause**: Per-invocation wrapper dataclass
- **Steps**: Move run() logic to UpdateManager private method, delete dataclass
- **Code areas**: update/workflow.py, update/manager.py
- **What can be removed**: UpdateWorkflow class, _build_workflow() factory
- **Verification**: Update workflow tests pass

### [2.3] Private Protocols in rotational_speeds.py
- **Validation**: CONFIRMED
- **Root cause**: Vacuous union types with structural-subtype redundancy
- **Steps**: Delete 2 Protocols, use concrete types in signatures
- **Code areas**: runtime/rotational_speeds.py
- **What can be removed**: 2 Protocol definitions, union types
- **Verification**: mypy passes

### [10.1] analysis/findings/ double-nesting
- **Validation**: CONFIRMED
- **Root cause**: Sub-package for related code within a package
- **Steps**: Move 14 files to analysis/ with findings_ prefix, update imports
- **Code areas**: analysis/findings/, all importing modules
- **What can be removed**: findings/ directory, __init__.py
- **Verification**: All analysis and integration tests pass
