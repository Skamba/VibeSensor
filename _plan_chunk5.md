# Chunk 5: Build, Tooling, Testing & Dependency Cleanup

## Mapped Findings

### F9.1: Ghost Library Directories
- **Validation**: CONFIRMED. `libs/core/` does not exist. `libs/shared/python/` does not exist. `find libs/ -type f` returns only `libs/shared/ts/contracts.ts`. `build.sh` lines 207/215/217 mkdir+rsync against nonexistent paths. Build.sh line 1009 has `vibesensor_shared` in an importlib validation loop for a package that no longer exists.
- **Validated root cause**: Former pip packages collapsed into `vibesensor/core/` and `vibesensor/contracts.py` without cleaning up build scripts.
- **Implementation**: Remove ghost mkdir+rsync lines from build.sh. Remove `vibesensor_shared` from import validation. Remove empty `libs/core/` dir if it exists.

### F9.2: libs/shared/ts/contracts.ts Through 230-Line Codegen Script
- **Validation**: CONFIRMED. `libs/shared/ts/contracts.ts` is a 22-line file with 2 constants. `sync_shared_contracts_to_ui.mjs` copies it with a comment header. The Python-side `LOCATION_CODES` in `contracts.py` is a dict (code→label), while the TS side is an array of codes — different shapes, not actually a shared contract.
- **Validated root cause**: Former JSON contract files were inlined independently on each side.
- **Counter-evidence**: The sync script also does OpenAPI type generation (useful). Only the contracts.ts copy is the unnecessary part.
- **Refinement**: Move the 2 constants directly into `apps/ui/src/constants.ts`. Delete `libs/shared/ts/contracts.ts`. Strip contract-copy logic from sync script, keep OpenAPI generation.

### F9.3: Simulator+Tools in Production Wheel
- **Validation**: CONFIRMED. `pyproject.toml` L61–67 has `where = [".", "../../apps/simulator", "../../tools/config"]` pulling `vibesensor_simulator` and `vibesensor_tools_config` into the server wheel. Scripts section (L42–44) exposes `vibesensor-sim`, `vibesensor-ws-smoke`, `vibesensor-config-preflight` on production. `build.sh` must rsync simulator sources.
- **Counter-evidence**: `vibesensor-config-preflight` IS needed on device for config validation at startup. The simulator is NOT needed on device.
- **Refinement**: Keep `vibesensor_tools_config` in the wheel (needed on Pi). Remove `vibesensor_simulator` from the wheel. Give simulator its own `pyproject.toml`. This is a medium-effort change with Pi deployment implications — DEFER for now. The finding is valid but the risk of breaking Pi image builds is too high for this simplification round.
- **DECISION**: Mark F9.3 as deferred (out of scope for this round) — Pi image build impact is significant.

### F7.1: CI Mirror Scripts Duplication
- **Validation**: CONFIRMED. `run_ci_parallel.py` (368 LOC) manually re-encodes every CI step. `run_verification.py` (105 LOC) is a pure dispatcher with zero logic.
- **Counter-evidence**: The parallel execution DOES provide meaningful wall-clock speedup (running lint, typecheck, and tests simultaneously). `act` is heavyweight and requires Docker. The value of `run_ci_parallel.py` is real.
- **Refinement**: REMOVE `run_verification.py` (pure dispatcher, adds no value). KEEP `run_ci_parallel.py` but note the maintenance burden. The Makefile already has `test-all` targeting it directly.
- **DECISION**: Delete `run_verification.py` only. Keep `run_ci_parallel.py` — the parallel speedup justifies its existence even with the sync burden.

### F7.2: run_full_suite.py Dual-Purpose Shard Worker
- **Validation**: CONFIRMED. `run_full_suite.py` (286 LOC) has 6 skip flags. `run_e2e_parallel.py` calls it with 4/5 features disabled.
- **Counter-evidence**: Extracting a focused e2e runner is significant work. The skip flags, while ugly, work correctly.
- **Refinement**: This is valid but lower priority. The skip-flag pattern works. DEFER for this round — the effort:benefit ratio is poor.
- **DECISION**: Deferred.

