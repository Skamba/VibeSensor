# Chunk 5: Test Organization & Contract Cleanup

## Overview
The test suite and contract layers have accumulated structural complexity: a `tests/regression/`
directory with split ownership that doesn't align with the feature-based test layout, builder
proliferation in fault scenario helpers, overlapping assertion namespaces across multiple
files, a convoluted WS contract generation pipeline, dual-maintained location codes, and an
oversized WebSocket row that serializes 13 fields the frontend never reads. This chunk dissolves
the regression directory, consolidates builder functions, simplifies assertion organization,
streamlines WS contract generation, unifies location codes to a shared JSON source of truth,
and trims `ClientApiRow` to only the fields the frontend actually consumes.

## Mapped Findings

### Finding 1: regression/ directory should dissolve into feature dirs (A6-2/A10-1)
- **Original**: Subagent 6 finding 2 + Subagent 10 finding 1 (duplicate)
- **Validation result**: CONFIRMED. `tests/regression/` contains 28 test files across 4
  subdirectories (`analysis/`, `cross_cutting/`, `report/`, `runtime/`). Per the repo's
  testing convention (`docs/testing.md`), tests should live in feature-based directories
  that mirror source modules. The regression directory creates split ownership: analysis
  regression tests live in `regression/analysis/` instead of `tests/analysis/`, report
  regression tests in `regression/report/` instead of `tests/report/`, etc.
- **Validated root cause**: The `regression/` directory was created as a separate test
  category, but the repo's testing layout convention is feature-based, not category-based.

### Finding 2: fault_scenarios.py builder proliferation (A6-1)
- **Original**: Subagent 6 finding 1
- **Validation result**: CONFIRMED. `fault_scenarios.py` in `test_support/` defines 12
  scenario builder functions. 2 are pure pass-throughs that delegate to another builder
  with no additional logic. Additionally, `fault_phase()` in `scenario_ground_truth.py`
  duplicates the core fault scenario construction pattern from `fault_scenarios.py`.
- **Validated root cause**: Builder functions were added incrementally for each test case
  without consolidating common patterns.

### Finding 3: Overlapping test_support assertion namespaces (A6-3)
- **Original**: Subagent 6 finding 3
- **Validation result**: CONFIRMED. Assertion functions are spread across 3 files in
  `test_support/`: `__init__.py` re-exports 85+ symbols, `core.py` contains 3 `assert_*`
  functions alongside non-assertion helpers, and at least one specialized assertion module
  exists. The boundary between "core assertions" and "specialized assertions" is unclear.
  Some consumers import from `test_support` (the re-export), others import from specific
  submodules directly, creating inconsistent import patterns.
- **Validated root cause**: Organic growth without clear ownership rules for where to place
  new assertion functions.

### Finding 4: WS contract generation pipeline complexity (A9-1)
- **Original**: Subagent 9 finding 1
- **Validation result**: CONFIRMED. The WS contract generation uses a multi-step pipeline:
  1. Generate JSON Schema from Python models
  2. Wrap JSON Schema in a fake OpenAPI 3.0 envelope (adding `paths: {}` etc.)
  3. Write to a temp file
  4. Shell out to `openapi-typescript` to convert OpenAPI → TypeScript types
  5. Delete temp file
  6. Append 13 hand-written type alias lines to the output
  The fake OpenAPI wrapping exists solely because `openapi-typescript` requires an OpenAPI
  document, even though the actual input is JSON Schema.
- **Validated root cause**: `openapi-typescript` was chosen for HTTP API types, then reused
  for WS types via a shim layer rather than using a JSON-Schema-to-TypeScript tool.

### Finding 5: Location codes dual-maintained (A9-2)
- **Original**: Subagent 9 finding 2
- **Validation result**: CONFIRMED. 15 location codes are defined in:
  1. `apps/server/vibesensor/locations.py` as Python lists/dicts
  2. `apps/ui/src/constants.ts` as TypeScript arrays
  A fragile regex-based sync test uses `re.findall()` + `split()` chain to extract codes
  from both files and compare them. There is no shared JSON file as the single source.
  The `libs/shared/contracts/` directory already exists and has `location_codes.json` per
  the memory note, but let me verify this is actually populated and used.
