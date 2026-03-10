# Report Generation Pipeline

## Overview

The report generation pipeline has two distinct phases:

1. **Post-stop analysis** (`vibesensor.analysis`) — runs once when a recording
   ends, producing a persisted summary dict and a `ReportTemplateData` artifact.
2. **Report rendering** (`vibesensor.report`) — loads the persisted
   `ReportTemplateData` and renders a PDF.  This phase performs **zero
   analysis** — it only formats and lays out pre-computed data.

```text
Recording stops
  → _run_post_analysis() [vibesensor.metrics_log.post_analysis]
    → summarize_run_data() [vibesensor.analysis.summary_builder]
      → summary_phases.py / summary_suitability.py / summary_payload.py
      → findings/, ranking.py, top_cause_selection.py, plot_data.py
    → map_summary() [vibesensor.analysis.report_mapping_pipeline]
      → report_mapping_actions.py / report_mapping_peaks.py / report_mapping_systems.py
    → store_analysis() [vibesensor.history_db]

GET /api/history/{run_id}/report.pdf [vibesensor.routes.history]
  → HistoryReportService.build_pdf() [vibesensor.history_services.reports]
    → build_report_pdf(data) [vibesensor.report.pdf_engine]
```

## Key Architectural Rules

### Post-stop-only analysis

All diagnostic analysis (findings, ranking, phase segmentation, strength
classification, test-plan generation, order tracking) runs **once** at
post-stop time and is persisted.  Report generation **never** re-runs
analysis.

### Renderer-only report package

The `vibesensor.report` package contains **only** rendering code:

| File | Purpose |
|---|---|
| `pdf_engine.py` | Public PDF entrypoint, validation, pagination, and page orchestration |
| `pdf_page1.py`, `pdf_page2.py` | Page-level composition |
| `pdf_page1_sections.py`, `pdf_page2_sections.py`, `pdf_page_layouts.py` | Focused page section renderers and geometry |
| `pdf_drawing.py`, `pdf_text.py`, `pdf_layout.py` | Shared drawing, text, and geometry helpers |
| `pdf_diagram_layout.py`, `pdf_diagram_models.py`, `pdf_diagram_render.py` | Diagram planning, typed models, and drawing |
| `pdf_helpers.py` | Shared PDF helper functions |
| `report_data.py` | Dataclass definitions (pure data) |
| `theme.py` | Color tokens and styling constants |

**Rule:** Report modules must not import from `vibesensor.analysis` at
module level.  A guardrail test (`test_report_analysis_separation.py`)
enforces this.

### ReportTemplateData schema

`ReportTemplateData` (defined in `vibesensor.report.report_data`) is the
canonical rendering artifact.  It contains everything the PDF renderer
needs:

- **Display metadata**: title, dates, sensor info, version marker
- **Observed signature**: primary system, location, speed band, strength
- **System finding cards**: top-3 ranked findings with parts suggestions
- **Next steps**: test plan or capture guidance (tier-dependent)
- **Data trust items**: suitability checks
- **Pattern evidence**: matched systems, certainty label, interpretation
- **Peak rows**: top diagnostic peaks with classification
- **Rendering context**: pre-computed findings, top causes,
  sensor intensity, location hotspot rows

### Mapping examples

| Analysis output               | ReportTemplateData field        |
|-------------------------------|----------------------------------|
| `confidence_0_to_1 = 0.62`   | `certainty_tier_key = "C"`      |
| `findings[].suspected_source` | `system_cards[].system_name`    |
| `test_plan[].what`            | `next_steps[].action`           |
| `speed_stats.steady_speed`    | used to compute `certainty_label` |
| `sensor_intensity_by_location`| `sensor_intensity_by_location`  |

## Adding new report sections

1. Add any new analysis output to `summarize_run_data()` in
   `vibesensor.analysis.summary_builder`.
2. Add a corresponding field to `ReportTemplateData` in
   `vibesensor.report.report_data`.
3. Populate the new field in `map_summary()` in
   `vibesensor.analysis.report_mapping_pipeline`.
4. Render the new field through `pdf_engine.py`, usually by wiring it into the relevant page or section module under `vibesensor.report`.
5. Never add analysis logic to the renderer package — always pre-compute.
