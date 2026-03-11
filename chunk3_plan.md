# Chunk 3: Persistence & Report Data Flow Simplification

## Overview
The persistence and report layers have accumulated unnecessary complexity through triple-
maintained column lists, unnecessary SensorFrame round-trips on DB-sourced samples, a redundant
second DB query hidden behind `getattr` duck-typing, and an 11-type conversion ceremony for
the report pipeline. This chunk consolidates the samples_v2 schema source of truth, removes
the SensorFrame round-trip for DB samples, inlines the `analysis_is_current` check, and
simplifies the `ReportTemplateData` conversion machinery.

## Mapped Findings

### Finding 1: samples_v2 column list triple-maintenance (A4-1)
- **Original**: Subagent 4 finding 1
- **Validation result**: CONFIRMED. The 26 data columns are maintained in 3 places:
  1. DDL string in `_schema.py:60-87` (SQL definition)
  2. `_V2_TYPED_COLS` + `_V2_PEAK_COLS` in `_samples.py:30-57` (Python tuples for INSERT/SELECT)
  3. `EXPORT_CSV_COLUMNS` in `exports.py:32-57` (CSV export ordering)
  Column ordering differs between exports and the other two. A hygiene test
  (`test_sample_column_alignment.py`) verifies set-equality but not order, so ordering
  discrepancies are undetectable. The docs (`history_db_schema.md`) have already drifted.
- **Validated root cause**: Concern separation (DDL vs serialization vs export) assumed
  independence, but all three are coupled to the same schema fact.

### Finding 2: Unnecessary SensorFrame round-trip for DB samples (A4-2)
- **Original**: Subagent 4 finding 2
- **Validation result**: CONFIRMED. In `post_analysis.py:235-240`, every sample from
  `db.iter_run_samples()` passes through `normalize_sample_record()` which constructs a
  `SensorFrame` then calls `.to_dict()`. `v2_row_to_dict()` in `_samples.py:119-141`
  already produces correctly typed output. The round-trip adds `record_type` and
  `schema_version` keys that are never read by analysis code (confirmed: zero matches
  for these keys in `vibesensor/analysis/`). On a Pi 3A+ with 12,000 samples, this
  means 12,000 unnecessary SensorFrame constructions + dict merges.
- **Validated root cause**: `normalize_sample_record()` was designed for the JSONL read path
  where raw records can contain string-encoded numbers. It was reused on the DB path without
  recognizing that DB output is already typed.

### Finding 3: analysis_is_current redundant DB query (A4-3)
- **Original**: Subagent 4 finding 3
- **Validation result**: CONFIRMED. `get_insights()` in `runs.py:42-71` first loads the
  full run via `async_require_run()` which calls `db.get_run()` including `analysis_version`
  in the returned dict (at `__init__.py:515`). Then separately dispatches
  `getattr(self._history_db, "analysis_is_current", None)` which issues a second
  `SELECT analysis_version FROM runs WHERE run_id = ?` — reading the same column already
  loaded. The `getattr` guard on a statically typed `HistoryDB` class serves no purpose
  (the method always exists).
- **Validated root cause**: `analysis_is_current` was added as a post-hoc check without
  noticing the run dict already contained the same data.

### Finding 4: ReportTemplateData conversion ceremony (A1-2)
- **Original**: Subagent 1 finding 2
- **Validation result**: CONFIRMED. The conversion pipeline from `SummaryData` to
  `ReportTemplateData` uses 11 named types: 2 private pipeline contexts in `mapping.py`
  (`ReportMappingContext` with 12 fields, `PrimaryCandidateContext` with 17 fields), 8
  component dataclasses in `report_data.py` (CarMeta, ObservedSignature, PartSuggestion,
  SystemFindingCard, NextStep, DataTrustItem, PatternEvidence, PeakRow), and
  `ReportTemplateData` itself. A `_FromDictMixin` framework with `_valid_field_names()`
  (lru_cache) and `_filter_fields()` supports `from_dict()` on 6 of the 8 component
  classes. The `_FromDictMixin` has zero consumers outside `report_data.py`.
- **Validated root cause**: The boundary between analysis output and PDF renderer was designed
  as a full typed-object conversion, but both source (`SummaryData` TypedDict with Optional/
  NotRequired fields) and target (dataclasses with Optional defaults) independently handle
  missing fields, making the conversion framework redundant.

