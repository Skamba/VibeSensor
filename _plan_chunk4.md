# Chunk 4: API, Interface, and Frontend Simplification

## Execution order: 4 of 5

## Mapped Findings

| ID | Original Finding | Validation Result |
|----|-----------------|-------------------|
| C1 | Car library forces 3 sequential HTTP round-trips | **DROPPED** — Validated as a correct cascading-selection wizard pattern. The 3 calls are user-paced (user picks brand → picks type → picks model), not programmatic sequential. This is standard UX for hierarchical selection and not unnecessarily complex. |
| C2 | Update and ESP-flash operations buried inside `/api/settings/` namespace | CONFIRMED — 9 update/flash endpoints under `/api/settings/update/` and `/api/settings/esp-flash/`. Total 26 endpoints under `/api/settings/`, making it the largest and most heterogeneous namespace. The route file is already separate (`updates.py`), only the URL prefix is misplaced. |
| C3 | `HealthResponse` exposes 43 flat fields through client-facing API | CONFIRMED — 21 direct fields + 3 nested types (25 fields total). Frontend uses exactly 6 leaf fields. 37 fields are transmitted every poll but never rendered. `build_health_snapshot()` is 80+ lines of aggregation logic inside a route file. `create_health_routes()` takes 5 injected dependencies. |
| C4 | Frontend `AdaptedClient` over-parses fields discarded by `AppState.clients` | CONFIRMED — `AdaptedClient` has 10 fields, `ClientRow` has 8. `sample_rate_hz` and `firmware_version` are parsed every WS tick but never accessed in any feature code. Two nearly-identical interfaces with silent structural-subtyping narrowing. |
| E5 | `LOCATION_CODES` duplicated in Python and TypeScript with no sync guard | CONFIRMED — Python dict (code→label) in `contracts.py` (moving to `locations.py` per Chunk 1) and TypeScript array (keys only) in `constants.ts`. Same 15 codes. No sync mechanism. No test enforces parity. |

## Root Causes

- **C2**: Incremental feature growth — update/flash endpoints were added to the settings page in the UI so they went under the settings URL prefix.
- **C3**: Health endpoint grew as internal observability was bolted onto a simple status check rather than being routed to a debug endpoint.
- **C4**: Two types emerged for the same concept at different layers (adaption vs display) without reconciling them.
- **E5**: `libs/shared/` was inlined and the sync mechanism was never rebuilt for the constants that weren't part of the schema-based sync pipeline.

## Simplification Approach

### C2: Move update/ESP-flash to top-level API namespaces

**Strategy**: Change URL prefixes from `/api/settings/update/` → `/api/update/` and `/api/settings/esp-flash/` → `/api/esp-flash/`. The backend route module (`updates.py`) stays the same file — only prefix constants change. Frontend API calls get updated paths.

**Steps**:
1. In `routes/updates.py`: change route path decorators from `"/api/settings/update/..."` to `"/api/update/..."` and `"/api/settings/esp-flash/..."` to `"/api/esp-flash/..."`
2. In `routes/__init__.py`: if there's prefix mounting, update it
3. In `apps/ui/src/api/settings.ts`: move update/flash functions to a new `apps/ui/src/api/operations.ts`
4. Update all frontend callers that import these functions
5. Update any references in tests, docs, or contracts

### C3: Trim HealthResponse to UI-needed fields

**Strategy**: Rather than a hard trim (which could break operator monitoring), restructure: keep the current full response but extract `build_health_snapshot()` business logic out of the route file into a service method. Reduce the 5-dependency injection to 2. Move detailed diagnostics that the frontend doesn't use into a nested `diagnostics` object so the shape is self-documenting about what's core vs debug.

Actually, on reflection, the simplest approach aligned with "no backward compatibility" policy: just trim the response. Since the repo explicitly says "we own the full codebase end to end" and "no-backward-compatibility policy", we can safely trim unused fields.

**Steps**:
1. Create a slimmed `HealthResponse` with only the fields the frontend uses:
   - `status`, `startup_state`, `processing_state`, `processing_failures`, `degradation_reasons`
   - `persistence.analysis_queue_depth`, `persistence.write_error` (minimal nested)
2. Move `build_health_snapshot()` aggregation logic out of `routes/health.py` into runtime state or a service function
3. Reduce `create_health_routes()` dependency injection from 5 → 2 parameters
4. Keep detailed diagnostics accessible via existing `/api/debug/` namespace if needed
5. Update `api_models.py` to remove trimmed fields from `HealthResponse`

Wait — this is risky. The health endpoint is likely polled by monitoring systems. Let me re-evaluate. 

