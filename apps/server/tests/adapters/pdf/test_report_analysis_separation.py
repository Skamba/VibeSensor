"""Guardrail tests enforcing the analysis/report separation.

These tests verify the architectural invariant that the ``vibesensor.adapters.pdf``
package is renderer-only and never imports from ``vibesensor.use_cases.diagnostics``.
"""

from __future__ import annotations

import importlib
import sys
from io import BytesIO

from _paths import SERVER_ROOT
from pypdf import PdfReader

from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    NextStep,
    PatternEvidence,
    RankedCandidateRow,
    ReportDocument,
    VerdictPageData,
)

# ---------------------------------------------------------------------------
# 1.  Runtime import guard — verify the report package can be loaded
#     without pulling in the analysis package.
# ---------------------------------------------------------------------------

_REPORT_DIR = SERVER_ROOT / "vibesensor" / "adapters" / "pdf"
_REPORT_MODULES = [
    p for p in _REPORT_DIR.glob("*.py") if p.name not in ("__init__.py", "mapping.py")
]


def test_report_package_imports_without_analysis() -> None:
    """Importing ``vibesensor.adapters.pdf`` must not import diagnostics."""
    # Clear cached modules so we get a clean import.
    analysis_modules_before = {
        name for name in sys.modules if name.startswith("vibesensor.use_cases.diagnostics")
    }

    # Re-import report modules (they may already be cached, so just verify
    # that none of them pull in analysis at module level).
    for mod_path in _REPORT_MODULES:
        mod_name = f"vibesensor.adapters.pdf.{mod_path.stem}"
        if mod_name in sys.modules:
            continue
        importlib.import_module(mod_name)

    analysis_modules_after = {
        name for name in sys.modules if name.startswith("vibesensor.use_cases.diagnostics")
    }
    # The explicit static-guard tool covers import structure. This runtime check
    # still catches module-level side-effect imports.
    new_analysis = analysis_modules_after - analysis_modules_before
    assert not new_analysis, f"Importing report modules pulled in analysis modules: {new_analysis}"


# ---------------------------------------------------------------------------
# 2.  Runtime import guard — verify the report package does not pull in
#     shared report-interpretation helpers at module import time.
# ---------------------------------------------------------------------------


def test_report_package_imports_without_shared_report_projection() -> None:
    """Importing ``vibesensor.adapters.pdf`` must not import report projection."""
    import vibesensor.adapters.pdf as pdf_pkg

    report_projection_helper = "vibesensor.shared.boundaries.reporting.projection"
    pdf_module_names = [f"vibesensor.adapters.pdf.{mod_path.stem}" for mod_path in _REPORT_MODULES]
    saved_attrs = {
        mod_path.stem: getattr(pdf_pkg, mod_path.stem, None) for mod_path in _REPORT_MODULES
    }
    saved_modules = {
        name: sys.modules.get(name) for name in [report_projection_helper, *pdf_module_names]
    }

    try:
        sys.modules.pop(report_projection_helper, None)
        for mod_name in pdf_module_names:
            sys.modules.pop(mod_name, None)

        for mod_name in pdf_module_names:
            importlib.import_module(mod_name)

        assert report_projection_helper not in sys.modules
    finally:
        for name in pdf_module_names:
            sys.modules.pop(name, None)
        sys.modules.pop(report_projection_helper, None)
        for name, module in saved_modules.items():
            if module is not None:
                sys.modules[name] = module
        for attr_name, module in saved_attrs.items():
            if module is None:
                if hasattr(pdf_pkg, attr_name):
                    delattr(pdf_pkg, attr_name)
            else:
                setattr(pdf_pkg, attr_name, module)


# ---------------------------------------------------------------------------
# 3.  Report generation fails clearly when ReportData is missing
# ---------------------------------------------------------------------------


def test_build_report_pdf_accepts_report_template_data() -> None:
    """build_report_pdf must accept a ReportDocument directly."""
    data = ReportDocument(
        title="Test Report",
        run_id="report-template",
        pattern_evidence=PatternEvidence(),
        lang="en",
    )
    pdf = build_report_pdf(data)
    assert pdf[:5] == b"%PDF-"


# ---------------------------------------------------------------------------
# 4.  Report output fidelity — rendered facts match ReportData
# ---------------------------------------------------------------------------