## Root Causes Behind These Findings
1. Schema facts coupled across 3 files with no single source of truth
2. Path-inappropriate normalization (JSONL normalizer applied to DB path)
3. Post-hoc queries that duplicate data already loaded
4. Over-engineered type conversion for a single-consumer pipeline

## Relevant Code Paths and Components

### Column list consolidation
- `apps/server/vibesensor/history_db/_schema.py` — DDL definition
- `apps/server/vibesensor/history_db/_samples.py` — V2_TYPED_COLS, V2_PEAK_COLS, INSERT/SELECT SQL
- `apps/server/vibesensor/history_services/exports.py` — EXPORT_CSV_COLUMNS
- `apps/server/tests/hygiene/test_sample_column_alignment.py` — sync verification

### SensorFrame round-trip removal
- `apps/server/vibesensor/metrics_log/post_analysis.py` — normalize_sample_record call
- `apps/server/vibesensor/runlog.py` — normalize_sample_record definition
- `apps/server/vibesensor/history_db/_samples.py` — v2_row_to_dict

### analysis_is_current removal
- `apps/server/vibesensor/history_services/runs.py` — get_insights(), getattr pattern
- `apps/server/vibesensor/history_db/__init__.py` — analysis_is_current method
- `apps/server/vibesensor/history_db/_schema.py` — ANALYSIS_SCHEMA_VERSION constant

### Report mapping simplification
- `apps/server/vibesensor/report/report_data.py` — dataclasses + _FromDictMixin
- `apps/server/vibesensor/report/mapping.py` — mapping pipeline + context classes
- `apps/server/vibesensor/report/pdf_engine.py` — consumer of ReportTemplateData

## Simplification Approach

### Step 1: Derive EXPORT_CSV_COLUMNS from _samples.py
1. In `exports.py`, import `_V2_TYPED_COLS` and `_V2_PEAK_COLS` from `history_db._samples`
2. Derive `EXPORT_CSV_COLUMNS` as `list(_V2_TYPED_COLS) + list(_V2_PEAK_COLS) + ["extras"]`
   (or whatever ordering matches the current export behavior — verify order expectations)
3. The DDL in `_schema.py` stays as-is (SQL DDL is naturally a separate artifact that must
   be literal)
4. Update the hygiene test to verify column order agreement, not just set equality

### Step 2: Remove SensorFrame round-trip for DB path
1. In `post_analysis.py`, remove `normalize_sample_record(sample)` from the DB sample
   iterator
