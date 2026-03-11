# Chunk 4: Configuration & Tooling Simplification

## Overview
The configuration and tooling layers have accumulated post-merge fallback clutter, never-
overridden config fields, and dual-maintained CI runner infrastructure. This chunk removes
redundant `config.get(key, fallback)` sites that exist after `deep_merge` guarantees defaults,
collapses `APSelfHealConfig` to only its 2 actually-overridden fields, simplifies CI parallel
runner duplication, removes bespoke build detection overhead, and creates a unified contract
regeneration command.

## Mapped Findings

### Finding 1: Redundant config fallbacks after deep_merge (A8-1)
- **Original**: Subagent 8 finding 1
- **Validation result**: CONFIRMED. `load_config()` in `config.py` uses `deep_merge()`
  (imported from `_dict_merge.py`) to overlay YAML values onto `DEFAULT_CONFIG`. After merge,
  every path in `DEFAULT_CONFIG` is guaranteed present. Yet 9 call sites still use
  `config.get("key", fallback)` or `config.get("section", {}).get("key", default)` pattern,
  adding redundant fallback logic. Additionally, 3 `default_*_cfg` local variables are
  extracted from `DEFAULT_CONFIG` then used as standalone fallback dicts, duplicating the
  merged config.
- **Validated root cause**: The fallback pattern predates `deep_merge` and was never cleaned
  up after merge guarantees were added.

### Finding 2: APSelfHealConfig has 3 never-overridden fields (A8-3)
- **Original**: Subagent 8 finding 3
- **Validation result**: CONFIRMED. `APSelfHealConfig` has 5 fields. Searching all YAML
  config files (`config.yaml`, `config.dev.yaml`, `config.docker.yaml`, `config.pi.yaml`),
  only `enabled` and `check_interval_s` are ever set. The other 3 fields
  (`max_restart_attempts`, `restart_delay_s`, `cooldown_period_s`) always use their Python
  defaults. These should be Python constants, not config fields.
- **Validated root cause**: Premature configurability — fields were added for hypothetical
  tuning needs.

### Finding 3: Duplicate CI parallel runner infrastructure (A7-1+A7-2)
- **Original**: Subagent 7 findings 1+2 (combined)
- **Validation result**: CONFIRMED. `run_ci_parallel.py` and `run_e2e_parallel.py` share
  duplicated infrastructure primitives: ANSI color helpers, progress line formatting,
  subprocess management, and result summary reporting. Both define 7 job groups that mirror
  `ci.yml`. `run_e2e_parallel.py` has its own `_run_job()`, `_print_summary()`, and color
  constants that are near-identical copies of the CI runner.
- **Validated root cause**: `run_e2e_parallel.py` was written by copying `run_ci_parallel.py`
  and adapting rather than extracting shared primitives.

### Finding 4: Bespoke incremental build detection (A7-3)
- **Original**: Subagent 7 finding 3
- **Validation result**: PARTIALLY CONFIRMED, SCALED BACK. The `hash_tree()` function
  in `build_ui_static.py` is primarily for build metadata stamps (embedding in output), not
  for build-skipping. The npm-ci lockfile hash check (`_needs_npm_ci()`) is only ~8 lines
  and provides legitimate value (avoids slow `npm ci` when `package-lock.json` hasn't
  changed). Scale back: only remove `hash_tree()` if it's truly unused for anything beyond
  metadata, and leave `_needs_npm_ci()` in place since it's small and useful.
- **Validated root cause**: `hash_tree()` adds complexity for build metadata that isn't
  consumed meaningfully.

### Finding 5: No unified contract regeneration command (A9-3)
- **Original**: Subagent 9 finding 3
- **Validation result**: CONFIRMED. `make sync-contracts` runs only the Node.js half
  (`tools/config/sync_shared_contracts_to_ui.mjs` which copies TS types from
  `libs/shared/ts/contracts.ts` to the UI generated output). Python contract exporters
  (if any) and the WS schema pipeline (A9-1, handled in Chunk 5) are separate manual steps.
  There's no single `make regen-contracts` that regenerates everything.
