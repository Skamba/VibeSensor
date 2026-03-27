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
    PartSuggestion,
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
# 2.  Runtime import guard — verify the report package does not pull in
#     shared report-interpretation helpers at module import time.
# ---------------------------------------------------------------------------


def test_report_package_imports_without_shared_report_interpretation() -> None:
    """Importing ``vibesensor.adapters.pdf`` must not import report interpretation."""
    import vibesensor.adapters.pdf as pdf_pkg

    report_interpretation_helper = "vibesensor.shared.boundaries.report_interpretation"
    pdf_module_names = [f"vibesensor.adapters.pdf.{mod_path.stem}" for mod_path in _REPORT_MODULES]
    saved_attrs = {
        mod_path.stem: getattr(pdf_pkg, mod_path.stem, None) for mod_path in _REPORT_MODULES
    }
    saved_modules = {
        name: sys.modules.get(name) for name in [report_interpretation_helper, *pdf_module_names]
    }

    try:
        sys.modules.pop(report_interpretation_helper, None)
        for mod_name in pdf_module_names:
            sys.modules.pop(mod_name, None)

        for mod_name in pdf_module_names:
            importlib.import_module(mod_name)

        assert report_interpretation_helper not in sys.modules
    finally:
        for name in pdf_module_names:
            sys.modules.pop(name, None)
        sys.modules.pop(report_interpretation_helper, None)
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
    """build_report_pdf must accept a ReportTemplateData directly."""
    data = ReportTemplateData(
        title="Test Report",
        pattern_evidence=PatternEvidence(),
        lang="en",
    )
    pdf = build_report_pdf(data)
    assert pdf[:5] == b"%PDF-"


# ---------------------------------------------------------------------------
# 4.  Report output fidelity — rendered facts match ReportData
# ---------------------------------------------------------------------------


def test_report_output_matches_template_data() -> None:
    """Key facts from ReportTemplateData appear in the rendered PDF text."""
    data = ReportTemplateData(
        title="VibeSensor Diagnostic Report",
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
        certainty_tier_key="C",
    )
    pdf_bytes = build_report_pdf(data)
    reader = PdfReader(BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    observed_start = text.find("Observed Signature")
    systems_start = text.find("Systems with findings")
    next_steps_start = text.find("Next steps")
    observed_section = text[observed_start:systems_start]
    systems_section = text[systems_start : next_steps_start if next_steps_start >= 0 else None]

    assert "Wheel / Tire" in text
    assert "Front Left" in text
    assert "Strongest sensor" not in observed_section
    assert "Strongest sensor: Front Left" in systems_section
    assert "VibeSensor Diagnostic Report" in text


def test_report_keeps_strongest_sensor_on_page_one_when_no_system_cards() -> None:
    """Low-confidence/no-card reports should keep strongest-location context on page 1."""
    data = ReportTemplateData(
        title="VibeSensor Diagnostic Report",
        observed=PatternEvidence(
            primary_system="Unknown",
            strongest_location="Rear Right",
            certainty_label="Low",
        ),
        pattern_evidence=PatternEvidence(strongest_location="Rear Right"),
        lang="en",
        certainty_tier_key="A",
    )
    pdf_bytes = build_report_pdf(data)
    reader = PdfReader(BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    observed_start = text.find("Observed Signature")
    systems_start = text.find("Systems with findings")
    observed_section = text[observed_start:systems_start]
    observed_single_line = " ".join(observed_section.split())

    assert "Strongest sensor: Rear Right" in observed_single_line
    assert "Confidence is too low to attribute vibration to specific systems." in text


def test_report_cards_switch_to_check_first_summary_when_parts_exist() -> None:
    """Actionable cards should spend space on pattern + first checks, not duplicate location."""
    data = ReportTemplateData(
        title="VibeSensor Diagnostic Report",
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
                parts=[
                    PartSuggestion(name="Wheel bearing assembly"),
                    PartSuggestion(name="Tire belt package"),
                ],
            ),
        ],
        pattern_evidence=PatternEvidence(
            matched_systems=["Wheel / Tire"],
            strongest_location="Front Left",
        ),
        lang="en",
        certainty_tier_key="C",
    )
    pdf_bytes = build_report_pdf(data)
    reader = PdfReader(BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    observed_start = text.find("Observed Signature")
    systems_start = text.find("Systems with findings")
    next_steps_start = text.find("Next steps")
    observed_section = text[observed_start:systems_start]
    systems_section = text[systems_start : next_steps_start if next_steps_start >= 0 else None]
    systems_single_line = " ".join(systems_section.split())

    assert "Strongest sensor: Front Left" not in observed_section
    assert "Strongest sensor: Front Left" not in systems_section
    assert "Pattern: 1x wheel order" in systems_single_line
    assert "What to check first: Wheel bearing assembly, Tire belt package" in systems_single_line
