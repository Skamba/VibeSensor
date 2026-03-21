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
from vibesensor.adapters.pdf.report_data import (
    PatternEvidence,
    ReportTemplateData,
    SystemFindingCard,
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
# 2.  Report generation fails clearly when ReportData is missing
# ---------------------------------------------------------------------------


def test_build_report_pdf_accepts_report_template_data() -> None:
    """build_report_pdf must accept a ReportTemplateData directly."""
    data = ReportTemplateData(
        title="Test Report",
        pattern_evidence=PatternEvidence(),
        lang="en",
    )
    pdf = build_report_pdf(data)
    assert pdf[:5] == b"%PDF-"


# ---------------------------------------------------------------------------
# 3.  Report output fidelity — rendered facts match ReportData
# ---------------------------------------------------------------------------


def test_report_output_matches_template_data() -> None:
    """Key facts from ReportTemplateData appear in the rendered PDF text."""
    data = ReportTemplateData(
        title="Diagnostic Worksheet",
        run_datetime="2026-01-15 10:30:00",
        sensor_count=4,
        observed=PatternEvidence(
            primary_system="Wheel / Tire",
            strongest_location="Front Left",
            certainty_label="High",
        ),
        system_cards=[
            SystemFindingCard(
                system_name="Wheel / Tire",
                strongest_location="Front Left",
                pattern_summary="1x wheel order",
            ),
        ],
        pattern_evidence=PatternEvidence(
            matched_systems=["Wheel / Tire"],
            strongest_location="Front Left",
        ),
        lang="en",
    )
    pdf_bytes = build_report_pdf(data)
    reader = PdfReader(BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "Wheel / Tire" in text
    assert "Front Left" in text
    assert "Diagnostic Worksheet" in text
