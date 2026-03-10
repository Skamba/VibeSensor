# Chunk 1: Package Structure & Build System

## Mapped Findings

- [9.1] vibesensor_simulator fake-independent package with fragile path hack
- [9.2] vibesensor_tools_config unnecessary 2-file package
- [9.3] Three-layer thin wrapper script proliferation
- [7.3] Config-tool triple-layering with inconsistent invocation paths
- [10.3] hotspot/ micro-package and live_diagnostics/ ghost directory

## Validation Outcomes

### [9.1] CONFIRMED (HIGH confidence)
`vibesensor_simulator` in `apps/simulator/vibesensor_simulator/` contains 5 source files (commands.py, profiles.py, server_http.py, sim_sender.py, ws_smoke.py). It imports directly from `vibesensor.*` (4+ imports from vibesensor.contracts, vibesensor.protocol, vibesensor.analysis_settings, vibesensor.constants). Cannot run independently. Bundled into the server wheel via a multi-root `packages.find where = [".", "../../apps/simulator", "../../tools/config"]` hack in pyproject.toml. Entry points (`vibesensor-sim`, `vibesensor-ws-smoke`) are registered in the server's pyproject.toml, not in a separate package. The Dockerfile has a redundant `COPY apps/simulator` step.

### [9.2] CONFIRMED (HIGH confidence)
`tools/config/vibesensor_tools_config/` contains only 2 source files (`config_preflight.py`, `check_line_endings.py`) plus an `__init__.py` with a docstring. `check_line_endings.py` has zero imports from `vibesensor.*` — it's a pure git/repo maintenance script using `subprocess`. It ships in the production wheel despite having no production purpose. The package adds a third root to `packages.find where`.

### [9.3] CONFIRMED (MEDIUM confidence)
Three thin wrapper scripts exist for the simulator that all do `from vibesensor_simulator.sim_sender import main; main()`:
- `apps/simulator/sim_sender.py`
- `apps/tools/simulator`
- `tools/simulator`

And for config:
- `tools/config/config_preflight.py`
- `apps/tools/config`

All are redundant with the registered entry points (`vibesensor-sim`, `vibesensor-config-preflight`).

### [7.3] CONFIRMED (MEDIUM-HIGH confidence)
Config preflight has 3 invocation paths: entry point `vibesensor-config-preflight`, script `tools/config/config_preflight.py`, and `apps/tools/config`. The `run_ci_parallel.py` uses the script path while `ci.yml` uses the entry point — confirmed drift.

### [10.3] CONFIRMED
- `live_diagnostics/`: Ghost directory containing only `__pycache__/` with stale .pyc files. No `.py` source files exist. Confirmed by filesystem check.
- `hotspot/`: Contains 2 files (parsers.py, self_heal.py) plus `__init__.py`. Only 3 import sites. Finding is valid for live_diagnostics/ (immediate cleanup); hotspot/ is borderline (keeping as package is defensible since it groups Wi-Fi AP concerns).

## Root Complexity Drivers

1. **Multi-root packages.find hack**: The main driver is the aspiration to treat simulator and tools as independent packages while they have zero independence. The `where = [".", "../../apps/simulator", "../../tools/config"]` pattern is fragile (only works from `apps/server/`), adds build complexity, and ships dev-only code in the production wheel.

2. **Accumulated wrapper scripts**: Each tool gained wrapper scripts in multiple locations (apps/tools/, tools/, module root) before entry points were standardized. Old wrappers were never cleaned up.

3. **Package-for-everything pattern**: `vibesensor_tools_config` was given a package namespace for 2 files. `hotspot/` was created for 2 files. `live_diagnostics/` was left as a ghost after its contents were moved.

## Simplification Strategy

### Step 1: Move vibesensor_simulator into vibesensor/simulator/

This is the highest-impact change in this chunk.

**Implementation:**
1. Create `apps/server/vibesensor/simulator/` directory
2. Move all 5 source files from `apps/simulator/vibesensor_simulator/` to `apps/server/vibesensor/simulator/`
3. Create `apps/server/vibesensor/simulator/__init__.py` (minimal, reexport main entry points if needed)
4. Update all imports from `vibesensor_simulator.X` to `vibesensor.simulator.X`:
   - Entry points in pyproject.toml: `vibesensor-sim`, `vibesensor-ws-smoke`
   - All test files that import from `vibesensor_simulator`
   - Any references in CI, Makefile, documentation
