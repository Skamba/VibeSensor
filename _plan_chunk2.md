# Chunk 2: Backend Module Consolidation

## Execution order: 2 of 5

## Mapped Findings

| ID | Original Finding | Validation Result |
|----|-----------------|-------------------|
| A1 | `analysis/` micro-file fragmentation (29 files, single-consumer modules, 4-deep findings chain) | CONFIRMED — `findings_order_assembly.py` (1 function, 1 consumer), `summary_models.py` (1 dataclass, 1 consumer), `findings_reference_checks.py` (1 function, 1 consumer), `findings_builder_support.py` (6 functions, 1 consumer). `findings_speed_profile.py` has 3 consumers — NOT single-consumer, keep separate. `plot_data.py` has 5 pure delegation wrappers that just forward to `plot_spectrum` and `plot_peak_table`. |
| A2 | `report/` single-consumer section files + nano-files (18 files) | CONFIRMED — `pdf_page1.py` has 7 forwarding wrappers importing from `pdf_page1_sections.py`. `pdf_page2.py` has 5 forwarding wrappers from `pdf_page2_sections.py`. `pdf_helpers.py` (2 functions, 1 consumer). `pdf_layout.py` (2 functions, 1 consumer). All 4 satellite files have exactly 1 production consumer each. |
| A3 | `processing/views.py` pure-delegation single-consumer class | CONFIRMED — `SignalProcessorViews` (200 lines, 10 methods) used only by `processor.py`. 5 methods on `processor.py` are one-liner delegations to `self._views.*`. Class never imported/instantiated elsewhere. |
| B4 | `HistoryExportArchiveBuilder` single-consumer wrapper class | CONFIRMED — Used only by `HistoryExportService` in production (same file). Has 1 test consumer (`test_history_http_services.py`) that tests it directly. Constructor + 1 method. |

## Root Causes

Incremental extraction refactoring produced increasingly small modules that fell below the minimum viable size. The analysis/ package grew by pulling functions into separate files without periodically re-evaluating consolidation. The report/ page/sections split was a file-size management strategy that introduced forwarding-only wrappers. The processing/views split tried to separate "compute" from "payload building" but ended up as pure delegation.

## Relevant Code Paths

### A1: analysis/ modules to merge
- `apps/server/vibesensor/analysis/findings_order_assembly.py` — 1 function `assemble_order_finding`, ~218 lines
- `apps/server/vibesensor/analysis/findings_order_findings.py` — sole consumer of `assemble_order_finding`
- `apps/server/vibesensor/analysis/summary_models.py` — 1 dataclass `PreparedRunData`, ~40 lines
- `apps/server/vibesensor/analysis/summary_builder.py` — sole consumer of `PreparedRunData`
- `apps/server/vibesensor/analysis/findings_reference_checks.py` — 1 function `_reference_missing_finding` + 2 constant dicts, ~46 lines
- `apps/server/vibesensor/analysis/findings_builder_support.py` — sole consumer of `_reference_missing_finding`
- `apps/server/vibesensor/analysis/plot_data.py` — 5 delegation wrappers + 1 orchestrator `_plot_data`, ~198 lines
- `apps/server/vibesensor/analysis/plot_spectrum.py` — actual implementation of spectrum functions
- `apps/server/vibesensor/analysis/plot_peak_table.py` — actual implementation of peak table functions
- Tests: `test_report_analysis_localization_integration.py`, `test_report_scenario_output_regression.py`, `test_findings_builder_support.py`

### A2: report/ modules to merge
- `apps/server/vibesensor/report/pdf_page1.py` — 7 forwarding wrappers + page orchestrator
- `apps/server/vibesensor/report/pdf_page1_sections.py` — 8 section render functions
- `apps/server/vibesensor/report/pdf_page2.py` — 5 forwarding wrappers + page orchestrator
- `apps/server/vibesensor/report/pdf_page2_sections.py` — 5 section render functions
- `apps/server/vibesensor/report/pdf_helpers.py` — 2 functions (`_canonical_location`, `_source_color`)
- `apps/server/vibesensor/report/pdf_layout.py` — 2 functions (`fit_rect_preserve_aspect`, `assert_aspect_preserved`)
- `apps/server/vibesensor/report/pdf_diagram_render.py` — sole consumer of `pdf_helpers.py`
- Tests: `test_runtime_nan_and_update_guard_regressions.py` imports from `pdf_helpers`, `test_report_new_modules_pdf_layout.py` imports from `pdf_layout`

