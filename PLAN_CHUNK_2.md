# Chunk 2: Runtime Architecture & Bootstrap Simplification

## Mapped Findings

| ID | Original Finding | Source Subagent | Validation Status |
|----|-----------------|-----------------|-------------------|
| A1+B3 | Five Runtime*Subsystem dataclasses are mandatory indirection with no isolation value | Architecture & Layering + Abstraction | **Validated** |
| A2 | bootstrap.py is a hollow 70-line sequencer wrapping runtime/builders.py | Architecture & Layering | **Validated** |

## Validation Outcomes

### A1+B3: Runtime*Subsystem intermediate containers — VALIDATED

Confirmed in `runtime/state.py`:
- `RuntimeIngressSubsystem`: 4 fields (registry, processor, control_plane, worker_pool)
- `RuntimeSettingsSubsystem`: 3 fields + 2 methods (apply_car_settings, apply_speed_source_settings)
- `RuntimePersistenceSubsystem`: 4 fields (history_db, run_service, report_service, export_service)
- `RuntimeProcessingSubsystem`: 3 fields (state, health_state, loop)
- `RuntimeWebsocketSubsystem`: 3 fields (hub, cache, broadcast)

`RuntimeState` holds these 5 containers plus 4 direct fields (config, metrics_logger, update_manager, esp_flash_manager, lifecycle).

Every access in routes, lifecycle, tests goes through an extra dot level: `runtime.ingress.registry`, `runtime.settings.settings_store`, etc. No container enforces any boundary — they are plain data holders.

The `RuntimeSettingsSubsystem` has two methods (`apply_car_settings`, `apply_speed_source_settings`) that are the only methods on any subsystem container. These are called from `bootstrap.py` at startup and from `routes/settings.py` when settings change. They read from `settings_store` and update `analysis_settings` and `gps_monitor`.

`RuntimePersistenceSubsystem` (B3 overlap): routes receive this container and immediately unpack 3 services, never touching `history_db`. The `history_db` field leaks the storage layer into routes.

The containers have zero boundary enforcement, zero lazy loading, and zero policies beyond settings' 2 sync methods.

### A2: bootstrap.py hollow sequencer — VALIDATED

Confirmed: `bootstrap.py` is 75 lines. Its `build_services()` function:
1. Imports 9 builder functions from `runtime/builders.py`
2. Calls them in dependency order
3. Creates `EspFlashManager()` inline
4. Creates `LifecycleManager`
5. Calls `apply_car_settings()` and `apply_speed_source_settings()`

Zero domain logic. All construction logic lives in `runtime/builders.py`. `app.py` imports from `bootstrap.py` which imports from `runtime/builders.py` — an unnecessary import hop.

## Root Causes

The subsystem containers were introduced when `RuntimeRouteServices` was removed, as an intermediate organizational step. They added conceptual grouping but no actual isolation. `bootstrap.py` was the original monolithic composition root; after extracting builders, it became a hollow sequencer but was never merged back.

## Implementation Steps

### Step 1: Flatten RuntimeState — remove subsystem containers

1. Move all fields from the 5 subsystem dataclasses directly onto `RuntimeState`:
   - From `RuntimeIngressSubsystem`: `registry`, `processor`, `control_plane`, `worker_pool`
   - From `RuntimeSettingsSubsystem`: `settings_store`, `analysis_settings`, `gps_monitor`
   - From `RuntimePersistenceSubsystem`: `history_db`, `run_service`, `report_service`, `export_service`
   - From `RuntimeProcessingSubsystem`: `processing_loop_state`, `health_state`, `processing_loop`
   - From `RuntimeWebsocketSubsystem`: `ws_hub`, `ws_cache`, `ws_broadcast`
   Note: rename some fields to avoid ambiguity at the flat level (e.g., `state` → `processing_loop_state`, `loop` → `processing_loop`, `hub` → `ws_hub`)

2. Delete the 5 `Runtime*Subsystem` dataclass definitions from `state.py`

3. Move `apply_car_settings` and `apply_speed_source_settings` to free functions in `state.py` (or keep as methods on `RuntimeState` directly, since they reference 3 of its fields)

