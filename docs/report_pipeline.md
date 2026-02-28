# Report Generation Pipeline

## Overview

The report generation pipeline has two distinct phases:

1. **Post-stop analysis** (`vibesensor.analysis`) — runs once when a recording
   ends, producing a persisted summary dict and a `ReportTemplateData` artifact.
2. **Report rendering** (`vibesensor.report`) — loads the persisted
   `ReportTemplateData` and renders a PDF.  This phase performs **zero
   analysis** — it only formats and lays out pre-computed data.

```
Recording stops
  │
  ▼
_run_post_analysis()          [vibesensor.metrics_log]
  ├─ summarize_run_data()     [vibesensor.analysis.summary]
  │    ├─ phase segmentation  [vibesensor.analysis.phase_segmentation]
  │    ├─ findings builder    [vibesensor.analysis.findings]
  │    ├─ order analysis      [vibesensor.analysis.order_analysis]
  │    ├─ test plan            [vibesensor.analysis.test_plan]
  │    ├─ plot data            [vibesensor.analysis.plot_data]
  │    └─ strength labels      [vibesensor.analysis.strength_labels]
  ├─ map_summary()            [vibesensor.analysis.report_data_builder]
  │    ├─ certainty_tier()     → tier A/B/C
  │    ├─ parts_for_pattern()  → suggested parts
  │    └─ location hotspots    → pre-computed rows
  └─ store_analysis()          [vibesensor.history_db]
       └─ Persists summary dict + embedded _report_template_data
  │
  ▼
GET /api/history/{run_id}/report.pdf   [vibesensor.api]
  ├─ Load persisted analysis + _report_template_data
  ├─ Reconstruct ReportTemplateData from dict
  └─ build_report_pdf(data)   [vibesensor.report.pdf_builder]
       ├─ Page 1: header, observed signature, systems, next steps
       └─ Page 2: car diagram, pattern evidence, peaks table
```

## Key Architectural Rules

### Post-stop-only analysis

All diagnostic analysis (findings, ranking, phase segmentation, strength
classification, test-plan generation, order tracking) runs **once** at
post-stop time and is persisted.  Report generation **never** re-runs
analysis.

### Renderer-only report package

The `vibesensor.report` package contains **only** rendering code:

| File              | Purpose                              |
|-------------------|--------------------------------------|
| `pdf_builder.py`  | PDF page layout and rendering        |
| `pdf_diagram.py`  | Car location diagram (ReportLab)     |
| `pdf_helpers.py`  | PDF rendering utilities              |
| `report_data.py`  | Dataclass definitions (pure data)    |
| `i18n.py`         | Translation string lookup            |
| `theme.py`        | Color tokens and styling constants   |

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

### Backward compatibility

For runs analyzed before `ReportTemplateData` persistence was introduced,
the PDF endpoint falls back to building `ReportTemplateData` from the
persisted summary dict via `map_summary()`.  This fallback uses a lazy
import to avoid violating the renderer-only rule at module level.  This
means that for legacy data, analysis code *is* called at report time as a
one-time migration path — new recordings always have pre-built
`ReportTemplateData` available.

## Adding new report sections

1. Add any new analysis output to `summarize_run_data()` in
   `vibesensor.analysis.summary`.
2. Add a corresponding field to `ReportTemplateData` in
   `vibesensor.report.report_data`.
3. Populate the new field in `map_summary()` in
   `vibesensor.analysis.report_data_builder`.
4. Render the new field in `pdf_builder.py`.
5. Never add analysis logic to `pdf_builder.py` — always pre-compute.