### F7.3: Release Workflow Duplicates build_ui_static.py
- **Validation**: NEED TO VERIFY. Check if `main-release.yml` exists and whether it duplicates the UI build steps.
- **Refinement**: If confirmed, replace inline bash with a call to `build_ui_static.py`. If the workflow file doesn't exist or has changed, skip.

### F6.1: Test Proxy Modules
- **Validation**: CONFIRMED. `_diagnosis_robustness_helpers.py` (20 lines) is pure re-export + 1 constant dupe. `_phased_scenario_helpers.py` (~136 lines) has re-exports + thin wrappers over `test_support`.
- **Implementation**: Delete both files. Update 5 callers to import from `test_support` directly. Merge any non-trivial helpers into `test_support`.

### F6.2: ScenarioSpec+PhaseStep Duration/Filename Redundancy
- **Validation**: CONFIRMED. Every `PhaseStep` usage duplicates `duration_s` in both the step and the kwargs. Every `ScenarioSpec` has identical `case_id` and `file_name`.
- **Implementation**: Remove `PhaseStep.duration_s` — extract from `kwargs["duration_s"]`. Default `ScenarioSpec.file_name` to `case_id` via `__post_init__`.

### F6.3: scenario_regression.py Wrapper
- **Validation**: CONFIRMED. `make_sample` in `scenario_regression.py` wraps the base with only a `speed_kmh=None → 0.0` conversion. `standard_metadata` differs only in `sensor_model` case.
- **Counter-evidence**: Only used by 3 test files. The module also exports `build_phased_samples` and `max_order_source_conf` which have real logic.
- **Refinement**: Keep the module but inline `make_sample` — its sole caller can use `speed_kmh=0.0` directly. Clean up the `standard_metadata` wrapper.

### F10.2: report_mapping Sub-Package Depth
- **Validation**: CONFIRMED. 8 files in `analysis/report_mapping/` but only one public export: `map_summary()`. Triple-dot imports (`from ...domain_models`).
- **Counter-evidence**: The internal decomposition has value — each file handles a distinct aspect of report mapping (peaks, systems, actions, context). The 8 files are individually readable.
- **Refinement**: The 3-level nesting is cosmetic complexity. The real cost is the triple-dot imports. A pragmatic fix: flatten from `analysis/report_mapping/` to `analysis/_report_mapping/` or just keep it and accept the depth. DEFER — this is cosmetic and the individual files are well-structured.
- **DECISION**: Deferred — the decomposition within report_mapping is legitimate.

## Decisions Summary
- **In scope**: F9.1, F9.2, F7.1 (partial), F7.3, F6.1, F6.2, F6.3
- **Deferred**: F9.3 (Pi image impact), F7.2 (effort:benefit), F10.2 (cosmetic)

## Root Complexity Drivers
1. Ghost artifacts from previous refactors never cleaned up
2. Shared contract abstraction for what are actually independent constants
3. Test helper modules that are pure re-export proxies with no value-add
4. Test data structures with duplicated fields
5. Dispatcher scripts that add no logic

## Simplification Approach

### Step 1: Remove ghost library directories
1. Remove mkdir+rsync lines for `libs/core` and `libs/shared/python` from `build.sh`
2. Remove `vibesensor_shared` from import validation in `build.sh`
3. Delete `libs/core/` directory if it exists
4. Delete `libs/shared/python/` directory if it exists

### Step 2: Move shared TS contracts inline
1. Read `libs/shared/ts/contracts.ts` content
2. Move `METRIC_FIELDS` and `LOCATION_CODES` definitions directly into `apps/ui/src/constants.ts`
3. Update `sync_shared_contracts_to_ui.mjs` to remove the contract-copy step
4. Delete `libs/shared/ts/contracts.ts`
5. Delete `libs/shared/ts/` directory
6. Delete `libs/shared/` directory (now empty)
7. Delete `libs/` directory (now empty)
8. Update `apps/ui/src/generated/shared_contracts.ts` if it re-exports from the copied file
9. Update build.sh references to `libs/shared/ts`

### Step 3: Delete run_verification.py dispatcher
1. Delete `tools/tests/run_verification.py`
2. Update Makefile if it references `run_verification.py`: redirect to `run_ci_parallel.py` directly
3. Remove any references in docs

