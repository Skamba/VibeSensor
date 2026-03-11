# Chunk 2: Data Payload & Type Safety Simplification

## Mapped Findings

| ID | Original Title | Validation | Status |
|----|---------------|------------|--------|
| C1/E1 | ClientApiRow.latest_metrics serialized on every WS tick, UI discards | **Validated** — `ws_broadcast.py` calls `all_latest_metrics()` per tick; `parseClient()` in UI server_payload.ts reads 10 flat fields, ignores latest_metrics entirely; UI gets strength metrics from `spectra.clients[id]` instead | Proceed |
| C2 | extract_strength_data() dismantles typed struct into opaque 6-tuple | **Validated** — Returns `tuple[dict, float|None, str|None, float|None, float|None, list]` from sample_builder.py; VibrationStrengthMetrics TypedDict already exists with all needed fields | Proceed |
| C3 | resolve_speed_context() returns 6-tuple with pass-through values | **Validated** — Returns 6 values, 2 of which (final_drive_ratio, gear_ratio) are read from settings and returned unchanged to caller who already has settings | Proceed |
| D3 | JSONL-era record_type/schema_version in SensorFrame | **Validated** — `record_type="sample"` and `schema_version="v2-jsonl"` set on every recording tick in sample_builder.py, silently discarded by `_V2_TYPED_COLS` in _samples.py | Proceed |

## Root Complexity Drivers

1. **WS payload carries dead weight**: `ClientApiRow` was designed as a single unified type for both REST and WS, causing per-tick serialization of data the UI never reads.
2. **Type-erased extraction**: `extract_strength_data()` re-extracts typed data through string-keyed dictionary access, returning positional tuples that drop type information.
3. **Pass-through return values**: Functions return values the caller already holds, adding positional slots that increase confusion risk.
4. **Legacy format fields embedded in domain model**: JSONL-era routing metadata persists in the live recording path despite being ignored by the SQLite persistence layer.

## Relevant Code Paths

### C1/E1: WS payload ClientApiRow
- `apps/server/vibesensor/runtime/ws_broadcast.py` — `_build_shared_payload()` calls `all_latest_metrics()`
- `apps/server/vibesensor/payload_types.py` — `ClientApiRow` type with 22 fields
- `apps/server/vibesensor/registry.py` — `snapshot_for_api()` builds `ClientApiRow` with metrics
- `apps/ui/src/server_payload.ts` — `parseClient()` reads 10 fields, ignores metrics
- `apps/server/vibesensor/routes/clients.py` — REST endpoint also uses `ClientApiRow`

### C2 + C3: Sample builder tuples
- `apps/server/vibesensor/metrics_log/sample_builder.py` — `extract_strength_data()`, `resolve_speed_context()`, `build_sample_records()`
- `apps/server/vibesensor/core/vibration_strength.py` — `VibrationStrengthMetrics` TypedDict

### D3: JSONL-era fields
- `apps/server/vibesensor/metrics_log/sample_builder.py` — sets `record_type`, `schema_version`
- `apps/server/vibesensor/domain_models.py` — `SensorFrame`, `RUN_SCHEMA_VERSION`
- `apps/server/vibesensor/history_db/_samples.py` — `_V2_TYPED_COLS` (excludes these fields)
- `apps/server/vibesensor/runlog.py` — JSONL reader does use `record_type`

## Simplification Approach

### C1/E1: Slim WS client payload

**Strategy**: Create a lightweight `WsClientRow` TypedDict with only the 10 fields `parseClient()` uses. Keep `ClientApiRow` for the REST `/api/clients` endpoint. The WS broadcast path skips `all_latest_metrics()`.

**Steps**:
1. Define `WsClientRow` TypedDict in `payload_types.py` with fields: `id`, `name`, `connected`, `mac_address`, `location_code`, `last_seen_age_ms`, `dropped_frames`, `frames_total`, `sample_rate_hz`, `firmware_version`
2. Add `ws_snapshot()` method to `ClientRegistry` that returns `list[WsClientRow]` — same as `snapshot_for_api()` but without metrics
3. In `ws_broadcast.py::_build_shared_payload()`, use `registry.ws_snapshot()` instead of `snapshot_for_api()` with `all_latest_metrics()`
4. Remove the `all_latest_metrics()` call from the WS hot path
5. Update `LiveWsPayload` type to use `list[WsClientRow]` for clients
6. Keep `ClientApiRow` and `snapshot_for_api()` for the REST endpoint

### C2: Replace extract_strength_data 6-tuple

**Strategy**: Return a small TypedDict or dataclass instead of a positional tuple. Alternatively, simplify by extracting fields inline in `build_sample_records()`.

**Steps**:
1. Define a `StrengthExtraction` TypedDict with named fields: `strength_metrics`, `vibration_strength_db`, `strength_bucket`, `strength_peak_amp_g`, `strength_floor_amp_g`, `top_peaks`
2. Modify `extract_strength_data()` to return `StrengthExtraction` instead of a 6-tuple
3. Update `build_sample_records()` to access fields by name instead of positional unpacking
4. Or simpler: inline the extraction into `build_sample_records()` since it's the only caller, making `extract_strength_data()` unnecessary

