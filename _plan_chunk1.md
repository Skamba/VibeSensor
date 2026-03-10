# Chunk 1: Update Package Consolidation

## Mapped Findings

### F1.1+F2.1: Update Config Object Duplication + 10-Class Micro-Service Explosion
- **Validation**: CONFIRMED. `_build_workflow()` (L222–259) builds 5 config dataclasses + 5 component objects. `_snapshot_for_rollback()` (L292–304) and `_rollback()` (L306–316) each redundantly construct `UpdateCommandExecutor` + `UpdateInstaller` + `UpdateInstallerConfig`. Triple duplication of `UpdateInstallerConfig` confirmed at L242–249, L296–301, L308–313.
- **Validated root cause**: Enterprise-style decomposition where every concern gets a class + config dataclass, even for concerns that are 1 method + 2 config fields (e.g., `UpdateServiceControlConfig` with 2 fields, `UpdateServiceController` with 1 method).
- **Counter-evidence check**: The decomposition aids individual unit testing of each controller. However, tests actually mock `CommandRunner.run` directly, not the controller-level interfaces. The controller abstraction is not used as a test boundary.

### F8.2: Dual Configuration Channels (YAML + Env Vars)
- **Validation**: CONFIRMED. `manager.py` L65–70 reads `VIBESENSOR_REPO_PATH`, `VIBESENSOR_ROLLBACK_DIR`, `VIBESENSOR_SERVER_REPO` as env var fallbacks. `release_fetcher.py` L46–50 re-reads `VIBESENSOR_SERVER_REPO` and `VIBESENSOR_ROLLBACK_DIR` independently. `firmware_cache.py` L165–173 has 4 env-var-only config keys with no YAML counterpart.
- **Validated root cause**: The updater started as a standalone CLI tool; YAML config was added on top without unifying.
- **Counter-evidence**: `GITHUB_TOKEN` is legitimately env-var-only (secret). The firmware env vars may serve CI override purposes.
- **Refinement**: Focus on eliminating the double-read of already-resolved values. Move firmware settings to config.yaml. Keep `GITHUB_TOKEN` as env-var.

### F10.1: 14-file Package + Scattered Siblings + `_sha256_file` Triplication
- **Validation**: CONFIRMED. 15 `.py` files in `update/`. `_sha256_file` defined identically in `installer.py:476`, `runtime_details.py:42`, and `release_validation.py:21`. `releases.py` imports `_sha256_file` from `runtime_details` (cross-private import). 3 root-level siblings: `release_fetcher.py`, `esp_flash_manager.py`, `firmware_cache.py`. `RuntimeUpdateSubsystem` groups `UpdateManager` + `EspFlashManager`, confirming they belong together.
- **Validated root cause**: One-class-per-file decomposition applied systematically without proportional complexity to justify it.
- **Counter-evidence**: `installer.py` (476 lines) and `wifi.py` are genuinely large enough to be standalone. `workflow.py` has a distinct run() orchestration method.
- **Refinement**: Keep `installer.py`, `wifi.py`, `workflow.py`, `manager.py` as standalone. Consolidate the smaller stubs.

## Root Complexity Drivers
1. Enterprise decomposition principle applied uniformly regardless of actual complexity
2. Each new concern became a new file + frozen config dataclass + constructor injection
3. Config objects are rebuilt on every use instead of built once
4. Env vars and YAML overlap without clear precedence
5. Related update code scattered across root-level and update/ directory

## Relevant Code Paths
- `apps/server/vibesensor/update/` (15 files, 2369 LOC total)
- `apps/server/vibesensor/release_fetcher.py`
- `apps/server/vibesensor/esp_flash_manager.py`
- `apps/server/vibesensor/firmware_cache.py`
- `apps/server/vibesensor/release_validation.py`
- `apps/server/vibesensor/runtime/subsystems.py` (RuntimeUpdateSubsystem)
- `apps/server/vibesensor/runtime/builders.py` (update builder)

## Simplification Approach