Actually, the safer approach: move `build_health_snapshot()` out of the route file (it's business logic in a route handler) and reduce the dependency injection. Keep all fields for now. The main simplification is architectural (moving logic to the right layer) rather than breaking API changes.

**Revised Steps**:
1. Move `build_health_snapshot()` from `routes/health.py` to a method on `RuntimeState` or an appropriate service
2. `create_health_routes()` takes 1-2 parameters instead of 5
3. The health route handler becomes a thin HTTP translator
4. Keep `HealthResponse` fields intact for now (defer trimming to a separate, intentional change)

### C4: Unify AdaptedClient and ClientRow

**Strategy**: Delete `ClientRow` interface. Use `AdaptedClient` directly in `AppState.clients`. This makes the contract explicit — all fields are visible and accessible.

**Steps**:
1. In `ui_app_state.ts`: change `clients: ClientRow[]` to `clients: AdaptedClient[]`
2. Import `AdaptedClient` in `ui_app_state.ts`
3. Delete the `ClientRow` interface
4. Update any other references to `ClientRow` across the UI codebase
5. The assignment in `ui_live_transport_controller.ts` now has matching types

### E5: Add LOCATION_CODES sync guard

**Strategy**: Add a hygiene test that verifies the frontend `constants.ts` location codes match the backend `locations.py` LOCATION_CODES keys. This prevents silent drift without removing the frontend fallback (which is needed for offline/initial state).

**Steps**:
1. Add a test in `tests/hygiene/` that:
   - Reads `LOCATION_CODES` from `vibesensor.locations` (after Chunk 1 moves it there)
   - Reads `apps/ui/src/constants.ts` and parses the LOCATION_CODES array
   - Asserts the key sets are identical
2. This is a ~15-line test that makes drift visible in CI

## Implementation Sequence

1. C4 (AdaptedClient/ClientRow — simplest, frontend-only)
2. E5 (sync guard test — quick addition)
3. C2 (URL prefix changes — backend + frontend coordination)
4. C3 (health endpoint restructuring — most complex)

## Dependencies on Other Chunks

- E5 depends on Chunk 1 (E6) which moves LOCATION_CODES to `locations.py`. Must reference the new import path.
- C2 frontend changes require knowing the current API client structure. No dependency on other chunks.
- C3 has no dependency on other chunks.
- C4 has no dependency on other chunks.

## Risks and Tradeoffs

- **C2**: Breaking URL change. All frontend API calls must be updated atomically. Tests that use these URLs must also update. The repo's "no backward compatibility" policy permits this.
- **C3**: Moving `build_health_snapshot()` out of the route file changes the architecture. Must ensure the method still has access to all needed data.
- **C4**: Very low risk. TypeScript structural typing means this is a type annotation change only.
- **E5**: Zero risk — adds a test, changes no production code.

## Validation Steps

1. `cd apps/ui && npm run typecheck && npm run build` — frontend type checking
2. `pytest -q apps/server/tests/api/` — API tests
3. `pytest -q apps/server/tests/hygiene/` — hygiene tests
4. `make lint && make typecheck-backend`
5. Full suite to catch any integration issues

## Required Documentation Updates

- Update API references in docs/ if they mention `/api/settings/update/` or `/api/settings/esp-flash/`
- Update `docs/ai/repo-map.md` route section

## Required AI Instruction Updates

- Add to frontend instructions: "Use a single canonical type for data that flows from WS parsing to state to rendering. Do not create parallel interface definitions for the same data."
- Add to backend instructions: "Keep API namespaces cohesive by domain (settings for config, operations for jobs). Do not mix persistent configuration endpoints with ephemeral job-management endpoints."

## Required Test Updates

- Update any API tests that use `/api/settings/update/` or `/api/settings/esp-flash/` URLs
- Add `test_location_codes_sync.py` in hygiene/
- Update frontend smoke tests if they reference the changed URLs

## Simplification Crosswalk

| Finding | Validation | Root Cause | Steps | Areas Changed | What's Removed | Verification |
|---------|-----------|------------|-------|---------------|----------------|--------------|
| C1 | DROPPED (justified wizard pattern) | N/A | N/A | N/A | N/A | N/A |
| C2 | CONFIRMED (26 endpoints under /api/settings/, 9 are operations not settings) | Incremental feature growth under wrong namespace | Change URL prefixes, split frontend API module | routes/updates.py, frontend api/ | 0 code removed, URLs clarified | API tests pass with new URLs |
| C3 | CONFIRMED (80+ lines of business logic in route file, 5-dependency injection) | Health endpoint grew as observability bolt-on | Move aggregation logic to service, reduce injection | routes/health.py, runtime or service layer | ~80 lines moved out of route file | Health endpoint returns same data, tests pass |
| C4 | CONFIRMED (2 near-identical interfaces with silent field loss) | Types diverged across layers | Delete ClientRow, use AdaptedClient in AppState | ui_app_state.ts, server_payload.ts | 1 interface (~10 lines) | Frontend builds, types check |
| E5 | CONFIRMED (15 codes duplicated, no sync) | libs/shared removal left no sync mechanism | Add hygiene test asserting parity | tests/hygiene/ | 0 code removed, drift guard added | Test passes, catches future drift |
