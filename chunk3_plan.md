# Chunk 3: Module Consolidation & Dead Code Removal

## Mapped Findings

| ID | Original Title | Validation | Status |
|----|---------------|------------|--------|
| A1 | update/workflow.py misnamed single-consumer module fragment | **Validated** — 3 exports (dataclass + 2 functions), single consumer (manager.py), docstring says "workflow orchestration" but actual orchestration is in manager.py | Proceed |
| B2 | UpdateRuntimeDetailsCollector single-method class wrapping Path | **Validated** — Class at status.py:278 with `__slots__ = ("_repo",)` and one `collect()` method. Constructed and immediately called in manager.py:76-77. Matches "construct-call-discard" anti-pattern. | Proceed |
| J2 | ESP/firmware 4 modules scattered at top level outside update/ | **Validated** — `release_fetcher.py`, `firmware_cache.py`, `esp_flash_manager.py`, `release_validation.py` at vibesensor/ root. `update/releases.py` imports `from ..release_fetcher`; `update/installer.py` references `vibesensor.firmware_cache` as subprocess. Tests mapped to tests/update/. | Proceed |
| J3 | metrics_log/ barrel re-export | **Validated** — `__init__.py` re-exports 9 symbols including `PostAnalysisWorker` and all `sample_builder` functions. Comment: "so that existing imports continue to work without changes". Only `MetricsLogger` and `MetricsLoggerConfig` used externally. | Proceed |
| D1 | schema_meta migration dead code running on every startup | **Validated** — `_ensure_schema()` checks for legacy `schema_meta` table on every startup. All current dbs use `PRAGMA user_version`. The check always finds nothing. | Proceed |
| D2 | analysis_version/analysis_is_current unused pipeline | **Validated** — `ANALYSIS_SCHEMA_VERSION=3` written to runs table, `analysis_is_current` computed and added to API response. UI never reads this field. No reanalysis endpoint exists. | Proceed |
| G3 | cleo_api_fixes.py dead one-shot script | **Validated** — Hardcodes `wave1/cleo-api` branch, contains literal patches, zero references from Makefile/CI/README. | Proceed |

## Root Complexity Drivers

1. **Module fragments left over from decomposition**: `workflow.py` and `UpdateRuntimeDetailsCollector` are artifacts of splitting larger classes into modules, where the split went too far.
2. **Scattered ownership**: ESP/firmware modules logically belong in `update/` but live at the package root, creating cross-boundary imports.
3. **Backward-compat shimming**: The metrics_log barrel re-export exists to preserve old import paths, violating the "no backward-compat" policy.
4. **Dead migration code**: `schema_meta` migration that has already completed runs on every startup.
5. **Speculative feature stub**: `analysis_version` supports a reanalysis feature that was never built.
6. **Dead tooling**: One-shot script preserved in tools/.

## Simplification Approach

### A1: Merge update/workflow.py into manager.py and models.py

**Steps**:
1. Move `UpdateValidationConfig` to `update/models.py`
2. Move `validate_prerequisites()` and `schedule_service_restart()` to `update/manager.py` as module-level functions
3. Delete `update/workflow.py`
4. Update imports in `update/manager.py` (from models import UpdateValidationConfig, remove workflow imports)
5. Update test imports if any reference workflow.py directly

### B2: Replace UpdateRuntimeDetailsCollector class with function

**Steps**:
1. Convert `UpdateRuntimeDetailsCollector.collect()` to a module-level function `collect_runtime_details(repo: Path) -> JsonObject` in `update/status.py`
2. Delete the `UpdateRuntimeDetailsCollector` class
3. In `update/manager.py`, replace `self._runtime_details = UpdateRuntimeDetailsCollector(repo=self._repo)` and `self._runtime_details.collect()` with `collect_runtime_details(self._repo)`
4. Update test code that accesses `manager._runtime_details.collect()` to call `collect_runtime_details(manager._repo)` or `collect_runtime_details(Path(...))` directly

### J2: Move ESP/firmware modules into update/

**Steps**:
1. Move `vibesensor/release_fetcher.py` → `vibesensor/update/release_fetcher.py`
2. Move `vibesensor/firmware_cache.py` → `vibesensor/update/firmware_cache.py`
3. Move `vibesensor/esp_flash_manager.py` → `vibesensor/update/esp_flash_manager.py`
4. Move `vibesensor/release_validation.py` → `vibesensor/update/release_validation.py`
5. Update all imports across the codebase:
   - `update/releases.py`: `from ..release_fetcher` → `from .release_fetcher`
   - `update/installer.py`: subprocess `vibesensor.firmware_cache` → `vibesensor.update.firmware_cache`
   - `runtime/state.py`: `from ..esp_flash_manager` → `from ..update.esp_flash_manager`
   - `runtime/builders.py`: similar import update
   - `routes/updates.py`: similar import update
6. Update test imports in `tests/update/`

### J3: Clean metrics_log barrel re-export

**Steps**:
1. Reduce `metrics_log/__init__.py` to export only `MetricsLogger`, `MetricsLoggerConfig`, `MetricsShutdownReport`
2. Remove re-exports of `PostAnalysisWorker`, `build_run_metadata`, `build_sample_records`, `dominant_hz_from_strength`, `extract_strength_data`, `resolve_speed_context`, `safe_metric`, `firmware_version_for_run`
3. Update the backward-compat comment to remove the "continue to work" language
4. Find and update any external imports that use the barrel path:
   - `tests/processing/test_sample_builder.py` → import from `vibesensor.metrics_log.sample_builder` directly
   - Any other test files or production code → similar import path updates
5. Consider moving `test_sample_builder.py` from `tests/processing/` to `tests/metrics_log/` if it exists (fixing the confused ownership)

