# Chunk 4: Type System, API & Data Flow

## Mapped Findings

- [5.1] Parallel TypedDict/Pydantic dual-layer type system (at least 6 mirror pairs)
- [5.2] /api/health is 65-70-line business logic function in a route handler
- [5.3] Redundant speed-override endpoint + /api/analysis-settings URL inconsistency
- [3.1] VibrationStrengthMetrics type-erased into nested dict, then re-parsed field by field
- [3.2] Dual ClientMetrics ownership in processor buffer AND ClientRecord
- [3.3] UI WS pipeline defensive re-parse with AdaptedSpectrum → SpectrumClientData identity remap

## Validation Outcomes

### [5.1] CONFIRMED (HIGH confidence)
At least 6 field-for-field mirror pairs exist between TypedDict definitions in `payload_types.py`/`backend_types.py` and Pydantic models in `api_models.py`:
- `HealthDataLossPayload` ↔ `HealthDataLossResponse` (6 fields)
- `HealthPersistencePayload` ↔ `HealthPersistenceResponse` (14 fields)
- `SpeedSourcePayload` ↔ `SpeedSourceResponse` (5 fields)
- `SpeedSourceStatusPayload` ↔ `SpeedSourceStatusResponse` (18 fields)
- `SensorConfigPayload` ↔ `SensorConfigResponse` (2 fields)
- `CarConfigPayload` ↔ `CarResponse` (5 fields)

**Revised scope**: Not all TypedDicts can be eliminated. WS payload TypedDicts (`LiveWsPayload`, `SpectraPayload`, etc.) serve a real purpose — they annotate dict construction for WebSocket wire payloads where Pydantic is not used. Only the HTTP response-mirroring TypedDicts in `payload_types.py` and `backend_types.py` should be removed. The WS TypedDicts stay.

### [5.2] CONFIRMED (HIGH confidence)
Health route handler has ~65-70 lines of business logic: builds `degradation_reasons` with 15+ conditional branches, computes `status` field, constructs nested response. Receives 5 injected dependencies (more than any other route module). The logic is pure business logic with zero HTTP concerns — it's untestable without a FastAPI test client.

### [5.3] CONFIRMED (HIGH confidence)
Both `POST /api/settings/speed-source` and `POST /api/simulator/speed-override` call the same private function `_apply_speed_source_update(req)`. The speed-override endpoint is a named alias with zero additional behavior. `/api/analysis-settings` breaks the `/api/settings/*` prefix convention used by all other settings endpoints.

### [3.1] CONFIRMED (HIGH confidence)
`VibrationStrengthMetrics` is stored in two places simultaneously:
1. `buf.latest_strength_metrics` (typed, direct)
2. `metrics["combined"]["strength_metrics"]` (type-erased, nested in generic dict)

`sample_builder.extract_strength_data()` receives the generic dict path and re-parses every field with `_safe_float()` guards, converting back to the same fields that were already typed at computation time.

### [3.2] CONFIRMED (MEDIUM-HIGH confidence)
Same `ClientMetrics` dict is written to both:
1. `ClientBuffer.latest_metrics` (via `buffer_store.store_metrics_result()`)
2. `ClientRecord.latest_metrics` (via `processing_loop → registry.set_latest_metrics()`)

Different consumers read from different copies. The dual write creates cross-subsystem coupling.

**Revised scope**: Removing `latest_metrics` from `ClientRecord` requires changing how `snapshot_for_api()` assembles the WS broadcast payload. This is a deeper refactor that could destabilize the hot path. **Decision**: Keep this finding but implement it as a targeted change: make `snapshot_for_api()` accept a `metrics_by_client` parameter instead of reading from `ClientRecord`. Remove `latest_metrics` from `ClientRecord` and the `set_latest_metrics` method. Remove the cross-subsystem write in `_run_tick()`.

### [3.3] CONFIRMED (HIGH confidence)
`AdaptedSpectrum` (in `server_payload.ts`) and `SpectrumClientData` (in `ui_app_state.ts`) are field-for-field identical: `{ freq: number[], combined: number[], strength_metrics: StrengthMetricsPayload }`. The transport controller does an explicit field-by-field identity spread from one to the other. The `adaptServerPayload()` function manually re-validates ~15 field definitions that are already available as generated types in `ws_payload_types.ts`.

