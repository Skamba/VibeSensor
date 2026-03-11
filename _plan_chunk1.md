# Chunk 1: Analysis & Report Package Consolidation

## Mapped Findings

| ID | Original Finding | Source Subagents | Validation Result |
|----|-----------------|------------------|-------------------|
| A1+I2+J1 | Analysis package 22-file fragmentation with helpers.py grab-bag, _i18n_ref misrouted, single-consumer file clusters | Architecture, Dependency, Folder Structure | **VALIDATED** — 27 files in analysis/ confirmed. 4 co-named clusters with single-consumer relationships confirmed. helpers.py has 20+ functions spanning unrelated domains. _i18n_ref confirmed in order_analysis.py, imported by 5+ non-order-analysis modules. |
| J2 | Report package 13 files for 2-page PDF, split by rendering layer | Folder Structure | **VALIDATED** — 14 files confirmed (incl __init__.py). pdf_render_context.py is a single frozen dataclass used by 2 callers. pdf_diagram_layout.py is single-consumer. theme.py and pdf_style.py split one concern across two files. |
| B2-report | One-shot frozen dataclasses in report/mapping (ReportMappingContext, PrimaryCandidateContext) | Abstraction | **VALIDATED** — ReportMappingContext and PrimaryCandidateContext are frozen dataclasses constructed and consumed within the same map_summary() call chain. PdfRenderContext is another one-shot context created via from_data() in pdf_engine. |
| C3 | Large-arity positional tuple returns in report/mapping.py | Data Flow | **VALIDATED** — extract_run_context returns a 9-tuple consumed only by prepare_report_mapping_context which immediately packs it into ReportMappingContext. resolve_primary_candidate returns a 6-tuple repacked into PrimaryCandidateContext. |
| C2-analysis | SummaryData 43-field fat dict threaded through 8+ functions | Data Flow | **REFINED** — SummaryData is a legitimate output contract. The unnecessary complexity is in intermediate tuple→dataclass roundtrips in mapping.py, not SummaryData itself. Addressed via tuple elimination (C3) and API surface expansion. |

## Root Causes

1. **Incremental file addition without consolidation**: Each feature or PR added a new file rather than extending existing ones. The analysis package grew from a few files to 27 without periodic consolidation.
2. **Premature extraction without consumer analysis**: Functions were extracted into their own files based on conceptual labels ("findings intensity" vs "findings speed profile") rather than actual consumer patterns. Single-consumer files proliferate.
3. **Rendering layer taxonomy over page ownership**: The report package was split by rendering concept (style, text, drawing, context, diagram layout) rather than by the actual page workflow that consumes them all together.
4. **Intermediary data structures without lifecycle**: Tuple returns exist as one-shot data carriers between functions in the same call chain, adding definitions with no reuse.

## Relevant Code Paths

### Analysis Package (27 files → target ~14 files)
- `vibesensor/analysis/__init__.py` — re-exports 8 symbols but external consumers bypass it
- `vibesensor/analysis/summary_builder.py` — imports from 18+ sibling modules
- `vibesensor/analysis/findings_builder.py` — 1 private function, calls findings_builder_support
- `vibesensor/analysis/findings_builder_support.py` — single consumer: findings_builder
- `vibesensor/analysis/findings_persistent.py` — single consumer: findings_builder
- `vibesensor/analysis/findings_intensity.py` — single consumer: findings_builder
- `vibesensor/analysis/findings_speed_profile.py` — 2 private helpers, single consumer
- `vibesensor/analysis/findings_order_findings.py` — single consumer pair with findings_order_analysis
- `vibesensor/analysis/findings_order_analysis.py` — already a partial consolidation of 4 files
- `vibesensor/analysis/summary_payload.py` — single consumer: summary_builder
- `vibesensor/analysis/summary_phases.py` — single consumer: summary_builder
- `vibesensor/analysis/summary_suitability.py` — single consumer: summary_builder
- `vibesensor/analysis/plot_data.py` — single consumer: summary_builder
- `vibesensor/analysis/plot_peak_table.py` — single consumer: plot_data
- `vibesensor/analysis/plot_series.py` — single consumer: plot_data
- `vibesensor/analysis/plot_spectrum.py` — single consumer: plot_data
- `vibesensor/analysis/order_analysis.py` — hosts _i18n_ref utility used by 5+ unrelated modules

### Report Package (14 files → target ~9 files)
- `vibesensor/report/pdf_render_context.py` — single class, 2 consumers → merge into pdf_style
- `vibesensor/report/pdf_diagram_layout.py` — 1 consumer → merge into pdf_diagram_render
- `vibesensor/report/theme.py` — color constants → merge into pdf_style
- `vibesensor/report/pdf_page_layouts.py` — geometry, 2 consumers → merge into pdf_style

## Simplification Approach

### Step 1: Consolidate analysis/ co-named clusters

