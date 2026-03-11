# Chunk 2: API Surface & Type System Simplification

## Mapped Findings

| ID | Original Finding | Source Subagents | Validation Result |
|----|-----------------|------------------|-------------------|
| B1 | TypedDict Required/Optional base-class inheritance split (FindingRequired, _SummaryDataRequired, _CarConfigPayloadRequired) | Abstraction | **VALIDATED** — FindingRequired at _types.py:104 is used only as base class for Finding. _SummaryDataRequired at _types.py:265 is used only as base for SummaryData. _CarConfigPayloadRequired at backend_types.py:28 is base for CarConfigPayload. The codebase already uses NotRequired (imported in backend_types.py line 5). |
| B3 | Private Pydantic base classes _FrozenBase and _ExtraAllowBase hiding model_config via inheritance | Abstraction | **VALIDATED** — _FrozenBase confirmed at api_models.py:88, used by 11+ request models. _ExtraAllowBase confirmed at api_models.py:94. Both add a single model_config attribute that is invisible at each model's definition site. |
| E1 | ClientApiRow broadcasts 15 debug-only fields on every WS tick | API & Interface | **VALIDATED** — ClientApiRow at payload_types.py has 23 fields. Frontend parseClient() in server_payload.ts uses ~10 fields. data_addr, control_addr, last_ack_*, reset_*, duplicates_received, parse_errors, server_queue_drops, queue_overflow_drops, timing_health, latest_metrics are never consumed by the UI. |
| E2 | HealthResponse is a backend diagnostic dump with ~60% unused fields | API & Interface | **VALIDATED** — HealthResponse has 22 top-level fields + 3 nested sub-models. update_feature.ts is the only UI consumer, accessing only ~8 fields. HealthIntakeStatsResponse (5 fields) has zero UI consumers. |
| E3 | Mutation responses typed through 3 layers but discarded by frontend | API & Interface | **VALIDATED** — setClientLocation(), identifyClient(), removeClient() all return Promise<void>. The Pydantic response models (SetClientLocationResponse, IdentifyResponse, RemoveClientResponse) are defined, schema-exported, and TS-typed but never read. |

## Root Causes

1. **Pre-NotRequired TypedDict pattern**: The Required base + total=False subclass pattern was the standard approach before Python 3.11's NotRequired. The codebase evolved past the need but never cleaned up the pattern.
2. **DRY reflex over readability**: _FrozenBase saves one line per model but hides the frozen constraint behind inheritance, requiring readers to jump to the base class.
3. **Debug-visibility creep**: ClientApiRow grew to serve both dashboard display and on-device diagnostics without separating the two concerns. Each new diagnostic field was added to the same dict.
4. **OpenAPI-first response discipline**: FastAPI's response_model encourages typed responses even for fire-and-forget mutations. The generated TS types create an illusion of a live API contract that the frontend silently ignores.

## Relevant Code Paths

### TypedDict Splits
- `vibesensor/analysis/_types.py` — FindingRequired (L104) + Finding (L114), _SummaryDataRequired (L265) + SummaryData (L309)
- `vibesensor/backend_types.py` — _CarConfigPayloadRequired (L28) + CarConfigPayload (L33)

### Pydantic Bases
- `vibesensor/api_models.py` — _FrozenBase (L88), _ExtraAllowBase (L94), 11+ consuming request models

### WS Payload
- `vibesensor/payload_types.py` — ClientApiRow (23 fields), ClientMetrics, AxisMetrics, AxisPeak, CombinedMetrics, TimingHealthPayload (all nested types)
- `vibesensor/registry.py` — _client_api_row() assembles all 25 fields unconditionally
- `apps/ui/src/server_payload.ts` — parseClient() extracts ~10 fields
- `apps/ui/src/contracts/ws_payload_types.ts` — generated types including 6 unused type definitions

### Health Response
- `vibesensor/api_models.py` — HealthResponse, HealthDataLossResponse, HealthPersistenceResponse, HealthIntakeStatsResponse
- `vibesensor/routes/health.py` — build_health_snapshot() collects from 5 services
- `apps/ui/src/app/features/update_feature.ts` — reads ~8 of ~47 fields

### Mutation Responses
- `vibesensor/api_models.py` — IdentifyResponse, SetClientLocationResponse, RemoveClientResponse
- `apps/ui/src/api/clients.ts` — all return Promise<void>

## Simplification Approach

### Step 1: Flatten TypedDict Required/Optional splits

For each split pair, merge into a single TypedDict using NotRequired:

1. **Finding**: Merge FindingRequired fields into Finding as Required[T] markers, delete FindingRequired
2. **SummaryData**: Merge _SummaryDataRequired fields into SummaryData, delete _SummaryDataRequired
3. **CarConfigPayload**: Already uses NotRequired for variant. Merge _CarConfigPayloadRequired into CarConfigPayload, delete _CarConfigPayloadRequired

### Step 2: Inline Pydantic model_config

Remove _FrozenBase and _ExtraAllowBase. Add `model_config = ConfigDict(frozen=True)` directly to each request model that inherited _FrozenBase. Add `model_config = ConfigDict(extra="allow")` to models that inherited _ExtraAllowBase.

### Step 3: Slim ClientApiRow for WS broadcast