2. Use `v2_row_to_dict` output directly (it's already typed)
3. Keep `normalize_sample_record` in `runlog.py` for the JSONL path (it's still needed there)
4. Verify no analysis code depends on `record_type` or `schema_version` keys being present

### Step 3: Remove analysis_is_current method and inline the check
1. In `runs.py:get_insights()`, replace the `getattr`/`analysis_is_current` call with:
   `analysis["analysis_is_current"] = int(run.get("analysis_version") or 0) >= ANALYSIS_SCHEMA_VERSION`
2. Import `ANALYSIS_SCHEMA_VERSION` from `history_db._schema`
3. Remove `analysis_is_current()` method from `HistoryDB` class
4. Update any test doubles that stub this method

### Step 4: Simplify ReportTemplateData conversion
1. Remove `_FromDictMixin`, `_filter_fields()`, `_valid_field_names()` from
   `report_data.py` — these are a custom framework with zero consumers outside this file
2. On each dataclass that used `_FromDictMixin`, replace `from_dict()` classmethod with
   direct keyword construction in `mapping.py` (the builder functions already have all the
   data extracted; they don't need a second `from_dict` step)
3. Simplify `ReportMappingContext` — if the 12-field frozen dataclass is only instantiated
   once by `prepare_report_mapping_context()` and consumed immediately, consider using local
   variables or a simpler NamedTuple instead
4. Keep `PrimaryCandidateContext` (17 fields) — it has enough fields to justify a named
   container, but consider if it can be a NamedTuple
5. Keep all 8 component dataclasses (they serve as typed contracts for the PDF renderer)
   but strip the `from_dict()` methods that aren't needed when construction happens in
   `mapping.py` already

## Dependencies on Earlier/Later Chunks
- **Depends on Chunk 1**: The confidence field rename (`confidence_0_to_1` → `confidence`)
  affects `extract_confidence()` in `report/mapping.py`. This chunk simplifies that function
  further. Chunk 1 must complete first.
- No dependencies on Chunk 2, 4, or 5.

## Risks and Tradeoffs
- **EXPORT_CSV_COLUMNS ordering**: If any consumer depends on the specific column order of
  the CSV export, deriving from `_V2_TYPED_COLS` may change the order. Need to verify and
  preserve existing order or document the change.
- **SensorFrame round-trip removal**: The JSONL path still needs `normalize_sample_record`.
  Only the DB path is changed. This is clean separation.
- **analysis_is_current removal**: The method is simple enough that inlining it is zero-risk.
  Test doubles that stub it must be updated.
- **ReportTemplateData simplification**: The `from_dict()` methods handle schema evolution
  for older persisted runs. After removing them, the `mapping.py` builder functions must
  handle missing/optional fields explicitly. This is already the case since the builder
  functions already use `.get()` with defaults.

## Validation Steps
1. `ruff check apps/server/` — lint passes
2. `make typecheck-backend` — type checking passes
3. `pytest -q apps/server/tests/history/` — history tests pass
4. `pytest -q apps/server/tests/report/` — report tests pass
5. `pytest -q apps/server/tests/metrics_log/` — metrics log tests pass
6. `pytest -q apps/server/tests/hygiene/` — hygiene tests pass (column alignment)
7. `pytest -q apps/server/tests/regression/report/` — report regression tests pass
8. Grep for `analysis_is_current` — zero matches in production code (only in test migration)
9. Grep for `normalize_sample_record` in post_analysis.py — zero matches

## Required Documentation Updates
- `docs/history_db_schema.md` — correct any drifted column documentation
- `docs/ai/repo-map.md` — update history_db description if methods change

## Required AI Instruction Updates
- Add guidance to derive column lists from a single source rather than maintaining parallels
- Add guidance against applying normalization functions to already-normalized data paths
- Add guidance against `getattr` duck-typing on concrete typed dependencies

## Required Test Updates
- Update `test_sample_column_alignment.py` to verify column order agreement
- Update/remove test doubles for `analysis_is_current`
- Verify post-analysis tests still pass without SensorFrame round-trip

## Simplification Crosswalk

### A4-1 → Single source of truth for samples_v2 columns
- Validation: CONFIRMED (3 files, ordering discrepancy, set-only test)
- Root cause: Assumed independence of DDL/serialization/export
- Steps: Derive EXPORT_CSV_COLUMNS from _samples.py tuples, add order test
- Code areas: exports.py, _samples.py, test_sample_column_alignment.py
- What can be removed: Hardcoded EXPORT_CSV_COLUMNS list
- Verification: Hygiene tests pass with order check

### A4-2 → Remove SensorFrame round-trip for DB samples
- Validation: CONFIRMED (unnecessary construction + dict merge per sample)
- Root cause: JSONL normalizer reused on typed DB output
- Steps: Remove normalize_sample_record from DB path in post_analysis.py
- Code areas: post_analysis.py
- What can be removed: normalize_sample_record call on DB samples (~5 lines)
- Verification: Post-analysis tests pass, analysis results unchanged

### A4-3 → Inline analysis_is_current check
- Validation: CONFIRMED (redundant DB query + getattr on concrete class)
- Root cause: Post-hoc check that duplicated already-loaded data
- Steps: Inline comparison in get_insights(), remove method from HistoryDB
- Code areas: runs.py, history_db/__init__.py
- What can be removed: analysis_is_current method, getattr pattern
- Verification: API tests pass, insights endpoint returns same data

### A1-2 → Simplify ReportTemplateData conversion
- Validation: CONFIRMED (11 intermediate types, _FromDictMixin framework)
- Root cause: Over-engineered type boundary for single-consumer pipeline
- Steps: Remove _FromDictMixin framework, simplify dataclass from_dict methods
- Code areas: report_data.py, mapping.py
- What can be removed: _FromDictMixin, _filter_fields, _valid_field_names, from_dict methods
- Verification: Report tests pass, PDF output unchanged