Merge single-consumer clusters into their lead files:

1. **Findings cluster** → `findings.py`:
   Merge findings_builder.py + findings_builder_support.py + findings_persistent.py + findings_intensity.py + findings_speed_profile.py

2. **Order analysis cluster** → `order_analysis.py`:
   Merge findings_order_findings.py + findings_order_analysis.py into existing order_analysis.py

3. **Summary cluster** → `summary_builder.py` (extend existing):
   Merge summary_payload.py + summary_phases.py + summary_suitability.py into summary_builder.py

4. **Plot cluster** → `plots.py`:
   Merge plot_data.py + plot_peak_table.py + plot_series.py + plot_spectrum.py into plots.py

### Step 2: Clean up helpers.py and _i18n_ref

1. Move `_i18n_ref` from `order_analysis.py` to `_types.py`
2. Keep helpers.py but remove `_load_run` (move to summary_builder, single consumer)

### Step 3: Expand analysis/__init__.py API surface

Add symbols that report/mapping.py needs so it stops reaching into private sub-modules.

### Step 4: Consolidate report/ primitives

1. Merge theme.py into pdf_style.py
2. Merge pdf_page_layouts.py into pdf_style.py
3. Merge pdf_render_context.py into pdf_style.py
4. Merge pdf_diagram_layout.py into pdf_diagram_render.py

### Step 5: Eliminate tuple returns in mapping.py

1. Inline extract_run_context() into prepare_report_mapping_context() — build ReportMappingContext directly
2. Inline resolve_primary_candidate() into resolve_primary_report_candidate() — build PrimaryCandidateContext directly

### Step 6: Update imports everywhere

Update all imports that referenced moved symbols. Update report/mapping.py to import from analysis package API.

## Simplification Crosswalk

### A1+I2+J1 → Analysis fragmentation
- **Validation**: Confirmed — 27 files, 4 single-consumer clusters
- **Root cause**: Incremental file addition without consolidation
- **Steps**: Merge 4 clusters, clean helpers.py, expand __init__.py
- **Removable**: ~13 files (findings_builder.py, findings_builder_support.py, findings_persistent.py, findings_intensity.py, findings_speed_profile.py, findings_order_findings.py, findings_order_analysis.py, summary_payload.py, summary_phases.py, summary_suitability.py, plot_data.py, plot_peak_table.py, plot_series.py, plot_spectrum.py)
- **Verification**: All tests pass, analysis __init__.py exports unchanged

### J2 → Report fragmentation
- **Validation**: Confirmed — 14 files for 2-page PDF
- **Steps**: Merge theme→pdf_style, pdf_page_layouts→pdf_style, pdf_render_context→pdf_style, pdf_diagram_layout→pdf_diagram_render
- **Removable**: theme.py, pdf_page_layouts.py, pdf_render_context.py, pdf_diagram_layout.py
- **Verification**: PDF renders identically, all report tests pass

### B2-report → One-shot frozen dataclasses
- **Validation**: Confirmed
- **Steps**: Keep dataclasses but eliminate intermediate tuple→dataclass layer
- **Verification**: map_summary() produces identical output

### C3 → Positional tuple returns
- **Validation**: Confirmed — 9-tuple and 6-tuple intermediaries
- **Steps**: Inline extract_run_context, inline resolve_primary_candidate
- **Removable**: extract_run_context(), resolve_primary_candidate() as separate functions
- **Verification**: mapping.py functional tests pass

### C2-analysis → SummaryData fat dict
- **Validation**: Refined — legitimate contract, issue is intermediate roundtrips
- **Steps**: Addressed via C3 tuple elimination and Step 3 API expansion
- **Verification**: Report mapping tests pass

## Dependencies on Later Chunks

- Chunk 2 handles TypedDict base-class splits in _types.py (Finding/FindingRequired). This chunk does NOT touch those.
- Chunk 4 handles test reorganization. This chunk updates test imports for file moves only.

## Risks and Tradeoffs

1. **Large diff**: Merging 13+ files creates a large diff.
2. **git blame loss**: Mitigated by preserving function names.
3. **Module size growth**: Acceptable — focused concerns, just larger files.

## Validation Steps

1. `pytest -q apps/server/tests/analysis/` — all analysis tests pass
2. `pytest -q apps/server/tests/report/` — all report tests pass
3. `make lint` — no import errors
4. `make typecheck-backend` — type checking passes
5. Verify analysis/__init__.py exports unchanged
6. Verify report/mapping.py no longer imports from private analysis sub-modules

## Required Documentation Updates

- docs/ai/repo-map.md — update analysis and report module descriptions
- vibesensor/report/__init__.py — update module topology docstring

## Required AI Instruction Updates

- Add guidance to .github/instructions/general.instructions.md discouraging single-consumer file splits

## Required Test Updates

- Update all test imports that reference moved/merged modules
- No test logic changes — only import path updates
