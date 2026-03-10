# Chunk 5: Persistence, Config & Documentation

## Mapped Findings

- [4.1] Four parallel peak columns with identical serialization
- [4.2] read_transaction() redundant API with getattr fallback in caller
- [4.3] get_run_analysis and get_run_status have zero production callers
- [10.2] AI guidance file chain: 10 surfaces, 3 redirects, measurable drift
- [8.2] Processing config section has 11 knobs never overridden from defaults
- [8.3] config.dev.yaml and config.docker.yaml share 3/4 identical fields

## Validation Outcomes

### [4.1] PARTIALLY REFUTED — reduced scope
The 4 peak columns DO exist as separate TEXT columns, and `_V2_PEAK_COLS` drives them. However, the serialization is already consolidated into a single loop per direction (not "four separate identical loops" as the subagent implied). The code is already reasonably factored; the question is whether 4 separate columns vs. 1 JSON column is better.

**Revised decision**: REMOVE from this chunk. The serialization code is already consolidated. The schema change (4 columns → 1) requires a migration for existing databases, and the complexity reduction is marginal since the loop already handles it cleanly. Cost exceeds benefit.

### [4.2] CONFIRMED with nuance (MEDIUM-HIGH confidence)
`read_transaction()` exists at line 118. It acquires the RLock, creates a cursor, issues `BEGIN`, yields `None` (not the cursor), commits on exit. The only production caller in `post_analysis.py` uses `getattr(db, "read_transaction", None)` with a `nullcontext()` fallback.

**Nuance**: The RLock and SQL `BEGIN` serve complementary purposes — RLock prevents Python thread interleaving, `BEGIN` creates a SQLite WAL snapshot. However, since the system uses a single connection managed by the RLock, the RLock already serializes all operations. The `getattr` fallback is a code smell regardless.

**Decision**: Remove `read_transaction()` and the `getattr` guard. The RLock serialization is sufficient.

### [4.3] CONFIRMED (HIGH confidence)
Both `get_run_analysis()` and `get_run_status()` have zero production callers. Used only in test files. `get_run()` already returns both `status` and `analysis` fields.

### [10.2] CONFIRMED (HIGH confidence)
11 AI guidance files total: AGENTS.md, CLAUDE.md, .github/copilot-instructions.md, 7 instruction files, docs/ai/repo-map.md. Two redirect hops (CLAUDE.md → AGENTS.md → copilot-instructions.md). `docs.instructions.md` (8 lines), `infra.instructions.md` (9 lines) have minimal delta content. `backend.instructions.md` has stale references (mentions `history_helpers.py` as standalone file — now inside `history_services/`).

### [8.2] CONFIRMED (MEDIUM confidence)
11 processing config knobs, all use hardcoded defaults, none overridden in any deployment config. `__post_init__` has 9 validation checks in ~90 lines.

**Revised decision**: KEEP IN SCOPE but with conservative approach. Rather than removing config fields (which could break custom deployments), convert the 7 fields that are truly hardware-coupled constants (`sample_rate_hz=800`, `fft_n=2048`, `waveform_seconds=8`, `accel_scale_g_per_lsb=None`, `waveform_display_hz=50`, `fft_update_hz=4`, `client_ttl_seconds=5`) to Python constants with config-override capability preserved. Simplify the validation proportionally.

Actually, on further reflection, this changes the config schema and adds risk for marginal benefit. **REVISED DECISION**: Mark as OUT OF SCOPE. The config knobs are legitimate even if never overridden — they document tunable parameters. The validation code, while long, prevents misconfigurations. Removing them risks breaking custom deployments with no concrete payoff.

### [8.3] CONFIRMED (MEDIUM confidence)
`config.dev.yaml` is a strict subset of `config.docker.yaml` — all 3 dev lines appear verbatim in docker.yaml. Docker adds 2 container-specific overrides.

**Revised decision**: OUT OF SCOPE. The files are 5-8 lines each. The duplication is minimal. Merging requires either a config system change or documentation to explain why one file covers both use cases. Cost exceeds benefit.

## Findings Remapped or Removed

- **[4.1] REMOVED** — serialization is already well-factored. Schema change cost exceeds benefit.
- **[8.2] OUT OF SCOPE** — config knobs are legitimate documentation of tunable parameters. Validation prevents misconfiguration.
- **[8.3] OUT OF SCOPE** — minimal duplication in tiny files. Not worth the merge effort.

## Remaining Active Findings

- [4.2] Remove read_transaction()
- [4.3] Remove get_run_analysis() and get_run_status()
- [10.2] Consolidate AI guidance files