- **Validated root cause**: Location codes were defined independently in each language before
  the shared contracts infrastructure existed.

### Finding 6: ClientApiRow sends unused fields over WebSocket (A5-1)
- **Original**: Subagent 5 finding 1
- **Validation result**: CONFIRMED. `ClientApiRow` has 23 fields. The frontend dashboard
  reads only ~10 fields from the WS message. 13 fields including the nested `latest_metrics`
  dict (which itself contains sub-dicts) are serialized and sent over WebSocket on every
  update but never consumed by any UI component. This wastes bandwidth on the Pi's limited
  hardware and adds serialization overhead.
- **Validated root cause**: `ClientApiRow` was designed as a comprehensive status dump rather
  than a targeted WS payload. The same type serves both the REST API (where all fields may
  be useful) and the WS push (where most are ignored).

## Root Causes Behind These Findings
1. Category-based test directory layout conflicts with feature-based convention
2. Incremental builder/assertion growth without consolidation
3. Tool-driven pipeline complexity (wrong tool for the job)
4. Pre-shared-contracts era dual-source maintenance
5. One-size-fits-all data type for different transport contexts

## Relevant Code Paths and Components

### Regression directory dissolution
- `apps/server/tests/regression/` — all 28 test files across 4 subdirectories
- `apps/server/tests/analysis/` — target for analysis regression tests
- `apps/server/tests/report/` — target for report regression tests
- `docs/testing.md` — testing layout documentation

### Fault scenario consolidation
- `apps/server/tests/test_support/fault_scenarios.py` — 12 builder functions
- `apps/server/tests/test_support/scenario_ground_truth.py` — fault_phase duplication

### Assertion namespace cleanup
- `apps/server/tests/test_support/__init__.py` — 85+ re-exports
- `apps/server/tests/test_support/core.py` — mixed assert_* and non-assertion helpers

### WS contract generation
- `tools/config/` — WS schema generation scripts
- `apps/ui/src/generated/` — generated TypeScript types

### Location codes
- `apps/server/vibesensor/locations.py` — Python location codes
- `apps/ui/src/constants.ts` — TypeScript location codes
- `libs/shared/contracts/location_codes.json` — shared source (if it exists)

### ClientApiRow
- `apps/server/vibesensor/payload_types.py` — ClientApiRow definition
- `apps/server/vibesensor/ws_models.py` — WS serialization
- `apps/ui/src/` — frontend consumers of WS data

## Simplification Approach

### Step 1: Dissolve regression/ into feature directories
1. For each file in `tests/regression/analysis/`, move to `tests/analysis/`
2. For each file in `tests/regression/report/`, move to `tests/report/`
3. For each file in `tests/regression/runtime/`, move to appropriate feature dirs
   (e.g., `tests/history/`, `tests/api/`)
4. For each file in `tests/regression/cross_cutting/`, evaluate:
   - If it primarily tests one subsystem: move to that feature dir
   - If it genuinely tests cross-cutting concerns: move to a `tests/integration/` dir
5. Update any imports that reference `tests.regression.`
6. Remove `tests/regression/` directory and its README
7. Update `docs/testing.md` to reflect the dissolution

### Step 2: Consolidate fault scenario builders
1. Identify the 2 pure pass-through functions in `fault_scenarios.py`
2. Replace call sites with direct calls to the underlying builder
3. Remove the pass-through functions
4. Move `fault_phase()` from `scenario_ground_truth.py` into `fault_scenarios.py` (or
   inline it at its call sites if it has few callers)
5. Look for builders with identical parameter patterns that could share a base function

