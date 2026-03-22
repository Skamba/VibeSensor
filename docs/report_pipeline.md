# Report Generation Pipeline

## Overview

The report generation pipeline has two distinct phases:

1. **Post-stop analysis** (`vibesensor.use_cases.diagnostics`) — runs once when a recording
   ends, producing an app-level `AnalysisResult`. The serialized summary dict is
   then created at the boundary by `vibesensor.shared.boundaries.analysis_summary`
   / `vibesensor.adapters.analysis_summary`.
2. **Report rendering** (`vibesensor.adapters.pdf`) — loads the persisted
   analysis summary, re-projects domain-owned fields at the history/PDF
   boundary, rebuilds `ReportTemplateData`, and renders a PDF. This phase
   performs **zero analysis** — it only canonicalizes persisted summary data
   and formats pre-computed results.

```text
Recording stops
  → _run_post_analysis() [vibesensor.use_cases.run.post_analysis]
    → build_post_analysis_summary() [vibesensor.use_cases.run.post_analysis]
      → RunAnalysis(...).summarize() [vibesensor.use_cases.diagnostics.summary_builder]
      → run_data_preparation.py + _summary_steps.py + _summary_result.py + summary_builder.py (preparation, phases, suitability, domain/result assembly)
      → analysis_result_to_summary() [vibesensor.shared.boundaries.analysis_summary]
      → findings.py + _peak_findings.py + _reference_findings.py, peak_binning.py, signal_aggregation.py, top_cause_selection.py, plots.py, peak_table.py
    → map_summary() [vibesensor.adapters.pdf.mapping]
      → report_context.py (context assembly, card decisions) + mapping.py (thin template mapper) + peak_table.py + report_sections.py
    → store_analysis() [vibesensor.adapters.persistence.history_db]

GET /api/history/{run_id}/report.pdf [vibesensor.adapters.http.history]
  → HistoryReportService.build_pdf() [vibesensor.use_cases.history.reports]
    → prepare_history_report_analysis() [vibesensor.adapters.history]
    → _build_pdf_bytes() [vibesensor.app.container]
    → build_report_pdf(data) [vibesensor.adapters.pdf.pdf_engine]
```

## Key Architectural Rules

### Post-stop-only analysis

All diagnostic analysis (findings, ranking, phase segmentation, strength
classification, test-plan generation, order tracking) runs **once** at
post-stop time and is persisted.  Report generation **never** re-runs
analysis.

### Renderer-only report package

The `vibesensor.adapters.pdf` package contains **only** rendering code:

| File | Purpose |
|---|---|
| `pdf_engine.py` | Public PDF entrypoint, validation, pagination, and page orchestration |
| `pdf_page1.py`, `pdf_page2.py` | Page-level composition (including section renderers and aspect-ratio helpers) |
| `pdf_style.py` | Page geometry, layout calculations, color tokens, styling constants, and render context |
| `pdf_drawing.py`, `pdf_text.py` | Shared drawing and text helpers |
| `pdf_diagram_render.py` | Diagram planning, drawing, and location normalization |
| `report_data.py` | Dataclass definitions (pure data) |
| `report_context.py` | Context assembly, data-prep, card-assembly (bridges domain/use-case and adapter) |
| `mapping.py` | Thin mapper: context → `ReportTemplateData` |
| `presentation.py` | Rendering-only label helpers (strength/order/classification text) |
| `peak_table.py` | Peak-row builders for the report evidence table |
| `report_sections.py` | Next-step and data-trust section builders |
| `pattern_parts.py` | Pattern-to-parts suggestion helpers |

**Rule:** Report modules must not import from `vibesensor.use_cases.diagnostics` at
module level.  A guardrail test (`test_report_analysis_separation.py`)
enforces this.

Pure report-domain interpretation that reads domain findings/test runs but
does not perform i18n or PDF dataclass assembly lives in
`vibesensor.use_cases.history.report_interpretation`, which `report_context.py`
consumes during context assembly.  `mapping.py` itself does **not** import
from `use_cases/` — `report_context.py` bridges that boundary.

### ReportTemplateData schema

`ReportTemplateData` (defined in `vibesensor.adapters.pdf.report_data`) is the
rendering artifact.  It contains everything the PDF renderer
needs:

- **Display metadata**: title, dates, sensor info, version marker
- **Observed signature**: primary system, location, speed band, strength
- **System finding cards**: top-3 ranked findings with parts suggestions
- **Next steps**: test plan or capture guidance (tier-dependent)
- **Data trust items**: suitability checks
- **Pattern evidence**: matched systems, certainty label, interpretation
- **Peak rows**: top diagnostic peaks with classification
- **Rendering context**: pre-computed findings (as ``FindingPresentation``
  snapshots), top causes, sensor intensity, location hotspot rows

### Mapping examples

| Analysis output               | ReportTemplateData field        |
|-------------------------------|----------------------------------|
| `confidence_0_to_1 = 0.62`   | `certainty_tier_key = "B"`      |
| `findings[].suspected_source` | `system_cards[].system_name`    |
| `test_plan[].what`            | `next_steps[].action`           |
| `speed_stats.steady_speed`    | used by `ConfidenceAssessment.assess()` |
| `sensor_intensity_by_location`| `sensor_intensity_by_location`  |

## Adding new report sections

1. Add any new diagnostics output to `RunAnalysis` / `AnalysisResult` in
   `vibesensor.use_cases.diagnostics`, then project it in
   `vibesensor.shared.boundaries.analysis_summary.analysis_result_to_summary()`
   (or the adapter wrappers in `vibesensor.adapters.analysis_summary` if the
   change only affects the serialized edge helper).
2. Add a corresponding field to `ReportTemplateData` in
   `vibesensor.adapters.pdf.report_data`.
3. Populate the new field in `map_summary()` in
   `vibesensor.adapters.pdf.mapping`.
4. Render the new field through `pdf_engine.py`, usually by wiring it into the relevant page or section module under `vibesensor.adapters.pdf`.
5. Never add analysis logic to the renderer package — always pre-compute.
