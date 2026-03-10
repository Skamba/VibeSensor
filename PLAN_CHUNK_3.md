# Chunk 3: Analysis Pipeline & Internal Module Consolidation

## Mapped Findings

| ID | Original Finding | Source Subagent | Validation Status |
|----|-----------------|-----------------|-------------------|
| J1+I1+I2 | findings_order_* 7-file micro-sharding + findings_constants.py re-export shim + callable injection | Folder/Module/Ownership + Dependency/Library | **Validated** |
| B2 | FindingsBundle/SensorAnalysisBundle/RunSuitabilityBundle one-shot wrappers | Abstraction & Indirection | **Validated** |
| A3+C3 | MetricsLogger session_state.py and persistence.py have no independent existence + callback injection | Architecture & Layering + Data Flow | **Validated** |
| I3 | vibesensor/core/ orphaned sub-package after libs/ absorbed | Dependency/Library | **Validated** |

## Validation Outcomes

### J1+I1+I2: findings_order_* micro-sharding — VALIDATED

Confirmed 7 files totaling 1189 lines:
- `findings_constants.py` (23 lines): pure `from ..constants import X as X` re-exports, self-described as "exists only to keep local imports short"
- `findings_order_models.py` (45 lines): 2 frozen dataclasses (`OrderMatchAccumulator`, `OrderFindingBuildContext`)
- `findings_order_matching.py` (136 lines): 1 function (`match_samples_for_hypothesis`)
- `findings_order_scoring.py` (231 lines): constants + 3 public functions
- `findings_order_support.py` (157 lines): 4 functions for phase stats, amplitude, localization, speed evidence
- `findings_order_assembly.py` (225 lines): 1 function (`assemble_order_finding`) with 7 `Callable[...]` parameters
- `findings_order_findings.py` (372 lines): orchestrator that imports from ALL siblings, defines ~6 private wrapper functions that shadow the implementations

The callable injection pattern in `findings_order_assembly.py` is confirmed: `assemble_order_finding()` takes 7 callables as keyword args. `findings_order_findings.py` defines private wrappers (e.g., `_detect_diffuse_excitation_impl`) that just forward to the implementations, then passes them as callables. No test injects custom callables.

`findings_constants.py` has zero logic — all 14 constants are verbatim re-exports.

### B2: One-shot wrapper dataclasses — VALIDATED

Confirmed in `summary_models.py`:
- `FindingsBundle` (5 fields): created in `build_findings_bundle()`, destructured immediately in `summarize_run_data()`
- `SensorAnalysisBundle` (3 fields): created in `build_sensor_bundle()`, destructured immediately
- `RunSuitabilityBundle` (3 fields): created in `build_run_suitability_bundle()`, destructured immediately

All three are constructed once and immediately unpacked. Zero external consumers outside `summary_builder.py`. `PreparedRunData` (also in `summary_models.py`) IS reused — it stays.

### A3+C3: MetricsLogger session_state/persistence — VALIDATED

Confirmed:
- `session_state.py`: `MetricsSessionState` (88 lines of thread-safe property wrappers for ~8 private fields). Only production import is in `logger.py`. Also exports `LoggingStatusPayload` (TypedDict) and `MetricsSessionSnapshot` (frozen dataclass).
- `persistence.py`: `MetricsPersistenceCoordinator` with `generation_matches: Callable[[int], bool]` injected at construction. 8 guard sites with `if not self._generation_matches(session_generation): return`. Only production consumer is `logger.py`.

The callback injection is confirmed: `logger.py` passes `generation_matches=self._session.matches_generation` — a closure wrapping a thread-safe integer comparison. The coordinator cannot be constructed independently.

### I3: vibesensor/core/ orphaned sub-package — VALIDATED

Confirmed: `vibesensor/core/__init__.py` is a docstring-only module. Contains 3 files:
- `vibration_strength.py`: canonical dB computation, ~20 import sites
- `strength_bands.py`: band definitions, bucket classification
- `sensor_units.py`: 26 lines, one function (`get_accel_scale_g_per_lsb`)

All imports use `from vibesensor.core.vibration_strength import ...`. The `core/` nesting adds no information — these are the most-imported modules and the extra path level costs every consumer a longer import.

## Root Causes

