# Chunk 5: Tooling, Testing & Structure Cleanup

## Mapped Findings

| ID | Original Finding | Source Subagent | Validation Status |
|----|-----------------|-----------------|-------------------|
| G1 | run_ci_parallel.py is a forked copy of ci.yml | Build/Tooling | **Validated, refined** |
| G2 | Three separate scripts for trivial git-hygiene grep checks | Build/Tooling | **Validated** |
| G3 | run_full_suite.py accumulated --skip-* flags from shard repurposing | Build/Tooling | **Validated, downgraded** |
| F1 | scenario_regression.py is a redundant shim module | Testing | **Validated** |
| F2 | Audit test files are half prose, half test | Testing | **Validated** |
| F3 | scenario_ground_truth.py duplicates fault_scenarios.py | Testing | **Validated** |
| J2 | Three UI single-file sub-directories | Folder/Module/Ownership | **Validated** |
| J3 | vibesensor/hotspot/ zero server consumers | Folder/Module/Ownership | **Validated, downgraded** |

## Validation Outcomes

### G1: run_ci_parallel.py CI mirror — VALIDATED, REFINED
The script mirrors CI job definitions locally. This duplication is real. However, the script provides genuine value: parallel local CI runs with per-job log files. The fix is not to delete it but to make it thinner — have it reference Makefile targets instead of inlining all step commands. This makes it a job-runner that delegates to existing targets rather than a CI-step-reimplementation.

**Refined scope**: Simplify `run_ci_parallel.py` to call Makefile targets (or small command groups) instead of inlining every ruff flag and mypy argument. This eliminates the "keep in sync" maintenance burden.

### G2: Three hygiene scripts — VALIDATED
Confirmed:
- `check_line_endings.py` (54 lines): CRLF detection via `git ls-files` + byte scan
- `check_no_pycache.py` (61 lines): **dead code** — not in CI, not in Makefile
- `verify_no_path_indirections.py` (65 lines): sys.path hack detection

`check_no_pycache.py` has zero callsites. The other two could be a single file or Makefile recipes.

### G3: run_full_suite.py --skip-* flags — VALIDATED, DOWNGRADED
The `--skip-*` flags are real complexity, but refactoring this involves splitting a 400+ line script and updating the E2E shard runner. This is a significant refactor with high test-infrastructure risk and modest simplification payoff. **Downgrade to out-of-scope** for this iteration — the finding is valid but the risk/benefit ratio for a working test pipeline doesn't justify the change.

### F1: scenario_regression.py shim — VALIDATED
Confirmed: `test_support/scenario_regression.py` wraps `sample_scenarios.make_sample` and `core.standard_metadata` with thin compatibility layers. Only 3 consumers, all in `tests/report/`. The module docstring calls `make_sample` a "compatibility sample factory."

### F2: Audit test prose — VALIDATED
Confirmed: `test_analysis_pipeline_audit.py` and `test_report_pipeline_audit.py` have extensive embedded prose ("FINDING N", "FIXED:", severity ratings). The tests themselves are valid regression tests but the framing is noise — git history is for tracking fixes.

### F3: scenario_ground_truth.py duplication — VALIDATED
Confirmed: `fault_phase`, `road_noise_phase`, `ramp_phase`, `idle_phase` duplicate logic from `sample_scenarios` and `fault_scenarios`. The `PhaseStep`/`ScenarioSpec` dataclass framework is useful but the phase functions duplicate existing builders.

### J2: UI single-file directories — VALIDATED
Confirmed:
- `app/state/` contains only `ui_app_state.ts`
- `app/dom/` contains only `ui_dom_registry.ts`
- `features/demo/` contains only `runDemoMode.ts`
All siblings in `app/` are flat files. The directories are inconsistent.

### J3: hotspot/ zero server consumers — VALIDATED, DOWNGRADED
Confirmed: zero server runtime imports from `vibesensor.hotspot`. But the package is correctly placed — it uses `vibesensor.config` types and shares the pip-installed package. Moving it elsewhere adds complexity. **Downgrade to out-of-scope** — the packaging is reasonable given it shares config types.

## Implementation Steps

### Step 1: Delete dead check_no_pycache.py + merge hygiene scripts (G2)

1. Delete `tools/dev/check_no_pycache.py` (dead code — no callsite)
2. Merge `check_line_endings.py` and `verify_no_path_indirections.py` into `tools/dev/check_hygiene.py`:
   - One file with `check_line_endings()` and `check_path_indirections()` functions
   - Main block runs both checks
3. Update CI workflow (`.github/workflows/ci.yml`) to call `check_hygiene.py` instead of the two separate scripts
4. Add `check_hygiene.py` to the Makefile `lint` target so local and CI align

### Step 2: Simplify run_ci_parallel.py (G1)

1. Replace inlined step commands with Makefile target calls where possible:
   - `backend-quality` job → `make lint` + `make docs-lint` + config preflight + hygiene check
   - `backend-typecheck` → `make typecheck-backend`
   - `frontend-typecheck` → `cd apps/ui && npm run typecheck`
   - `backend-tests` → `pytest -q apps/server/tests/ -m "not selenium"`
   - `e2e` → existing `run_e2e_parallel.py` call
2. Keep the parallel-threading infrastructure (it provides genuine value)
3. Remove the duplicated per-step ruff flags, mypy arguments, and npm commands — let Makefile own those
4. This turns `run_ci_parallel.py` from a "CI reimplementation" into a "parallel job launcher"

### Step 3: Delete scenario_regression.py shim (F1)

