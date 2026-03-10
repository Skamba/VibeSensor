# Chunk 4: Persistence & History Consolidation

## Mapped Findings

### F4.1: Dual Analysis Versioning + analysis_persistence.py Envelope
- **Validation**: CONFIRMED. `analysis_persistence.py` (49 LOC) wraps analysis summaries in an envelope `{"schema_version": 1, "summary": {...}}` via `wrap_analysis_for_storage()`. The INTEGER column `analysis_version` in `runs` table stores the same version number. `unwrap_persisted_analysis()` handles both enveloped and "legacy non-enveloped" formats — the legacy path is dead code since all v4 databases were wiped by the v4→v5 schema bump.
- **Validated root cause**: Belt-and-suspenders versioning — envelope in JSON and column in table.
- **Counter-evidence**: The envelope does isolate the public summary shape from the storage shape. But `ANALYSIS_SCHEMA_VERSION` has been `1` since introduction and there's never been a second version.
- **Refinement**: Remove the envelope. Store the summary dict directly in `analysis_json`. Keep the `analysis_version` INTEGER column as the sole version signal. Delete `analysis_persistence.py`. Simplify `analysis_is_current()` to a 2-line column check.

### F4.2: SensorFrame Quadruple Field Definition
- **Validation**: CONFIRMED. A sensor sample field is defined in:
  1. `SensorFrame` dataclass in `domain_models.py` (~30 fields with `to_dict()`/`from_dict()`)
  2. `_V2_TYPED_COLS` + `_V2_PEAK_COLS` tuples in `_samples.py` (L28–55)
  3. DDL `SCHEMA_SQL` in `_schema.py` (L58–99)
  4. `EXPORT_CSV_COLUMNS` in `exports.py` (L30–62)
  The positional offset arithmetic (`_V2_TYPED_OFFSET`, `_V2_PEAK_OFFSET`, `_V2_EXTRA_OFFSET`) depends on all column definitions staying in sync.
