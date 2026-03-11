# Chunk 1: Runtime Architecture Simplification

## Mapped Findings

| ID | Original Title | Validation | Status |
|----|---------------|------------|--------|
| A2 | RuntimeState.lifecycle nullable circular back-reference | **Validated** — `lifecycle: LifecycleManager \| None = None` at state.py:53, `assert runtime.lifecycle is not None` at app.py:75, circular wiring in builders.py:187 | Proceed |
| A3 | AnalysisSettingsStore manual sync via callback chain | **Validated** — `apply_car_settings()` and `apply_speed_source_settings()` on RuntimeState, 5+ callsites in settings routes, callbacks threaded through routes/__init__.py | Proceed |
| E2 | HealthResponse 3 nested sub-models for barely-used telemetry | **Validated** — `build_health_snapshot` is 80-line business logic in routes/health.py, returned via lambda closure from routes/__init__.py; UI reads only `status`, `degradation_reasons`, and `persistence.analysis_queue_depth` | Proceed |
| B3 | _MetricsSessionState + _MetricsPersistenceCoordinator intra-module fragments | **Validated** — Two private classes with independent RLocks in metrics_log/logger.py. Neither is imported or tested independently. Single consumer: MetricsLogger | Proceed |

## Root Complexity Drivers

1. **Post-construction wiring ceremony**: RuntimeState is a 22-field dataclass where one field (`lifecycle`) breaks the type contract by being nullable, requiring assertion guards and a 2-step construction pattern.
2. **Callback-based cache invalidation threaded through 3 layers**: Settings changes require manual `apply_car_settings()` calls in 5+ route handlers, with callbacks passed as function parameters through RuntimeState → routes/__init__.py → settings routes.
3. **Business logic in route module**: `build_health_snapshot` (80 lines, 5 service deps) lives in `routes/health.py` though it's pure business logic, and is exported to `routes/__init__.py` where it's wrapped in a lambda closure.
4. **Intra-module class fragmentation with dual locks**: MetricsLogger delegates to two private helper classes that hold independent locks, creating subtle concurrency hazards without testing benefit.

## Relevant Code Paths

### A2: Lifecycle back-reference
- `apps/server/vibesensor/runtime/state.py` — RuntimeState dataclass, `lifecycle` field
- `apps/server/vibesensor/runtime/builders.py` — `build_runtime()`, post-construction `runtime.lifecycle = LifecycleManager(runtime=runtime)`
- `apps/server/vibesensor/app.py` — `assert runtime.lifecycle is not None` in lifespan
- `apps/server/vibesensor/runtime/lifecycle.py` — `LifecycleManager.__init__(runtime=runtime)`, stores `self._runtime`

### A3: Settings callback chain
- `apps/server/vibesensor/runtime/state.py` — `apply_car_settings()`, `apply_speed_source_settings()` methods
- `apps/server/vibesensor/routes/__init__.py` — passes `services.apply_car_settings`, `services.apply_speed_source_settings` as callables
- `apps/server/vibesensor/routes/settings.py` — receives and calls the callbacks in 5+ route handlers
- `apps/server/vibesensor/analysis_settings.py` — `AnalysisSettingsStore.update()`
- `apps/server/vibesensor/settings_store.py` — `SettingsStore`, source of car aspects

### E2: Health route business logic
- `apps/server/vibesensor/routes/health.py` — `build_health_snapshot()` function
- `apps/server/vibesensor/routes/__init__.py` — lambda wrapping 5 service references
- `apps/server/vibesensor/api_models.py` — `HealthResponse`, sub-models

### B3: MetricsLogger class fragments
- `apps/server/vibesensor/metrics_log/logger.py` — `_MetricsSessionState`, `_MetricsPersistenceCoordinator`, `MetricsLogger`

## Simplification Approach

### A2: Remove lifecycle from RuntimeState

