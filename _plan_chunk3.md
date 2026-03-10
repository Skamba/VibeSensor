# Chunk 3: WebSocket & API Schema Simplification

## Mapped Findings

### F3.1+F5.1: Dual WS Schema (TypedDicts + Pydantic Mirrors)
- **Validation**: CONFIRMED. `ws_models.py` (179 LOC) defines 10 Pydantic BaseModel classes that mirror 8+ TypedDicts in `payload_types.py` (263 LOC). The ONLY production import from `ws_models.py` is `SCHEMA_VERSION` (a string constant) in `ws_broadcast.py:27`. `ws_schema_export.py:28` uses `LiveWsPayload.model_json_schema()` — the sole reason these Pydantic models exist.
- **Validated root cause**: Pydantic models provide easy JSON Schema export via `model_json_schema()`. TypedDicts are used at runtime for zero-overhead dict construction.
- **Counter-evidence**: None — Pydantic v2's `TypeAdapter` can generate JSON Schema from TypedDicts natively (`TypeAdapter(SomeTypedDict).json_schema()`), making the mirror classes redundant.
- **Implementation**: Replace `LiveWsPayload.model_json_schema()` in `ws_schema_export.py` with `TypeAdapter(LiveWsPayload).json_schema()` using the TypedDict from `payload_types.py`. Delete all Pydantic models from `ws_models.py`. Move `SCHEMA_VERSION` to `payload_types.py`. Delete `test_ws_payload_alignment.py`.

### F5.3: Request Model None-Filter Bridge Boilerplate
- **Validation**: CONFIRMED. Four `to_store_payload()` / `to_settings_payload()` methods exist:
  1. `AnalysisSettingsRequest.to_settings_payload()` (api_models.py L142–149): uses `model_dump(exclude_none=True)` then adds a dead isinstance guard
  2. `CarUpsertRequest.to_store_payload()` (api_models.py L169–178): manual `if field is not None` × 4
  3. `SpeedSourceRequest.to_store_payload()` (api_models.py L196–205): manual `if field is not None` × 4
  4. `SensorRequest.to_store_payload()` (api_models.py L236–242): manual `if field is not None` × 2
- **Validated root cause**: Bridge between Pydantic `Optional` fields and `total=False` TypedDict payloads.
- **Counter-evidence**: `AnalysisSettingsRequest.to_settings_payload()` applies `float()` coercion — but Pydantic already validates as `float | None`, so this is redundant.
- **Refinement**: Replace all 4 methods with `self.model_dump(exclude_none=True)` at the call site. The `float()` coercion in `AnalysisSettingsRequest` is redundant — Pydantic already validates.

### F2.3: Analysis Staging Dataclasses Destructured Immediately
- **Validation**: NEEDS DEEPER INSPECTION. Subagent reported `SummaryComputation` bundles 4 dataclasses assembled in `summarize_run_data()` then immediately destructured via `computation.X.Y` accesses. Also reported 5 TypeAlias = JsonObject aliases in `_types.py` that provide no enforcement.
- **Counter-evidence**: The individual bundle dataclasses (`PreparedRunData`, `FindingsBundle`, etc.) may have value if they're used as function return types from well-named pipeline stages. The destructuring at the end may be the only ugly part.
- **Refinement**: Need to verify the actual usage pattern. If `SummaryComputation` is only used in one function body to pass locals to another function in the same module, it should be removed. The TypeAlias question is separate and lower priority.

## Root Complexity Drivers
1. Parallel type systems maintained for schema export convenience
2. Bridge methods that mechanically replicate `model_dump(exclude_none=True)`
3. Staging dataclasses that exist to pass local variables between functions in the same module

## Relevant Code Paths
- `apps/server/vibesensor/ws_models.py` (179 LOC)
- `apps/server/vibesensor/payload_types.py` (263 LOC)
- `apps/server/vibesensor/ws_schema_export.py`
- `apps/server/vibesensor/api_models.py`
- `apps/server/vibesensor/routes/settings.py`
- `apps/server/tests/hygiene/test_ws_payload_alignment.py`
- `apps/server/vibesensor/analysis/summary_builder.py`
- `apps/server/vibesensor/analysis/summary_models.py`
- `apps/server/vibesensor/analysis/_types.py`

## Simplification Approach

