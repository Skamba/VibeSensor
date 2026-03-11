# Chunk 1: Analysis Package Consolidation

## Overview
The analysis package (`vibesensor/analysis/`) has accumulated unnecessary complexity through
dead code, duplicate functions, micro-module fragmentation, inconsistent field naming, and
cross-module private symbol leakage. This chunk addresses 4 validated findings to reduce
the analysis package from 14 to ~10 modules, eliminate a 565-line dead file, unify a
field-naming inconsistency across 8+ modules, and consolidate a duplicated utility function.

## Mapped Findings

### Finding 1: Dead `findings_order_analysis.py` with exact function duplicates (A1-1 + A10-2)
- **Original**: Subagent 1 finding 1 + Subagent 10 finding 2
- **Validation result**: CONFIRMED. The file exists (565+ lines), is imported by zero
  production code, and contains 9 functions/classes that are character-for-character
  identical to definitions in `order_analysis.py`. The file's docstring confirms it was a
  mid-consolidation artifact that was never completed.
- **Validated root cause**: A four-module consolidation merged `findings_order_models.py`,
  `findings_order_matching.py`, `findings_order_scoring.py`, and `findings_order_support.py`
  into `findings_order_analysis.py`, but the final merge into `order_analysis.py` never
  happened. The file was left in place as dead code.

### Finding 2: `confidence_0_to_1` / `confidence` field name split (A1-3)
- **Original**: Subagent 1 finding 3
- **Validation result**: CONFIRMED. `Finding` uses `confidence_0_to_1` as the field name.
  `TopCause` uses `confidence`. The explicit rename happens at `top_cause_selection.py:79`:
  `"confidence": representative.get("confidence_0_to_1")`. A compensating `extract_confidence()`
  dual-lookup function exists in `report/mapping.py:191-198`. `ranking.py` re-implements the 
  same lookup pattern independently. The split touches `_types.py`, `findings.py`, 
  `order_analysis.py`, `summary_builder.py`, `ranking.py`, `top_cause_selection.py`, 
  `test_plan.py`, `report/mapping.py`, and `report/pdf_page2.py`.
- **Validated root cause**: `confidence_0_to_1` was the original verbose name (signaling 0-1
  range). When `TopCause` was introduced, the field was shortened to `confidence` for brevity,
  but `Finding` was never updated. Every downstream consumer must handle both.

### Finding 3: Duplicate `_i18n_ref` helper (A2-3)
- **Original**: Subagent 2 finding 3
- **Validation result**: CONFIRMED with nuance. Two independent copies exist:
  - `run_context.py:19`: private, 4 internal callsites, returns `JsonObject`
  - `order_analysis.py:178`: private but imported by 3 sibling modules
    (`summary_builder.py:70`, `findings.py:57`, `test_plan.py:13`), returns `I18nRef`
  Both produce identical `{"_i18n_key": key, **params}` dicts. The cross-module import of
  a private symbol from `order_analysis` couples 3 modules to that file's internal layout.
- **Validated root cause**: Both modules independently needed a lightweight i18n-ref builder
  and each wrote a local copy. No one consolidated the two.

### Finding 4: Vehicle settings field name mismatch in analysis (A3-1)
- **Original**: Subagent 3 finding 1
- **Validation result**: REFINED. The dual-source read pattern (sample first, metadata
  fallback) is justified for `gear` since it genuinely changes mid-run. However, the field
  name mismatch is unnecessary complexity: samples use `gear` while metadata uses
  `current_gear_ratio` for the same concept. The `analysis_settings_snapshot` nested sub-dict
  duplicates the flat metadata keys. After validation, the highest-value simplification is
  removing the `analysis_settings_snapshot` nested duplication and standardizing the
  `final_drive_ratio` read path (it doesn't change mid-run, so the per-sample copy is
  redundant). The field-name mismatch between `gear` and `current_gear_ratio` should be
  unified.
- **Validated root cause**: Settings were copied into samples via `_SETTINGS_PASSTHROUGH_KEYS`
  at record time, then `apply_run_context_snapshot()` wrote them again as a nested
  `analysis_settings_snapshot`. The `gear` vs `current_gear_ratio` naming diverged because
  the sample-level key was simplified while the metadata key preserved the config name.

## Root Causes Behind These Findings
1. Incomplete refactoring: merges that were started but never completed
2. Organic field naming: different naming conventions at different layers
3. Private-symbol leakage: modules importing `_`-prefixed symbols from siblings
4. Incremental settings accumulation: snapshot mechanisms added without cleanup