1. Delete `tests/test_support/scenario_regression.py`
2. Update the 3 consumers in `tests/report/`:
   - `test_report_scenario_output_regression.py`
   - `test_report_scenario_confidence_regression.py`
   - `test_report_scenario_phase_regression.py`
3. Replace imports:
   - `from test_support.scenario_regression import make_sample` → `from test_support.sample_scenarios import make_sample`
   - `from test_support.scenario_regression import standard_metadata` → `from test_support.core import standard_metadata`
   - `from test_support.scenario_regression import build_speed_sweep_samples` → use `from test_support.fault_scenarios import build_speed_sweep_fault_samples` (or refactor)

### Step 4: Consolidate scenario_ground_truth.py duplicates (F3)

1. Replace `idle_phase`, `road_noise_phase`, `ramp_phase`, `fault_phase` in `scenario_ground_truth.py` with thin adapters that delegate to canonical builders:
   - `idle_phase` → delegates to `sample_scenarios.make_idle_samples`
   - `road_noise_phase` → delegates to `sample_scenarios.make_noise_samples`
   - `ramp_phase` → delegates to `sample_scenarios.make_ramp_samples`
   - `fault_phase` → delegates to `fault_scenarios.make_fault_samples`
2. Replace `sensor_offset()` with `_stable_hash()` from `core.py`
3. Keep `PhaseStep` and `ScenarioSpec` (genuinely useful framework)
4. Reduce from ~120 lines of duplicate logic to ~20 lines of delegation

### Step 5: Clean up audit test prose (F2)

1. In `test_analysis_pipeline_audit.py`:
   - Remove embedded "FINDING N" severity/evidence/root-cause prose blocks
   - Keep one-line comment per test class explaining what invariant is enforced
   - Remove `# FIXED:` annotations (that's what git is for)
   - Rename classes from `TestFindingN_Name` to behavior-oriented names
2. In `test_report_pipeline_audit.py`:
   - Same cleanup pattern
3. In `test_coverage_gap_audit_top10.py`:
   - Remove audit methodology prose in module docstring
   - Keep concise test docstrings

### Step 6: Flatten UI single-file directories (J2)

1. Move `apps/ui/src/app/state/ui_app_state.ts` → `apps/ui/src/app/ui_app_state.ts`
2. Move `apps/ui/src/app/dom/ui_dom_registry.ts` → `apps/ui/src/app/ui_dom_registry.ts`
3. Move `apps/ui/src/features/demo/runDemoMode.ts` → `apps/ui/src/app/demo_mode.ts` (or `apps/ui/src/features/demo_mode.ts`)
4. Delete empty directories
5. Update all import paths in TypeScript files
6. Verify: `cd apps/ui && npm run typecheck && npm run build`

### Step 7: Verify everything

1. `ruff check apps/server/`
2. `make typecheck-backend`
3. `pytest -q apps/server/tests/ -m "not selenium"`
4. `cd apps/ui && npm run typecheck && npm run build`
5. `make test-all` (verify the simplified CI runner works)

## Dependencies on Other Chunks

- Executes last — no downstream dependencies
- G1 (CI runner) depends on Makefile targets being stable from Chunks 1-4

## Risks and Tradeoffs

- **G1 refactoring**: Changing the CI-parity runner may break `make test-all`. Must test carefully.
- **F3 consolidation**: The delegation approach requires the canonical builders to accept the same parameters as the ground-truth phase functions. Minor signature adjustments may be needed.
- **J2 UI moves**: Import path changes touch multiple TypeScript files. `npm run typecheck` verifies correctness.
- **G3 out of scope**: The run_full_suite.py complexity remains. Document as known complexity.
- **J3 out of scope**: The hotspot package structure remains. Reasonable given shared config types.

## Validation Steps

- `ruff check apps/server/ tools/`
- `make typecheck-backend`
- `pytest -q apps/server/tests/ -m "not selenium"`
- `cd apps/ui && npm run typecheck && npm run build`
- `make test-all`

## Documentation Updates

- Update `docs/testing.md` if test helper structure changes
- Update `docs/ai/repo-map.md` if test layout description changes

## AI Instruction Updates

- Add to `tests.instructions.md`:
  - "Do not create compatibility shim modules in test_support/. Import from the canonical builder modules directly."
  - "Do not embed extensive prose audit reports in test files. Keep test class/function docstrings to one line describing the invariant being enforced. Use git history for tracking fix provenance."
  - "Do not create duplicate sample-building functions across test helper modules. Extend existing builders with parameters instead."
- Add to `general.instructions.md`:
  - "Do not create standalone Python scripts for operations that a Makefile recipe can express in 1-3 lines (grep checks, git hygiene)."
  - "Do not fork CI workflow step definitions into local scripts. If a local CI-parity tool is needed, have it call Makefile targets rather than inlining CI step commands."

## Test Updates

- All test changes in this chunk ARE the test updates (F1, F2, F3 are test findings)
- Verify scenario tests still pass after ground-truth consolidation
- Verify report regression tests still pass after shim deletion

## Simplification Crosswalk

| Finding | Steps | Removable | Verification |
|---------|-------|-----------|-------------|
| G1 | Step 2 | ~150 lines of inlined CI step commands | make test-all works |
| G2 | Step 1 | 1 dead file, 2 files merged into 1 | CI hygiene checks pass |
| G3 | N/A | Out of scope | Documented |
| F1 | Step 3 | 1 shim file | report regression tests pass |
| F2 | Step 5 | ~100+ lines of prose comments | audit tests still pass |
| F3 | Step 4 | ~100 lines of duplicate logic | scenario tests pass |
| J2 | Step 6 | 3 unnecessary directories | npm typecheck + build pass |
| J3 | N/A | Out of scope | Documented |