### A3: processing/views.py
- `apps/server/vibesensor/processing/views.py` — `SignalProcessorViews` class
- `apps/server/vibesensor/processing/processor.py` — sole consumer, 5 delegation methods

### B4: HistoryExportArchiveBuilder
- `apps/server/vibesensor/history_services/exports.py` — both classes in same file
- `apps/server/tests/history_services/test_history_http_services.py` — direct test consumer

## Simplification Approach

### A1: Merge analysis/ micro-files (29 → ~24 files)

**Step 1**: Merge `findings_order_assembly.py` into `findings_order_findings.py`
- Move `assemble_order_finding()` function into `findings_order_findings.py`
- Update the import within `findings_order_findings.py` from external to local
- Update test import in `test_report_analysis_localization_integration.py`
- Delete `findings_order_assembly.py`

**Step 2**: Merge `summary_models.py` into `summary_builder.py`
- Move `PreparedRunData` dataclass to top of `summary_builder.py`
- Remove the import line
- Delete `summary_models.py`

**Step 3**: Merge `findings_reference_checks.py` into `findings_builder_support.py`
- Move `_REF_MISSING`, `_REF_MISSING_AMPLITUDE` dicts and `_reference_missing_finding()` function
- Update imports
- Update test import in `test_report_scenario_output_regression.py`
- Delete `findings_reference_checks.py`

**Step 4**: Eliminate `plot_data.py` delegation wrappers
- In `plot_data.py`, the orchestrator function `_plot_data()` calls 5 wrapper functions that just delegate. Replace with direct calls to `plot_spectrum.*` and `plot_peak_table.*`
- Keep `_plot_data()` as the orchestrator but inline calls
- OR: move `_plot_data()` into `summary_builder.py` (its primary consumer) and delete `plot_data.py` entirely
- Update `_types.py` if it imports `PlotDataResult` from `plot_data`

**NOT merging**: `findings_speed_profile.py` — has 3 consumers, justified as a standalone utility module.

### A2: Merge report/ nano-files (18 → ~12 files)

**Step 1**: Merge `pdf_page1_sections.py` into `pdf_page1.py`
- Move all 8 section render functions into `pdf_page1.py`
- Remove the 7 forwarding wrappers and `_impl` aliases
- Replace wrapper calls with direct section function calls
- Delete `pdf_page1_sections.py`

**Step 2**: Merge `pdf_page2_sections.py` into `pdf_page2.py`
- Same approach as Step 1
- Delete `pdf_page2_sections.py`

**Step 3**: Merge `pdf_helpers.py` into `pdf_diagram_render.py`
- Move `_canonical_location()` and `_source_color()` into `pdf_diagram_render.py`
- Update test import in `test_runtime_nan_and_update_guard_regressions.py`
- Delete `pdf_helpers.py`

**Step 4**: Merge `pdf_layout.py` into `pdf_page2.py` (since `pdf_page2_sections.py` is now merged there)
- Move `fit_rect_preserve_aspect()` and `assert_aspect_preserved()` 
- Update test import in `test_report_new_modules_pdf_layout.py`
- Delete `pdf_layout.py`

### A3: Inline processing/views.py

**Step 1**: Move all methods from `SignalProcessorViews` into `SignalProcessor`
- Copy method bodies into `processor.py`
- Methods that access `self._store` and `self._metrics` can use the same attributes since `SignalProcessor` already owns them
- Replace 5 delegation methods with the actual implementation code
- Add a comment section `# --- Payload / view methods ---` for readability

**Step 2**: Remove `SignalProcessorViews` instantiation from `SignalProcessor.__init__`
- Delete `self._views = SignalProcessorViews(...)` line

**Step 3**: Delete `views.py`
- Update `processing/__init__.py` if it re-exports anything from views

### B4: Inline HistoryExportArchiveBuilder

**Step 1**: Move `build_zip_file()` method into `HistoryExportService`
- Rename to `_build_zip_file()` (private)
- Wire `self._history_db` directly (already available on the service)

**Step 2**: Update `build_export()` to call `self._build_zip_file(...)` instead of `self._archive_builder.build_zip_file(...)`

