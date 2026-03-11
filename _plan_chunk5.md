# Chunk 5: Build, Tooling, and Test Infrastructure

## Execution order: 5 of 5

## Mapped Findings

| ID | Original Finding | Validation Result |
|----|-----------------|-------------------|
| E1 | Three-layer E2E runner chain: `run_ci_parallel.py` → `run_e2e_parallel.py` → `run_full_suite.py` (330 lines, 14 argparse flags, 4 always-skipped) | CONFIRMED — Full chain verified. run_full_suite.py is a 330-line orchestration script with 14 argparse flags and 4 features that are always-skipped. run_e2e_parallel.py adds a parallel wrapper. After removing always-skipped code, ~50 lines of Docker orchestration logic survive. |
| E2 | `run_ci_parallel.py` mirrors CI YAML jobs with an explicit "keep in sync" docstring — no shared config | CONFIRMED — Docstring says "keep this file in sync with .github/workflows/ci.yml". 7 CI jobs are mirrored inline. One divergence: local script adds `[ocr]` extras for the test install. |
| E3 | Release workflow has an inline shell UI build while `tools/build_ui_static.py` is a separate implementation for the same task | CONFIRMED — Release workflow `.github/workflows/main-release.yml` has 8 lines of inline shell for UI build. `tools/build_ui_static.py` is a proper Python script. They have 3 differences: contract sync step, typecheck step, metadata JSON. |
| E4 | `sync_shared_contracts_to_ui.mjs` dedicates 48% of its code (65/136 lines) to converting WebSocket schema to fake-OpenAPI format | CONFIRMED — 65 of 136 lines are devoted to a fake-OpenAPI conversion pipeline that wraps WS message schemas in an artificial OpenAPI response envelope. |
| T1 | Dual phase-builder families for test fixture construction — `scenario_ground_truth.py` and `sample_scenarios.py` provide overlapping builder types | CONFIRMED — 3 of 7 builder types are duplicated (idle, noise, ramp). Both share the same `make_sample` base function. `scenario_ground_truth.py` has 3 test file consumers. |
| T2 | `report_analysis_integration.py` patches private internals to create fixtures | Has 4 test consumers (not 2 as originally stated): test_report_analysis_log_integration.py, test_report_analysis_phase_flow.py, test_report_analysis_localization_integration.py, test_report_analysis_findings_integration.py. |
| A4 | `tools/ci/` subdirectory contains exactly 1 file (`watch_pr_checks.py`) | CONFIRMED — tools/ci/ is a single-file subdirectory. tools/ root also has 2 loose files (build_ui_static.py, cleo_api_fixes.py). |

## Root Causes

- **E1**: Test orchestration scripts were layered incrementally (full_suite first, then E2E parallelizer, then CI parallelizer) without consolidating. Features were skipped via flags rather than deleted.
- **E2**: No shared definition of CI jobs; each copy (YAML, Python) is maintained independently with only a docstring reminder to stay in sync.
- **E3**: Release workflow was written before `build_ui_static.py` existed, and neither was unified afterward.
- **E4**: WebSocket schemas don't fit OpenAPI natively, so a conversion layer was added to reuse `openapi-typescript` for codegen. The conversion is fragile and verbose.
- **T1**: Test DSL (`sample_scenarios.py`) was added after `scenario_ground_truth.py`, which already had its own builder functions. Neither was consolidated.
- **T2**: Integration helpers patch private module internals because the public API doesn't expose the right seams for testing.
- **A4**: `tools/ci/` was created speculatively before more CI tools were added.

## Simplification Approach

### E1: Simplify E2E runner chain

**Strategy**: Inline the Docker orchestration logic from `run_full_suite.py` into `run_e2e_parallel.py`. Remove `run_full_suite.py`. Strip out the 4 always-skipped feature flags and their dead code.

**Steps**:
1. Read `run_full_suite.py` and identify the ~50 lines of surviving Docker orchestration logic
2. Move that logic into `run_e2e_parallel.py` as a helper function
3. Delete `run_full_suite.py`
4. In `run_e2e_parallel.py`, remove any argparse flags that only existed for skipped features
5. Update any Makefile targets or docs that reference `run_full_suite.py`

### E2: Reduce run_ci_parallel.py drift risk

