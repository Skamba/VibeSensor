# Chunk 1: Runtime & Service Layer Flattening

## Mapped Findings

| ID | Title | Validation | Status |
|----|-------|------------|--------|
| A2 | Runtime subsystem wrappers add navigation layer | PARTIALLY VALID | Plan below |
| A3 | History services micro-classes | PARTIALLY VALID | Plan below |
| B1 | build_lifecycle_manager pass-through | VALID | Plan below |
| B2/D3 | HistoryJsonResult bypasses error model | PARTIALLY VALID | Plan below |
| D1 | Triple _report_template_data sanitization | PARTIALLY VALID | Plan below |

## Root Causes

The runtime composition root grew from a principled layering intention — group related services,
provide factory functions — but each layer was applied uniformly regardless of whether the
individual case warranted it. The result is that most subsystem wrappers are structurally
pass-through containers that every consumer immediately unpacks, and one builder function is
a pure identity relay. Similarly, `history_services/` decomposed into 4 service classes where
2 of them (`HistoryRunDeleteService`, `HistoryExportService`) have exactly 1 public method each,
creating class overhead for what could be methods on a single service.

## Validation Details

### A2: Runtime Subsystem Wrappers (PARTIALLY VALID)

**Validated structure:**
- 5 subsystem dataclasses in `runtime/subsystems.py`
- `RuntimeSettingsSubsystem` has 2 real methods (`apply_car_settings`, `apply_speed_source_settings`)
- All other 4 subsystems are pure field containers (no behavior)
- Routes access individual fields through 2-level dotted paths
- `RuntimeState` in `_state.py` has 10 fields pointing to subsystem wrappers or standalone services

**Validated approach:** Cannot fully flatten because `RuntimeSettingsSubsystem` owns real coordination.
However, the 4 behavior-free subsystems (Ingress, Persistence, Processing, Websocket) can be
replaced with direct fields on `RuntimeState`. The settings subsystem stays as a thin coordinator.

