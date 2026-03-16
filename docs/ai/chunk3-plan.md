# Chunk 3 Plan: Consolidate Persistence Layer and Unify Type Registries

## Mapped Findings

| ID | Original Finding | Source Subagents |
|----|-----------------|-----------------|
| P1 | Four parallel column manifests with artificial typed/peak split | Persistence #1 |
| P2 | Dead JSONL write infrastructure maintained at production quality | Persistence #2 |
| P3 | JSONL-era protocol fields produced everywhere, stored nowhere | Persistence #3 |
| I1 | TypedDict/Pydantic parallel type system for HTTP boundaries | API #1 |
| F2 | PDF adapter dissolves use_case boundary by importing 4 private internals | Folder #2 |
| F3 | Dual type registry: cross-layer types in private use_case module | Folder #3 |

## Validation Summary

### P1: Four Parallel Column Manifests — CONFIRMED (3 independent + 1 computed)

Three truly independent manifests of the same column set:
1. `_V2_TYPED_COLS` + `_V2_PEAK_COLS` in `_samples.py` (25 + 1 columns)
2. `CREATE TABLE samples_v2` DDL in `_schema.py` (26 columns)
3. `EXPORT_CSV_COLUMNS` in `exports.py` (26 columns, different order)

`_V2_PEAK_OFFSET` is computed from column counts, creating fragile offset arithmetic. `_V2_PEAK_COLS` is a one-element tuple elevated to its own abstraction. Adding a column requires editing all three files independently.

### P2: Dead JSONL Write Infrastructure — CONFIRMED (write side only)

`append_jsonl_records`, `RunEndRecord`, `create_run_end_record`: **0 production callers**. Only used by 5 test files. The production write path is `RunRecorder → HistoryDB.append_samples()` exclusively via SQLite. `RunData` is NOT dead — it's returned by `read_jsonl_run` which is still used in production for JSONL file analysis via `helpers.py:281`.

### P3: JSONL-Era Protocol Fields — CONFIRMED

`SensorFrame.to_dict()` emits `record_type: "sample"` and `schema_version: "v2-jsonl"` on every call. Neither field appears in `_V2_TYPED_COLS`. Both are silently discarded by `sample_to_v2_row()`. `docs/history_db_schema.md` lists phantom columns (`record_type`, `schema_version`, `extra_json`) that don't exist in actual DDL. Schema version documented as "5" but actual `SCHEMA_VERSION = 9`.

### I1: TypedDict/Pydantic Parallel Types — CONFIRMED

5 pairs of identical/near-identical types:
- `HistoryRunListEntryPayload` ↔ `HistoryListEntryResponse` (7/7 field overlap)
- `SensorConfigPayload` ↔ `SensorConfigResponse` (2/2)
- `CarConfigPayload` ↔ `CarResponse` (5/5)
- `SpeedSourcePayload` ↔ `SpeedSourceResponse` (5/5)
- `HistoryRunPayload` ↔ `HistoryRunResponse` (12 vs 4+extra)

Routes connect them via fragile `**dict` unpacking. The repo's own rules state: "Do not create TypedDict mirrors of Pydantic models."

### F2: PDF Adapter Private Imports — CONFIRMED

`adapters/pdf/mapping.py` imports 11 symbols from 4 `use_cases/diagnostics/` submodules, including the private `_types.py` (underscore prefix). Symbols imported: `IntensityRow`, `JsonValue`, `MetadataDict`, `RunSuitabilityCheck`, `SpeedStats`, `TestStep`, `PHASE_I18N_KEYS`, `PeakTableRow`, `certainty_tier`, `strength_label`, `strength_text`.

### F3: Dual Type Registry — CONFIRMED

`AnalysisSummary` (40-field TypedDict, the most widely consumed boundary type) lives in `use_cases/diagnostics/_types.py` (private module) while narrower single-subsystem types live in `shared/types/`. Five `JsonObject` aliases in `_types.py` (`Sample`, `MetadataDict`, `IntensityRow`, `I18nRef`, `TestStep`) add zero type safety. `json_types.py` is 29 lines — too thin for its own module.

## Simplification Strategy

### Step 1: Remove Dead JSONL Write Infrastructure (P2)

1. In `runlog.py`, remove:
   - `append_jsonl_records()` function and `_sanitize_non_finite()` helper
   - `RunEndRecord` TypedDict
   - `create_run_end_record()` function
   - Remove these from `__all__`