**Revised scope**: Full elimination of the defensive parsing layer is high-risk for the UI. **Decision**: Keep the schema-version check. Unify `AdaptedSpectrum` and `SpectrumClientData` into a single type. Remove the identity remap. Simplify `adaptServerPayload()` to use `as` type assertion after schema version check, keeping only the minimal business-logic transformations (location_code fallback, etc.) rather than full field-by-field re-parse.

## Root Complexity Drivers

1. **Type-definition sprawl**: Multiple files define the same shapes for different layers (internal TypedDict, external Pydantic). No tooling enforces sync.

2. **Route-as-service pattern**: Business logic that should be in a service class lives inside route handlers, making it untestable without HTTP infrastructure.

3. **Endpoint accumulation**: New endpoints were added alongside existing ones without consolidating the redundant older ones.

4. **Type-erasure through dict nesting**: Typed objects are embedded in generic dicts to pass through a single pipeline, then manually re-extracted downstream.

5. **Defensive-everything frontend**: The UI treats backend payloads as fully untrusted, re-validating every field despite owning both ends.

## Simplification Strategy

### Step 1: Remove TypedDict mirrors of Pydantic models

**Implementation:**
1. Identify all TypedDicts in `payload_types.py` and `backend_types.py` that mirror Pydantic models in `api_models.py`
2. For each mirror pair:
   a. Check all callers that construct the TypedDict
   b. Have those callers return the Pydantic model directly, or a plain dict that the route handler wraps in Pydantic
   c. Delete the TypedDict definition
3. TypedDicts to DELETE from `payload_types.py`:
   - `HealthDataLossPayload` (→ use `HealthDataLossResponse` or plain dict)
   - `HealthPersistencePayload` (→ use `HealthPersistenceResponse` or plain dict)
4. TypedDicts to DELETE from `backend_types.py`:
   - `SpeedSourcePayload` (→ use `SpeedSourceResponse`)
   - `SpeedSourceStatusPayload` (→ use `SpeedSourceStatusResponse`)
   - `SensorConfigPayload` (→ use `SensorConfigResponse`)
   - `CarConfigPayload` (→ use `CarResponse`)
5. TypedDicts to KEEP in `payload_types.py`:
   - `LiveWsPayload`, `SpectraPayload`, `ClientApiRow`, `StrengthMetricsPayload` — these annotate WS dict construction, not HTTP responses
6. If `backend_types.py` becomes empty or has only type aliases, fold remaining content into `api_models.py` or `payload_types.py`
7. Update all imports accordingly

### Step 2: Extract /api/health business logic to a service

**Implementation:**
1. Create a function `build_health_snapshot()` (either in a new `runtime/health_service.py` or in the existing `runtime/health.py` if it exists) that:
   - Accepts the 5 subsystem references
   - Performs the degradation-reason enumeration (15+ conditional branches)
   - Returns a dict or a `HealthSnapshot` dataclass
2. The health route handler becomes ~5 lines:
   ```python
   @router.get("/api/health")
   async def health() -> HealthResponse:
       snapshot = build_health_snapshot(loop_state, health_state, processor, registry, metrics_logger)
       return HealthResponse(**snapshot)
   ```
3. Add unit tests for `build_health_snapshot()` that don't require FastAPI test client
4. The route factory `create_health_routes` still receives the 5 dependencies and passes them to the extracted function — no change to the wiring surface

**NOTE**: This step pairs well with Step 1 — once the TypedDict mirrors for health payloads are removed, the health service can return plain dicts or Pydantic models directly.

### Step 3: Remove redundant speed-override endpoint and fix URL prefix

**Implementation:**
1. Delete `POST /api/simulator/speed-override` endpoint from `routes/settings.py`
2. Update any UI/simulator code that calls `/api/simulator/speed-override` to use `/api/settings/speed-source` instead
3. Move `/api/analysis-settings` (GET and POST) to `/api/settings/analysis`:
   - `GET /api/analysis-settings` → `GET /api/settings/analysis`
   - `POST /api/analysis-settings` → `POST /api/settings/analysis`
4. Update UI/frontend code to use the new URL prefix
5. Update any test code that references these endpoints

### Step 4: Fix VibrationStrengthMetrics type-erasure

