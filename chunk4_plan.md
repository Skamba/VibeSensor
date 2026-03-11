# Chunk 4: Test Infrastructure Simplification

## Mapped Findings

| ID | Original Title | Validation | Status |
|----|---------------|------------|--------|
| F1/J1 | regression/ hollow duplicate directory | **Validated** — 4 files in 3 subdirs, all byte-for-byte identical to copies in analysis/ and integration/. Confirmed via diff. | Proceed |
| F2 | test_support/ scenario builders over-split into 5 thin modules | **Validated** — perturbation_scenarios.py (112 lines, 5 thin functions), scenario_ground_truth.py (192 lines, keyword-argument adapters), __init__.py re-exports ~80 symbols. Chain: core→sample_scenarios→fault_scenarios/perturbation_scenarios/scenario_ground_truth. | Proceed |
| F3 | Four independent FakeState classes | **Validated** — conftest.py:FakeState (112 lines), api/_history_endpoint_helpers.py:FakeState, analysis/test_analysis_settings_source_of_truth.py:_State, analysis/test_analysis_persistence.py:_FakeState. Each has its own field set that must track RuntimeState evolution. | Proceed |
| B1 | SignalProcessor private bridge shims for test access | **Validated** — 5 one-liner methods at processor.py:117-136 (`_get_or_create`, `_resize_buffer`, `_latest`, `_fft_params`, `_compute_fft_spectrum`). Zero production callers. Tests can use SignalBufferStore/SignalMetricsComputer directly. | Proceed |
| I1 | Selenium: full browser framework CI never runs | **Validated** — Only in test_ui_selenium.py:14 via importorskip. CI permanently excludes with `-m "not selenium"`. Playwright suites already exist in apps/ui/tests/. | Proceed |
| I2 | pypdfium2: 80MB binary in mandatory dev deps for one skippable test | **Validated** — In pyproject.toml `[dev]` deps. Single consumer: test_report_pdf_ocr_text_fidelity.py:16 via importorskip. Its companion rapidocr is correctly in `[ocr]` extras. | Proceed |

## Root Complexity Drivers

1. **Zombie directory**: `regression/` was partially migrated but originals were never deleted, causing test double-running.
2. **Over-split helpers**: Test scenario builders were split by category into too many thin modules, requiring an 80-symbol barrel re-export.
3. **Duplicated runtime fakes**: Four independent RuntimeState fakes drift out of sync with the real RuntimeState.
4. **Test-only bridge methods on production class**: SignalProcessor carries 5 private methods used exclusively by tests, when the underlying components can be tested directly.
5. **Dead dependency**: Selenium is installed but CI never runs it; Playwright covers the same layer.
6. **Incorrectly scoped dependency**: pypdfium2 is in mandatory dev deps but its test uses importorskip (designed for optional deps).

## Simplification Approach

### F1/J1: Delete regression/ duplicate directory

**Steps**:
1. Delete `apps/server/tests/regression/` directory entirely (all 4 files are duplicates)
2. Verify the canonical copies exist: `analysis/test_analysis_pipeline_integration_regressions.py`, `integration/test_concurrency_generation_guard_regressions.py`, `integration/test_runtime_nan_and_update_guard_regressions.py`, `integration/test_coverage_gap_audit_round2.py`
3. Remove any `conftest.py` or `__init__.py` files in regression/ subdirs

### F2: Consolidate test_support/ scenario builders

**Strategy**: Merge `perturbation_scenarios.py` and `scenario_ground_truth.py` into `sample_scenarios.py`. Merge `report_analysis_integration.py` into `report_helpers.py`. Slim down `__init__.py` re-exports.

**Steps**:
1. Move all functions from `perturbation_scenarios.py` into `sample_scenarios.py` (at the end, with a section comment)
2. Move all functions from `scenario_ground_truth.py` into `sample_scenarios.py`
3. Delete `perturbation_scenarios.py` and `scenario_ground_truth.py`
4. Move all functions from `report_analysis_integration.py` into `report_helpers.py`
5. Delete `report_analysis_integration.py`
6. Update `__init__.py` to import from the remaining modules only (core, analysis, assertions, sample_scenarios, report_helpers)
7. Update all test files that import from the deleted modules to use the new locations
8. Since most tests import from `test_support` via the barrel `__init__.py`, most imports should work without changes

### F3: Unify FakeState implementations

**Strategy**: Extend the root conftest.py `FakeState` to be the single authoritative fake. Other test files use it instead of creating their own.

**Steps**:
1. Review what each FakeState variant provides that the root one doesn't
2. Add any missing capabilities to the root `FakeState` in conftest.py (e.g., configurable `iter_run_samples`, `delete_run_if_safe`)
3. Update `api/_history_endpoint_helpers.py` to use the root `FakeState` via the `fake_runtime` fixture or import
4. Update `analysis/test_analysis_settings_source_of_truth.py` to use root `FakeState`
5. Update `analysis/test_analysis_persistence.py` to use root `FakeState`
6. Delete the local FakeState/`_State`/`_FakeState` classes
7. Note: After Chunk 1's A2 change, `lifecycle` field is removed from RuntimeState, so FakeState loses it too

### B1: Remove SignalProcessor bridge shims

**Steps**:
1. Delete the 5 private bridge methods from `SignalProcessor` in processor.py:
   - `_get_or_create()`
   - `_resize_buffer()`
   - `_latest()`
   - `_fft_params()`
   - `_compute_fft_spectrum()`
