# Report Generation Pipeline

## Overview

The report generation pipeline has two distinct phases:

1. **Post-stop analysis** (`vibesensor.use_cases.diagnostics`) — runs once when a recording
   ends, producing an app-level `AnalysisResult`. The serialized summary dict is
   then created at the boundary by `vibesensor.shared.boundaries.analysis_payloads`
   / `vibesensor.adapters.analysis_summary`.
2. **History request loading + reporting-boundary preparation + rendering**
      (`vibesensor.use_cases.history` →
      `vibesensor.shared.boundaries.reporting` →
      `vibesensor.adapters.pdf`) — loads the persisted analysis object, shapes
      runtime warnings and cache metadata, prepares one explicit
     `PreparedReportInput` with an authoritative reconstructed domain aggregate
     plus precomputed semantic report facts, builds one canonical
     `ReportDocument`, and renders a PDF. This phase performs **zero
      analysis** — it only shapes persisted report data and formats pre-computed
      results. If a run had raw capture available, that evidence was already
      folded into the persisted analysis during post-stop replay.

```text
Recording stops
  → _run_post_analysis() [vibesensor.use_cases.run.post_analysis]
    → build_post_analysis_summary() [vibesensor.use_cases.run.post_analysis]
      → RunAnalysis(...).summarize() [vibesensor.use_cases.diagnostics.run_analysis]
      → run_analysis.py + analysis_pipeline.py + run_data_preparation.py + _summary_steps.py + _summary_result.py (preparation, phases, suitability, domain/result assembly)
      → analysis_result_to_summary() [vibesensor.shared.boundaries.analysis_payloads.summary]
      → findings.py + _reference_findings.py + _context_decode.py/_context_projection.py + _sample_metrics.py + _analysis_models.py + orders/{pipeline,matching,scoring,finding_builder,statistics,heuristics,settings}.py + peaks/{findings,accumulation,classification,scoring,finding_builder,statistics,settings,table}.py + signal_aggregation.py + top_cause_selection.py + plots.py
    → build_report_document() [vibesensor.use_cases.history.report_document]
      → builder.py + document_context.py + composition.py + appendix_c.py +
        timeline_graph.py + traceability.py + report_sections.py + peak_table.py
    → store_analysis() [vibesensor.adapters.persistence.history_db]

GET /api/history/{run_id}/report.pdf [vibesensor.adapters.http.history]
  → HistoryReportService.build_pdf() [vibesensor.use_cases.history.reports]
    → HistoryReportRequestLoader.load_report_request() [vibesensor.use_cases.history.report_loader]
    → prepare_report_input() [vibesensor.shared.boundaries.reporting.preparation]
    → _build_pdf_bytes() [vibesensor.app.container]
      → build_report_document(prepared_input) [vibesensor.use_cases.history.report_document]
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
| `pdf_engine.py` | Public PDF entrypoint, validation, pagination, and document orchestration |
| `pdf_page1.py`, `page1_*.py`, `action_cards.py` | Page-1 composition and section-specific helpers for the shipped worksheet surface |
| `pdf_appendices/` | Appendix page rendering, shared appendix tables/layout, and title-bar helpers |
| `pdf_style.py` | Page geometry, shared style tokens, and layout constants for the shipped PDF surface |
| `pdf_drawing.py`, `pdf_text.py` | Shared drawing and text helpers |
| `pdf_diagram_render.py` | Diagram planning, drawing, and location normalization |
| `report_types.py` | Adapter-local render plans derived from `ReportDocument` |

**Rule:** Report modules must not import from `vibesensor.use_cases.diagnostics` at
module level.  A guardrail test (`test_report_analysis_separation.py`)
enforces this.

Canonical report preparation now lives in
`vibesensor.shared.boundaries.reporting`, which owns the explicit
`PreparedReportInput` seam, projectability gating, one-time
`NormalizedReportSummary` decoding, domain reconstruction, filename/language
normalization, and grouped semantic fact assembly:

- `facts.py` builds `PreparedReportFacts(run=..., sensor=..., decision=..., findings=...)`
- `evidence_facts.py` builds explicit proof facts (data basis, supporting-window count/duration, stable frequency band, strongest supporting sensors, and caveats) from persisted analysis + reconstructed domain findings
- `findings.py` owns report-facing finding/top-cause presentation shaping
- `sensor_facts.py` owns sensor/coverage shaping
- `decision_facts.py` owns primary-candidate, warning, and action-decision shaping
- `projection.py` owns primary-candidate/origin projection only

Canonical report-document assembly lives in
`vibesensor.use_cases.history.report_document`, which maps `PreparedReportInput`
into the renderer-facing `ReportDocument`. Pure report-domain interpretation
that reads domain findings/test runs but does not perform i18n or PDF dataclass
assembly still lives in `vibesensor.shared.boundaries.report_interpretation`,
but it is consumed by the reporting boundary rather than imported directly by
`adapters.pdf` modules.

### ReportDocument schema

`ReportDocument` (defined in
`vibesensor.shared.boundaries.reporting.document`) is the canonical rendering
artifact. It contains everything the PDF renderer
needs:

- **Display metadata**: title, dates, sensor info, version marker
- **Observed signature**: primary system, location, speed band, strength
- **System finding cards**: top-3 ranked findings with parts suggestions
- **Next steps**: test plan or capture guidance (tier-dependent)
- **Data trust items**: suitability checks
- **Pattern evidence**: matched systems, certainty label, interpretation
- **Evidence snapshots**: concise page-1 proof rows plus Appendix-C proof rows built from prepared evidence facts, not renderer-time DSP
- **Peak rows**: top diagnostic peaks with classification
- **Rendering context**: pre-computed findings (as ``FindingPresentation``
  snapshots), top causes, sensor intensity, location hotspot rows

### Mapping examples

| Analysis output               | ReportDocument field            |
|-------------------------------|----------------------------------|
| `confidence_0_to_1 = 0.62`   | `certainty_tier_key = "B"`      |
| `findings[].suspected_source` | `system_cards[].system_name`    |
| `test_plan[].what`            | `next_steps[].action`           |
| `speed_stats.steady_speed`    | used by `ConfidenceAssessment.assess()` |
| `sensor_intensity_by_location`| `sensor_intensity_by_location`  |

## Adding new report sections

1. Add any new diagnostics output to `RunAnalysis` / `AnalysisResult` in
   `vibesensor.use_cases.diagnostics`, then project it in
   `vibesensor.shared.boundaries.analysis_payloads.analysis_result_to_summary()`
   (or the adapter wrappers in `vibesensor.adapters.analysis_summary` if the
   change only affects the serialized edge helper).
2. Add a corresponding field to `ReportDocument` in
   `vibesensor.shared.boundaries.reporting.document`.
3. If the new section needs report-specific shaping, add it under
   `vibesensor.shared.boundaries.reporting` (`facts.py`, `sensor_facts.py`,
   `decision_facts.py`, `projection.py`, `reconstruction.py`, or
   `preparation.py` as appropriate), then populate the final renderer field in
   `build_report_document()` in
   `vibesensor.use_cases.history.report_document`.
   Keep the default report-request/cache path driven only by persisted run data
   and persisted analysis. If a feature needs to compare a historical run
   against current mutable settings, model that as an explicit advisory overlay
   instead of threading live settings into the base report request.
4. Render the new field through `pdf_engine.py`, usually by wiring it into the relevant page or section module under `vibesensor.adapters.pdf`.
5. Never add history/report semantic interpretation logic to the renderer
   package — always pre-compute it in
   `vibesensor.shared.boundaries.reporting` before PDF rendering.