4. Update `bootstrap.py`/`builders.py` to construct `RuntimeState` with flat fields

5. Update all files that access subsystem fields:
   - `routes/__init__.py`: `services.ingress.registry` → `services.registry`, etc.
   - `routes/history.py`: `persistence.run_service` → access flat fields
   - `routes/settings.py`: `settings.settings_store` → flat field
   - `runtime/lifecycle.py`: `self._runtime.ingress.control_plane` → `self._runtime.control_plane`
   - `runtime/ws_broadcast.py`: references to websocket subsystem
   - `runtime/processing_loop.py`: references to processing subsystem
   - All test files: `FakeState` construction, subsystem field access patterns

6. Update `tests/conftest.py`: simplify `FakeState` to construct with flat fields (removes ~30 lines of subsystem assembly boilerplate)

### Step 2: Merge bootstrap.py into runtime/builders.py

1. Move `build_services()` body from `bootstrap.py` into `runtime/builders.py` as `build_runtime()` (or keep the name `build_services`)
2. Move the `EspFlashManager()` inline creation into the builder
3. Move `LifecycleManager` creation into the builder
4. Move the `apply_car_settings()` / `apply_speed_source_settings()` startup calls into the builder
5. Update `app.py` import: `from .bootstrap import build_services` → `from .runtime.builders import build_runtime`
6. Delete `bootstrap.py`
7. Update `BOUNDARIES.md` to remove stale references to `composition.py`, `subsystems.py`, `settings_sync.py`

### Step 3: Update all consumers

1. Systematically update every file that imports from `runtime/state.py`:
   - Remove any `RuntimeIngressSubsystem`, `RuntimeSettingsSubsystem`, etc. imports
   - Update field access patterns to use flat RuntimeState
2. Update type annotations in route factory functions
3. Update type annotations in lifecycle manager
4. Verify with mypy: `make typecheck-backend`

### Step 4: Update tests

1. Rewrite `FakeState` in `conftest.py` to use flat field construction
2. Update all test files that construct or mock subsystem containers
3. Verify all tests pass: `pytest -q apps/server/tests/`

## Dependencies on Other Chunks

- Must execute after Chunk 1 (dead code removal) so we work with a cleaner codebase
- Chunk 3's metrics_log consolidation (A3) is independent of this chunk
- Chunk 4's configuration simplification is independent

## Risks and Tradeoffs

- **Large blast radius**: Flattening RuntimeState touches every file that accesses runtime services — routes, lifecycle, ws_broadcast, processing_loop, tests. Careful systematic find-and-replace needed.
- **Settings callbacks**: The 2 methods on `RuntimeSettingsSubsystem` (`apply_car_settings`, `apply_speed_source_settings`) need new homes. Making them methods on `RuntimeState` directly is simplest since they reference state fields.
- **BOUNDARIES.md staleness**: The doc references non-existent files. Must be updated.

## Validation Steps

1. `ruff check apps/server/`
2. `make typecheck-backend`
3. `pytest -q apps/server/tests/`
4. Verify no `RuntimeIngressSubsystem`, `RuntimeSettingsSubsystem`, etc. references remain

## Documentation Updates

- Update `docs/ai/repo-map.md`: remove subsystem container references, update RuntimeState description
- Update `.github/copilot-instructions.md`: remove subsystem references
- Update `.github/instructions/backend.instructions.md`: update runtime ownership section
- Update or delete `vibesensor/BOUNDARIES.md`
- Update `apps/server/README.md` if it references subsystems

## AI Instruction Updates

- Add to `general.instructions.md`: "Do not introduce intermediate container dataclasses to group services unless the container enforces an actual boundary (access control, lazy initialization, lifecycle management). Plain field grouping on the parent state object is sufficient."

## Simplification Crosswalk

| Finding | Steps | Removable | Verification |
|---------|-------|-----------|-------------|
| A1+B3 | Step 1, 3 | 5 dataclass definitions (~60 lines), one dot-level from all access paths, ~30 lines of test boilerplate | No subsystem type references remain, all tests pass |
| A2 | Step 2 | bootstrap.py (~75 lines), one import hop from app.py | app.py imports directly from builders, no bootstrap.py exists |
