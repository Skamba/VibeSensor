# Chunk 3: State Management & Persistence Simplification

## Mapped Findings

| ID | Original Finding | Source Subagents | Validation Result |
|----|-----------------|------------------|-------------------|
| A2+C1 | Metrics_log lock-per-property boilerplate in _MetricsSessionState and _MetricsPersistenceCoordinator (~150 lines of individual-field locks alongside batch snapshot methods) | Architecture, Data Flow | **VALIDATED** — _MetricsSessionState confirmed at logger.py:79 with 9+ individually-locked properties. _MetricsPersistenceCoordinator has 8+ individually-locked properties. Both provide snapshot()/status_snapshot() that do the correct single-lock bulk read. The per-property locks provide individual field safety but callers need multi-field consistency, which only snapshots provide. |
| D1 | Four parallel sample column definitions maintained independently with no enforcement | Persistence | **VALIDATED** — Schema DDL at _schema.py:40, _V2_TYPED_COLS list at _samples.py, SensorFrame at domain_models.py, and EXPORT_CSV_COLUMNS at exports.py each independently define the sample field set. No automated cross-check exists. A typo produces silent NULL insertion. |
| D2 | Settings persistence as degenerate one-row KV table + dual sensor name stores (client_names table vs sensorsByMac blob) | Persistence | **PARTIALLY VALIDATED** — settings_kv table uses a single key 'settings_snapshot'. However, the KV pattern is cosmetically inefficient but functionally simple. The dual sensor name issue (client_names vs sensorsByMac) is the actual complexity problem. Downscoped: focus on documenting/resolving the dual sensor name ambiguity rather than restructuring settings_kv. |
| D3 | Two schema version trackers with inconsistent storage — schema_meta table vs PRAGMA user_version | Persistence | **VALIDATED** — schema_meta table at _schema.py:30 reimplements what PRAGMA user_version does natively. _ensure_schema() has 40+ lines for this. ANALYSIS_SCHEMA_VERSION is stored as a column on runs, which is legitimate for per-row versioning. The schema_meta → PRAGMA user_version migration is a clean, low-risk simplification. |
| B2-ws | WsBroadcastCache dataclass as externally-visible mutable container in ws_broadcast.py | Abstraction | **NEEDS VALIDATION** — Must check if WsBroadcastCache fields are accessed outside WsBroadcastService. |

## Additional Validation: WsBroadcastCache

Need to verify whether WsBroadcastCache is accessed externally.

## Root Causes

1. **Defensive concurrency habit**: Every mutable field gets its own lock guard, creating boilerplate that doesn't address the actual multi-field consistency requirement.
2. **No schema-column enforcement**: Sample fields are defined in 4 places because each serves a slightly different purpose (DDL, insertion, domain model, export). No mechanism derives them from one source.
3. **SQLite feature unfamiliarity**: schema_meta reimplements a built-in SQLite mechanism (PRAGMA user_version) because the developer preferred a table-based approach.
4. **Settings evolution**: The single-key KV pattern was an over-general design for future extensibility that never materialized.

## Relevant Code Paths

### Lock-per-property (metrics_log/logger.py)
- `_MetricsSessionState` — 9 properties with individual `with self._lock:` blocks, plus snapshot(), pending_flush_snapshot(), start_new_session(), stop_session() for bulk reads
- `_MetricsPersistenceCoordinator` — 8+ similarly-locked properties, plus status_snapshot() for bulk reads
- `MetricsLogger.status()` and `.health_snapshot()` — callers that read multiple fields

### Sample columns
- `history_db/_schema.py` — DDL for samples_v2 table (26 columns)
- `history_db/_samples.py` — _V2_TYPED_COLS tuple (25 entries), _V2_PEAK_COLS, sample_to_v2_row(), v2_row_to_dict()
- `domain_models.py` — SensorFrame dataclass (27 fields), to_dict(), from_dict()
- `history_services/exports.py` — EXPORT_CSV_COLUMNS (27 entries)
- `metrics_log/sample_builder.py` — build_sample_records() produces the dict at runtime

### Schema version
- `history_db/_schema.py` — SCHEMA_VERSION = 7, schema_meta DDL
- `history_db/__init__.py` — _ensure_schema() with 40+ lines of schema_meta management

### WsBroadcastCache
- `runtime/ws_broadcast.py` — WsBroadcastCache dataclass definition
- `runtime/builders.py` — constructs WsBroadcastCache

## Simplification Approach

### Step 1: Remove per-property lock boilerplate from _MetricsSessionState