## Relevant Code Paths and Components

### Dead file deletion
- `apps/server/vibesensor/analysis/findings_order_analysis.py` — delete entirely
- No production imports to update

### Confidence field rename
- `apps/server/vibesensor/analysis/_types.py` — `Finding` TypedDict: rename field
- `apps/server/vibesensor/analysis/findings.py` — all sites that set `confidence_0_to_1`
- `apps/server/vibesensor/analysis/order_analysis.py` — all sites that set `confidence_0_to_1`
- `apps/server/vibesensor/analysis/ranking.py` — reads `confidence_0_to_1`
- `apps/server/vibesensor/analysis/top_cause_selection.py` — reads and renames
- `apps/server/vibesensor/analysis/summary_builder.py` — reads `confidence_0_to_1`
- `apps/server/vibesensor/analysis/test_plan.py` — reads `confidence_0_to_1`
- `apps/server/vibesensor/report/mapping.py` — `extract_confidence()` dual-lookup
- `apps/server/vibesensor/report/pdf_page2.py` — may read confidence
- Tests: any test that asserts on `confidence_0_to_1` key name

### _i18n_ref consolidation
- `apps/server/vibesensor/analysis/_types.py` — add `i18n_ref()` function
- `apps/server/vibesensor/analysis/order_analysis.py` — remove local `_i18n_ref`, import from `_types`
- `apps/server/vibesensor/analysis/summary_builder.py` — change import source
- `apps/server/vibesensor/analysis/findings.py` — change import source
- `apps/server/vibesensor/analysis/test_plan.py` — change import source
- `apps/server/vibesensor/run_context.py` — remove local copy, import from `analysis._types`

### Vehicle settings field name unification
- `apps/server/vibesensor/analysis/helpers.py` — dual-source lookup pattern
- `apps/server/vibesensor/analysis/order_analysis.py` — dual-source lookup pattern
- `apps/server/vibesensor/metrics_log/sample_builder.py` — where passthrough keys are defined
- Run context snapshot code

## Simplification Approach

### Step 1: Delete `findings_order_analysis.py`
1. Delete `apps/server/vibesensor/analysis/findings_order_analysis.py`
2. Verify no imports break (already confirmed: zero production imports)
3. Verify no test files import from it
4. Clean any `__pycache__` or `.mypy_cache` references

### Step 2: Unify `confidence_0_to_1` → `confidence`
1. In `_types.py`, rename `Finding["confidence_0_to_1"]` to `Finding["confidence"]`
2. In `findings.py`, update all `"confidence_0_to_1": value` to `"confidence": value`
3. In `order_analysis.py`, update all `"confidence_0_to_1": value` to `"confidence": value`
4. In `ranking.py`, update all `.get("confidence_0_to_1")` to `.get("confidence")`
5. In `top_cause_selection.py`, remove the rename step (`"confidence": representative.get("confidence_0_to_1")` → just pass through `confidence`)
6. In `summary_builder.py`, update all reads of `confidence_0_to_1` to `confidence`
7. In `test_plan.py`, update reads
8. In `report/mapping.py`, simplify `extract_confidence()` to single `.get("confidence")`
9. Update all tests that assert on the `confidence_0_to_1` key name
10. Grep for any remaining references to `confidence_0_to_1` and update

### Step 3: Consolidate `_i18n_ref`
1. Add `def i18n_ref(key: str, **params: JsonValue) -> I18nRef:` to `analysis/_types.py`
   (public name, no underscore, placed in the shared types module)
2. In `order_analysis.py`, delete local `_i18n_ref`, add `from ._types import i18n_ref`
3. In `summary_builder.py`, change `from .order_analysis import _i18n_ref` to `from ._types import i18n_ref`
4. In `findings.py`, change `from .order_analysis import _build_order_findings, _i18n_ref` to separate imports
5. In `test_plan.py`, update import
6. In `run_context.py`, change to `from vibesensor.analysis._types import i18n_ref`
7. Update all callsites from `_i18n_ref(...)` to `i18n_ref(...)`

### Step 4: Standardize vehicle settings field names
1. In `sample_builder.py`, verify `_SETTINGS_PASSTHROUGH_KEYS` uses `gear` not `current_gear_ratio`
2. In `analysis/helpers.py`, unify the lookup: use `sample.get("gear")` with fallback to
   `metadata.get("gear")` (not `current_gear_ratio`)
