# Chunk 2: Tooling & Testing Infrastructure

## Mapped Findings

- [7.1] run_ci_parallel.py manually duplicates ci.yml (~375 lines)
- [7.2] Five test entry points, two aliased to "don't use me"
- [6.3] run_coverage.py wraps 4 pytest flags in 56 lines
- [6.1] test_support/ wrapper-chain with thin wrappers and star exports
- [6.2] integration/test_level_* opaque alphabetic taxonomy
- [8.1] Dual systemd unit sources with diverged content

## Validation Outcomes

### [7.1] CONFIRMED (HIGH confidence)
`run_ci_parallel.py` is ~375 lines, explicitly documents sync obligation ("keep them in sync"). Four confirmed drift items: docs_lint step missing locally, config_preflight uses different invocation path than CI, `--tb=short` flag missing, e2e shards differ (3 vs 2). The script re-implements CI execution graph with threading, locks, dataclasses.

### [7.2] CONFIRMED with count correction (HIGH confidence)
5 test-related Makefile targets (not 6): `test`, `test-fast` (alias), `test-all`, `test-ci` (alias), `test-full-suite`. The two aliases have explicit "use X instead" comments. Finding confirmed but count was 5, not 6.

### [6.3] CONFIRMED (HIGH confidence)
`run_coverage.py` is 56 lines. Uses 4 core always-on flags plus 2 conditional flags. The entire script does nothing beyond assembling a `pytest` command line and calling `subprocess.run()`. No logic, no orchestration, no parallelism.

### [6.1] PARTIALLY CONFIRMED (MEDIUM-HIGH confidence)
`test_support/` has 11 files. `__init__.py` star-imports from 6 submodules. `response_models.py` is 8 lines with one function. `scenario_regression.py` rewraps `make_sample` from `sample_scenarios.py`. The wrapper inflation is real but "sprawl" overstates it — some modules contain real logic. Focus on: eliminating `response_models.py` (trivial inline), cleaning up star-import `__init__.py`, and removing thin rewrapping in `scenario_regression.py`.

### [6.2] CONFIRMED (MEDIUM confidence)
9 of 18 integration test files use `test_level_*` naming. The letter codes (B through F, plus e2e) are opaque. The descriptive suffixes already communicate the scenario content. Alongside them, 9 other files use normal descriptive names — inconsistent.

### [8.1] CONFIRMED (HIGH confidence)
3 systemd unit files appear in both `apps/server/systemd/` (template with `__PI_DIR__` tokens) and `infra/pi-image/pi-gen/assets/` (hardcoded paths). Real content drift found: `vibesensor-hotspot.service` has `--config` flag and `Environment=` in the template but not in the baked copy.

## Root Complexity Drivers

1. **DIY CI runner**: `run_ci_parallel.py` was built as a local CI-parity tool but drifts because there's no automated sync mechanism. The sync obligation is perpetual.

2. **Makefile alias accumulation**: Self-documenting aliases ("use X instead") were kept for backward compatibility that the repo explicitly says it doesn't support.

3. **Script-per-concern pattern**: Each test-running scenario got its own Python script instead of being expressed as Makefile recipes or pytest configuration.

4. **Test helper over-factoring**: `test_support/` grew modules faster than the test suite grew in complexity. Star-re-exports hide origins.

5. **Template fork**: systemd units were forked into `infra/pi-image/pi-gen/assets/` for convenience, creating an unsynchronized copy.

## Simplification Strategy

### Step 1: Remove Makefile aliases and simplify coverage targets

**Implementation:**
1. Delete `test-fast` target (alias for `test` with "use 'make test'" comment)
2. Delete `test-ci` target (alias for `test-all` with "use 'make test-all'" comment)
3. Delete `run_coverage.py` script
4. Replace 3 coverage Makefile targets (`coverage`, `coverage-html`, `coverage-strict`) with a single inline `coverage` target using `pytest` flags directly:
   ```makefile
   coverage:
   	cd apps/server && python -m pytest -q -m "not selenium" --cov=vibesensor --cov-report=term-missing:skip-covered tests
   coverage-html: coverage
   	cd apps/server && python -m pytest -q -m "not selenium" --cov=vibesensor --cov-report=html:htmlcov tests
   ```
   Or optionally make coverage-html a variant of the same target with a variable.

### Step 2: Simplify run_ci_parallel.py