- **Validated root cause**: Contract sync was added incrementally, Node.js half first, without
  a unified entry point.

## Root Causes Behind These Findings
1. Post-merge fallback patterns left behind after `deep_merge()` was introduced
2. Premature configurability for fields that have never been overridden
3. Copy-paste development for parallel test runners
4. Build metadata complexity that may not justify its cost
5. Incremental contract tooling without a unified entry point

## Relevant Code Paths and Components

### Config fallback cleanup
- `apps/server/vibesensor/config.py` — `load_config()`, `DEFAULT_CONFIG`, `deep_merge`
- `apps/server/vibesensor/_dict_merge.py` — `deep_merge()` implementation
- All consumer sites that call `config.get("key", fallback)`

### APSelfHealConfig
- `apps/server/vibesensor/hotspot/self_heal.py` or wherever APSelfHealConfig is defined
- All YAML config files: `config.yaml`, `config.dev.yaml`, `config.docker.yaml`, `config.pi.yaml`

### CI runner
- `tools/tests/run_ci_parallel.py` — main CI runner
- `tools/tests/run_e2e_parallel.py` — E2E runner
- `.github/workflows/ci.yml` — source of truth for CI jobs

### Build detection
- `tools/build_ui_static.py` — `hash_tree()`, `_needs_npm_ci()`

### Contract regen
- `tools/config/sync_shared_contracts_to_ui.mjs` — TS contract sync
- `Makefile` — `sync-contracts` target

## Simplification Approach

### Step 1: Remove redundant config fallbacks
1. Identify all 9 `config.get("key", fallback)` sites post-deep_merge
2. Replace each with direct `config["key"]` access (safe because deep_merge guarantees
   every DEFAULT_CONFIG path exists in the merged result)
3. Remove the 3 `default_*_cfg` extraction variables that duplicate DEFAULT_CONFIG sections
4. Keep `deep_merge()` and `DEFAULT_CONFIG` as they are — they're the correct mechanism
5. Add a test that verifies `load_config()` output always has all expected keys (if not
   already covered)

### Step 2: Collapse APSelfHealConfig
1. Remove the 3 never-overridden fields from the config dataclass
2. Convert them to module-level constants (e.g., `_MAX_RESTART_ATTEMPTS = 3`)
3. Update all consumers to read from constants instead of config fields
4. Remove the fields from `DEFAULT_CONFIG` if they're present there
5. Verify no YAML file mentions these fields (already confirmed)

### Step 3: Consolidate CI runner infrastructure
1. Extract shared primitives from `run_ci_parallel.py`: ANSI colors, progress formatting,
   subprocess management, result summary
2. Create a minimal shared module `tools/tests/_runner_utils.py` (or similar) with these
   primitives
3. Have both `run_ci_parallel.py` and `run_e2e_parallel.py` import from the shared module
4. Remove duplicated code from `run_e2e_parallel.py`
5. Verify both runners produce identical output format

### Step 4: Remove hash_tree if unused
1. Verify `hash_tree()` output is not consumed by any downstream artifact
2. If confirmed unused beyond metadata: remove `hash_tree()` from `build_ui_static.py`
3. Keep `_needs_npm_ci()` — it's small, useful, and well-scoped
4. If `hash_tree()` IS consumed meaningfully, leave it and document why

### Step 5: Unified contract regeneration
1. Add a `make regen-contracts` target that runs all contract generation steps:
   - `sync_shared_contracts_to_ui.mjs` (existing)
   - Any Python contract exporters
   - WS schema generation (if still present after Chunk 5 simplification)
2. Update documentation to reference `make regen-contracts` as the single entry point
3. Consider having `make sync-contracts` call `make regen-contracts` or vice versa to avoid
   confusion

## Dependencies on Earlier/Later Chunks
- **No dependencies on other chunks.** This chunk is self-contained.
- Chunk 5 may simplify the WS schema pipeline (A9-1), which affects what goes into the
  unified `regen-contracts` command. The Make target should be designed to be easily updated
  when Chunk 5 runs.