**Strategy**: Remove the `lifecycle` field from RuntimeState entirely. Construct `LifecycleManager` in `app.py::create_app()` after `build_runtime()`. The `lifespan` closure captures it directly.

**Steps**:
1. Remove `lifecycle: LifecycleManager | None = None` from `RuntimeState` in state.py
2. Remove `from .lifecycle import LifecycleManager` from state.py
3. In builders.py, remove `runtime.lifecycle = LifecycleManager(runtime=runtime)` — return `runtime` without lifecycle
4. In app.py, construct `LifecycleManager(runtime=runtime)` inline after `build_runtime()`, use it directly in the lifespan closure
5. Remove the `assert runtime.lifecycle is not None` guard
6. Add `from .runtime.lifecycle import LifecycleManager` to app.py
7. Update tests that access `runtime.lifecycle` to construct lifecycle locally

### A3: Internalize settings cache invalidation

**Strategy**: Make `SettingsStore` auto-invalidate `AnalysisSettingsStore` on car-profile writes, and auto-update `GPSSpeedMonitor` on speed-source writes. Remove the callback parameters from routes.

**Steps**:
1. Modify `SettingsStore.__init__` to accept optional `analysis_settings: AnalysisSettingsStore` and `gps_monitor: GPSSpeedMonitor`
2. In every car-mutating method (`add_car`, `update_car`, `delete_car`, `set_active_car`, `reset_active_car`), call `self._invalidate_analysis()` internally after the DB write
3. In `set_speed_source()`, call `self._invalidate_speed_source()` internally
4. Implement private `_invalidate_analysis()` and `_invalidate_speed_source()` methods on `SettingsStore` (same logic as current `RuntimeState.apply_car_settings()` / `apply_speed_source_settings()`)
5. Remove `apply_car_settings()` and `apply_speed_source_settings()` from RuntimeState
6. Remove the two callback parameters from `create_settings_routes()` signature
7. Remove the 5+ `apply_car_settings()` / `apply_speed_source_settings()` calls from settings route handlers
8. In builders.py, pass `analysis_settings` and `gps_monitor` to `SettingsStore()` constructor
9. Remove `runtime.apply_car_settings()` and `runtime.apply_speed_source_settings()` lines from builders.py
10. In routes/__init__.py, remove the callback args from `create_settings_routes()` call

### E2: Simplify health route wiring

**Strategy**: Pass 5 service dependencies directly to `create_health_routes` instead of wrapping in a lambda closure. Make `build_health_snapshot` private to health.py.

**Steps**:
1. Change `create_health_routes(snapshot_fn: Callable)` → `create_health_routes(loop_state, health_state, processor, registry, metrics_logger)`
2. The route handler calls `_build_health_snapshot(...)` directly
3. Rename `build_health_snapshot` → `_build_health_snapshot` (private)
4. Remove the export from routes/__init__.py's import list
5. In routes/__init__.py, replace the lambda with direct service passing

### B3: Merge MetricsLogger class fragments

**Strategy**: Inline the fields and methods of `_MetricsSessionState` and `_MetricsPersistenceCoordinator` directly into `MetricsLogger`. Use a single `RLock`.