1. **findings_order_***: Decomposition refactor went too fine-grained, creating a file per concern where a module per concern would suffice. Callable injection was likely an attempt to break potential circular imports or enable test injection, but neither need materialized.
2. **One-shot bundles**: Pipeline was split into named sub-steps for readability, using typed containers instead of tuples. The containers add type safety but violate the "no wrapper dataclasses for one-shot operations" rule.
3. **session_state/persistence**: Internal implementation details extracted for testability, but they're so coupled to the logger that they can't be independently constructed or tested meaningfully.
4. **core/**: Historical artifact from when shared libraries were separate pip packages.

## Implementation Steps

### Step 1: Delete findings_constants.py and update imports

1. Delete `vibesensor/analysis/findings_constants.py`
2. In all 7 consumer files, replace `from .findings_constants import X` with `from ..constants import X`
3. Verify with `ruff check` and `make typecheck-backend`

### Step 2: Consolidate findings_order_* into 2 files

Target structure:
- `findings_order_analysis.py` (merge models + matching + scoring + support): contains `OrderMatchAccumulator`, `OrderFindingBuildContext`, `match_samples_for_hypothesis`, scoring functions, support functions
- `findings_order_assembly.py` (keep, but remove callable injection): refactor `assemble_order_finding` to call scoring/support functions directly instead of receiving them as callables
- Delete `findings_order_models.py`, `findings_order_matching.py`, `findings_order_scoring.py`, `findings_order_support.py`
- Simplify `findings_order_findings.py`: remove private wrapper functions, call implementations directly from `findings_order_analysis.py`

Implementation:
1. Create `findings_order_analysis.py` by merging content from models, matching, scoring, support
2. Update `findings_order_assembly.py` to import directly from `findings_order_analysis.py` instead of taking callables
3. Remove all `Callable[...]` parameters from `assemble_order_finding()` — call functions directly
4. Simplify `findings_order_findings.py`:
   - Remove all private wrapper functions (`_detect_diffuse_excitation`, etc.)
   - Import directly from `findings_order_analysis.py`
   - The `_build_order_findings()` function calls functions directly
5. Delete the 4 old files
6. Update all test imports

### Step 3: Inline one-shot summary bundles

1. In `summary_builder.py`, replace `FindingsBundle`, `SensorAnalysisBundle`, `RunSuitabilityBundle` with direct local variable bindings
2. The `build_findings_bundle()`, `build_sensor_bundle()`, `build_run_suitability_bundle()` functions return tuples or their results are inlined into `summarize_run_data()`
3. Remove the 3 dataclass definitions from `summary_models.py`
4. Keep `PreparedRunData` (it IS reused)
5. If `summary_models.py` only has `PreparedRunData` left, keep it or merge into `summary_builder.py`

### Step 4: Merge metrics_log session_state.py and persistence.py into logger.py

1. Move `MetricsSessionState` class from `session_state.py` into `logger.py` (as `_MetricsSessionState`)
2. Move `LoggingStatusPayload` and `MetricsSessionSnapshot` into `logger.py`
3. Move `MetricsPersistenceCoordinator` from `persistence.py` into `logger.py` (as `_MetricsPersistenceCoordinator`)
4. Replace the `generation_matches` callable with a direct reference to `MetricsSessionState` (pass the state object, not a closure)
5. Delete `session_state.py` and `persistence.py`
6. Update `metrics_log/__init__.py` exports
7. Keep `post_analysis.py` and `sample_builder.py` as separate files (they are genuinely independent)
8. Update test imports — tests that construct `MetricsPersistenceCoordinator` directly should test through `MetricsLogger` instead, or access the private class for focused testing

### Step 5: Flatten vibesensor/core/ into vibesensor/

1. Move `vibration_strength.py`, `strength_bands.py`, `sensor_units.py` from `vibesensor/core/` to `vibesensor/`
2. Delete `vibesensor/core/__init__.py` and `vibesensor/core/` directory
3. Update all ~20+ import sites: `from vibesensor.core.vibration_strength import ...` → `from vibesensor.vibration_strength import ...` (or `from ..vibration_strength import ...` for relative imports)
4. Update test imports similarly
5. Update `pyproject.toml` mypy entries if they reference `core/`

### Step 6: Verify everything

1. `ruff check apps/server/`
2. `make typecheck-backend`
3. `pytest -q apps/server/tests/analysis/ apps/server/tests/metrics_log/`
4. Full test suite: `pytest -q apps/server/tests/ -m "not selenium"`

## Dependencies on Other Chunks

- Executes after Chunk 1 (dead code) and Chunk 2 (runtime flattening)
- Independent of Chunks 4 and 5

## Risks and Tradeoffs

- **findings_order_analysis.py size**: Merging models + matching + scoring + support creates a ~570-line file. This is acceptable — the algorithms are cohesive and readers no longer need to hop between 7 files.
- **metrics_log/logger.py size**: Merging session_state and persistence makes logger.py ~500+ lines. The internal classes are prefixed with `_` to signal they're implementation details. Tests can still import them for focused testing.
- **core/ flattening import churn**: ~20+ import sites need updating. This is mechanical and safe.

## Validation Steps

- `ruff check apps/server/`
- `make typecheck-backend`
- `pytest -q apps/server/tests/analysis/ apps/server/tests/metrics_log/ apps/server/tests/domain/`
- Full: `pytest -q apps/server/tests/ -m "not selenium"`

## Documentation Updates

- Update `docs/ai/repo-map.md`: remove `core/` sub-package reference, update metrics_log description, update analysis description
- Update `.github/copilot-instructions.md`: remove `vibesensor/core/` reference, update canonical dB definition path
- Update `.github/instructions/backend.instructions.md`: update package layout section
- Update `docs/testing.md` if test paths changed

## AI Instruction Updates

- Add to `general.instructions.md`:
  - "Do not create re-export shim modules that only alias imports from another module. Consumers should import from the source directly."
  - "Do not use Callable injection in function signatures when the callables are always the same implementations and no test injects alternatives. Call functions directly."
  - "Do not split a coherent algorithm across more than 3 files unless files have genuinely independent consumers."

## Test Updates

- Update test imports for renamed/moved modules
- Simplify tests that import `MetricsPersistenceCoordinator` directly
- Update analysis test imports for consolidated findings_order modules
- Verify regression tests still pass with inlined summary bundles

## Simplification Crosswalk

| Finding | Steps | Removable | Verification |
|---------|-------|-----------|-------------|
| J1+I1+I2 | Steps 1-2 | 5 files deleted, ~6 wrapper functions, callable injection pattern, re-export shim | analysis tests pass, zero remaining findings_constants imports |
| B2 | Step 3 | 3 dataclass definitions, 3 intermediate functions | summary_builder tests pass, PreparedRunData still exists |
| A3+C3 | Step 4 | 2 files deleted, callback injection pattern simplified | metrics_log tests pass, logger.py consolidates session/persistence |
| I3 | Step 5 | core/ directory, __init__.py, one import level across ~20 sites | all imports resolve, typecheck passes |