**Revised plan:**
- Merge `subsystems.py` and `_state.py` into a single `runtime/state.py`
- Flatten 4 pure-container subsystems into direct fields on `RuntimeState`
- Keep `RuntimeSettingsSubsystem` (it has real behavior) but inline it into `state.py`
- Merge builder functions from `builders.py` into `bootstrap.py` (they're only called there)
- Result: `runtime/` drops from needing `subsystems.py` + `_state.py` + `builders.py` → `state.py`

### A3: History Services Micro-Classes (PARTIALLY VALID)

**Validated structure:**
- `HistoryRunQueryService`: 3 async methods — substantive
- `HistoryRunDeleteService`: 1 async method (5 lines) — thin wrapper
- `HistoryReportService`: 2+ methods with genuine PDF caching logic — substantive
- `HistoryReportPdfCache`: separate cache class with locking — substantive
- `HistoryExportService`: 1 async method — thin wrapper
- `HistoryExportArchiveBuilder`: 1 method (ZIP streaming) — thin wrapper

**Counter-evidence:** `HistoryReportService` and `HistoryReportPdfCache` own real logic.

**Revised plan:**
- Merge `HistoryRunDeleteService` (1 method) into `HistoryRunQueryService` → rename to `HistoryRunService`
- Keep `HistoryReportService` (substantive with caching logic)
- Merge `HistoryExportService` + `HistoryExportArchiveBuilder` into one class → `HistoryExportService`
- Keep `reports.py` and `exports.py` as separate files (they have enough logic)
- Merge `runs.py` `HistoryRunDeleteService` class into `HistoryRunQueryService` class within same file
- Result: 4 service classes → 3 service classes; files stay at 3 (runs.py, reports.py, exports.py)
- Simplify `RuntimePersistenceSubsystem` from 5 fields → 4 (drop separate delete_service)

### B1: build_lifecycle_manager Pass-Through (VALID)

**Validated:** Pure 9-arg relay. Only production caller is `bootstrap.py`. Two test callers.

**Plan:** Delete `build_lifecycle_manager` from `builders.py`. Replace calls in `bootstrap.py` with
direct `LifecycleManager(...)` construction. Update test imports.

### B2/D3: HistoryJsonResult (PARTIALLY VALID)

**Validated:** `HistoryJsonResult` is used exclusively for `get_insights()` to carry HTTP 202
for the "still analyzing" case. The concern is real but the counter-argument is also valid:
returning HTTP 202 is "not an error" semantically.

**Revised plan:** Instead of forcing exception-for-success, simplify by having `get_insights()`
return `tuple[int, JsonObject]` (status_code, payload) directly — eliminate the class wrapper
while keeping the semantics clean. This removes the dataclass overhead without misusing exceptions.
Actually even simpler: have `get_insights()` return `JsonObject | None` where None means
analysis is still running, and let the route handle the 202 directly. This is the simplest
approach: the service returns domain data, the route handles HTTP semantics.

### D1: Triple Sanitization (PARTIALLY VALID)

**Validated:** `_sanitize_for_read` is NOT dead code (called in 2 production paths). But the
triple sanitization IS redundant: `strip_internal_fields` at the service boundary handles
all `_`-prefixed keys, making the DB-layer sanitizers for the single key redundant.

**Revised plan:** Remove `_sanitize_for_storage` and `_sanitize_for_read` from `history_db/__init__.py`.
The service-layer `strip_internal_fields` already covers all `_`-prefixed keys on the read path.
On the write path, storing `_report_template_data` is harmless because it never reaches consumers.
Actually — keep `_sanitize_for_storage` to prevent bloating the database with template data that is
only needed transiently. Remove only `_sanitize_for_read` since `strip_internal_fields` handles reads.

## Implementation Steps

### Step 1: Merge subsystems.py and _state.py → runtime/state.py
1. Create `runtime/state.py` with `RuntimeState` containing flattened fields
2. Move `RuntimeSettingsSubsystem` class into `state.py` (keep it, it has behavior)
3. Replace subsystem wrapper fields with direct service fields for Ingress, Persistence, Processing, Websocket
4. Delete `runtime/subsystems.py` and `runtime/_state.py`
5. Update all imports across routes/, lifecycle.py, bootstrap.py, tests

### Step 2: Merge builders.py into bootstrap.py
1. Move all `build_*` functions from `builders.py` into `bootstrap.py` as private functions
2. Delete `build_lifecycle_manager` entirely (B1) — inline `LifecycleManager(...)` call
3. Delete `runtime/builders.py`
4. Update all imports

### Step 3: Merge HistoryRunDeleteService into HistoryRunQueryService
1. In `history_services/runs.py`, move `delete_run` method into `HistoryRunQueryService`
2. Rename class to `HistoryRunService`
3. Delete `HistoryRunDeleteService` class
4. Update `RuntimePersistenceSubsystem` to remove `delete_service` field
5. Update routes/history.py to use `run_service.delete_run` instead of `delete_service.delete_run`

### Step 4: Simplify HistoryJsonResult (B2)
1. Change `get_insights()` to return `JsonObject | None` (None = still analyzing)
2. Delete `HistoryJsonResult` dataclass
3. Update route handler to check for None and return 202

### Step 5: Remove _sanitize_for_read (D1)
1. Remove `_sanitize_for_read` function from `history_db/__init__.py`
2. Remove its call sites in `get_run()` and `get_run_analysis()`
3. Keep `_sanitize_for_storage` (prevents database bloat)
4. `strip_internal_fields` at service boundary handles read-side sanitization

### Step 6: Update tests
1. Update test imports for moved builders
2. Update tests that reference subsystem wrappers
3. Update tests that use `HistoryRunDeleteService` or `HistoryJsonResult`

### Step 7: Update routes/__init__.py
1. Change all 2-level `services.processing.state` → `services.processing_state` (direct fields)
2. Update route factory signatures where subsystem wrappers were unpacked

## Dependencies on Other Chunks
- None (this is independent)

## Risks
- Merge of builders into bootstrap.py makes bootstrap.py larger but more self-contained
- Flattening subsystems means RuntimeState has ~15-18 individual fields instead of 10 grouped ones
- RuntimeSettingsSubsystem behavior methods need to stay somewhere

## Documentation Updates Required
- `docs/ai/repo-map.md`: update runtime package description
- `.github/instructions/backend.instructions.md`: update backend ownership boundaries
- `.github/copilot-instructions.md`: update backend package layout description

## AI Instruction Updates
- Add guidance to prefer flat state containers over nested subsystem wrappers
- Add guidance against single-method service classes

## Validation
- Run `pytest apps/server/tests/app/` for runtime tests
- Run full `make test-all` after all changes
- Verify no import errors with `make typecheck-backend`
