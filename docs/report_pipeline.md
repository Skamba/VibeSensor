# Report Generation Pipeline

## Overview

The report generation pipeline has two distinct phases:

1. **Post-stop analysis** (`vibesensor.use_cases.run.post_analysis_executor` +
   `vibesensor.use_cases.diagnostics`) — runs once when a recording ends. It
   builds dense whole-run sidecar artifacts when raw capture is available, builds
   the compact diagnostics summary, appends compact whole-run report-facing
   summaries, and persists the resulting `PersistedAnalysis`.
2. **History request loading + reporting-boundary preparation + rendering**
      (`vibesensor.use_cases.history` →
      `vibesensor.shared.boundaries.reporting` →
      `vibesensor.adapters.pdf`) — loads the persisted analysis object, shapes
      runtime warnings and cache metadata, prepares one explicit
     `PreparedReportInput` with an authoritative reconstructed domain aggregate
     plus precomputed semantic report facts, builds one canonical
     `ReportDocument`, and renders a PDF. This phase performs **zero
      analysis** — it only shapes persisted report data and formats pre-computed
       results. If a run had raw capture available, raw-backed replay and any
       whole-run sidecar summaries were already folded into the persisted
       analysis during post-stop execution.

```text
Recording stops
  → _run_post_analysis() [vibesensor.use_cases.run.post_analysis]
    → execute_post_analysis() [vibesensor.use_cases.run.post_analysis_executor]
      → load_post_analysis_run() [vibesensor.use_cases.run.post_analysis_loader]
      → build_whole_run_artifacts() [vibesensor.use_cases.run.post_analysis_whole_run_builders]
        → whole_run_spectra.py + whole_run_context.py + whole_run_spatial_coherence.py
        → orders/whole_run_traces.py + orders/whole_run_scoring.py + orders/whole_run_family_summaries.py
      → astore_whole_run_artifacts() [vibesensor.adapters.persistence.history_db]
      → build_post_analysis_summary() [vibesensor.use_cases.run.post_analysis_summary]
        → RunAnalysis(...).summarize() [vibesensor.use_cases.diagnostics.run_analysis]
        → run_analysis.py + analysis_pipeline.py + run_data_preparation.py + _summary_steps.py + _summary_result.py
        → analysis_result_to_summary() [vibesensor.shared.boundaries.analysis_payloads.summary]
      → append compact whole-run report-facing summaries
      → astore_analysis() [vibesensor.adapters.persistence.history_db]

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

- `facts.py` builds `PreparedReportFacts(run=..., fallback_reasons=..., sensor=..., decision=..., evidence=..., confidence=..., findings=...)`
- `fallback_reasons.py` owns stable machine-readable fallback reason codes for history/report consumers (`raw_capture_not_configured`, `raw_capture_loss_exceeded`, `raw_capture_finalize_timeout`, `whole_run_analysis_pending`, `whole_run_analysis_failed`, `legacy_summary_only`, `sidecar_summary_mismatch`, `whole_run_evidence_missing`, and `whole_run_evidence_incomplete`)
- `evidence_facts.py` builds explicit proof facts (data basis, supporting-window count/duration, stable frequency band, strongest supporting sensors, and caveats) from persisted analysis + reconstructed domain findings
- `confidence_facts.py` converts persisted evidence quality signals into bounded report confidence (raw-backed vs summary-only basis, support count/duration, frequency stability, order-lock quality, spatial concentration, counterevidence, and reference gaps)
- `findings.py` owns report-facing finding/top-cause presentation shaping
- `sensor_facts.py` owns sensor/coverage shaping
- `decision_facts.py` owns primary-candidate, warning, and action-decision shaping
- `projection.py` owns primary-candidate/origin projection only

Canonical report-document assembly lives in
`vibesensor.use_cases.history.report_document`, which maps `PreparedReportInput`
into the renderer-facing `ReportDocument`. Report-specific interpretation and
fact preparation live under `vibesensor.shared.boundaries.reporting/` (for
example `facts.py`, `evidence_facts.py`, `confidence_facts.py`, `findings.py`,
`sensor_facts.py`, `decision_facts.py`, `projection.py`, and
`preparation.py`) rather than in `adapters.pdf` modules.

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
- **Confidence surfaces**: observed certainty, page-1 confidence row, and proof caveats come from prepared `ReportConfidenceFacts`, not renderer-only heuristics
- **Fallback reasons**: history and report preparation expose explicit `fallback_reasons` instead of inferring from missing fields; report confidence/caveats use the same stable codes carried in `analysis_metadata.fallback_reasons`
- **Appendix-C proof pack**: a diagnosis-focused evidence chain plus retained supporting-window exemplars for the selected diagnosis; the older ranked-measurement table is fallback-only when exemplar windows are unavailable
- **Location proof surfaces**: page-1 and Appendix-B location diagrams/hotspot summaries should use diagnosis-supporting window location facts when they exist, with explicit summary-only / whole-run fallback notes instead of silently reusing whole-run intensity
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
   `decision_facts.py`, `projection.py`, `findings.py`, `evidence_facts.py`, or
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
