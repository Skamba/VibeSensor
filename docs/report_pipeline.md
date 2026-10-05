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
| `report/run_quality.py` | Wording of each suitability check (plain sentence plus its specifics) and which run warnings a failing check already states. The quality page and the History run detail's warning banners both use it, so they say the same thing. |
| `report/pdf.py` | ReportLab canvas renderer with built-in Helvetica: one function per page (`_owner_page`, `_mechanic_page`, `_quality_page`), the car diagram, and the spectrum and amplitude-vs-speed charts. Layout only. |
| `report/service.py` | `HistoryReportService`: loads the run, picks the language, caches PDFs, and calls the injected renderer (composition imports ReportLab lazily on first use). |
| `report/cache.py` | LRU PDF cache with per-key build coordination. |
| `report/i18n.py` | `tr()` lookup in `data/report_i18n.json` (English and Dutch), `normalize_lang()`, and `resolve_i18n()` for language-neutral refs in summary warnings and suitability checks. |

`report` never imports `analysis` (import-linter contract in
`apps/server/pyproject.toml`).

## Pages

1. **Owner page**:
   - Header: car, tires, date, speeds driven, duration, and sensors. The date
     shows in the user's time zone (reported by the browser), else in the
     offset recorded with the run.
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
       the fix (re-run the test; what pass means). After a guided neutral
       coast-down the description adds whether the vibration follows road or
       engine speed, and the neutral coast-down check is not suggested again.
       When the engine turns at the diagnosed wheel or propshaft order's
       rhythm in some gear (engine check `same_rhythm_as_candidate`, see
       "Engine alias" in `docs/analysis_pipeline.md`), the description adds
       that without measured RPM it can also be the engine.
       Brake judder names the front or rear brake discs, says the vibration
       came only while braking, and its cheap check is a few firm stops from
       about 100 km/h.
     - Weak evidence: the hedged best candidate, 1–2 plain reasons, and a
       recapture recipe.
     - No fault: a verdict sentence that names only the sources the run could
       check (hedged when the check rests on an estimate, e.g. "engine (top
       gear only)") and the ones it could not, never "your car is fine"; what
       the test covered; "Not covered", built from `source_checks` (each
       untested or estimate-based source with how to close the gap: add the
       missing reference, enter the exact ratio, or connect OBD-II), then
       the speeds and driving the run left out, and last what no run
       analyses (a misfiring engine's half order, a six-cylinder's firing
       rhythm, wheel-bearing hum and, without measured RPM, an idle shake at
       a standstill; for an EV, the motor's electrical and gear-mesh rhythms
       and wheel-bearing hum); and what to do if the
       vibration is still felt. History shows the same sentence and a
       "Checked / Couldn't check" block in the same words.
2. **Workshop page** (always included):
   - Test conditions: tire size and circumference, final drive and top gear
     ratio, each with its provenance ("entered by you", "car library,
     official", "car library, model-family estimate", … or "not provided"),
     speed source, whether RPM was measured or estimated assuming top gear,
     driving phases, the guided test steps (or "not used"), and sensor
     positions.
   - A GM-worksheet-style findings table, one row per order (an order found at
     several corners stays one row; the per-location table holds the corners),
     the diagnosed (dominant) order first and the diagnosed source's other
     orders under it (for example T1 with T2 present). Columns: order label
     with plain text, Hz at the reference speed, km/h range, driving phases,
     presence, strongest location, and level.
   - Per-location amplitude at the diagnosed order in mg, with dB above that
     location's floor in brackets and the ratio to the strongest location.
   - Ruled-out and not-testable sources, each with a plain reason (an EV's
     motor names its reduction ratio, not a final drive).
   - Recurring-peak spectrum at the strongest location, with T1/T2/P1/P2/E1/E2
     markers.
   - Amplitude-vs-speed chart, shown only when the swept range is at least
     30 km/h.
   - Shop-request box for the fault type.
3. **Data quality page**: suitability checks in plain words, warnings (minus
   any a failing check already states), and traceability (run id, sensor, firmware, sample rate, VibeSensor version).
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