1. Create `ClientWsRow` with only the ~10 fields the UI actually consumes: id, mac_address, name, connected, location, firmware_version, sample_rate_hz, frame_samples, last_seen_age_ms, frames_total, dropped_frames
2. Add a `snapshot_for_ws()` method to registry that returns ClientWsRow
3. Keep full ClientApiRow for the HTTP GET /api/clients endpoint (diagnostic use)
4. Update LiveWsPayload to use ClientWsRow instead of ClientApiRow
5. Update the WS broadcast path to use snapshot_for_ws()
6. Regenerate TS contracts — the unused TS types (AxisMetrics, CombinedMetrics, TimingHealthPayload, etc.) will be removed from ws_payload_types.ts

### Step 4: Slim HealthResponse for UI

1. Split HealthResponse into a slim `HealthUiResponse` (8 fields the UI reads) used by the /api/health endpoint
2. Move the full diagnostic payload to a /api/debug/health endpoint using the existing HealthResponse or a raw dict
3. Keep HealthDataLossResponse (all 6 fields are used by UI)
4. Slim HealthPersistenceResponse from 14 to 5 fields for the UI version
5. Remove HealthIntakeStatsResponse (zero UI consumers) from the UI-facing model

### Step 5: Simplify mutation responses

1. Change setClientLocation, identifyClient, removeClient routes to return 204 No Content instead of typed response models
2. Delete IdentifyResponse, SetClientLocationResponse, RemoveClientResponse from api_models.py
3. Remove from __all__ and generated schema
4. Update frontend API functions (they already discard the response, so no logic change needed)

### Step 6: Regenerate contracts

Run the contract sync pipeline to update TypeScript types reflecting the slimmer API surface.

## Simplification Crosswalk

### B1 → TypedDict base-class splits
- **Validation**: Confirmed — 3 split pairs, all using pre-NotRequired pattern, NotRequired already imported
- **Root cause**: Pre-Python 3.11 pattern not cleaned up
- **Steps**: Merge each Required base into its subclass using NotRequired/Required markers
- **Removable**: FindingRequired, _SummaryDataRequired, _CarConfigPayloadRequired
- **Verification**: All imports of Finding, SummaryData, CarConfigPayload still work; mypy passes

### B3 → Pydantic hidden bases
- **Validation**: Confirmed — 2 private bases, 11+ consumers
- **Root cause**: DRY over readability
- **Steps**: Delete _FrozenBase and _ExtraAllowBase, inline model_config on each consumer
- **Removable**: _FrozenBase, _ExtraAllowBase
- **Verification**: All API model tests pass, schema unchanged

### E1 → ClientApiRow WS bloat
- **Validation**: Confirmed — 15 unused fields broadcast per tick
- **Root cause**: Single dict serves dashboard + diagnostics
- **Steps**: Create ClientWsRow (10 fields), use in WS payload, keep full ClientApiRow for HTTP
- **Removable**: 6 unused TS types from contracts
- **Verification**: UI renders correctly, WS payload smaller, /api/clients still returns full data

### E2 → HealthResponse bloat
- **Validation**: Confirmed — ~28 of ~47 fields unused by frontend
- **Root cause**: Single endpoint serves UI + diagnostics
- **Steps**: Slim HealthResponse for UI, move full dump to debug endpoint
- **Removable**: HealthIntakeStatsResponse, ~14 fields from HealthResponse, ~9 from HealthPersistenceResponse
- **Verification**: Update feature UI still works, debug endpoint returns full data

### E3 → Mutation response waste
- **Validation**: Confirmed — 3 response models never read by frontend
- **Root cause**: OpenAPI response_model discipline applied to fire-and-forget mutations
- **Steps**: Return 204 No Content, delete 3 response models
- **Removable**: IdentifyResponse, SetClientLocationResponse, RemoveClientResponse
- **Verification**: Frontend mutation calls still succeed (they already ignore responses)

## Dependencies on Other Chunks

- Chunk 1 consolidates analysis/ files including _types.py where FindingRequired lives. Chunk 1 moves files but doesn't change TypedDict patterns. This chunk changes the TypedDict pattern without moving files. No conflict.
- Chunk 5 handles contract sync pipeline simplification. This chunk uses the existing pipeline to regenerate; Chunk 5 simplifies the pipeline itself.

## Risks and Tradeoffs

1. **ClientApiRow split**: External tooling or scripts that consume /ws may break if they read debug fields. Risk is low — the WS protocol is internal.
2. **HealthResponse split**: Any external monitoring consuming /api/health will see fewer fields. Mitigated: move full data to /api/debug/health.
3. **204 No Content**: Any client that inspects mutation responses will get none. Current frontend doesn't, but hypothetical future consumers might.

## Validation Steps

1. `pytest -q apps/server/tests/` — full test suite passes
2. `make lint` — clean
3. `make typecheck-backend` — clean
4. `cd apps/ui && npm run typecheck && npm run build` — frontend builds
5. Contract sync produces expected slimmer types
6. Verify WS payload in browser devtools shows only 10 client fields

## Required Documentation Updates

- docs/protocol.md — update WS payload field documentation if it references ClientApiRow
- docs/ai/repo-map.md — update if it references health/client API specifics

## Required AI Instruction Updates

- Add to .github/instructions/general.instructions.md: "Do not add diagnostic/debug fields to UI-facing payload types. Use separate debug endpoints."
- Add: "Do not create response models for fire-and-forget mutations. Use 204 No Content."

## Required Test Updates

- Update tests that construct ClientApiRow with all 25 fields to use the appropriate type
- Update tests that test health endpoint response shape
- May need to add tests for /api/debug/health endpoint