### D1: Remove schema_meta migration dead code

**Steps**:
1. In `history_db/__init__.py::_ensure_schema()`, remove the block that checks for `schema_meta` table and migrates to `PRAGMA user_version`
2. Remove any tests that create fake `schema_meta` tables to test the migration
3. Update `docs/history_db_schema.md` to remove `schema_meta` documentation

### D2: Remove analysis_version/analysis_is_current pipeline

**Steps**:
1. In `_schema.py`, remove `ANALYSIS_SCHEMA_VERSION = 3` constant
2. In `history_db/__init__.py::store_analysis()`, remove writing `ANALYSIS_SCHEMA_VERSION` to runs table
3. In `history_services/runs.py`, remove `analysis_is_current` computation
4. In `api_models.py`, remove `analysis_is_current` field from the response model
5. Keep `analysis_version INTEGER` column in schema SQL for now (removing columns requires a migration; the column can remain unused)
6. Update generated TypeScript types if they include `analysis_is_current`

### G3: Delete cleo_api_fixes.py

**Steps**:
1. Delete `tools/cleo_api_fixes.py`

## Dependencies on Other Chunks

- J3 barrel cleanup may interact with Chunk 2's changes to sample_builder (C2, C3) — ensure import paths remain consistent
- D2 removal of ANALYSIS_SCHEMA_VERSION: verify no tests in Chunk 4 depend on it

## Risks and Tradeoffs

1. **J2 (move to update/)**: The `firmware_cache.py` subprocess invocation uses module path `vibesensor.firmware_cache` — must update to `vibesensor.update.firmware_cache`. All consumers must be found and updated.
2. **D2**: Leaving the `analysis_version` column in the schema is a minor inconsistency but avoids needing a schema migration. The column will simply stop being written to.
3. **A1**: `validate_prerequisites` is moderately large (~100 lines). Moving it to manager.py increases that file's size but improves discoverability.

## Validation Steps

1. `pytest -q apps/server/tests/update/` — update module tests
2. `pytest -q apps/server/tests/history/` — history/schema tests
3. `pytest -q apps/server/tests/processing/` — sample builder tests
4. `pytest -q apps/server/tests/integration/` — integration tests
5. `make lint && make typecheck-backend`

## Required Documentation Updates

- `docs/ai/repo-map.md` — update update/ package description, metrics_log description
- `docs/history_db_schema.md` — remove schema_meta docs, note analysis_version column unused
- `.github/copilot-instructions.md` — update update/ file list if documented

## Required AI Instruction Updates

- Add guardrail: "Do not create barrel re-exports in package __init__.py for internal implementation symbols. Only export the package's true public API."
- Update update/ file count in backend instructions

## Required Test Updates

- Update test imports for moved modules
- Remove tests for schema_meta migration
- Update tests that check analysis_is_current field

## Simplification Crosswalk

### A1: update/workflow.py misnamed fragment
- **Validation**: Confirmed. 3 exports, 1 consumer, misleading name.
- **Root cause**: Over-decomposition during module split.
- **Steps**: Move dataclass to models.py, functions to manager.py, delete workflow.py.
- **Code areas**: update/workflow.py, update/manager.py, update/models.py
- **Removed**: 1 file (workflow.py)
- **Verification**: `pytest -q apps/server/tests/update/`

### B2: UpdateRuntimeDetailsCollector class
- **Validation**: Confirmed. Single-method class, construct-call-discard.
- **Root cause**: Extraction from manager preserved object style.
- **Steps**: Convert to function, update callers.
- **Code areas**: update/status.py, update/manager.py
- **Removed**: 1 class definition
- **Verification**: `pytest -q apps/server/tests/update/`

### J2: ESP/firmware modules at package root
- **Validation**: Confirmed. 4 files logically belong in update/.
- **Root cause**: Left at top level during update/ consolidation.
- **Steps**: Move 4 files into update/, update all imports.
- **Code areas**: 4 module files + all importers
- **Removed**: 4 files from package root (moved)
- **Verification**: `pytest -q apps/server/tests/ && make typecheck-backend`

### J3: metrics_log barrel re-export
- **Validation**: Confirmed. 9 symbols re-exported, only 3 used externally.
- **Root cause**: Backward-compat shim never cleaned up.
- **Steps**: Reduce __init__.py to 3 exports, fix external imports.
- **Code areas**: metrics_log/__init__.py, external importers
- **Removed**: 6 unnecessary re-exports
- **Verification**: `pytest -q apps/server/tests/`

### D1: schema_meta dead migration
- **Validation**: Confirmed. Always no-ops, runs every startup.
- **Root cause**: One-shot migration never cleaned up.
- **Steps**: Remove migration block and tests.
- **Code areas**: history_db/__init__.py, tests/history/
- **Removed**: ~15 lines migration code, related tests
- **Verification**: `pytest -q apps/server/tests/history/`

### D2: analysis_version/analysis_is_current
- **Validation**: Confirmed. UI never reads field, no reanalysis endpoint.
- **Root cause**: Speculative feature stub.
- **Steps**: Remove constant, stop writing, remove computation, remove API field.
- **Code areas**: _schema.py, history_db, history_services/runs.py, api_models.py
- **Removed**: 1 constant, 1 write, 1 computation, 1 API field
- **Verification**: `pytest -q apps/server/tests/history/ apps/server/tests/api/`

### G3: cleo_api_fixes.py
- **Validation**: Confirmed. Dead script, hardcoded branch, no references.
- **Root cause**: One-shot automation never removed.
- **Steps**: Delete file.
- **Code areas**: tools/cleo_api_fixes.py
- **Removed**: 1 file
- **Verification**: N/A (no consumers)
