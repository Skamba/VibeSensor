# Chunk 3: Abstraction and Indirection Reduction

## Execution order: 3 of 5

## Mapped Findings

| ID | Original Finding | Validation Result |
|----|-----------------|-------------------|
| B1 | `LoggingStatusPayload` TypedDict mirrors `LoggingStatusResponse` Pydantic model | CONFIRMED — 9 identical fields. TypedDict docstring says "so the dict can be unpacked directly into the Pydantic model." Violates project's own rule: "Do not create TypedDict mirrors of Pydantic models." Used in 3 route handlers via `LoggingStatusResponse(**metrics_logger.status())`. Also used in `MetricsShutdownReport.final_status`. |
| B2 | `UpdatePrerequisiteValidator` + `UpdateServiceController` are one-shot wrapper classes | CONFIRMED — Both constructed in `_run_update_inner()`, each called once, then discarded. `UpdatePrerequisiteValidator` has 1 public method (`validate`) + 1 private helper. `UpdateServiceController` has 1 public method (`schedule_restart`). Both match the prohibited pattern: "Do not create wrapper dataclasses for one-shot operations." |
| B3 | `MetricsLogger` has 3 separate RLocks via 2 private proxy classes | CONFIRMED — `_MetricsSessionState._lock` (10 per-property lock blocks), `_MetricsPersistenceCoordinator._lock` (10 per-property lock blocks), `MetricsLogger._lock`. Both private classes are exclusively owned by `MetricsLogger`. ~20 `@property` methods follow identical `with self._lock: return self._field` pattern. |

## Root Causes

- **B1**: Layering purism — avoiding an import from `api_models` in a service-layer module. The TypedDict was created as an internal type to avoid the perception of a "wrong direction" import.
- **B2**: Domain-object-per-phase design — each update phase was modeled as a separate class to give it a namespace, even though neither phase carries state across calls.
- **B3**: Progressive privatization — two coherent subsets of MetricsLogger state were extracted into private classes, each with their own lock, creating three independent locking domains for fields that are always read/written as a unit during `status()` calls.

## Relevant Code Paths

### B1: LoggingStatusPayload mirror
- `apps/server/vibesensor/metrics_log/logger.py` L57-68 — `LoggingStatusPayload` TypedDict (9 fields)
- `apps/server/vibesensor/api_models.py` — `LoggingStatusResponse` Pydantic model (same 9 fields)
- `apps/server/vibesensor/routes/recording.py` L25,29,33 — bridge: `LoggingStatusResponse(**metrics_logger.status())`
- `apps/server/vibesensor/metrics_log/logger.py` L537 — `MetricsShutdownReport.final_status: LoggingStatusPayload`
- `apps/server/vibesensor/metrics_log/__init__.py` L20 — re-exports `LoggingStatusPayload`

### B2: Update one-shot classes
- `apps/server/vibesensor/update/workflow.py` L25 — `UpdatePrerequisiteValidator` class
- `apps/server/vibesensor/update/workflow.py` L125 — `UpdateServiceController` class
- `apps/server/vibesensor/update/manager.py` L213-234 — construction and single-call sites
- Both config dataclasses (`UpdateValidationConfig`, `UpdateServiceControlConfig`) stay — they're legitimate config groupings
- `apps/server/tests/update/test_update_validation.py` — tests `UpdatePrerequisiteValidator` directly

### B3: MetricsLogger locking
- `apps/server/vibesensor/metrics_log/logger.py` L85 — `_MetricsSessionState._lock` 
- `apps/server/vibesensor/metrics_log/logger.py` L244 — `_MetricsPersistenceCoordinator._lock`
- `apps/server/vibesensor/metrics_log/logger.py` L577 — `MetricsLogger._lock`
- Per-property pattern: `@property def X(self): with self._lock: return self._X` × ~20

## Simplification Approach

### B1: Delete LoggingStatusPayload, use dict return

**Strategy**: Remove the TypedDict entirely. Have `MetricsLogger.status()`, `start_logging()`, `stop_logging()` return `dict[str, object]`. The route handlers already construct `LoggingStatusResponse` from the dict — they just won't need a TypedDict annotation.

**Steps**:
1. In `logger.py`: delete the `LoggingStatusPayload` TypedDict definition (L57-68)
2. Update `MetricsLogger.status()` return type from `LoggingStatusPayload` to `dict[str, object]`
3. Update `MetricsLogger.start_logging()` return type similarly
4. Update `MetricsLogger.stop_logging()` return type similarly
5. Update `MetricsShutdownReport.final_status` type from `LoggingStatusPayload` to `dict[str, object]`
6. Remove `LoggingStatusPayload` from `metrics_log/__init__.py` re-exports
7. Routes in `recording.py` continue to work unchanged: `LoggingStatusResponse(**metrics_logger.status())`
8. The Pydantic model `LoggingStatusResponse` becomes the single source of truth for field names

### B2: Convert one-shot classes to module-level functions

**Strategy**: Replace each one-shot class with a standalone async function. The function receives the same parameters that were in `__init__`.

**Steps**:
1. In `workflow.py`: convert `UpdatePrerequisiteValidator` class to `async def validate_prerequisites(commands, tracker, config, ssid) -> bool`
   - Move `_probe_rollback_dir()` to be a nested function or module-level private function
   - The `validate()` method body becomes the function body
   
2. In `workflow.py`: convert `UpdateServiceController` class to `async def schedule_service_restart(commands, tracker, config) -> bool`
   - The `schedule_restart()` method body becomes the function body