**Steps**:
1. Move all fields from `_MetricsSessionState.__init__` into `MetricsLogger.__init__`
2. Move all methods from `_MetricsSessionState` into `MetricsLogger` (with section comments)
3. Move all fields from `_MetricsPersistenceCoordinator.__init__` into `MetricsLogger.__init__`
4. Move all methods from `_MetricsPersistenceCoordinator` into `MetricsLogger` (with section comments)
5. Replace `self._session._lock` and `self._persistence._lock` with a single `self._lock`
6. Replace all `self._session.xxx` with direct field access
7. Replace all `self._persistence.xxx` with direct field access
8. Delete the two private class definitions
9. Keep `MetricsSessionSnapshot` and `PersistenceStatusSnapshot` dataclasses (they're return types)

## Dependencies on Other Chunks

- A3 (callback removal) reduces `create_settings_routes` args from 5 to 3, which partially addresses Chunk 5's E3 finding. Chunk 5 should note this prerequisite.
- A2 (lifecycle removal from RuntimeState) affects tests in Chunk 4 that use FakeState. FakeState's `lifecycle` field will need removal.

## Risks and Tradeoffs

1. **A2**: `LifecycleManager` still takes `runtime` as a parameter — the circular usage is legitimate (lifecycle manages the runtime). Only the nullable field ownership on RuntimeState is removed.
2. **A3**: Adding `analysis_settings` and `gps_monitor` to `SettingsStore` creates a coupling, but it's strictly better than the 3-layer callback chain because it enforces the invalidation invariant via the type system.
3. **B3**: MetricsLogger will grow to ~500+ lines. Acceptable for a facade class — the dual-lock alternative is worse.
4. **E2**: Passing 5 explicit service args is more verbose than a lambda but removes the indirection.

## Validation Steps

1. `pytest -q apps/server/tests/app/` — app creation and lifecycle tests
2. `pytest -q apps/server/tests/api/` — API route tests (settings callbacks removed)
3. `pytest -q apps/server/tests/integration/` — cross-cutting integration tests
4. `pytest -q apps/server/tests/analysis/` — analysis settings tests
5. `make lint && make typecheck-backend`

## Required Documentation Updates

- `docs/ai/repo-map.md` — update RuntimeState description (no lifecycle field), update metrics_log description

## Required AI Instruction Updates

- Add guardrail to general.instructions.md: "Do not add nullable fields to RuntimeState for post-construction wiring"
- Add guardrail: "When a service mutates state that another service caches, the mutating service must own the cache invalidation"

## Required Test Updates

- Tests accessing `runtime.lifecycle` must construct lifecycle separately
- Settings route tests that verify callback invocation → verify auto-invalidation instead
- FakeState in conftest.py loses its `lifecycle` field

## Simplification Crosswalk

### A2: RuntimeState.lifecycle nullable circular back-reference
- **Validation**: Confirmed. Only nullable field in 22-field dataclass.
- **Root cause**: Circular dependency resolved via nullable field instead of external construction.
- **Steps**: Remove field from dataclass, construct in app.py, remove assertion guard.
- **Code areas**: state.py, builders.py, app.py
- **Removed**: 1 nullable field, 1 import, 1 assertion, 1 builder line
- **Verification**: `pytest -q apps/server/tests/app/ && make typecheck-backend`

### A3: AnalysisSettingsStore manual sync via callback chain
- **Validation**: Confirmed. 5+ callsites, 2 callback params, 2 RuntimeState methods.
- **Root cause**: SettingsStore doesn't own its cache invalidation.
- **Steps**: Add deps to SettingsStore, auto-invalidate on writes, remove callbacks.
- **Code areas**: settings_store.py, state.py, routes/__init__.py, routes/settings.py, builders.py
- **Removed**: 2 RuntimeState methods, 2 route callback params, 5+ manual sync calls
- **Verification**: `pytest -q apps/server/tests/api/ apps/server/tests/analysis/`

### E2: HealthResponse business logic in route module
- **Validation**: Confirmed. 80-line function, lambda closure in routes/__init__.py.
- **Root cause**: Business logic placed in route file for convenience.
- **Steps**: Pass services directly, make function private.
- **Code areas**: routes/health.py, routes/__init__.py
- **Removed**: Lambda closure, public export
- **Verification**: `pytest -q apps/server/tests/api/`

### B3: MetricsLogger class fragments
- **Validation**: Confirmed. Two private classes, independent locks, single consumer.
- **Root cause**: Over-decomposition within single module.
- **Steps**: Inline all fields/methods, single RLock.
- **Code areas**: metrics_log/logger.py
- **Removed**: 2 class definitions, 1 extra RLock
- **Verification**: `pytest -q apps/server/tests/ -k "metrics"`