2. Keep: `read_jsonl_run()`, `normalize_sample_record()`, `RunData`, `utc_now_iso()`, `parse_iso8601()`, `bounded_sample()`, `create_run_metadata()`
3. Update test files that called `append_jsonl_records`:
   - `test_runlog.py` — remove write tests, keep read tests
   - `test_runlog_error_fallbacks.py` — delete entirely (all 6+ tests are write-path edge cases)
   - Other test helpers that used `append_jsonl_records` for test fixture setup — refactor to use SQLite-based fixture setup instead

### Step 2: Remove JSONL-Era Protocol Fields (P3)

1. In `SensorFrame.to_dict()` (`protocol.py:467`), remove `record_type` and `schema_version` from the returned dict
2. These belong to JSONL framing, not to the domain object. If any JSONL writer still needs them, it should add them at the serialization boundary
3. Check `normalize_sample_record()` in `runlog.py` — does it depend on these fields from `to_dict()`? If so, add them in the JSONL-specific path
4. Update `docs/history_db_schema.md`:
   - Remove phantom columns (`record_type`, `schema_version`, `extra_json`)
   - Update schema version from "5" to current (9)
   - Document the actual `case_id` column added in v9

### Step 3: Unify Column Manifests (P1)

1. In `_samples.py`, merge `_V2_TYPED_COLS` and `_V2_PEAK_COLS` into a single `_V2_COLUMNS` tuple:
   ```python
   _V2_COLUMNS: tuple[str, ...] = ("run_id", "timestamp_us", ..., "top_peaks")
   ```
2. Add a column serializer map for JSON-encoded columns:
   ```python
   _COLUMN_SERIALIZERS: dict[str, Callable] = {
       "top_peaks": lambda v: json.dumps(v) if v is not None else None,
   }
   ```
3. Rewrite `sample_to_v2_row()` to iterate `_V2_COLUMNS` with a single loop, applying serializers where defined
4. Rewrite `v2_row_to_dict()` to iterate `_V2_COLUMNS` with a single loop
5. Remove `_V2_PEAK_OFFSET`, `_V2_TYPED_OFFSET`, `_V2_PEAK_COLS`
6. Derive `EXPORT_CSV_COLUMNS` from `_V2_COLUMNS` (or define it alongside with a reference)

### Step 4: Remove TypedDict/Pydantic Parallel HTTP Types (I1)

1. Remove from `backend_types.py`:
   - `HistoryRunListEntryPayload`
   - `SensorConfigPayload`
   - `CarConfigPayload`
   - `SpeedSourcePayload`
2. Keep `HistoryRunPayload` for now — it has 12 fields and serves the history use case as a typed dict for the service layer (non-HTTP internal use). Evaluate whether the service can return Pydantic directly.
3. Update service methods to return Pydantic models directly or use `model_validate()`:
   - `list_runs()` → return `list[HistoryListEntryResponse]`
   - Settings store methods → return Pydantic model instances
4. Update routes to return service results directly instead of `**dict` unpacking
5. If any non-HTTP consumer (WebSocket, internal service) needs the TypedDict form, keep it only for that specific consumer

### Step 5: Promote Cross-Layer Types from Private _types.py (F2, F3)