Rather than deleting `run_ci_parallel.py` entirely (it serves a real purpose: running all CI check types locally in parallel), the strategy is to **reduce its maintenance burden** by fixing the confirmed drift:

**Implementation:**
1. Add the missing `docs_lint` step to the `backend-quality` job
2. Fix config_preflight to use the entry point `vibesensor-config-preflight` (matching CI)
3. Fix e2e shard count to match CI (3 shards)
4. Add `--tb=short` to backend-tests flags (matching CI)
5. Add a header comment listing the exact CI steps it must mirror, and a hygiene test that verifies the step lists match (or document the acceptable intentional differences)

**Alternative considered**: Delete entirely and rely on `act` or direct pytest calls. Rejected because: (a) `act` requires Docker and GitHub Actions runner images, adding more complexity than it removes; (b) the script does provide genuine parallel execution value.

### Step 3: Consolidate test_support/

**Implementation:**
1. **Inline `response_models.py`**: It's 8 lines with 1 function (`response_payload()`). Move to `conftest.py` as a fixture or helper, or inline at each call site. Given ~20 import sites, `conftest.py` is cleaner.
2. **Replace star-import `__init__.py`**: Replace wildcard imports with explicit named imports so symbol origins are traceable:
   ```python
   from .core import make_sample, make_summary, ...
   from .assertions import assert_sample_valid, ...
   ```
3. **Consolidate thin wrapper modules**: If `scenario_regression.py` mostly rewraps `sample_scenarios.make_sample()` with a `strength_bucket` injection, fold that logic into `sample_scenarios.make_sample()` as an optional parameter. Delete `scenario_regression.py` and update callers.
4. **Merge small overlapping modules**: If `fault_scenarios.py` and `perturbation_scenarios.py` are both thin scenario generators, consider whether they could merge into `sample_scenarios.py`. Only act if the modules are genuinely thin (<100 lines each).

### Step 4: Rename test_level_* files

**Implementation:**
1. Rename 9 files from `test_level_X_suffix.py` to `test_suffix.py`:
   - `test_level_b_single_no_transient.py` → `test_single_no_transient.py`
   - `test_level_c_single_transient.py` → `test_single_transient.py`
   - `test_level_d_multi_no_transient.py` → `test_multi_no_transient.py`
   - `test_level_e_multi_transient.py` → `test_multi_transient.py`
   - `test_level_e2e_report.py` → `test_report_pipeline.py`
   - `test_level_f_messy_real_world.py` → `test_messy_real_world.py`
   - `test_level_integration.py` → `test_integration_pipeline.py`
   - `test_level_sim_ingestion.py` → `test_sim_ingestion.py`
   - `test_level_ui_mock.py` → `test_ui_mock.py`
2. Update any docstrings that reference "Level B", "Level C", etc.
3. Verify no pytest node IDs or CI configurations reference the old filenames

### Step 5: Unify systemd unit sources

**Implementation:**
1. Delete `infra/pi-image/pi-gen/assets/vibesensor-hotspot.service`
2. Delete `infra/pi-image/pi-gen/assets/vibesensor-hotspot-self-heal.service`
3. Delete `infra/pi-image/pi-gen/assets/vibesensor-rfkill-unblock.service`
4. Delete `infra/pi-image/pi-gen/assets/vibesensor-hotspot-self-heal.timer` (if it exists in assets/)
5. In `infra/pi-image/pi-gen/build.sh`, replace the direct copy of service files from `assets/` with the same `sed` pattern already used for `vibesensor.service`:
   ```bash
   sed -e "s|__PI_DIR__|/opt/VibeSensor/apps/server|g" \
       -e "s|__VENV_DIR__|/opt/VibeSensor/apps/server/.venv|g" \
       -e "s|__SERVICE_USER__|pi|g" \
       "$SYSTEMD_SRC/vibesensor-hotspot.service" > "$ROOTFS/etc/systemd/system/vibesensor-hotspot.service"
   ```
6. This ensures the template source of truth (`apps/server/systemd/`) is used everywhere, with build-time substitution for both install paths.

## Dependencies on Other Chunks

- **Chunk 1** may have already deleted `apps/tools/` and changed invocation paths referenced by `run_ci_parallel.py`. If so, step 2 must adjust accordingly.
- Steps in this chunk are largely independent of chunks 3-5.

## Risks and Tradeoffs