## Root Complexity Drivers

1. **API surface accumulation**: `HistoryDB` gained convenience methods that were never used in production, only tests. The API surface grew without production need.

2. **Defensive duck-typing**: The `getattr` + `nullcontext()` pattern in `post_analysis.py` treats an internal API as uncertain, adding fragility.

3. **Guidance file proliferation**: Each concern got its own guidance file. Redirect chains (CLAUDE.md → AGENTS.md → copilot-instructions.md) add hops without content. Small-delta files (docs.instructions.md, infra.instructions.md) don't justify separate `applyTo` scoping.

## Simplification Strategy

### Step 1: Remove unused HistoryDB methods

**Implementation:**
1. Delete `get_run_analysis()` from `HistoryDB` in `history_db/__init__.py`
2. Delete `get_run_status()` from `HistoryDB` in `history_db/__init__.py`
3. Update test callers:
   - In `test_metrics_log_helpers.py`: Replace `db.get_run_analysis(run_id)` with `db.get_run(run_id).get("analysis")`
   - In `test_metrics_log_helpers.py`: Replace `db.get_run_status(run_id)` with `db.get_run(run_id)["status"]`
   - In `test_coverage_gap_audit_round2.py`: Replace similarly
   - In `test_history_db_lifecycle.py`: Replace similarly
   - In `test_history_db_structured_storage.py`: Replace similarly
   - In `test_analysis_persistence.py`: Replace similarly
   - In `test_metrics_logger_lifecycle.py`: Replace similarly
4. Note: `get_run_analysis` has a subtle `AND status = 'complete'` SQL filter. Replace with explicit assertion in test: fetch run, check status, check analysis.

### Step 2: Remove read_transaction()

**Implementation:**
1. Delete `read_transaction()` context manager from `HistoryDB` in `history_db/__init__.py`
2. In `post_analysis.py`: Remove the `getattr`/`nullcontext` guard:
   ```python
   # DELETE:
   read_tx = getattr(db, "read_transaction", None)
   tx_ctx = read_tx() if callable(read_tx) else nullcontext()
   with tx_ctx:
       ...
   
   # REPLACE WITH direct call (no transaction wrapper needed):
   # Just call db.iter_run_samples() directly
   ```
3. Verify that the RLock in `_cursor()` provides sufficient serialization for the batch sample scan

### Step 3: Consolidate AI guidance files

**Implementation:**
1. **Delete CLAUDE.md** — it's a 4-line redirect to AGENTS.md
2. **Simplify AGENTS.md** — make it a 1-line pointer to copilot-instructions.md:
   ```markdown
   # Agent guidance
   See [.github/copilot-instructions.md](.github/copilot-instructions.md) for all AI guidance.
   ```
3. **Fold docs.instructions.md into general.instructions.md** — its 8 lines of documentation guidance can be a section in general
4. **Fold infra.instructions.md into general.instructions.md** — its 9 lines of infra guidance can be a section in general
5. **Fold report.instructions.md into backend.instructions.md** — report is a backend sub-concern, the 5 substantive rules fit naturally under backend guidance
6. **Fix drift in backend.instructions.md**: Update stale references to `history_helpers.py`, `history_exports.py`, `history_runs.py` → now inside `history_services/` package
7. **Update copilot-instructions.md**: After the folds, update the "Area-specific deltas" list to reflect the remaining files:
   - `general.instructions.md` (shared + docs + infra)
   - `backend.instructions.md` (backend + report)
   - `frontend.instructions.md`
   - `tests.instructions.md`
8. Result: From 10 AI guidance files → 6 (AGENTS.md, copilot-instructions.md, general.instructions.md, backend.instructions.md, frontend.instructions.md, tests.instructions.md)

### Step 4: Add anti-complexity guardrails to AI instructions

This is the step where we add concrete guidance to prevent the complexity patterns found across all 5 chunks from recurring.

**Implementation in general.instructions.md:**
Add a new section "Complexity guardrails" with specific rules:
```markdown
Complexity guardrails
- Do not create sub-packages for single-consumer, single-export modules. A flat module file is preferred until 3+ distinct consumers exist.
- Do not create Protocol types for single-implementor classes. Use the concrete type directly.
- Do not add compatibility aliases or shims when refactoring. Update all consumers directly in the same change set.
- Do not create wrapper dataclasses for one-shot operations (constructed only to call a single method and then discarded).
- Do not create separate packages for code that imports from the main server package. If it depends on vibesensor.*, it belongs inside vibesensor/.
- Do not create TypedDict mirrors of Pydantic models. Use Pydantic for HTTP boundaries and TypedDicts only for WebSocket/non-Pydantic dict construction.
- Route handlers must be thin HTTP translators. Extract business logic into service functions that are independently testable.
- Do not create duplicate API endpoints for the same operation.
- Do not create standalone Python scripts for simple pytest flag combinations. Use Makefile recipes directly.
- Do not create Makefile aliases that are documented as "use X instead". Remove the alias.
- Avoid defensive re-parsing of internally-validated data. Trust upstream validation at subsystem boundaries.
- Prefer few large modules over many tiny modules when the modules serve a single consumer.
- Do not add forward-extensibility machinery (protocols, registries, factories) until a second concrete consumer exists.
```