3. In `manager.py`: update `_run_update_inner()` to call the functions directly:
   ```python
   # Before:
   validator = UpdatePrerequisiteValidator(commands=commands, tracker=tracker, config=self._validation_config)
   if not await validator.validate(request.ssid): return
   
   # After:
   if not await validate_prerequisites(commands, tracker, self._validation_config, request.ssid): return
   ```
   
4. Keep `UpdateValidationConfig` and `UpdateServiceControlConfig` frozen dataclasses — they're legitimate config groupings with 3+ fields each

5. Update `test_update_validation.py` to test `validate_prerequisites()` function directly instead of constructing `UpdatePrerequisiteValidator`

### B3: Reduce MetricsLogger per-property lock boilerplate

**Strategy**: Rather than the risky full refactor of merging private classes into MetricsLogger, take the safer approach: replace individual per-property lock acquisitions with bulk snapshot/status methods. Keep the class structure but eliminate the boilerplate pattern.

**Steps**:
1. In `_MetricsSessionState`: 
   - Remove individual `@property` getters that do `with self._lock: return self._X`
   - Keep compound methods (`start_new_session`, `stop_session`, `snapshot`) that legitimately need the lock
   - Replace per-field reads in MetricsLogger with `snapshot()` calls where multiple fields are needed
   - For 1-2 fields accessed individually (like `run_id`), use direct attribute access (GIL-safe for simple attribute reads)

2. In `_MetricsPersistenceCoordinator`:
   - Same approach: remove per-property lock wrappers
   - Keep compound methods (`reset_for_new_session`, `ensure_history_run_created`, `append_rows`, `finalize_run`)
   - Add a `status_snapshot()` method that reads all status-relevant fields under one lock

3. In `MetricsLogger.status()`:
   - Instead of 5 separate property accesses (each acquiring its own lock), call `self._session.snapshot()` + `self._persistence.status_snapshot()` for two lock acquisitions total

4. Keep the 3-lock architecture (don't merge classes yet — too risky for this PR)

## Implementation Sequence

1. B1 (LoggingStatusPayload removal — lowest risk, clear rule violation)
2. B2 (Update classes → functions — moderate, well-scoped)
3. B3 (MetricsLogger lock cleanup — most complex, do last)

## Dependencies on Other Chunks

- B1 changes `MetricsLogger` return types — no dependency on other chunks
- B2 changes `update/workflow.py` and `update/manager.py` — no dependency on other chunks
- B3 changes `metrics_log/logger.py` — must be done after B1 (which also changes logger.py)
- No dependency on Chunk 1 or 2

## Risks and Tradeoffs

- **B1**: Very low risk. The route handlers already construct `LoggingStatusResponse` from the dict via `**` unpack. Removing the TypedDict doesn't change any runtime behavior.
- **B2**: Low-medium risk. The function signatures preserve all the same parameters. Test must be updated to call functions instead of constructing classes.
- **B3**: Medium risk. Changing locking patterns in a threaded recording path requires careful verification. The "replace per-property with bulk snapshot" approach is much safer than full class merge. Key risk: callers of individual properties must be identified and updated to use snapshot results.

## Validation Steps

1. `pytest -q apps/server/tests/api/` — recording route tests
2. `pytest -q apps/server/tests/update/` — update tests
3. `pytest -q apps/server/tests/app/` — app-level tests
4. `make lint && make typecheck-backend`
5. Full suite: `python3 tools/tests/run_ci_parallel.py --job backend-tests`

## Required Documentation Updates

- Update `docs/ai/repo-map.md` update/ section to mention functions instead of classes
- No significant doc changes needed for B1 or B3

## Required AI Instruction Updates

- Add to `.github/instructions/general.instructions.md` complexity hygiene:
  - "Do not create TypedDict mirrors of Pydantic models at HTTP boundaries. Use the Pydantic model directly or return `dict[str, object]` and let the route handler validate."
  - "Do not create classes for one-shot operations. If a class is constructed, used once, and discarded, convert it to a function."
  - "Avoid per-property lock patterns for private classes. Use bulk snapshot methods that read all needed fields under a single lock acquisition."

## Required Test Updates

- `test_update_validation.py` — update to test `validate_prerequisites()` function
- Recording route tests — should continue to pass unchanged (they test the response shape, not the TypedDict)
- MetricsLogger tests — update any that access individual properties directly

## Simplification Crosswalk

| Finding | Validation | Root Cause | Steps | Areas Changed | What's Removed | Verification |
|---------|-----------|------------|-------|---------------|----------------|--------------|
| B1 | CONFIRMED (9-field TypedDict identical to Pydantic model) | Layering purism avoiding api_models import | Delete TypedDict, return dict[str, object] | logger.py, __init__.py | ~15 lines TypedDict + re-export, 1 type definition | Recording route tests pass, status endpoint returns same JSON |
| B2 | CONFIRMED (2 classes with 1 method each, constructed and discarded per-call) | Domain-object-per-phase design | Convert classes to async functions | workflow.py, manager.py, test_update_validation.py | 2 classes (~70 lines of class scaffolding) | Update tests pass, update flow works |
| B3 | CONFIRMED (20 per-property lock blocks across 2 private classes) | Progressive privatization of state subsets | Replace per-property locks with bulk snapshot methods | logger.py | ~40 lines of per-property lock boilerplate | MetricsLogger tests pass, status() returns correct data, no race conditions |