- **run_ci_parallel.py changes**: Fixing drift items is low-risk; each is a flag or step addition. The risk is that future drift will recur. Adding a sync-verification mechanism (even a comment-based one) mitigates this.
- **test_support/ refactoring**: Inlining `response_models.py` touches ~20 test files. Risk is low (mechanical import changes) but the blast radius is moderate.
- **test_level_* renames**: Pure file renames with no code changes. Risk is low. May affect any CI caching that relies on filename stability, but pytest discovery is by directory, not by name.
- **systemd unit unification**: The template in `apps/server/systemd/` has `--config /etc/vibesensor/config.yaml` for the hotspot service, which the assets/ copy was missing. Unifying to the template means the pi-gen build will now include this flag. This is likely the **correct** behavior (the drift was a bug, not a feature).

## Validation Steps

1. `make test` — verify basic tests pass
2. `make lint` — verify ruff passes
3. `make typecheck-backend` — verify mypy passes
4. `pytest -q apps/server/tests/integration/` — verify integration tests pass after renames
5. Check that Makefile has no `test-fast` or `test-ci` targets
6. Verify `tools/tests/run_coverage.py` no longer exists
7. Verify `infra/pi-image/pi-gen/assets/` no longer has service/timer files
8. Verify all `test_level_*` files have been renamed

## Required Documentation Updates

- `docs/testing.md`: Update any references to test_level_* file names
- `docs/ai/repo-map.md`: No changes needed (doesn't reference specific test filenames)

## Required AI Instruction Updates

- `.github/instructions/tests.instructions.md`: Remove any references to test_level_* naming convention
- `.github/instructions/general.instructions.md`: Add guidance discouraging:
  - Creating standalone Python scripts for simple pytest flag combinations
  - Creating Makefile aliases that are immediately documented as "don't use this"
  - Duplicating CI job definitions in local runner scripts without a sync mechanism

## Required Test Updates

- Rename 9 test files (step 4)
- Move `response_payload()` from `test_support/response_models.py` to `conftest.py` or inline
- Update ~20 test files importing from `test_support.response_models`
- Potentially merge `scenario_regression.py` into `sample_scenarios.py`

## Simplification Crosswalk

### [7.1] run_ci_parallel.py drift
- **Validation**: CONFIRMED (4 drift items)
- **Root cause**: Manual sync obligation with no enforcement
- **Steps**: Fix 4 drift items, add sync documentation
- **Code areas**: tools/tests/run_ci_parallel.py
- **What can be removed**: Nothing deleted — drift fixed instead
- **Verification**: Local run matches CI step list

### [7.2] Makefile alias targets
- **Validation**: CONFIRMED (5 targets, 2 aliased)
- **Root cause**: Backward-compatibility aliases in a no-backward-compatibility repo
- **Steps**: Delete test-fast and test-ci from Makefile
- **Code areas**: Makefile
- **What can be removed**: 2 Makefile targets
- **Verification**: `make test` and `make test-all` still work

### [6.3] run_coverage.py
- **Validation**: CONFIRMED (56-line flag wrapper)
- **Root cause**: Script-per-concern pattern
- **Steps**: Delete script, inline pytest flags into Makefile coverage target
- **Code areas**: tools/tests/run_coverage.py, Makefile
- **What can be removed**: 1 file (56 lines)
- **Verification**: `make coverage` works with inline flags

### [6.1] test_support/ wrapper chain
- **Validation**: PARTIALLY CONFIRMED
- **Root cause**: Over-modularization of test helpers
- **Steps**: Inline response_models.py, replace star imports, consolidate scenario_regression.py
- **Code areas**: apps/server/tests/test_support/
- **What can be removed**: 1-2 files, star-import __init__.py
- **Verification**: All tests pass

### [6.2] test_level_* naming
- **Validation**: CONFIRMED
- **Root cause**: Home-grown alphabetic taxonomy
- **Steps**: Rename 9 files to descriptive names
- **Code areas**: apps/server/tests/integration/
- **What can be removed**: Opaque letter codes from filenames
- **Verification**: pytest still discovers all tests

### [8.1] Dual systemd unit sources
- **Validation**: CONFIRMED (real content drift)
- **Root cause**: Template fork for build convenience
- **Steps**: Delete assets/ copies, use sed on templates in build.sh
- **Code areas**: infra/pi-image/pi-gen/assets/, infra/pi-image/pi-gen/build.sh
- **What can be removed**: 3-4 duplicate service files
- **Verification**: build.sh sed-generates correct service files