## Risks and Tradeoffs
- **Config fallback removal**: If any code path runs before `deep_merge`, or if external
  callers construct partial configs, direct access will KeyError. Need to verify all config
  creation paths go through `load_config()`.
- **APSelfHealConfig reduction**: The 3 removed fields effectively become hardcoded. If
  anyone later needs to tune them, they'd need a code change. This is acceptable per the
  repo's no-speculative-config policy.
- **CI runner extraction**: The shared module is a new file, but it's justified by serving
  2 consumers and eliminating ~100 lines of duplication.
- **hash_tree removal**: Need to confirm no consumer depends on the hash before removing.

## Validation Steps
1. `ruff check apps/server/` — lint passes
2. `make typecheck-backend` — type checking passes
3. `pytest -q apps/server/tests/config/` — config tests pass
4. `pytest -q apps/server/tests/hotspot/` — hotspot/self-heal tests pass
5. `python3 tools/tests/run_ci_parallel.py --help` — CI runner still works
6. `python3 tools/tests/run_e2e_parallel.py --help` — E2E runner still works
7. `make sync-contracts` — contract sync still works
8. `make regen-contracts` — new unified command works

## Required Documentation Updates
- `docs/ai/repo-map.md` — update config section if APSelfHealConfig changes
- `docs/operational-runbooks.md` — update if contract regen workflow changes
- `CONTRIBUTING.md` — update if `make regen-contracts` is added

## Required AI Instruction Updates
- Add guidance: "After deep_merge, use direct dict access, not .get() with fallbacks"
- Add guidance: "Do not add config fields unless at least one deployment overrides the default"
- Add guidance: "Use `make regen-contracts` for all contract regeneration"

## Required Test Updates
- Add or verify test that `load_config()` result has all expected top-level keys
- Verify self-heal tests pass with constant access instead of config fields
- Verify CI runner test coverage (if any) still passes

## Simplification Crosswalk

### A8-1 → Remove redundant config fallbacks
- Validation: CONFIRMED (9 sites, 3 default_*_cfg variables)
- Root cause: Pre-deep_merge fallback pattern never cleaned up
- Steps: Replace .get(key, fallback) with direct access, remove default_*_cfg vars
- Code areas: config.py, consumer call sites
- What can be removed: ~15-20 lines of fallback code
- Verification: Config tests pass, no KeyError in tests

### A8-3 → Collapse APSelfHealConfig to 2 fields
- Validation: CONFIRMED (3 of 5 fields never overridden)
- Root cause: Premature configurability
- Steps: Move 3 fields to constants, remove from config
- Code areas: APSelfHealConfig definition, consumers, DEFAULT_CONFIG
- What can be removed: 3 config fields + their DEFAULT_CONFIG entries
- Verification: Hotspot tests pass

### A7-1+A7-2 → Consolidate CI runner infrastructure
- Validation: CONFIRMED (duplicated ANSI, progress, subprocess, summary code)
- Root cause: Copy-paste development
- Steps: Extract shared module, deduplicate
- Code areas: run_ci_parallel.py, run_e2e_parallel.py
- What can be removed: ~100 lines of duplicated utility code
- Verification: Both runners produce correct output

### A7-3 → Remove hash_tree if unused
- Validation: PARTIALLY CONFIRMED, SCALED BACK
- Root cause: Build metadata complexity
- Steps: Verify hash_tree consumers, remove if truly unused
- Code areas: build_ui_static.py
- What can be removed: hash_tree function (if unused), ~20 lines
- Verification: UI build still works

### A9-3 → Unified contract regeneration command
- Validation: CONFIRMED (no single regen command)
- Root cause: Incremental tooling without unified entry point
- Steps: Add make regen-contracts target
- Code areas: Makefile, tools/config/
- What can be removed: Nothing (additive change)
- Verification: make regen-contracts runs all sync steps