**Implementation:**
1. In `processing/compute.py`: Keep storing `strength_metrics` in both `buf.latest_strength_metrics` (typed) AND `combined_metrics["strength_metrics"]` (for WS broadcast compatibility)
2. In `metrics_log/sample_builder.py`: Instead of calling `extract_strength_data()` on the generic `metrics` dict:
   a. Pass `latest_strength_metrics: VibrationStrengthMetrics` directly from the buffer or from the metrics result
   b. Access fields directly: `strength_metrics["vibration_strength_db"]` instead of `_safe_float(nested_dict, "vibration_strength_db")`
   c. Eliminate `extract_strength_data()` function and the `_safe_float()` re-validation
3. The key change: `build_sample_records()` needs access to the typed `VibrationStrengthMetrics`, not just the generic `ClientMetrics` dict

**Dependency**: This step intersects with [3.2] — if `ClientRecord.latest_metrics` is the current source for sample_builder, and we're removing that in step 5, we need to coordinate the data source.

### Step 5: Remove dual ClientMetrics ownership

**Implementation:**
1. Remove `latest_metrics` field from `ClientRecord` in `registry.py`
2. Remove `set_latest_metrics()` method from registry
3. Remove the cross-subsystem write loop in `processing_loop._run_tick()`:
   ```python
   # DELETE this loop:
   for client_id, metrics in metrics_by_client.items():
       self._ingress.registry.set_latest_metrics(client_id, metrics)
   ```
4. Modify `snapshot_for_api()` to accept `metrics_by_client: dict[str, ClientMetrics]` as a parameter
5. The WS broadcast pass calls `snapshot_for_api(metrics_by_client)` — the metrics come from the processing loop's most recent `compute_all()` result, passed through to the broadcast
6. Update `sample_builder` to receive metrics from the processing result, not from the registry

### Step 6: Simplify UI WS pipeline

**Implementation:**
1. Unify `AdaptedSpectrum` and `SpectrumClientData` into a single type. Keep `SpectrumClientData` as the canonical name, delete `AdaptedSpectrum`
2. In `ui_live_transport_controller.ts`, remove the identity remap — assign spectrum data directly instead of field-by-field spread
3. Simplify `adaptServerPayload()` in `server_payload.ts`:
   - Keep the `EXPECTED_SCHEMA_VERSION` check as the meaningful safety net
   - Replace the manual field-by-field re-validation functions with a type assertion: `const payload = data as LiveWsPayload` (using the generated type)
   - Keep only true business-logic transformations (location_code fallback, etc.)
   - Remove `parseClient()`, `parseSpectra()`, `parseStrengthMetrics()` manual parsers (or reduce them significantly)
4. Update any other UI code that referenced `AdaptedSpectrum`

## Dependencies on Other Chunks

- **Chunk 3** should complete first — the analysis/findings/ flattening and Protocol removal may affect some of the same files
- Steps within this chunk have ordering dependencies:
  - Step 1 (TypedDict removal) before Step 2 (health extraction) — cleaner if health sub-models are already simplified
  - Step 4 (strength metrics) and Step 5 (dual metrics) should be done together — they share the data flow
  - Step 6 (UI WS) is independent of steps 1-5

## Risks and Tradeoffs

- **TypedDict removal**: Callers that currently type-annotate internal dicts with these TypedDicts lose that annotation. Mitigation: the Pydantic model at the HTTP boundary provides the same validation. Internal code can use plain `dict` or annotate with the Pydantic model type.
- **Health logic extraction**: Creating a new file/function for ~65 lines of logic adds a file. Mitigation: the benefit (unit-testability, thin route) outweighs the cost.
- **API endpoint changes**: Removing `/api/simulator/speed-override` and moving `/api/analysis-settings` are breaking API changes. Per the repo's no-backward-compatibility policy, this is acceptable.
- **Dual metrics removal**: Changing how `snapshot_for_api()` receives metrics affects the hot WS broadcast path. Must be thoroughly tested.
- **UI WS simplification**: Removing defensive parsing could mask backend bugs that corrupt payload shapes. Mitigation: the schema-version check remains; the generated TypeScript types serve as the compile-time safety net; the backend's Python-side validation at point of construction covers runtime safety.

## Validation Steps