### Step 1: Eliminate dual WS schema
1. Move `SCHEMA_VERSION` from `ws_models.py` to `payload_types.py`
2. Update `ws_broadcast.py` import: `from ..payload_types import SCHEMA_VERSION`
3. Rewrite `ws_schema_export.py`:
   ```python
   from pydantic import TypeAdapter
   from vibesensor.payload_types import LiveWsPayload
   schema = TypeAdapter(LiveWsPayload).json_schema()
   ```
4. Verify the generated schema is identical (or acceptably similar) to the current one
5. Delete all Pydantic model classes from `ws_models.py` (or delete the file entirely)
6. Delete `tests/hygiene/test_ws_payload_alignment.py`
7. Update any imports of `ws_models` across the codebase

### Step 2: Remove request model bridge methods
1. In `routes/settings.py` and other route files, replace:
   ```python
   payload = req.to_store_payload()
   ```
   with:
   ```python
   payload = req.model_dump(exclude_none=True)
   ```
2. Delete `to_store_payload()` from `CarUpsertRequest`, `SpeedSourceRequest`, `SensorRequest`
3. Delete `to_settings_payload()` from `AnalysisSettingsRequest` (including the dead isinstance guard)
4. Verify all route handlers still produce correct payloads by running settings tests

### Step 3: Simplify analysis staging dataclasses (validated scope)
1. Read `summary_builder.py` and `summary_models.py` thoroughly
2. If `SummaryComputation` is only constructed and destructured in one function:
   - Remove `SummaryComputation` dataclass
   - Pass the component locals directly to `build_summary_payload()`
3. If the individual bundles (`PreparedRunData`, `FindingsBundle`, etc.) are only used as intermediate locals:
   - Consider removing them too and using plain variables
   - But if they serve as named return types from pipeline stage functions, keep them
4. For `_types.py` TypeAlias proliferation: 
   - Replace the 5 `TypeAlias = JsonObject` aliases with direct `JsonObject` usage
   - Or convert to `NewType` if genuine type distinction is desired
   - Lower priority — do this only if time permits

## Dependencies on Other Chunks
- None. This chunk is independent.

## Risks and Tradeoffs
- **Schema drift**: The TypeAdapter-generated schema may differ slightly from the Pydantic model-generated schema (field ordering, description metadata). Need to compare and verify CI still passes.
- **Type safety**: Replacing `to_store_payload()` with `model_dump(exclude_none=True)` loses the explicit TypedDict return type annotation. The settings store methods accept `dict` anyway, so this is low risk.
- **`AnalysisSettingsRequest`**: The `float()` coercion may be intentional for `int` → `float` promotion (Pydantic allows `int` for `float` fields). Need to verify that settings store handles `int` values correctly, or keep the `float()` cast inline.

## Validation Steps
1. Regenerate WS schema and compare: `python -m vibesensor.ws_schema_export --check`
2. `pytest -q apps/server/tests/hygiene/`
3. `pytest -q apps/server/tests/routes/` (settings route tests)
4. `pytest -q apps/server/tests/analysis/`
5. `make lint && make typecheck-backend`

## Required Documentation Updates
- `docs/ai/repo-map.md`: Update ws_models description (or remove reference)
- `.github/copilot-instructions.md`: Remove ws_models from typed-boundary list

## Required AI Instruction Updates
- Add guidance: "Do not maintain parallel Pydantic models for TypedDicts — use TypeAdapter for schema generation"
- Add guidance: "Do not add bridge methods that replicate model_dump() with exclude_none=True"

## Required Test Updates
- Delete `tests/hygiene/test_ws_payload_alignment.py`
- Update any tests importing from `ws_models`
- Add a test verifying schema generation from TypedDicts works correctly

## Simplification Crosswalk

| Finding | Validation | Root Cause | Steps | Verify |
|---------|-----------|------------|-------|--------|
| F3.1+F5.1: Dual WS schema | Confirmed: 10 mirror classes, 1 test file, 0 runtime use | Schema export convenience | Step 1 | ws_models.py deleted, schema export passes |
| F5.3: Request bridge boilerplate | Confirmed: 4 methods, 1 dead guard | TypedDict bridge | Step 2 | to_store_payload methods removed |
| F2.3: Staging dataclasses | Needs verification | Pipeline decomposition | Step 3 | SummaryComputation removed if single-use |