### Step 3: Simplify assertion namespace
1. Audit the 85+ symbols in `test_support/__init__.py` — which are assertions vs helpers?
2. Ensure `core.py` contains only core assertion functions (move non-assertion helpers out)
3. Establish a clear pattern: `assert_*` functions in `core.py` (or `assertions.py`),
   helper functions in their respective modules
4. Update `__init__.py` to re-export only what's needed
5. Standardize import patterns across tests (prefer importing from `test_support` directly)

### Step 4: Simplify WS contract generation
1. Evaluate if `json-schema-to-typescript` (npm package) or similar can replace the
   JSON Schema → fake OpenAPI → openapi-typescript pipeline
2. If yes: replace the pipeline with direct JSON Schema → TypeScript conversion
3. Remove the fake OpenAPI envelope construction
4. Keep the 13 hand-written type aliases (they provide named exports for common types)
5. If no suitable tool exists: document why the shim is necessary and simplify where possible

### Step 5: Unify location codes
1. Verify `libs/shared/contracts/location_codes.json` exists and is populated
2. If it exists: make Python `locations.py` load from it (or import via vibesensor_shared)
3. If it doesn't exist: create it with the 15 location codes, then update both Python and TS
4. Update the TS side to import from the shared contracts generated output
5. Remove the fragile regex-based sync test (replace with a simpler test that loads both
   and compares, or rely on the shared source eliminating the need for sync testing)
6. Run `make sync-contracts` (or the new `make regen-contracts` from Chunk 4) to verify

### Step 6: Split ClientApiRow into LiveRow/DiagRow (or trim WS payload)
1. Audit which 10 fields the frontend actually reads from WS messages
2. Create a `WsLiveRow` TypedDict with only those 10 fields
3. Keep full `ClientApiRow` for the REST API path
4. In the WS broadcast code, construct `WsLiveRow` from the full state instead of
   serializing the entire `ClientApiRow`
5. Update the WS contract types to match the trimmed payload
6. Verify the frontend works correctly with the reduced payload
7. Measure: this should reduce WS message size significantly (13 fewer fields)

## Dependencies on Earlier/Later Chunks
- **Depends on Chunk 4**: The unified `make regen-contracts` command from Chunk 4 should
  be in place before adding more contract generation steps here.
- **Depends on Chunk 1**: Location codes use the shared contracts pattern established in
  the codebase. Chunk 1 doesn't touch this, so no direct dependency, but the repo-map
  updates from Chunk 1 should be done first.
- The regression directory dissolution is independent of all other chunks.
- ClientApiRow trimming is independent but should go last within this chunk (highest risk).

## Risks and Tradeoffs
- **Regression directory dissolution**: No functional risk — only test file locations change.
  But merge conflicts are likely if other branches touch regression tests. Move quickly.
- **fault_scenarios consolidation**: Low risk — pass-through removal is mechanical. The
  `fault_phase` merge requires careful parameter alignment.
- **WS contract generation**: Medium risk — changing the generation tool may produce
  slightly different TypeScript types. Need thorough type-check verification.
- **Location codes unification**: Low risk if `location_codes.json` already exists. Medium
  risk if creating it fresh (must verify no consumer depends on the Python/TS ordering).
- **ClientApiRow split**: HIGHEST RISK in this chunk. If any frontend code reads an
  "unused" field that wasn't caught in the audit, the dashboard will break. Must do a
  thorough grep of all frontend WS message consumers. Consider making the change backward-
  compatible first (send both shapes, verify, then remove old shape).

## Validation Steps
1. `ruff check apps/server/` — lint passes
2. `make typecheck-backend` — type checking passes
3. `cd apps/ui && npm run typecheck` — frontend type checking passes
4. `pytest -q apps/server/tests/` — ALL tests pass (regression tests moved, not deleted)
5. `make test-all` — full CI parity suite passes
6. `cd apps/ui && npm run build` — frontend builds successfully
7. Grep for `tests/regression` or `regression/` imports — zero matches (fully dissolved)
8. Grep for removed pass-through function names — zero matches
9. `make sync-contracts` — contract sync works
10. Docker smoke test: `docker compose build --pull && docker compose up -d` then
    `vibesensor-sim --count 5 --duration 10 --no-interactive`

