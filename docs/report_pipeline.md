# Report Generation Pipeline

## Overview

The PDF report has two phases:

1. **Post-stop analysis** (`vibesensor.analysis.post_analysis_executor` +
   `vibesensor.analysis`) runs once when a recording ends and persists the
   `PersistedAnalysis`. Its `diagnosis` block (`analysis/diagnosis.py`, contract
   in `summary/diagnosis_contracts.py`) is the single verdict that both the
   History UI and the PDF show: verdict, confidence level, order label, zone,
   mg amplitudes per location, amplitude vs speed, recurring-peak spectrum,
   source checks, and test conditions.
2. **Report rendering** (`vibesensor.report`) runs on request. It performs no
   analysis: it translates the stored analysis plus the run metadata into text
   and draws it.

```text
GET /api/history/{run_id}/report.pdf?lang=nl   [vibesensor.web.history]
  -> HistoryReportService.build_pdf()          [vibesensor.report.service]
     -> HistoryDB.get_run() + require_analysis_ready()
     -> HistoryReportPdfCache (key: run_id, language, analysis_completed_at)
     -> build_report_view(analysis, metadata, lang=...)  [vibesensor.report.view_model]
     -> render_report_pdf(view)                           [vibesensor.report.pdf]
```

The report language is the requested `lang`, falling back to the run's
language. `vibesensor-report <history.db> <run_id> [--lang en|nl] [--output
file.pdf]` (`vibesensor.cli.report`) renders the same report from a stored run.

## Modules

| Module | Role |
|---|---|
| `report/view_model.py` | Pure translation of the stored analysis + `RunMetadata` into a `ReportView`: every localized string, number format (decimal comma in Dutch), and chart series the PDF draws. Never re-derives the verdict, level, order labels, amplitudes, or zones. |
| `report/pdf.py` | ReportLab canvas renderer with built-in Helvetica: one function per page (`_owner_page`, `_mechanic_page`, `_quality_page`), the car diagram, and the spectrum and amplitude-vs-speed charts. Layout only. |
| `report/service.py` | `HistoryReportService`: loads the run, picks the language, caches PDFs, and calls the injected renderer (composition imports ReportLab lazily on first use). |
| `report/cache.py` | LRU PDF cache with per-key build coordination. |
| `report/i18n.py` | `tr()` lookup in `data/report_i18n.json` (English and Dutch), `normalize_lang()`, and `resolve_i18n()` for language-neutral refs in summary warnings and suitability checks. |

`report` never imports `analysis` (import-linter contract in
`apps/server/pyproject.toml`).

## Pages

1. **Owner page**:
   - Header: car, tires, date, speeds driven, duration, and sensors.
   - Verdict box with exactly one confidence expression: the level word plus
     its action meaning (Strong: go fix it; Moderate: do the cheap confirming
     check first; Weak: don't buy parts, record the test again). No
     percentages.
   - One plain sentence: what repeats (order), at which frequency and speed,
     where, and over which speeds.
   - Car diagram: sensor dots sized by ratio to the strongest location, with the
     corner or zone highlighted.
   - What to do next, by verdict:
     - Fault: the next step, a fallback step ("If that doesn't fix it: ..."),
       the cheap confirming check when the level is Moderate, and how to check
       the fix (re-run the test; what pass means).
     - Weak evidence: the hedged best candidate, 1–2 plain reasons, and a
       recapture recipe.
     - No fault: what the test covered, what it did not cover, and what to do
       if the vibration is still felt.
2. **Workshop page** (always included):
   - Test conditions: tire size and circumference, ratios, speed source,
     whether RPM was measured, driving phases, and sensor positions.
   - A GM-worksheet-style findings table, one row per order-tracked finding.
     Columns: order label with plain text, Hz at the reference speed, km/h
     range, driving phases, presence, strongest location, and level.
   - Per-location amplitude at the diagnosed order in mg, with dB above that
     location's floor in brackets and the ratio to the strongest location.
   - Ruled-out and not-testable sources, each with a plain reason.
   - Recurring-peak spectrum at the strongest location, with T1/T2/P1/P2/E1/E2
     markers.
   - Amplitude-vs-speed chart, shown only when the swept range is at least
     30 km/h.
   - Shop-request box for the fault type.
3. **Data quality page**: suitability checks in plain words, warnings, and
   traceability (run id, sensor, firmware, sample rate, VibeSensor version).
   When every check passes and there are no warnings, this collapses into one
   footer line on page 2.

## Adding report content

1. If the content is a new diagnostic fact, compute it once in the analysis and
   persist it in the `diagnosis` block (bump `PERSISTED_ANALYSIS_SCHEMA_VERSION`
   when the contract gains a required field; stored runs are re-analysed on
   startup).
2. Add the text to `ReportView` in `report/view_model.py`, with the strings in
   `data/report_i18n.json` (both `en` and `nl`).
3. Draw it in the matching page function in `report/pdf.py`.
4. Cover it in `tests/report/test_report_view_model.py` (text per scenario) and
   `tests/report/test_report_pdf.py` (rendered text per variant). Check long
   values visually by rendering sample pages to PNG (`pypdfium2`).