1. Move `PHASE_I18N_KEYS` from `use_cases/diagnostics/helpers.py` to `shared/locations.py` or a new `shared/constants.py` (it's shared display data, not analysis logic)
2. Move `PeakTableRow` from `use_cases/diagnostics/plots.py` to `shared/types/` or promote to `use_cases/diagnostics/__init__.py` public surface
3. Promote `certainty_tier`, `strength_label`, `strength_text` from `strength_labels.py` to `use_cases/diagnostics/__init__.py` re-exports
4. Remove the `JsonValue`/`JsonObject` re-exports from `_types.py` — callers should import from `shared/types/json_types` directly
5. Remove the 5 `JsonObject` alias no-ops from `_types.py` (`Sample`, `MetadataDict`, `IntensityRow`, `I18nRef`, `TestStep`) — use `JsonObject` directly at their use sites
6. Consider merging `json_types.py` (29 lines) into `shared/types/__init__.py` or `payload_types.py`
7. Update `adapters/pdf/mapping.py` imports to use the new canonical locations

## Simplification Crosswalk

### P1: Four Parallel Column Manifests
- **Validation result:** CONFIRMED (3 independent + 1 computed)
- **Root cause:** typed/peak split for JSON serialization of one column, calcified into architecture
- **Steps:** Step 3
- **Areas:** `adapters/persistence/history_db/_samples.py`, `use_cases/history/exports.py`
- **Removed:** `_V2_PEAK_COLS`, `_V2_PEAK_OFFSET`, `_V2_TYPED_OFFSET`, dual-loop pattern
- **Verification:** Sample insert/read round-trips correctly, CSV export matches

### P2: Dead JSONL Write Infrastructure
- **Validation result:** CONFIRMED (write side)
- **Root cause:** JSONL was original persistence format; write path fully migrated to SQLite but not cleaned up
- **Steps:** Step 1
- **Areas:** `adapters/persistence/runlog.py`, test files for JSONL writes
- **Removed:** `append_jsonl_records`, `_sanitize_non_finite`, `RunEndRecord`, `create_run_end_record`, `test_runlog_error_fallbacks.py`
- **Verification:** All production read paths still work, write path unaffected

### P3: JSONL-Era Protocol Fields
- **Validation result:** CONFIRMED
- **Root cause:** `SensorFrame.to_dict()` not cleaned up when SQLite replaced JSONL writes
- **Steps:** Step 2
- **Areas:** `adapters/udp/protocol.py`, `docs/history_db_schema.md`
- **Removed:** 2 phantom keys from `to_dict()`, 3 phantom columns from docs
- **Verification:** DB insert path unaffected (fields were already discarded), JSONL read path still works (fields added at JSONL boundary if needed)

### I1: TypedDict/Pydantic Parallel HTTP Types
- **Validation result:** CONFIRMED
- **Root cause:** TypedDicts added for service typing, Pydantic added separately for FastAPI, both maintained
- **Steps:** Step 4
- **Areas:** `shared/types/backend_types.py`, `shared/types/api_models.py`, route handlers
- **Removed:** 4 TypedDict definitions, `**dict` unpacking pattern
- **Verification:** All HTTP endpoints return correct response shapes, mypy passes

### F2: PDF Adapter Private Imports
- **Validation result:** CONFIRMED
- **Root cause:** Symbols needed by PDF adapter never promoted to public use_case surface
- **Steps:** Step 5
- **Areas:** `adapters/pdf/mapping.py` imports, `use_cases/diagnostics/__init__.py`, `shared/`
- **Removed:** Private module imports from adapter layer
- **Verification:** PDF rendering unchanged, import boundaries restored

### F3: Dual Type Registry
- **Validation result:** CONFIRMED
- **Root cause:** AnalysisSummary grew up in analysis pipeline, never moved to shared/types
- **Steps:** Step 5 (part of same consolidation)
- **Areas:** `use_cases/diagnostics/_types.py`, `shared/types/`
- **Removed:** 5 JsonObject alias no-ops, indirect JsonValue re-export, json_types.py standalone file
- **Verification:** All type imports resolve correctly, mypy passes

## Dependencies

- **Depends on Chunk 1:** Chunk 1 may remove some domain types that `_types.py` references in its TypedDicts. Execute after Chunk 1.
- **Chunk 4 benefits:** Promoting `AnalysisSummary` to a shared location makes Chunk 4's round-trip elimination cleaner.
- **Chunk 5 depends:** Test reorganization (T1) may move tests that reference types relocated in this chunk.

## Risks and Tradeoffs

1. **P2 (JSONL write removal):** Test fixtures that used `append_jsonl_records` to create test data need alternative setup. Most can use SQLite-based fixture creation instead.

2. **P3 (SensorFrame.to_dict):** Removing `record_type`/`schema_version` from `to_dict()` may break the JSONL read path if `normalize_sample_record()` expects them. Need to verify the read path adds these fields independently (it does — `read_jsonl_run` reads them from the raw JSON line, not from `to_dict()`).

3. **I1 (TypedDict removal):** If any non-HTTP consumer (tests, internal service) constructs these TypedDicts directly, those call sites need updating. The WebSocket path uses different types and is unaffected.

4. **F3 (type relocation):** Moving `AnalysisSummary` to `shared/types/` would touch many import statements across the codebase. Consider whether it's worth the churn — an alternative is to promote it to the public surface of `use_cases/diagnostics/__init__.py` (it's already re-exported there).

## Required Documentation Updates
- `docs/history_db_schema.md`: full rewrite to match schema v9
- `docs/ai/repo-map.md`: update references to _types.py, runlog.py

## Required AI Instruction Updates
- Add: "Do not maintain parallel TypedDict and Pydantic models for the same HTTP boundary. Use Pydantic for HTTP boundaries."
- Add: "Do not keep dead write infrastructure. If a persistence write path is fully migrated, remove the old write code."
- Add: "Protocol framing fields (record_type, schema_version) belong at the serialization boundary, not in domain object methods."

## Required Test Updates
- Delete `test_runlog_error_fallbacks.py`
- Update `test_runlog.py` to remove write-path tests
- Update type import paths in tests
- Verify sample round-trip tests still pass after column manifest unification