**Implementation in backend.instructions.md:**
Fix the stale history_* references and add backend-specific guardrails.

**Implementation in copilot-instructions.md:**
Update the canonical instruction source list to reflect the reduced set.

## Dependencies on Other Chunks

- This chunk should execute LAST — it updates documentation and guardrails that reference the state after all other chunks are complete.
- Steps 1-2 (DB cleanup) are independent of chunks 1-4.
- Step 3-4 (guidance cleanup) must happen after all code changes are done so the documentation reflects the final state.

## Risks and Tradeoffs

- **Removing get_run_analysis()**: The implicit `AND status = 'complete'` filter is a subtle behavior difference from `get_run()`. Tests must be updated to explicitly check status before accessing analysis data.
- **Removing read_transaction()**: If the RLock is not actually sufficient for cross-batch isolation under WAL mode, removing the explicit `BEGIN` could introduce rare data inconsistencies during analysis. Risk is low because the single-connection model serializes all operations.
- **AI guidance consolidation**: Fewer files means less precise `applyTo` scoping. The 8-line docs guidance will be injected for all files, not just docs/. This is acceptable — the rules are short and universally applicable.

## Validation Steps

1. `pytest -q apps/server/tests/` — all backend tests pass
2. `make lint` — ruff passes
3. `make typecheck-backend` — mypy passes
4. Verify CLAUDE.md no longer exists
5. Verify only 4 files remain in .github/instructions/ (general, backend, frontend, tests)
6. Verify no references to `get_run_analysis` or `get_run_status` in production code
7. Verify no `read_transaction` references remain

## Required Documentation Updates

- `docs/ai/repo-map.md`: Update test layout section, update guidance file references
- `.github/copilot-instructions.md`: Update instruction source list
- `AGENTS.md`: Simplify to single pointer
- All surviving instruction files: Update cross-references

## Required AI Instruction Updates

- Covered extensively in Steps 3 and 4 above

## Required Test Updates

- Update 5-7 test files that call `get_run_analysis()` or `get_run_status()` to use `get_run()` instead
- Verify test coverage for `read_transaction` scenarios still passes without the method

## Simplification Crosswalk

### [4.2] read_transaction()
- **Validation**: CONFIRMED
- **Root cause**: Redundant API with defensive getattr caller
- **Steps**: Delete method, remove getattr guard, call iter_run_samples directly
- **Code areas**: history_db/__init__.py, post_analysis.py
- **What can be removed**: ~20 lines from HistoryDB, getattr guard
- **Verification**: Analysis pipeline tests pass

### [4.3] get_run_analysis/get_run_status
- **Validation**: CONFIRMED
- **Root cause**: Convenience methods with zero production use
- **Steps**: Delete methods, update test callers to use get_run()
- **Code areas**: history_db/__init__.py, 5-7 test files
- **What can be removed**: ~30 lines from HistoryDB
- **Verification**: All tests pass with updated callers

### [10.2] AI guidance file chain
- **Validation**: CONFIRMED
- **Root cause**: File proliferation and redirect chains
- **Steps**: Delete CLAUDE.md, fold docs/infra/report instructions, fix drift, add guardrails
- **Code areas**: CLAUDE.md, AGENTS.md, .github/instructions/*.md, copilot-instructions.md
- **What can be removed**: 4 files (CLAUDE.md, docs.instructions.md, infra.instructions.md, report.instructions.md)
- **Verification**: Remaining guidance files are consistent and complete

### [4.1] Four parallel peak columns — REMOVED
- **Reason**: Serialization is already well-factored via loop. Schema migration cost exceeds benefit.

### [8.2] Processing config knobs — OUT OF SCOPE
- **Reason**: Config knobs document legitimate tunable parameters. Validation prevents misconfiguration. Not structural complexity.

### [8.3] dev/docker config duplication — OUT OF SCOPE
- **Reason**: Files are 5-8 lines. Duplication is minimal. Merge effort exceeds payoff.