2. Update tests that call `proc._get_or_create(...)` to construct `SignalBufferStore` directly
3. Update tests that call `proc._fft_params(...)` to use `SignalMetricsComputer` directly
4. Follow the pattern already established in `test_processing_components.py`

### I1: Remove Selenium dependency

**Steps**:
1. Remove `"selenium>=4.20,<5"` from `pyproject.toml` `[dev]` dependencies
2. Delete `apps/server/tests/e2e/test_ui_selenium.py`
3. If the `e2e/` directory is empty after deletion, remove it (check for other files first)

### I2: Move pypdfium2 to optional extras

**Steps**:
1. Remove `"pypdfium2>=4.30,<5"` from the `[dev]` extras in pyproject.toml
2. Add it to an `[ocr]` extras group (alongside `rapidocr-onnxruntime`)
3. The `importorskip` guard in the test file already handles the case where it's not installed

## Dependencies on Other Chunks

- F3 depends on Chunk 1's A2 (lifecycle field removal) — FakeState should not have a lifecycle field afterwards
- B1 must happen after Chunk 2 if any processor bridge tests are affected, but they're independent
- F2 must happen after Chunk 3's J3 (metrics_log barrel cleanup) to avoid conflicting import updates

## Risks and Tradeoffs

1. **F2**: Merging scenario modules makes `sample_scenarios.py` larger (~700+ lines). This is acceptable for a test helper that serves as a single source of synthetic data.
2. **F3**: The root `FakeState` may need to grow to accommodate API test needs. If it becomes too complex, we can use fixtures with different configurations rather than separate classes.
3. **I1**: The selenium test contained some checks that Playwright doesn't. Verify Playwright coverage is adequate.
4. **B1**: Tests that use the bridge methods must be refactored to use the sub-components directly, which may reveal that some tests were testing at the wrong level.

## Validation Steps

1. `pytest -q apps/server/tests/` — full test suite (verify no double-runs from regression/)
2. `pytest -q apps/server/tests/processing/` — processor tests after bridge shim removal
3. `pytest -q apps/server/tests/api/` — API tests with unified FakeState
4. `pytest -q apps/server/tests/analysis/` — analysis tests with unified FakeState
5. `make lint && make typecheck-backend`

## Required Documentation Updates

- `docs/testing.md` — remove regression/ from layout if mentioned, confirm integration/ as the regression home

## Required AI Instruction Updates

- Add guardrail to tests.instructions.md: "Do not create local FakeState/fake runtime classes. Use the shared FakeState from conftest.py and configure it for your test's needs."
- Add guardrail: "Do not add private bridge methods to production classes for test access. Test sub-components directly instead."

## Required Test Updates

- Delete 4 duplicate test files in regression/
- Refactor tests using bridge shims to use sub-components directly
- Update all test imports for consolidated scenario builders
- Verify test counts are unchanged (minus the duplicates)

## Simplification Crosswalk

### F1/J1: regression/ duplicate directory
- **Validation**: Confirmed byte-for-byte via diff.
- **Root cause**: Incomplete migration — copies left behind.
- **Steps**: Delete entire regression/ directory.
- **Code areas**: apps/server/tests/regression/
- **Removed**: 4 duplicate test files, 3 subdirectories
- **Verification**: `pytest -q apps/server/tests/ | tail -5` — verify test count

### F2: test_support/ over-split builders
- **Validation**: Confirmed. perturbation_scenarios (112 lines), scenario_ground_truth (192 lines) are thin wrappers.
- **Root cause**: Incremental splitting by semantic category with too little content per file.
- **Steps**: Merge thin modules into sample_scenarios.py and report_helpers.py.
- **Code areas**: test_support/
- **Removed**: 3 thin modules (perturbation_scenarios.py, scenario_ground_truth.py, report_analysis_integration.py)
- **Verification**: `pytest -q apps/server/tests/`

### F3: Four independent FakeState classes
- **Validation**: Confirmed. 4 separate implementations tracking RuntimeState shape.
- **Root cause**: Each test module created its own for slightly different needs.
- **Steps**: Extend root FakeState, replace local variants.
- **Code areas**: conftest.py, api/_history_endpoint_helpers.py, 2 analysis test files
- **Removed**: 3 duplicate FakeState classes
- **Verification**: `pytest -q apps/server/tests/api/ apps/server/tests/analysis/`

### B1: SignalProcessor bridge shims
- **Validation**: Confirmed. 5 one-liners, zero production callers.
- **Root cause**: Test access hooks from before component split.
- **Steps**: Delete 5 methods, refactor tests to use components directly.
- **Code areas**: processing/processor.py, affected test files
- **Removed**: 5 methods from production class
- **Verification**: `pytest -q apps/server/tests/processing/`

### I1: Selenium
- **Validation**: Confirmed. CI permanently excludes, Playwright covers same layer.
- **Root cause**: Written before Playwright adoption, never removed.
- **Steps**: Remove dep, delete test file.
- **Code areas**: pyproject.toml, tests/e2e/test_ui_selenium.py
- **Removed**: 1 dependency, 1 test file
- **Verification**: `pip install -e ".[dev]" && pytest -q apps/server/tests/`

### I2: pypdfium2 optional
- **Validation**: Confirmed. importorskip signals optional but dep is mandatory.
- **Root cause**: Inconsistent dep classification.
- **Steps**: Move from [dev] to [ocr] extras.
- **Code areas**: pyproject.toml
- **Removed**: 80MB from default dev install
- **Verification**: `pip install -e ".[dev]"` — verify no pypdfium2