3. In `analysis/order_analysis.py`, same unification
4. If `current_gear_ratio` is set anywhere in metadata construction, rename it to `gear`
5. Update the `analysis_settings_snapshot` to not duplicate flat keys that are already present

## Dependencies on Other Chunks
- Chunk 3 (Persistence/Report) depends on the confidence field rename from this chunk
- No dependencies on other chunks

## Risks and Tradeoffs
- **Confidence rename**: This is a mechanical rename, but it changes the persisted field name
  in `Finding` dicts. Since `Finding` dicts flow through `SummaryData` and are persisted in
  the DB analysis JSON, older persisted runs may still have `confidence_0_to_1`. The
  `analysis_is_current` mechanism (being removed in Chunk 3) triggers re-analysis, so old
  runs would be re-analyzed with the new field name. However, any code that reads historical
  analysis JSON should handle the old name gracefully during transition. We'll add a
  one-line fallback in `extract_confidence()` for backward compat if needed.
- **_i18n_ref rename**: Public name (`i18n_ref` without underscore) makes the symbol explicitly
  part of the module's public API instead of an accidentally-leaked private.
- **Dead file deletion**: Zero risk — confirmed no production imports.

## Validation Steps
1. `ruff check apps/server/` — lint passes
2. `make typecheck-backend` — type checking passes
3. `pytest -q apps/server/tests/analysis/` — all analysis tests pass
4. `pytest -q apps/server/tests/report/` — report tests pass (confidence rename)
5. `pytest -q apps/server/tests/regression/analysis/` — regression tests pass
6. Grep for `confidence_0_to_1` across codebase — zero matches
7. Grep for `findings_order_analysis` across codebase — zero matches
8. Grep for `from .order_analysis import.*_i18n_ref` — zero matches

## Required Documentation Updates
- `docs/ai/repo-map.md` — update analysis package description if file count changes
- No user-facing docs affected

## Required AI Instruction Updates
- Add guidance to `.github/instructions/backend.instructions.md` about:
  - Not creating parallel file copies during refactoring (complete the merge)
  - Using `confidence` as the canonical confidence field name
  - Importing shared analysis utilities from `_types.py`, not from sibling modules

## Required Test Updates
- Update any tests that assert on `"confidence_0_to_1"` key in Finding dicts
- Update any tests that import from `findings_order_analysis`
- Verify no test creates samples with `"current_gear_ratio"` expecting the old name

## Simplification Crosswalk

### A1-1+A10-2 → Delete dead `findings_order_analysis.py`
- Validation: CONFIRMED dead (zero imports, 9 duplicate functions)
- Root cause: Incomplete refactoring
- Steps: Delete file, verify no breakage
- Code areas: `vibesensor/analysis/findings_order_analysis.py`
- What can be removed: Entire 565-line file
- Verification: Zero grep matches for filename, all tests pass

### A1-3 → Unify confidence field name
- Validation: CONFIRMED (dual-lookup in mapping.py, rename in top_cause_selection.py)
- Root cause: Partial rename when TopCause was introduced
- Steps: Rename in _types.py, update all 8 producer/consumer files, simplify extract_confidence()
- Code areas: _types.py, findings.py, order_analysis.py, ranking.py, top_cause_selection.py,
  summary_builder.py, test_plan.py, report/mapping.py
- What can be removed: extract_confidence() dual-lookup logic, rename step in top_cause_selection.py
- Verification: Zero grep matches for old name, all analysis+report tests pass

### A2-3 → Consolidate _i18n_ref
- Validation: CONFIRMED (two copies, cross-module private import)
- Root cause: Independent implementations, no shared location
- Steps: Add to _types.py as public `i18n_ref`, update 5 import sites, delete 2 copies
- Code areas: _types.py, order_analysis.py, summary_builder.py, findings.py, test_plan.py, run_context.py
- What can be removed: Two local `_i18n_ref` definitions
- Verification: Zero grep matches for `def _i18n_ref`, all tests pass

### A3-1 → Standardize settings field names
- Validation: REFINED — dual-source justified for gear, but field name mismatch is real
- Root cause: Different naming conventions at sample vs metadata layers
- Steps: Unify `current_gear_ratio` → `gear` in metadata, simplify helpers
- Code areas: analysis/helpers.py, analysis/order_analysis.py, metrics_log/sample_builder.py
- What can be removed: One half of the dual-lookup where fields don't change mid-run
- Verification: Analysis tests pass, no references to old field name