5. Remove `../../apps/simulator` from `packages.find where`
6. Remove `vibesensor_simulator*` from `packages.find include`
7. Remove `COPY apps/simulator` from Dockerfile
8. Delete `apps/simulator/` directory entirely (including README.md, the root sim_sender.py, ws_smoke.py wrappers)

**Import changes needed (search for `vibesensor_simulator`):**
- pyproject.toml entry points
- Test files (integration tests, scenario tests)
- Dockerfile
- Any CI or script references

### Step 2: Inline vibesensor_tools_config

**Implementation:**
1. Move `tools/config/vibesensor_tools_config/config_preflight.py` to `apps/server/vibesensor/config_preflight.py`
2. Move `tools/config/vibesensor_tools_config/check_line_endings.py` to `tools/dev/check_line_endings.py` (it's a dev-only script, should NOT be in the wheel)
3. Update entry point in pyproject.toml: `vibesensor-config-preflight = "vibesensor.config_preflight:main"`
4. Remove `../../tools/config` from `packages.find where`
5. Remove `vibesensor_tools_config*` from `packages.find include`
6. Delete `tools/config/vibesensor_tools_config/` directory
7. Update any CI, test, or script references

### Step 3: Delete thin wrapper scripts

**Implementation:**
1. Delete `apps/simulator/sim_sender.py` (3-line wrapper)
2. Delete `apps/simulator/ws_smoke.py` (if it exists as a wrapper)
3. Delete `apps/tools/simulator` (3-line wrapper)
4. Delete `apps/tools/config` (3-line wrapper)
5. Delete `tools/simulator` (3-line wrapper)
6. Delete `tools/config/config_preflight.py` (3-line wrapper)
7. After all wrappers are deleted, check if `apps/tools/` directory is empty — if so, delete it
8. Update any Makefile or CI references to use entry point names instead of script paths
9. Update `run_ci_parallel.py` (if it still exists at this point) to use entry point `vibesensor-config-preflight` instead of `python tools/config/config_preflight.py`

### Step 4: Clean up ghost directory and micro-packages

**Implementation:**
1. Delete `apps/server/vibesensor/live_diagnostics/` entirely (ghost directory with only `__pycache__/`)
2. For `hotspot/`: Keep as-is. With only 2 files and 3 import sites, the package adds minimal overhead. The `vibesensor-hotspot-self-heal` entry point references `vibesensor.hotspot.self_heal:main`, so flattening would change a registered entry point for marginal benefit. Decision: **Keep hotspot/ as a package**.

### Step 5: Simplify pyproject.toml packages.find

After steps 1-4, the `packages.find` section simplifies from:
```toml
where = [".", "../../apps/simulator", "../../tools/config"]
include = ["vibesensor*", "vibesensor_simulator*", "vibesensor_tools_config*"]
```
To:
```toml
where = ["."]
include = ["vibesensor*"]
```

This is the single most impactful line-count reduction: eliminates the fragile relative-path hack entirely.

## Dependencies on Other Chunks

- **Chunk 2** references `run_ci_parallel.py` which uses script paths that this chunk changes. If chunk 2 deletes `run_ci_parallel.py`, the path fix in step 3 is moot. If chunk 2 doesn't delete it, this chunk must update it.
- **Chunk 5** documentation updates will reference the new `vibesensor.simulator` import path.
- No dependencies on chunks 3 or 4.

## Risks and Tradeoffs

- **Import churn**: All `vibesensor_simulator` imports must be updated. This touches integration tests, simulation-related tests, and possibly CI scripts. Risk is low (mechanical find/replace) but the blast radius is moderate.
- **Entry point stability**: The `vibesensor-sim` and `vibesensor-ws-smoke` CLI entry points don't change for end users — only their internal module path changes. No breaking change for Raspberry Pi deployments.
- **Dockerfile change**: Removing `COPY apps/simulator` simplifies the Docker build. The server's pip install pulls in the simulator since it's now inside `vibesensor/`.
- **check_line_endings.py removal from wheel**: This script was never production-relevant, so removing it from the wheel is pure benefit.

## Validation Steps

1. `pip install -e "./apps/server[dev]"` — verify clean install without multi-root hack
2. `vibesensor-sim --help` — verify entry point works
3. `vibesensor-ws-smoke --help` — verify entry point works
4. `vibesensor-config-preflight apps/server/config.yaml` — verify entry point works
5. `pytest -q apps/server/tests/integration/test_level_sim_ingestion.py` — verify sim tests pass
6. `make lint` — verify ruff passes
7. `make typecheck-backend` — verify mypy passes
8. `docker compose build --pull` — verify Docker build succeeds
9. Verify `apps/simulator/` no longer exists
10. Verify `tools/config/vibesensor_tools_config/` no longer exists
11. Verify `apps/server/vibesensor/live_diagnostics/` no longer exists
12. Verify `apps/tools/` no longer exists (if empty)
13. Run full test suite: `pytest -q -m "not selenium" apps/server/tests`

## Required Documentation Updates

- `docs/ai/repo-map.md`: Update simulator reference from `apps/simulator/` to `vibesensor/simulator/`
- `.github/copilot-instructions.md`: Update simulator tooling reference
- `apps/server/README.md`: Update any simulator references
- `CONTRIBUTING.md`: Update if it references simulator paths

## Required AI Instruction Updates

- `.github/copilot-instructions.md`: Remove references to `apps/simulator/` as a separate app
- `.github/instructions/general.instructions.md`: Add guidance against creating separate packages for code that depends on the main server package

## Required Test Updates

- All tests importing from `vibesensor_simulator` must be updated to `vibesensor.simulator`
- Test files referencing `apps/simulator/` paths must be updated

## Simplification Crosswalk

### [9.1] vibesensor_simulator → vibesensor/simulator/
- **Validation**: CONFIRMED
- **Root cause**: Package separation aspiration with zero actual independence
- **Steps**: Move files, update imports, update entry points, remove Dockerfile COPY, clean up pyproject.toml
- **Code areas**: apps/simulator/, apps/server/pyproject.toml, Dockerfile, test files
- **What can be removed**: apps/simulator/ directory, multi-root path hack
- **Verification**: Entry points work, tests pass, Docker builds

### [9.2] vibesensor_tools_config → inline
- **Validation**: CONFIRMED
- **Root cause**: Package namespace for 2 files, one of which isn't even production code
- **Steps**: Move config_preflight to vibesensor/, move check_line_endings to tools/dev/, update entry point, clean up pyproject.toml
- **Code areas**: tools/config/vibesensor_tools_config/, pyproject.toml
- **What can be removed**: vibesensor_tools_config package, third packages.find root
- **Verification**: Entry point works, check_line_endings still runs, clean lint

### [9.3] Delete thin wrapper scripts
- **Validation**: CONFIRMED
- **Root cause**: Historical accumulation of pre-entry-point era scripts
- **Steps**: Delete 5-6 wrapper scripts, delete apps/tools/ if empty
- **Code areas**: apps/simulator/sim_sender.py, apps/tools/*, tools/simulator, tools/config/config_preflight.py
- **What can be removed**: ~6 files, potentially apps/tools/ directory
- **Verification**: Entry points still work, no references to deleted scripts

### [7.3] Config-tool triple-layering
- **Validation**: CONFIRMED (merged with [9.2] and [9.3])
- **Root cause**: Same as [9.2] and [9.3] — resolved by those steps
- **Steps**: Covered by [9.2] (entry point path fix) and [9.3] (wrapper deletion)
- **Verification**: Single invocation path works

### [10.3] Ghost directory and micro-packages
- **Validation**: CONFIRMED for live_diagnostics/; hotspot/ retained
- **Root cause**: live_diagnostics/ is leftover from module removal
- **Steps**: Delete live_diagnostics/ directory
- **Code areas**: apps/server/vibesensor/live_diagnostics/
- **What can be removed**: Ghost directory with stale __pycache__
- **Verification**: No import errors, no test failures
