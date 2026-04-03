# Report Generation Pipeline

## Overview

The report generation pipeline has two distinct phases:

1. **Post-stop analysis** (`vibesensor.use_cases.diagnostics`) — runs once when a recording
   ends, producing an app-level `AnalysisResult`. The serialized summary dict is
   then created at the boundary by `vibesensor.shared.boundaries.analysis_summary`
   / `vibesensor.adapters.analysis_summary`.
2. **History-side report preparation + rendering** (`vibesensor.use_cases.history`
   → `vibesensor.adapters.pdf`) — loads the persisted analysis object, shapes
   runtime warnings and cache metadata, prepares one explicit
   `PreparedReportInput` with an authoritative reconstructed domain aggregate
   plus precomputed semantic report facts, maps that prepared input to
   `ReportTemplateData`, and renders a PDF. This phase performs **zero
   analysis** — it only shapes persisted report data and formats pre-computed
   results.

```text
Recording stops
  → _run_post_analysis() [vibesensor.use_cases.run.post_analysis]
    → build_post_analysis_summary() [vibesensor.use_cases.run.post_analysis]
      → RunAnalysis(...).summarize() [vibesensor.use_cases.diagnostics.run_analysis]
      → run_analysis.py + analysis_pipeline.py + run_data_preparation.py + _summary_steps.py + _summary_result.py (preparation, phases, suitability, domain/result assembly)
      → analysis_result_to_summary() [vibesensor.shared.boundaries.analysis_summary]
      → findings.py + _reference_findings.py + _context_decode.py/_context_projection.py + _sample_metrics.py + _analysis_models.py + orders/{pipeline,matching,scoring,finding_builder,statistics,heuristics,settings}.py + peaks/{findings,accumulation,classification,scoring,finding_builder,statistics,settings,table}.py + signal_aggregation.py + top_cause_selection.py + plots.py
    → map_summary() [vibesensor.adapters.pdf.assembly]
      → assembler.py (summary/facts orchestration) + template_builder.py + peak_table.py + report_sections.py
    → store_analysis() [vibesensor.adapters.persistence.history_db]

GET /api/history/{run_id}/report.pdf [vibesensor.adapters.http.history]
  → HistoryReportService.build_pdf() [vibesensor.use_cases.history.reports]
    → HistoryReportRequestLoader.load_report_request() [vibesensor.use_cases.history.report_loader]
    → prepare_report_input() [vibesensor.use_cases.history.report_preparation]
    → _build_pdf_bytes() [vibesensor.app.container]
      → map_summary(prepared_input) [vibesensor.adapters.pdf.mapping]
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
| `pdf_page1.py`, `pdf_page2.py` | Page-level composition over the grouped `panels/_panel_*.py` renderers, including section layout and aspect-ratio helpers |
| `panels/_panel_*.py` | Panel renderers grouped by page section (header, systems, trust steps, diagram, evidence, observations, peaks, title bar) |
| `pdf_style.py` | Page geometry, layout calculations, color tokens, styling constants, and render context |
| `pdf_drawing.py`, `pdf_text.py` | Shared drawing and text helpers |
| `pdf_diagram_render.py` | Diagram planning, drawing, and location normalization |
| `models/` | Dataclass definitions (pure data) |
| `assembly/assembler.py` | Thin mapper: `PreparedReportInput` → `ReportTemplateData` using canonical summary + prepared facts |
| `template_builder.py` | Final field assignment from prepared inputs into `ReportTemplateData` |
| `presentation.py` | Rendering-only label helpers (strength/order/classification text) |
| `peak_table.py` | Peak-row builders for the report evidence table |
| `report_sections.py` | Next-step and data-trust section builders |
| `pattern_parts.py` | Pattern-to-parts suggestion helpers |

**Rule:** Report modules must not import from `vibesensor.use_cases.diagnostics` at
module level.  A guardrail test (`test_report_analysis_separation.py`)
enforces this.

History-side report preparation now lives in
`vibesensor.use_cases.history.report_preparation`, which owns the explicit
`PreparedReportInput` seam passed into the PDF adapter, projectability gating,
one-time `NormalizedReportSummary` decoding, domain reconstruction,
filename/language normalization, and final prepared-input assembly. Semantic
report-facts shaping now lives in the dedicated
`vibesensor.use_cases.history.report_facts` and
`vibesensor.use_cases.history.report_display_facts` modules, which precompute
the origin, active sensor intensity, hotspot rows, primary-candidate facts,
verdict/appendix display decisions, next-step inputs, and data-trust inputs the
adapter needs. Pure report-domain interpretation that reads domain
findings/test runs but does not perform i18n or PDF dataclass assembly still
lives in
`vibesensor.shared.boundaries.report_interpretation`, but it is consumed by
history-side preparation rather than imported directly by `adapters.pdf`
modules.

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
3. If the new section needs report-specific shaping, add it to
   `vibesensor.use_cases.history.report_facts` /
   `vibesensor.use_cases.history.report_display_facts` (for semantic report
   facts and display decisions) or
   `vibesensor.use_cases.history.report_preparation` (for the outer prepared
   handoff), then populate the final renderer field in `map_summary()` in
   `vibesensor.adapters.pdf.mapping`.
   Keep the default report-request/cache path driven only by persisted run data
   and persisted analysis. If a feature needs to compare a historical run
   against current mutable settings, model that as an explicit advisory overlay
   instead of threading live settings into the base report request.
4. Render the new field through `pdf_engine.py`, usually by wiring it into the relevant page or section module under `vibesensor.adapters.pdf`.
5. Never add history/report semantic interpretation logic to the renderer
   package — always pre-compute it on the history side in `report_facts.py`
   and `report_preparation.py`.