**Strategy**: The "keep in sync" approach is inherently fragile. The simplest fix is to add a comment in CI YAML pointing to the Python script and vice versa, making the coupling explicit and bidirectional. Also remove the OCR extras divergence by standardizing on one approach.

Actually, for a simplification PR, the most impactful approach is: reduce the drift surface by extracting CI job definitions to a shared data structure. But this adds machinery. The pragmatic approach: add a hygiene test that confirms the local runner's job list matches CI YAML job names. This catches drift at CI time.

**Steps**:
1. Add a hygiene test that reads `.github/workflows/ci.yml` and extracts job names
2. Import the job list from `run_ci_parallel.py` 
3. Assert both lists match (ignoring execution details)
4. Fix the OCR extras divergence — add `[ocr]` to the CI install too, or remove it from local

### E3: Unify UI build

**Strategy**: Make the release workflow call `build_ui_static.py` instead of inline shell. Add the missing steps (contract sync, typecheck) to `build_ui_static.py` if they're not already there.

**Steps**:
1. Read `build_ui_static.py` and identify what it does vs what the release workflow does
2. Add missing steps to `build_ui_static.py` (contract sync, typecheck) if needed
3. Replace the inline shell in `main-release.yml` with a call to `python3 tools/build_ui_static.py`
4. Test that the build produces the same output

### E4: Simplify WS schema sync

**Strategy**: The fake-OpenAPI conversion exists solely to reuse `openapi-typescript` for WS schema types. The simpler alternative: generate TypeScript types directly from the Python schemas without the OpenAPI detour. This eliminates 48% of the script.

But this is a significant refactor with risk of breaking the generated types. A safer approach: extract the WS schema conversion into a clearly separated section with explicit comments, making it obvious what's WS-specific vs general. Or better — just simplify the conversion logic itself.

Actually, the simplest approach aligned with "minimize machinery": if the WS schemas are simple enough, hand-maintain the TypeScript types and delete the codegen pipeline entirely. But this creates drift risk.

For this PR, the pragmatic approach: clean up the 65-line conversion to be more concise (the code likely has unnecessary intermediate transformations). Target: reduce from 65 lines to ~30 by removing redundant steps.

**Steps**:
1. Read `sync_shared_contracts_to_ui.mjs` in full
2. Identify which conversion steps are actually necessary
3. Simplify: remove unnecessary intermediate arrays, reduce object spreading, consolidate transformation steps
4. Verify the generated TypeScript output is identical before and after

### T1: Consolidate phase-builder families

**Strategy**: Make `scenario_ground_truth.py` use the builders from `sample_scenarios.py` instead of duplicating them. Since `sample_scenarios.py` is the DSL layer, it should be the single source of builder functions.

**Steps**:
1. In `scenario_ground_truth.py`, replace the 3 duplicated builder functions (idle, noise, ramp) with imports from `sample_scenarios.py`
2. Verify that the builder APIs are compatible (same parameters, same output format)
3. If APIs differ slightly, adapt `scenario_ground_truth.py` callers to use the DSL API
4. Ensure all 3 test consumers still pass

### T2: Localize report_analysis_integration helpers

**Strategy**: Since all 4 consumers are in `tests/report/`, this helper is scoped to report testing. Keep it but clean up any private-patching that could be replaced with public API usage.

**Steps**:
1. Read `report_analysis_integration.py` to understand what it patches
2. Determine which patches can be replaced with public API calls
3. Where patches are truly necessary, add comments explaining why
4. Keep the file in `test_support/` since 4 consumers share it

### A4: Flatten tools/ci/

**Strategy**: Move `watch_pr_checks.py` from `tools/ci/` to `tools/`. Delete the empty `tools/ci/` directory.

**Steps**:
1. Move `tools/ci/watch_pr_checks.py` → `tools/watch_pr_checks.py`
2. Update all references: `.github/copilot-instructions.md`, Makefile, any docs
3. Delete `tools/ci/` directory
4. Update any imports or path references

## Implementation Sequence

1. A4 (flatten tools/ci/ — smallest change, no dependencies)
2. E1 (simplify E2E chain — self-contained test infra change)
3. T1 (consolidate phase-builders — test helper cleanup)
4. T2 (localize integration helpers — inspect and clean up)
5. E3 (unify UI build — CI workflow change)
6. E4 (simplify WS schema sync — tool script cleanup)
7. E2 (CI drift guard — hygiene test addition)

