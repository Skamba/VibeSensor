# Chunk 4: Test Infrastructure & Tooling Simplification

## Mapped Findings

| ID | Title | Validation | Status |
|----|-------|------------|--------|
| F1 | scenario_ground_truth.py parallel implementation | INVALID — inputs vs outputs, not duplicative | Removed |
| F2 | regression/audits/ omnibus files | PARTIALLY VALID | Plan below |
| F3 | Multiple standard_metadata builders | PARTIALLY VALID | Plan below |
| G1 | run_ci_parallel.py duplicates CI YAML | VALID | Plan below |
| G3 | release-smoke blocks backend-tests in CI | VALID | Plan below |

## Validation Details

### F1: REMOVED (INVALID)

Validation showed `scenario_ground_truth.py` builds expected output assertions while
`sample_scenarios.py` builds input sample data. They are complementary, not duplicative.
No action.

### F2: regression/audits/ Omnibus Files (PARTIALLY VALID)

**Validated:** 5 files in `regression/audits/`:
- `test_analysis_pipeline_audit.py` → tests analysis modules → re-home to `regression/analysis/`
- `test_report_pipeline_audit.py` → tests report mapping → re-home to `regression/report/`
- `test_backend_typing_boundary_audit.py` → meta/architecture → re-home to `hygiene/`
- `test_coverage_gap_audit_top10.py` → mostly analysis → re-home to `regression/analysis/`
- `test_coverage_gap_audit_round2.py` → genuinely cross-cutting → re-home to `regression/cross_cutting/`

**Plan:** Redistribute all 5 files, delete `regression/audits/` directory. Rename test classes
to use behavior-descriptive names instead of "FindingN" prefix where practical.

### F3: Multiple standard_metadata Builders (PARTIALLY VALID)

**Validated:** 3 instances found (not 4):
1. `test_support/core.py::standard_metadata()` — canonical
2. `test_support/scenario_regression.py::standard_metadata()` — wrapper with different defaults
3. `tests/integration/test_real_world_scenarios.py::_standard_metadata()` — local duplicate

**Plan:** Delete the local `_standard_metadata()` in `test_real_world_scenarios.py` and import
from `test_support`. The wrapper in `scenario_regression.py` serves a different defaults profile
so it stays — but rename it to `scenario_regression_metadata()` to avoid name collision risk.

### G1: run_ci_parallel.py Duplicates CI YAML (VALID)

**Validated:** ~310 lines mirroring all 7 CI job groups. Job definitions must be kept in sync
with `ci.yml`. The script serves a legitimate purpose (local parallel CI) but the duplication
is the core risk.

**Revised plan:** Rather than deleting the script (it's the documented `make test-all` tool),
reduce it by extracting job commands from a shared source or simplifying the infrastructure.
Practically: slim the script by removing the custom threading/logging infrastructure and using
`subprocess` with `concurrent.futures.ThreadPoolExecutor` instead. This is a moderate reduction
(~310 → ~200 lines) but the real fix is acknowledging the duplication and adding a comment
pointing to `ci.yml` as source of truth for job definitions.

### G3: release-smoke Blocks backend-tests in CI (VALID)

**Validated:** `ci.yml` shows `backend-tests` and `e2e` both `needs: [..., release-smoke]`.
`release-smoke` includes a full UI build + wheel compilation, creating a ~20-minute gate before
backend tests can start.

**Plan:** Remove `release-smoke` from the `needs` list of `backend-tests` and `e2e`. These tests
are logically independent of wheel packaging correctness. Keep `release-smoke` as a parallel job.

## Implementation Steps

### Step 1: Redistribute regression/audits/ tests (F2)
1. Move `test_analysis_pipeline_audit.py` to `tests/regression/analysis/`
2. Move `test_report_pipeline_audit.py` to `tests/regression/report/`
3. Move `test_backend_typing_boundary_audit.py` to `tests/hygiene/`
4. Move `test_coverage_gap_audit_top10.py` to `tests/regression/analysis/`
5. Move `test_coverage_gap_audit_round2.py` to `tests/regression/cross_cutting/`
6. Delete empty `tests/regression/audits/` directory
7. Update `tests/regression/README.md` to remove audits/ reference

### Step 2: Consolidate standard_metadata (F3)
1. In `tests/integration/test_real_world_scenarios.py`: delete `_standard_metadata()`, import
   `standard_metadata` from `test_support`
2. Delete `_TIRE_CIRC` local constant (already available as `TIRE_CIRC` in `test_support.core`)

### Step 3: Fix CI dependency chain (G3)
1. Edit `.github/workflows/ci.yml`:
   - Remove `release-smoke` from `backend-tests.needs`
   - Remove `release-smoke` from `e2e.needs`
   - Keep `release-smoke` as independent parallel job

### Step 4: Simplify run_ci_parallel.py (G1)
1. Add comment noting ci.yml is the source of truth for job definitions
2. Simplify logging infrastructure — remove custom PRINT_LOCK/RESULT_LOCK in favor of
   simpler concurrent.futures pattern if feasible without major rewrite

## Dependencies on Other Chunks
- Independent of all other chunks

## Risks
- Moving test files could break pytest collection if conftest.py scoping differs
- CI dependency change could surface a real release-smoke → backend-tests dependency (unlikely)

## Documentation Updates Required
- `tests/regression/README.md`: remove audits/ section
- `docs/testing.md`: update regression directory description if it mentions audits/

## Validation
- Run full `make test-all` after moving files to ensure all tests still pass
- Verify moved tests are collected by pytest in their new locations