1. `pytest -q apps/server/tests/` — all backend tests pass
2. `make lint` and `make typecheck-backend` — clean
3. `cd apps/ui && npm run typecheck && npm run build` — frontend compiles
4. `pytest -q apps/server/tests/routes/` — route tests pass
5. `pytest -q apps/server/tests/integration/` — integration tests pass
6. `pytest -q apps/server/tests/metrics_log/` — metrics tests pass
7. Docker build and run: verify WebSocket data flow works end-to-end

## Required Documentation Updates

- `docs/ai/repo-map.md`: Update any references to backend_types.py if it's eliminated
- `docs/protocol.md`: Update if it references endpoint URLs that changed
- `docs/metrics.md`: Update if it references the strength_metrics data flow

## Required AI Instruction Updates

- `.github/instructions/backend.instructions.md`: Update to reflect simplified type system:
  - Remove `backend_types.py` from the type gate list if eliminated
  - Note that WS payload TypedDicts stay in `payload_types.py`
  - Note that HTTP response types use Pydantic models only (no TypedDict mirrors)
- `.github/instructions/general.instructions.md`: Add guidance:
  - Do not create TypedDict mirrors of Pydantic models
  - Route handlers should be thin HTTP translators, not business logic containers
  - Do not create duplicate API endpoints for the same operation
  - Avoid re-validating data that was already validated at the point of construction

## Required Test Updates

- Add unit tests for `build_health_snapshot()` function
- Update route tests that reference deleted endpoints
- Update tests that use TypedDict type annotations from deleted definitions
- Add/keep tests validating the strength_metrics data flow

## Simplification Crosswalk

### [5.1] TypedDict/Pydantic dual layer
- **Validation**: CONFIRMED (6+ mirror pairs)
- **Root cause**: Separate "internal" and "external" type layers with no actual boundary
- **Steps**: Delete 6+ TypedDict mirrors, update callers, potentially fold backend_types.py
- **Code areas**: payload_types.py, backend_types.py, api_models.py, all importing modules
- **What can be removed**: ~200 lines of duplicate type definitions
- **Verification**: mypy passes, routes still serialize correctly

### [5.2] Health route business logic
- **Validation**: CONFIRMED (65-70 lines of policy logic)
- **Root cause**: Business logic in route handler
- **Steps**: Extract to build_health_snapshot(), thin route handler
- **Code areas**: routes/health.py, new health service function
- **What can be removed**: 60+ lines moved out of route handler
- **Verification**: Health endpoint returns same data, new unit tests pass

### [5.3] Redundant speed-override + URL prefix
- **Validation**: CONFIRMED
- **Root cause**: Endpoint accumulation without consolidation
- **Steps**: Delete redundant endpoint, move analysis-settings URL
- **Code areas**: routes/settings.py, UI fetch calls
- **What can be removed**: 1 endpoint, 1 handler function
- **Verification**: Settings API works, UI uses correct URLs

### [3.1] VibrationStrengthMetrics type-erasure
- **Validation**: CONFIRMED
- **Root cause**: Typed data buried in generic dict, re-parsed downstream
- **Steps**: Pass typed object directly to sample_builder, delete extract_strength_data()
- **Code areas**: sample_builder.py, compute.py, buffer_store.py
- **What can be removed**: extract_strength_data(), _safe_float() calls (~60 lines)
- **Verification**: Metrics logging produces identical output

### [3.2] Dual ClientMetrics ownership
- **Validation**: CONFIRMED
- **Root cause**: Cross-subsystem copy for convenience
- **Steps**: Remove from ClientRecord, pass through parameters, update snapshot_for_api()
- **Code areas**: registry.py, processing_loop.py, ws_broadcast
- **What can be removed**: ClientRecord.latest_metrics field, set_latest_metrics(), cross-subsystem write loop
- **Verification**: WS broadcast works, API snapshots correct

### [3.3] UI WS pipeline
- **Validation**: CONFIRMED
- **Root cause**: Defensive parsing + duplicate type definitions
- **Steps**: Unify types, remove identity remap, simplify parsePayload
- **Code areas**: server_payload.ts, ui_app_state.ts, ui_live_transport_controller.ts
- **What can be removed**: AdaptedSpectrum type, identity remap, manual parsers (~120-150 lines)
- **Verification**: UI builds, WebSocket data displayed correctly