1. Make all state fields plain `_x` attributes (no property wrappers)
2. Keep `start_new_session()`, `stop_session()`, `snapshot()`, `pending_flush_snapshot()` as the only locked transaction methods
3. Add a `should_auto_stop()` locked method for the timeout check
4. The `enabled` setter needs to remain as a locked setter (it's called from HTTP handlers)
5. Remove all 7-8 property getters that just `with self._lock: return self._x`
6. Audit callers to ensure they use snapshot methods, not individual field access

### Step 2: Remove per-property lock boilerplate from _MetricsPersistenceCoordinator

1. Make all state fields plain `_x` attributes
2. Keep `status_snapshot()` as the only bulk read method
3. Keep specific write methods (set_history_run_created, record_write, etc.) as locked setters
4. Remove all 8+ property getters that just `with self._lock: return self._x`

### Step 3: Replace schema_meta table with PRAGMA user_version

1. In _ensure_schema(), replace `CREATE TABLE IF NOT EXISTS schema_meta` DDL with `PRAGMA user_version`
2. Replace the version read: `SELECT value FROM schema_meta WHERE key = 'version'` → `PRAGMA user_version`
3. Replace the version write: `INSERT/UPDATE schema_meta` → `PRAGMA user_version = N`
4. Remove schema_meta DDL from SCHEMA_SQL
5. Handle migration: if schema_meta table exists (old DB), read version from it, set PRAGMA, then drop schema_meta table
6. This simplifies _ensure_schema() from ~40 lines to ~15 lines

### Step 4: Derive sample column definitions from a single source

1. Create a canonical `SAMPLE_COLUMNS` tuple in `_samples.py` defining every column with its name and SQL type
2. Generate `_V2_TYPED_COLS` from SAMPLE_COLUMNS
3. Add a hygiene test that verifies SensorFrame.to_dict() keys and EXPORT_CSV_COLUMNS align with SAMPLE_COLUMNS
4. This doesn't change runtime behavior but prevents drift

### Step 5: Document dual sensor name stores

1. Add a clear documentation comment in settings_store.py and registry.py explaining the two stores and their distinct purposes
2. The actual merge of client_names into sensorsByMac is too risky for this chunk (it would change runtime behavior for sensor auto-discovery). Document it as a future simplification.

### Step 6: WsBroadcastCache inline (if validated)

- If WsBroadcastCache is only accessed within WsBroadcastService, inline its 5 fields as private attributes on the service.

## Simplification Crosswalk

### A2+C1 → Lock-per-property boilerplate
- **Validation**: Confirmed — 17+ property getters doing nothing but lock-acquire-read-release
- **Root cause**: Defensive concurrency habit; callers need multi-field snapshots, not individual reads
- **Steps**: Remove property wrappers, make fields plain attributes, keep only transaction methods
- **Removable**: ~100 lines of property boilerplate across both classes
- **Verification**: All metrics_log tests pass, MetricsLogger.status() still returns correct data

### D1 → Parallel sample column definitions
- **Validation**: Confirmed — 4 independent definitions with no cross-check
- **Root cause**: Each definition serves a different purpose with no enforcement
- **Steps**: Create canonical SAMPLE_COLUMNS, derive _V2_TYPED_COLS, add drift-detection test
- **Removable**: Nothing removed (this is a guardrail addition)
- **Verification**: Hygiene test catches any column drift, existing tests still pass

### D2 → Settings KV + dual sensor names
- **Validation**: Partially validated — KV table is cosmetic, dual names is real
- **Root cause**: settings_kv uses generic KV for a single-key use case; client_names vs sensorsByMac serve different purposes but overlap
- **Steps**: Document the dual-store relationship; the KV→single-row migration is cosmetic and not worth the schema migration risk
- **Removable**: Nothing removed (documentation improvement)
- **Verification**: No runtime changes, documentation review

### D3 → Schema version via schema_meta table
- **Validation**: Confirmed — schema_meta reimplements PRAGMA user_version
- **Root cause**: SQLite feature unfamiliarity
- **Steps**: Replace schema_meta with PRAGMA user_version, handle migration from existing DBs
- **Removable**: schema_meta DDL, 25+ lines of _ensure_schema() logic
- **Verification**: Fresh DB and migrated DB both work, schema version reads correctly

### B2-ws → WsBroadcastCache externally visible
- **Validation**: Needs code inspection to confirm external access
- **Steps**: If confirmed externally unused, inline 5 fields on WsBroadcastService
- **Removable**: WsBroadcastCache class definition
- **Verification**: WS broadcast still works, all WS tests pass

## Dependencies on Other Chunks

- No dependencies on Chunks 1 or 2.
- Chunk 4 (testing) may need to update tests that construct _MetricsSessionState or check individual properties.
- Chunk 5 is independent.

## Risks and Tradeoffs

1. **Lock removal**: Removing per-property locks changes the threading contract. Risk: callers that currently read individual fields outside snapshots will lose per-field atomicity. Mitigated: audit all callers to ensure they use snapshots.
2. **PRAGMA user_version migration**: Existing databases have schema_meta. Need graceful migration path. Risk: if migration fails, DB is unusable. Mitigated: read from schema_meta first if it exists, migrate forward.
3. **Sample column enforcement**: Adding a hygiene test may fail initially if columns have already drifted. This is intentional — it catches existing drift.

## Validation Steps

1. `pytest -q apps/server/tests/metrics_log/` — metrics_log tests pass
2. `pytest -q apps/server/tests/history/` — history/persistence tests pass  
3. `pytest -q apps/server/tests/hygiene/` — hygiene tests pass (including new column drift test)
4. `make lint` — clean
5. `make typecheck-backend` — clean
6. Full test suite: `pytest -q -m "not selenium" apps/server/tests`

## Required Documentation Updates

- docs/history_db_schema.md — update schema version mechanism description
- docs/ai/repo-map.md — update history_db description

## Required AI Instruction Updates

- Add to .github/instructions/general.instructions.md: "Use snapshot methods instead of per-property lock wrapping for concurrent state. Do not add new per-property lock patterns."
- Add: "Prefer SQLite built-in mechanisms (PRAGMA, CHECK constraints) over reimplementing them in table design."

## Required Test Updates

- Update tests that access _MetricsSessionState properties directly → use snapshot methods
- Add hygiene test for sample column alignment
- Update _ensure_schema tests for PRAGMA user_version