### Step 1: Deduplicate `_sha256_file`
- Create a single `_sha256_file` in `update/installer.py` (it's the primary consumer)
- Update `releases.py` and `runtime_details.py` to import from `installer.py`, or move this to a shared location in update package
- Delete duplicate from `release_validation.py` — this file is outside `update/` so it should import from there

### Step 2: Build config objects once in `UpdateManager.__init__`
- Move `UpdateInstallerConfig`, `UpdateWifiConfig`, `UpdateReleaseConfig`, `UpdateValidationConfig`, `UpdateServiceControlConfig` construction to `__init__`
- Store as `self._installer_config`, `self._wifi_config`, etc.
- `_build_workflow()`, `_snapshot_for_rollback()`, `_rollback()` all reference `self._installer_config` instead of reconstructing
- `_build_wifi_controller()` uses `self._wifi_config`

### Step 3: Consolidate small stub files into their natural parent
- **Merge `service_control.py` (57 lines) into `workflow.py`**: `schedule_restart()` is only called at the end of a workflow run. The 2-field config becomes local constants.
- **Merge `validation.py` (~80 lines) into `workflow.py`**: Prerequisite validation is the first step of the workflow. The 2-field config uses `self._rollback_dir` and `MIN_FREE_DISK_BYTES` directly.
- **Merge `state_store.py` (~80 lines) into `status.py`**: State store is only used by the status tracker.
- **Merge `commands.py` into `runner.py`**: `UpdateCommandExecutor` wraps `CommandRunner` with sudo prefix and tracker logging. These are one concern.
- **Merge `runtime_details.py` into `status.py`**: Runtime details collection feeds the status tracker.
- **Inline `network.py` constants into `wifi.py`**: The 12 constants in `network.py` are only used by `wifi.py` and `manager.py`.

### Step 4: Move scattered root-level siblings into `update/`
- Move `esp_flash_manager.py` → `update/firmware.py`
- Move `firmware_cache.py` → `update/firmware.py` (merge with above — they're the same domain)
- Move `release_fetcher.py` → either into `update/releases.py` or keep at root if it has non-update callers
- Move `release_validation.py` → `update/releases.py` (it validates releases)
- Update all imports across the codebase

### Step 5: Unify config channels
- Remove env var fallbacks in `manager.py.__init__` for values already passed from `bootstrap.py`
- For `firmware_cache.py`, move the 4 env-var-only settings into `config.yaml` under `firmware_update:` section
- Keep `GITHUB_TOKEN` as the sole env-var exception (secret)
- Remove the dual-read in `release_fetcher.py` that re-reads `VIBESENSOR_SERVER_REPO`

### Step 6: Eliminate `UpdateInstallerConfig` duplication
After Step 2, the triple construction is already eliminated. But also:
- Inline `UpdateServiceControlConfig` (2 fields) as module constants
- Simplify `UpdateValidationConfig` (2 fields) — pass `rollback_dir` and `min_free_disk_bytes` directly

## Target File Structure
```
update/
  __init__.py      (re-exports)
  manager.py       (public API, config construction, task management)
  workflow.py      (orchestration + validation + service control inlined)
  installer.py     (install/rollback logic + _sha256_file)
  wifi.py          (nmcli logic + network constants inlined)
  releases.py      (release discovery + validation + fetcher logic)
  runner.py        (CommandRunner + CommandExecutor merged)
  status.py        (tracker + state store + runtime details merged)
  models.py        (enums + data classes — unchanged)
  firmware.py      (esp_flash_manager + firmware_cache merged)
```

Result: 15 → 10 files in `update/`, 3 root-level siblings removed, triple config duplication eliminated, env var duplication removed.

## Dependencies on Other Chunks
- None. This chunk is self-contained.

## Risks and Tradeoffs
- **Import path changes**: Many files import from `update/` submodules. Need grep-search for all imports.
- **`release_fetcher.py`**: May have callers outside `update/` — need to verify.
- **Config consolidation**: Changing how firmware cache reads config may affect Docker/Pi environments.
- **Mitigation**: Run full test suite after each merge step to catch breakage early.

## Validation Steps
1. All existing update tests pass
2. `make lint && make typecheck-backend`
3. `pytest -q apps/server/tests/update/`
4. Verify no triple duplication remains via grep for `UpdateInstallerConfig(`
5. Verify no `_sha256_file` duplication via grep

## Required Documentation Updates
- `docs/ai/repo-map.md`: Update update/ package description
- `.github/copilot-instructions.md`: Update update/ package description
- `.github/instructions/backend.instructions.md`: Update `update/` ownership

## Required AI Instruction Updates
- Add guidance: "Do not create a new file for a class with fewer than ~100 lines of logic and a single caller"
- Add guidance: "Build all static config objects once in constructors, not per-use"

## Required Test Updates
- Update import paths in `apps/server/tests/update/` to match new module locations
- Verify tests still pass with merged modules

## Simplification Crosswalk

| Finding | Validation | Root Cause | Steps | Verify |
|---------|-----------|------------|-------|--------|
| F1.1+F2.1: Config duplication + class explosion | Confirmed: triple InstallerConfig, 5 per-use config builds | Enterprise decomposition | Steps 2,3,6 | grep for duplicate config constructors |
| F8.2: Dual config channels | Confirmed: env var reads duplicate YAML | CLI-first design | Step 5 | grep for VIBESENSOR_ env reads outside token |
| F10.1: 14 files + scattered siblings + sha256 | Confirmed: 3 identical _sha256_file | Over-fragmentation | Steps 1,3,4 | file count, grep for _sha256_file defs |