### C3: Simplify resolve_speed_context return

**Strategy**: Remove pass-through values from the return. Return only the 4 computed values.

**Steps**:
1. Remove `final_drive_ratio` and `gear_ratio` from `resolve_speed_context()` return
2. Return a 4-element named result or TypedDict: `speed_kmh`, `gps_speed_kmh`, `speed_source`, `engine_rpm_estimated`
3. In `build_sample_records()`, read `final_drive_ratio` and `gear_ratio` directly from `analysis_settings_snapshot` instead of from the tuple

### D3: Remove JSONL-era fields from live recording path

**Strategy**: Make `record_type` and `schema_version` optional on `SensorFrame`. Stop setting them in `build_sample_records()`. Keep them in the JSONL read/write path.

**Steps**:
1. In `domain_models.py`, make `record_type` and `schema_version` optional with `None` default on `SensorFrame`
2. In `sample_builder.py::build_sample_records()`, stop setting `record_type="sample"` and `schema_version="v2-jsonl"` on each frame
3. In `runlog.py`, continue setting these fields when writing JSONL (the JSONL path genuinely needs them)
4. Review `RUN_SCHEMA_VERSION` constant — if only used in JSONL metadata creation, make it local to that usage
5. Verify `_V2_TYPED_COLS` in `_samples.py` doesn't need any changes (it already excludes these fields)

## Dependencies on Other Chunks

- No dependencies on earlier chunks. This chunk is independent.
- Chunk 3 (D1, D2) also touches persistence/schema but on different code paths.

## Risks and Tradeoffs

1. **C1/E1**: The REST `/api/clients` endpoint keeps full `ClientApiRow`. If any future WS consumer needs per-client metrics, they'd access them via `spectra.clients[id]` which already exists.
2. **C2**: Inlining `extract_strength_data` is simpler but makes `build_sample_records` longer. A named return type is the better balance.
3. **D3**: Making `record_type`/`schema_version` optional on `SensorFrame` means JSONL-reading code should handle `None`. Check `read_jsonl_run()` and `normalize_sample_record()`.

## Validation Steps

1. `pytest -q apps/server/tests/processing/` — processor and sample builder tests
2. `pytest -q apps/server/tests/integration/` — integration tests
3. `pytest -q apps/server/tests/report/` — report tests that use sample data
4. `make lint && make typecheck-backend`
5. Verify UI still works with the slimmer WS payload (docker compose build + up)

## Required Documentation Updates

- `docs/ai/repo-map.md` — update ws_broadcast description
- `docs/protocol.md` — if WS payload contract is documented there

## Required AI Instruction Updates

- Add guardrail: "Do not share heavyweight REST response types as WS broadcast payloads. WS payloads should contain only fields the UI actually consumes."
- Add guardrail: "Prefer named return types (TypedDict/dataclass) over positional tuples with 4+ elements."

## Required Test Updates

- Update WS payload tests to expect slim `WsClientRow` instead of full `ClientApiRow`
- Update sample builder tests for new return types
- Verify JSONL round-trip tests still pass with optional fields

## Simplification Crosswalk

### C1/E1: ClientApiRow.latest_metrics on WS tick
- **Validation**: Confirmed. `parseClient()` reads 10 fields, ignores rest.
- **Root cause**: Shared type between REST and WS without differentiation.
- **Steps**: Create WsClientRow, add ws_snapshot, skip all_latest_metrics in WS path.
- **Code areas**: payload_types.py, registry.py, ws_broadcast.py
- **Removed**: Per-tick all_latest_metrics() call, dead payload data
- **Verification**: `pytest -q apps/server/tests/ && npm run build`

### C2: extract_strength_data opaque 6-tuple
- **Validation**: Confirmed. 6-tuple with type-erased extraction.
- **Root cause**: Defensive Mapping[str, object] handling instead of using typed struct.
- **Steps**: Return named type or inline extraction.
- **Code areas**: sample_builder.py
- **Removed**: Positional tuple contract
- **Verification**: `pytest -q apps/server/tests/processing/`

### C3: resolve_speed_context pass-through tuple
- **Validation**: Confirmed. 2 of 6 return values are pass-throughs.
- **Root cause**: Bundled all SensorFrame inputs for convenience.
- **Steps**: Remove pass-throughs, caller reads settings directly.
- **Code areas**: sample_builder.py
- **Removed**: 2 positional slots in return tuple
- **Verification**: `pytest -q apps/server/tests/processing/`

### D3: JSONL-era fields in SensorFrame
- **Validation**: Confirmed. Set unconditionally, discarded by SQLite path.
- **Root cause**: SensorFrame retained JSONL routing metadata after SQLite migration.
- **Steps**: Make fields optional, stop setting in live path.
- **Code areas**: domain_models.py, sample_builder.py
- **Removed**: 2 constant field assignments per sample per tick
- **Verification**: `pytest -q apps/server/tests/`