## Required Documentation Updates
- `docs/testing.md` — remove regression directory section, update layout guidance
- `apps/server/tests/regression/README.md` — delete
- `docs/ai/repo-map.md` — update test layout description
- `docs/protocol.md` — update if WS payload schema changes

## Required AI Instruction Updates
- `.github/instructions/tests.instructions.md` — add guidance that regression tests go
  in feature directories, not a separate regression/ directory
- Add guidance: "Do not create category-based test directories (regression/, integration/);
  use feature-based directories that mirror source modules"
- Add guidance: "Do not add pass-through builder functions; call the underlying builder
  directly"
- Add guidance: "Use shared contracts JSON for cross-language data definitions"

## Required Test Updates
- All moved test files should pass in their new locations
- Remove fragile regex-based location code sync test
- Add simpler shared-contract-based sync test (or remove if shared source eliminates need)
- Update frontend tests if WS payload shape changes
- Run Playwright smoke tests after ClientApiRow changes

## Simplification Crosswalk

### A6-2/A10-1 → Dissolve regression/ into feature directories
- Validation: CONFIRMED (28 files across 4 subdirs, split ownership)
- Root cause: Category-based layout conflicts with feature-based convention
- Steps: Move files to matching feature dirs, update imports, delete regression/
- Code areas: tests/regression/**, tests/{analysis,report,history,api}/**
- What can be removed: Entire tests/regression/ directory + README
- Verification: All tests pass in new locations, no regression/ imports

### A6-1 → Consolidate fault scenario builders
- Validation: CONFIRMED (2 pass-throughs, fault_phase duplication)
- Root cause: Incremental builder growth
- Steps: Remove pass-throughs, merge fault_phase
- Code areas: test_support/fault_scenarios.py, test_support/scenario_ground_truth.py
- What can be removed: 2 pass-through functions, duplicated fault_phase
- Verification: All scenario tests pass

### A6-3 → Simplify assertion namespace
- Validation: CONFIRMED (3 files, unclear boundaries, inconsistent imports)
- Root cause: Organic growth without ownership rules
- Steps: Audit symbols, establish boundaries, standardize imports
- Code areas: test_support/__init__.py, test_support/core.py
- What can be removed: Unnecessary re-exports, misplaced functions
- Verification: All tests pass with updated imports

### A9-1 → Simplify WS contract generation
- Validation: CONFIRMED (JSON Schema → fake OpenAPI → TS pipeline)
- Root cause: Wrong tool reused for different use case
- Steps: Replace pipeline with direct JSON Schema → TS, remove OpenAPI shim
- Code areas: tools/config/ generation scripts
- What can be removed: Fake OpenAPI envelope construction, temp file management
- Verification: Generated TS types match, frontend typechecks pass

### A9-2 → Unify location codes to shared JSON
- Validation: CONFIRMED (dual-source, fragile regex test)
- Root cause: Pre-shared-contracts dual maintenance
- Steps: Use/create shared JSON, update Python/TS, remove regex test
- Code areas: locations.py, constants.ts, libs/shared/contracts/
- What can be removed: Hardcoded location arrays, fragile sync test
- Verification: make sync-contracts works, both languages see same codes

### A5-1 → Trim ClientApiRow for WS (split LiveRow/DiagRow)
- Validation: CONFIRMED (13/23 fields unused by frontend on WS)
- Root cause: One-size-fits-all type for REST + WS
- Steps: Create WsLiveRow with 10 used fields, broadcast trimmed payload
- Code areas: payload_types.py, ws_models.py, UI WS consumers
- What can be removed: 13 unused fields from WS payload
- Verification: Frontend works, WS messages smaller, Playwright tests pass