- **Validated root cause**: Each layer has its own column definition because they were extracted independently.
- **Counter-evidence**: The DDL must exist independently (it's SQL). The SensorFrame dataclass is the domain model. The column tuples are performance-oriented (avoid dict keys in hot path).
- **Refinement**: Derive `_V2_TYPED_COLS` from `SensorFrame.__dataclass_fields__` where possible. Use `cursor.description` for column-name-based deserialization instead of positional offsets. Keep the DDL as is (must be SQL). Derive `EXPORT_CSV_COLUMNS` or add a hygiene test.

### F4.3: Migration Scaffolding with Delete-the-DB Policy
- **Validation**: CONFIRMED. `schema_meta` table stores exactly one row (`key='version'`, `value='5'`). `_ensure_schema()` (history_db/__init__.py L130–180) has 3 branches: version match (happy), version > current (raise), version < current (raise with "delete DB"). SQLite's `PRAGMA user_version` provides the same capability with zero infrastructure.
- **Validated root cause**: Django-style schema versioning pattern applied to a "delete and recreate" policy.
- **Counter-evidence**: `schema_meta` could theoretically store other keys. Currently only 'version'. The `PRAGMA user_version` approach is marginally less discoverable.
- **Refinement**: Replace `schema_meta` table with `PRAGMA user_version`. Remove the corrupted-version recovery branch (dead code). Simplify `_ensure_schema()` to ~10 lines.

### F10.3: Two-Package History Domain + Root-Level Stray
- **Validation**: CONFIRMED. History domain spans: (1) `history_db/` package (3 files: `__init__.py`, `_schema.py`, `_samples.py`), (2) `history_services/` package (5 files: `__init__.py`, `runs.py`, `reports.py`, `exports.py`, `helpers.py`), (3) `analysis_persistence.py` at `vibesensor/` root. `analysis_persistence.py` is only imported by `history_db/__init__.py` lines 23–26.
- **Validated root cause**: Repository-pattern layering (history_db = repository, history_services = service layer). `analysis_persistence.py` placed at root to avoid circular imports.
- **Counter-evidence**: The service layer classes (`HistoryRunQueryService`, `HistoryReportService`, `HistoryExportService`) do have genuine logic (insights localization, PDF caching, streaming ZIP export). They're not thin wrappers. The two-tier split has some merit.
- **Refinement**: Given that the service classes have real logic, merging the two packages may not simplify much. HOWEVER: (1) `analysis_persistence.py` should move into `history_db/` since its only consumer is `history_db/__init__.py`. (2) If F4.1 removes `analysis_persistence.py` entirely, this is solved for free. (3) The two-package split can stay if the service classes are genuinely distinct. Re-evaluate after F4.1.

## Root Complexity Drivers
1. Belt-and-suspenders versioning with redundant envelope + column
2. Four independent definitions of the same column list with fragile offset arithmetic
3. Full migration infrastructure for a "delete the DB" policy
4. Persistence logic split across 3 locations with a stray root-level file

## Relevant Code Paths
- `apps/server/vibesensor/analysis_persistence.py` (49 LOC)
- `apps/server/vibesensor/history_db/__init__.py` (large — HistoryDB class)
- `apps/server/vibesensor/history_db/_schema.py` (SCHEMA_SQL, SCHEMA_VERSION, ANALYSIS_SCHEMA_VERSION)
- `apps/server/vibesensor/history_db/_samples.py` (_V2_TYPED_COLS, row conversion)
- `apps/server/vibesensor/history_services/exports.py` (EXPORT_CSV_COLUMNS)
- `apps/server/vibesensor/history_services/helpers.py` (strip_internal_fields)
- `apps/server/vibesensor/domain_models.py` (SensorFrame)

## Simplification Approach

### Step 1: Remove analysis envelope — delete analysis_persistence.py
1. In `history_db/__init__.py`, change the write path:
   - Before: `safe_json_dumps(wrap_analysis_for_storage(analysis))`
   - After: `safe_json_dumps(sanitize_analysis_summary(analysis))` — inline the sanitization (pop `_report_template_data`)
2. In `history_db/__init__.py`, change the read path:
   - Before: `unwrap_persisted_analysis(parsed_analysis)`
   - After: Use parsed JSON directly (it's already the summary dict)
3. Simplify `analysis_is_current()`:
   - Before: Parses full JSON, checks envelope `schema_version`, falls back to column
   - After: `return (analysis_version or 0) >= ANALYSIS_SCHEMA_VERSION`
4. Remove imports of `analysis_persistence` from `history_db/__init__.py`
5. Delete `apps/server/vibesensor/analysis_persistence.py`
6. Move `sanitize_analysis_summary` logic (1 line: `pop _report_template_data`) inline where needed
7. This also resolves F10.3's root-level stray file

### Step 2: Replace schema_meta with PRAGMA user_version
1. Remove `schema_meta` table from `SCHEMA_SQL`
2. In `_ensure_schema()`:
   - After `executescript(SCHEMA_SQL)`, check: `cur.execute("PRAGMA user_version")` → `version = cur.fetchone()[0]`
   - If version == 0 (fresh DB): `cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")`
   - If version == SCHEMA_VERSION: pass
   - If version > SCHEMA_VERSION: raise "cannot downgrade"
   - If version < SCHEMA_VERSION: raise "delete DB" message
3. Remove the corrupted-version recovery branch
4. Remove `schema_meta` INSERT/UPDATE logic
5. The `_ensure_schema()` method shrinks from ~35 lines to ~15 lines

### Step 3: Reduce SensorFrame quadruple definition
1. Derive `_V2_TYPED_COLS` from `SensorFrame.__dataclass_fields__` keys (or maintain a mapping from dataclass fields to DB column names)
2. In `v2_row_to_dict()`, use column-name-based deserialization via `cursor.description` instead of positional offsets
3. Remove `_V2_TYPED_OFFSET`, `_V2_PEAK_OFFSET`, `_V2_EXTRA_OFFSET` — these become unnecessary with name-based access
4. In `sample_to_v2_row()`, when input is `SensorFrame`, read attributes directly instead of `to_dict()` → string-key extraction roundtrip
5. Add a hygiene test asserting `EXPORT_CSV_COLUMNS` matches the defined schema columns

### Step 4: Consolidate history packages (scope: only if needed after Step 1)
- After Step 1, `analysis_persistence.py` is gone, resolving F10.3's stray file
- The two-package split (`history_db/` + `history_services/`) can remain — the service classes have genuine logic
- If desirable, rename to `history/` with `db.py` and service files, but this is lower priority

## Dependencies on Other Chunks
- F4.1's envelope removal resolves F10.3's stray file — no action needed for F10.3 beyond Step 1
- Must run after Chunk 2 if there are shared test fixtures, but no direct code dependency

## Risks and Tradeoffs
- **Existing databases**: Removing the envelope means existing DBs with enveloped analysis JSON will be read differently. Need to handle one-time migration: when reading, check for `summary` key and unwrap if present.
- **PRAGMA user_version**: On existing databases, `user_version` is 0 by default. The migration check at startup must handle: if `schema_meta` table exists but `user_version` is 0, read version from `schema_meta` first, set `user_version`, then drop `schema_meta`. OR: simpler approach — since the policy is "delete DB on mismatch", just treat `user_version=0` as "fresh DB" and set it to current version. Existing DBs with schema_meta will still have version 5 in schema_meta but user_version=0. The `executescript(SCHEMA_SQL)` won't recreate existing tables. So we need the transition path.
- **SensorFrame column derivation**: Some DB columns don't map 1:1 to dataclass field names (e.g., `extra_json` is a serialized blob, not a direct attribute). Need careful handling.

### Risk mitigation
- For envelope removal: Add a one-time read-path compat: if analysis JSON has `"summary"` key, unwrap it. This handles existing DBs without requiring a migration.
- For PRAGMA: Keep it simple — the "delete DB" policy means we don't need to handle old DBs gracefully. But add a transitional check in case someone is running with an existing DB.

## Validation Steps
1. `pytest -q apps/server/tests/history_db/`
2. `pytest -q apps/server/tests/analysis/`
3. `pytest -q apps/server/tests/report/`
4. `make lint && make typecheck-backend`
5. Verify `analysis_persistence.py` is deleted
6. Verify `schema_meta` table is removed from SCHEMA_SQL
7. End-to-end: create a run, analyze it, verify analysis JSON is stored directly

## Required Documentation Updates
- `docs/ai/repo-map.md`: Remove analysis_persistence.py reference, update history_db description
- `docs/history_db_schema.md`: Update schema description (no schema_meta, PRAGMA user_version)
- `.github/copilot-instructions.md`: Update history_db package description

## Required AI Instruction Updates
- Add guidance: "Do not maintain parallel version tracking in both JSON envelopes and DB columns — pick one"
- Add guidance: "Use PRAGMA user_version for SQLite schema versioning instead of a dedicated meta table"
- Add guidance: "Derive column lists from source-of-truth definitions rather than maintaining parallel lists"

## Required Test Updates
- Update tests that construct analysis payloads with envelope format
- Update tests that check `schema_meta` table
- Add hygiene test for EXPORT_CSV_COLUMNS matching generated column list

## Simplification Crosswalk

| Finding | Validation | Root Cause | Steps | Verify |
|---------|-----------|------------|-------|--------|
| F4.1: Dual analysis versioning | Confirmed: envelope + column + dead legacy path | Belt-and-suspenders | Step 1 | analysis_persistence.py deleted, analysis_is_current 2 lines |
| F4.2: Quadruple field definition | Confirmed: 4 independent column lists | Independent extraction | Step 3 | _V2_TYPED_COLS derived, offset arithmetic removed |
| F4.3: Migration scaffolding | Confirmed: schema_meta for 1 row, 3 dead-code branches | Django-style pattern | Step 2 | PRAGMA user_version used, schema_meta removed |
| F10.3: Split history domain + stray | Confirmed: 3 locations | Circular import avoidance | Step 1 resolves stray, Step 4 optional | analysis_persistence.py gone |