## Dependencies on Other Chunks

- E5 sync guard (Chunk 4) depends on E6 (Chunk 1) for `locations.py` as LOCATION_CODES source. No conflict with Chunk 5.
- T1 and T2 are independent of all other chunks.
- E1/E2/E3 touch CI infrastructure but don't conflict with other chunks.
- A4 (tools/ flatten) doesn't affect other chunks since the `watch_pr_checks.py` path is referenced in copilot-instructions.md (updated in Chunk 1's doc updates if needed, or done here).

## Risks and Tradeoffs

- **E1**: Low risk. Deleting a script and inlining its surviving logic. May break Makefile targets that reference `run_full_suite.py`.
- **E2**: Very low risk. Adding a hygiene test, not changing production code.
- **E3**: Medium risk. Changing CI workflow requires being very confident the Python script replicates the inline shell behavior.
- **E4**: Medium risk. Any change to codegen scripts could produce different TypeScript output. Must verify output is identical.
- **T1**: Low risk. Replacing builder definitions with imports. If APIs differ, need careful adaptation.
- **T2**: Low risk. Inspecting and potentially cleaning up test helpers. No production code changes.
- **A4**: Zero risk. File move with reference updates.

## Validation Steps

1. `make test-all` — full CI-parity run to catch any breakage
2. `pytest -q apps/server/tests/regression/` — regression suite
3. `make lint && make typecheck-backend` — code quality
4. `cd apps/ui && npm run typecheck && npm run build` — frontend (for E4 changes)
5. Verify generated TypeScript output is identical after E4 changes
6. Check Makefile targets still work after file moves

## Required Documentation Updates

- `docs/ai/repo-map.md` — update tools/ section
- `docs/testing.md` — update runner references
- `.github/copilot-instructions.md` — update `watch_pr_checks.py` path
- `tools/tests/README.md` or similar if exists

## Required AI Instruction Updates

- `.github/instructions/tests.instructions.md`: "Use sample_scenarios.py builders as the single source for test fixture construction. Do not duplicate builder functions across helper modules."
- `.github/instructions/general.instructions.md`: "Reference tools/ scripts by flat paths. Do not create subdirectories for single files."

## Required Test Updates

- Fix any tests that import from `run_full_suite.py` or reference it
- Add hygiene test for CI job list parity (E2)
- Update test fixture imports after T1 consolidation

## Simplification Crosswalk

| Finding | Validation | Root Cause | Steps | Areas Changed | What's Removed | Verification |
|---------|-----------|------------|-------|---------------|----------------|--------------|
| E1 | CONFIRMED (330 lines, 14 flags, 4 always-skip) | Layered scripts without consolidation | Inline Docker logic into run_e2e_parallel.py, delete run_full_suite.py | tools/tests/ | 1 file (~330 lines) | make test-all passes |
| E2 | CONFIRMED (explicit sync warning, 7 mirrored jobs) | No shared job definition | Add hygiene test for job-name parity | tests/hygiene/ | 0 code removed, drift guard added | Hygiene test passes |
| E3 | CONFIRMED (2 separate UI build implementations) | Scripts created at different times | Make release workflow call build_ui_static.py | main-release.yml, build_ui_static.py | ~8 lines inline shell from workflow | Release workflow functions correctly |
| E4 | CONFIRMED (48% of sync script is fake-OpenAPI) | Reusing openapi-typescript for non-OpenAPI schemas | Simplify conversion logic | sync_shared_contracts_to_ui.mjs | ~30 lines of verbose conversion | Generated TS output identical |
| T1 | CONFIRMED (3 of 7 builders duplicated) | DSL added after ground-truth without consolidation | Use sample_scenarios.py builders instead of duplicates | scenario_ground_truth.py | 3 duplicated builder functions | All 3 test consumers pass |
| T2 | CONFIRMED (4 consumers, patches privates) | Public API lacks test-friendly seams | Inspect and document, clean up where possible | report_analysis_integration.py | Private patches replaced where feasible | All 4 consumer tests pass |
| A4 | CONFIRMED (1-file subdirectory) | Speculative directory creation | Move file, delete directory | tools/ci/ → tools/ | 1 empty directory | All path references updated |