def test_report_output_matches_template_data() -> None:
    """Key facts from ReportDocument appear in the rendered PDF text."""
    data = ReportDocument(
        title="VibeSensor Diagnostic Report",
        run_id="report-output-match",
        run_datetime="2026-01-15 10:30:00",
        sensor_count=4,
        verdict_page=VerdictPageData(
            suspected_source="Wheel / Tire",
            inspect_first="Front-Left",
            action_status="Action-ready",
            reason_sentence=(
                "Wheel / Tire remains the strongest source because the repeated pattern "
                "stayed strongest near Front-Left."
            ),
            dominant_corner="Front-Left",
            location_confidence="Strong",
            coverage_label="4 of 4 expected positions stayed connected.",
            proof_summary=(
                "Front-Left outranked the next location by 2.1x on the p95 intensity map."
            ),
        ),
        appendix_a=AppendixAData(
            mode="workflow",
            primary_source="Wheel / Tire",
            why_primary_first=(
                "Supporting signal stayed strongest near Front-Left in the 50-60 km/h window."
            ),
            ranked_candidates=[
                RankedCandidateRow(
                    source_name="Wheel / Tire",
                    inspect_first="Front-Left",
                    path_role="Primary path",
                    reason=(
                        "Supporting signal stayed strongest near Front-Left in the "
                        "50-60 km/h window."
                    ),
                )
            ],
        ),
        next_steps=[
            NextStep(
                action="Check wheel balance",
                why="The repeated pattern stayed strongest near the front-left wheel path.",
                confirm=(
                    "If balance is the driver, the repeated pattern should reduce after correction."
                ),
            )
        ],
        lang="en",
    )
    pdf_bytes = build_report_pdf(data)
    reader = PdfReader(BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "Wheel / Tire" in text
    assert "Front-Left" in text
    assert "Action-ready" in text
    assert "Inspection Path" in text
    assert "VibeSensor Diagnostic Report" in text


def test_report_keeps_strongest_sensor_on_page_one_when_no_system_cards() -> None:
    """Page one keeps the dominant corner visible even without worksheet rows."""
    data = ReportDocument(
        title="VibeSensor Diagnostic Report",
        run_id="strongest-sensor-page-one",
        verdict_page=VerdictPageData(
            suspected_source="Unknown resonance",
            inspect_first="Rear-Right",
            action_status="Recapture before acting",
            reason_sentence=(
                "Unknown resonance remained strongest near Rear-Right during the captured window."
            ),
            dominant_corner="Rear-Right",
            location_confidence="Weak",
            coverage_label="1 of 1 expected positions stayed connected.",
            proof_summary=(
                "Rear-Right remained the strongest connected location on the p95 intensity map."
            ),
            proof_caveat=(
                "Localization is weak; capture another run before treating this corner as final."
            ),
        ),
        next_steps=[
            NextStep(action="Repeat the run with a broader speed sweep."),
            NextStep(action="Add more sensor locations for spatial separation."),
        ],
        lang="en",
    )
    pdf_bytes = build_report_pdf(data)
    reader = PdfReader(BytesIO(pdf_bytes))
    page_one = reader.pages[0].extract_text() or ""
    page_one_single_line = " ".join(page_one.split())

    assert "Rear-Right" in page_one_single_line
    assert "Recapture before acting" in page_one_single_line
    assert "Why this corner wins" in page_one


def test_report_cards_switch_to_check_first_summary_when_parts_exist() -> None:
    """Workflow appendix surfaces primary path context and concrete action rows."""
    data = ReportDocument(
        title="VibeSensor Diagnostic Report",
        run_id="cards-check-first-summary",
        verdict_page=VerdictPageData(
            suspected_source="Wheel / Tire",
            inspect_first="Front-Left",
            action_status="Action-ready",
            reason_sentence=(
                "Wheel / Tire remains the strongest source because the repeated pattern "
                "stayed strongest near Front-Left."
            ),
        ),
        appendix_a=AppendixAData(
            mode="workflow",
            primary_source="Wheel / Tire",
            alternative_source="Driveline",
            why_primary_first="Pattern stayed strongest near Front-Left.",
            next_if_clean="Move to the driveline path next and inspect Front-Right.",
            ranked_candidates=[
                RankedCandidateRow(
                    source_name="Wheel / Tire",
                    inspect_first="Front-Left",
                    path_role="Primary path",
                    reason="Pattern stayed strongest near Front-Left.",
                )
            ],
        ),
        next_steps=[
            NextStep(
                action="Check wheel bearing assembly",
                why="The strongest repeated pattern stayed near the front-left wheel path.",
                confirm=(
                    "If the bearing is the driver, the repeated pattern should reduce "
                    "after correction."
                ),
                falsify="If the bearing is clean, move to the driveline path.",
            ),
            NextStep(
                action="Inspect tire belt package",
                why="The wheel/tire path remained the strongest ranked source.",
                confirm=(
                    "If tire condition is the driver, the repeated pattern should "
                    "reduce after correction."
                ),
            ),
        ],
        lang="en",
    )
    pdf_bytes = build_report_pdf(data)
    reader = PdfReader(BytesIO(pdf_bytes))
    page_two = reader.pages[1].extract_text() or ""
    page_three = reader.pages[2].extract_text() or ""
    page_three_single_line = " ".join(page_three.split())

    assert "Evidence and Run Context" in page_two
    assert "Inspection Path" in page_three
    assert "Primary vs alternative source" in page_three
    assert "Front-Left" in page_three
    assert "Check wheel bearing assembly" in page_three_single_line
    assert "Inspect tire belt package" in page_three_single_line