### Step 4: Fix release workflow if it duplicates build_ui_static.py
1. Read `.github/workflows/main-release.yml`
2. If it has inline npm build steps, replace with `python3 tools/build_ui_static.py`
3. Keep the `npm run typecheck` step separate (build_ui_static.py doesn't do typecheck)

### Step 5: Delete test proxy modules
1. Read callers of `_diagnosis_robustness_helpers.py` and `_phased_scenario_helpers.py`
2. Update all 5+ callers to import from `test_support` directly
3. Move any non-trivial helpers (like `build_fault_samples_at_speed`) into `test_support/`
4. Delete both proxy files

### Step 6: Fix ScenarioSpec+PhaseStep redundancy
1. In `test_support/scenario_ground_truth.py`:
   - Remove `duration_s` field from `PhaseStep`
   - In `build_summary_from_scenario`, extract duration from `step.kwargs["duration_s"]`
2. In `ScenarioSpec`:
   - Make `file_name` default to `case_id` (add `__post_init__`)
3. Update all callers in `test_scenario_ground_truth_*.py` to remove redundant args

### Step 7: Clean up scenario_regression.py
1. In `test_support/scenario_regression.py`:
   - Remove `make_sample` wrapper or simplify it
   - Update callers to use `speed_kmh=0.0` directly
2. Simplify `standard_metadata` to use base with `raw_sample_rate_hz=1000.0` override

## Dependencies on Other Chunks
- None. This chunk is independent of Chunks 1–4.

## Risks and Tradeoffs
- **build.sh changes**: Must verify Pi image build still works (can't test locally, but changes are deletion-only)
- **libs/ removal**: Any CI or other tooling referencing `libs/` path
- **Test proxy removal**: Need to verify all callers are updated

## Validation Steps
1. `make lint && make typecheck-backend`
2. `pytest -q apps/server/tests/analysis/`
3. `pytest -q apps/server/tests/integration/`
4. `pytest -q apps/server/tests/report/`
5. `cd apps/ui && npm run typecheck && npm run build`
6. Full CI parity: `make test-all`

## Required Documentation Updates
- `docs/ai/repo-map.md`: Remove libs/ references, update test description
- `docs/testing.md`: Update test support description
- `.github/copilot-instructions.md`: Remove libs/ references

## Required AI Instruction Updates
- Add guidance: "Clean up all build script references when removing packages or directories"
- Add guidance: "Do not create test helper modules that only re-export from test_support — import directly"
- Add guidance: "Avoid duplicating field values across data structure positions — derive from the canonical location"

## Required Test Updates
- Update `tests/analysis/` imports
- Update `tests/integration/test_scenario_ground_truth_*.py`
- Update `tests/report/` scenario regression imports

## Simplification Crosswalk

| Finding | Validation | Root Cause | Steps | Verify |
|---------|-----------|------------|-------|--------|
| F9.1: Ghost lib dirs | Confirmed: nonexistent paths in build.sh | Stale artifacts | Step 1 | build.sh clean, libs/core gone |
| F9.2: TS contracts stub | Confirmed: 22-line file + 230-line sync | Former JSON contracts | Step 2 | libs/ deleted, constants inline |
| F9.3: Simulator in wheel | Confirmed but DEFERRED | Deployment convenience | — | — |
| F7.1: CI mirror (partial) | Confirmed: dispatcher is zero-logic | Script layering | Step 3 | run_verification.py deleted |
| F7.2: run_full_suite dual | Confirmed but DEFERRED | Reuse as shard worker | — | — |
| F7.3: Release workflow dupe | Needs verification | Independent authoring | Step 4 | release uses build_ui_static.py |
| F6.1: Test proxy modules | Confirmed: pure re-exports | Pre-consolidation artifact | Step 5 | both proxy files deleted |
| F6.2: ScenarioSpec+PhaseStep | Confirmed: duration×2, filename=case_id | Data redundancy | Step 6 | single duration, default filename |
| F6.3: scenario_regression | Confirmed: 1-line wrapper | Convenience layer | Step 7 | make_sample simplified |
| F10.2: report_mapping depth | Confirmed but DEFERRED | Cosmetic nesting | — | — |