**Step 3**: Remove `HistoryExportArchiveBuilder` class and its construction in `__init__`

**Step 4**: Update test in `test_history_http_services.py` to test through `HistoryExportService` instead of `HistoryExportArchiveBuilder` directly

## Implementation Sequence

1. A1 (analysis/ merges) — largest, most impactful
2. A2 (report/ merges) — second largest
3. A3 (processing/views.py) — straightforward
4. B4 (HistoryExportArchiveBuilder) — quick, one file

## Dependencies on Other Chunks

- Chunk 1 dissolves `contracts.py` — no dependency on this chunk
- Chunk 3 changes `MetricsLogger` and `update/workflow.py` — no dependency on analysis/report/processing changes
- Test imports will change — tests in Chunk 5 (T1, T2) may need minor adjustments if they import from merged modules

## Risks and Tradeoffs

- **A1**: Large merge in analysis/ may cause merge conflicts if other work touches these files. Mitigated by doing it early.
- **A2**: Report files are complex (PDF rendering with coordinates). Must verify PDF output is unchanged by running report tests.
- **A3**: `processor.py` will grow by ~200 lines. Still reasonable for a primary class file. The conceptual separation is preserved via comment sections.
- **B4**: Test change required — the test that directly tests `HistoryExportArchiveBuilder` must be updated to test through `HistoryExportService`.

## Validation Steps

1. `pytest -q apps/server/tests/analysis/` — all analysis tests
2. `pytest -q apps/server/tests/report/` — all report tests
3. `pytest -q apps/server/tests/history_services/` — export tests
4. `make lint && make typecheck-backend`
5. Full suite: `python3 tools/tests/run_ci_parallel.py --job backend-tests`

## Required Documentation Updates

- Update `docs/ai/repo-map.md` to reflect reduced file counts in analysis/ and report/
- Update any references to deleted file names in docs/

## Required AI Instruction Updates

- Add to `.github/instructions/general.instructions.md` complexity hygiene section:
  - "Do not extract single-function or single-consumer modules. Keep functions in their consumer's module until 3+ distinct consumers exist."
  - "Do not create forwarding-wrapper modules that alias imports with no added logic."
  - "Prefer few large focused modules over many tiny single-purpose modules."

## Required Test Updates

- `test_report_analysis_localization_integration.py` — update import from `findings_order_assembly` to `findings_order_findings`
- `test_report_scenario_output_regression.py` — update import from `findings_reference_checks` to `findings_builder_support`
- `test_runtime_nan_and_update_guard_regressions.py` — update import from `pdf_helpers` to `pdf_diagram_render`
- `test_report_new_modules_pdf_layout.py` — update import from `pdf_layout` to `pdf_page2`
- `test_history_http_services.py` — update test to use `HistoryExportService`
- `test_findings_builder_support.py` — may need import updates

## Simplification Crosswalk

| Finding | Validation | Root Cause | Steps | Areas Changed | What's Removed | Verification |
|---------|-----------|------------|-------|---------------|----------------|--------------|
| A1 | CONFIRMED (4 single-consumer modules in 29-file package) | Incremental extraction without consolidation review | Merge 3 single-consumer modules + eliminate 5 delegation wrappers in plot_data | findings_order_assembly→findings_order_findings, summary_models→summary_builder, findings_reference_checks→findings_builder_support, plot_data simplified | 3-4 files (~300 lines of module overhead) | analysis tests pass, imports resolve |
| A2 | CONFIRMED (4 single-consumer modules in 18-file package) | File-size management split that created forwarding-only wrappers | Merge sections→pages, merge nano-files into consumers | pdf_page1_sections→pdf_page1, pdf_page2_sections→pdf_page2, pdf_helpers→pdf_diagram_render, pdf_layout→pdf_page2 | 4 files (~150 lines of forwarding boilerplate) | report tests pass, PDF output unchanged |
| A3 | CONFIRMED (pure-delegation class with 1 consumer) | Extraction for size management | Move methods into SignalProcessor, delete views.py | processing/views.py→processor.py | 1 file, ~200 lines of delegation overhead | processing tests pass |
| B4 | CONFIRMED (single-consumer wrapper class in same file) | Refactor split for threading boundary visibility | Inline _build_zip_file into HistoryExportService | history_services/exports.py | 1 class (~25 lines of scaffolding) | export tests pass |
