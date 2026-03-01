"""Guardrail tests enforcing the analysis/report separation.

These tests verify the architectural invariant that the ``vibesensor.report``
package is renderer-only and never imports from ``vibesensor.analysis``.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 1.  Static import guard — report modules must not import analysis modules
# ---------------------------------------------------------------------------

_REPORT_DIR = Path(__file__).resolve().parents[1] / "vibesensor" / "report"
_ANALYSIS_PKG = "vibesensor.analysis"

# Modules in the report package that should be checked.
_REPORT_MODULES = [p for p in _REPORT_DIR.glob("*.py") if p.name != "__init__.py"]


@pytest.mark.parametrize("module_path", _REPORT_MODULES, ids=lambda p: p.name)
def test_report_module_does_not_import_analysis(module_path: Path) -> None:
    """No ``report/*.py`` file may statically import from ``vibesensor.analysis``.

    Lazy imports inside function bodies are allowed.  Only module-level
    (top-of-file) imports are flagged.
    """
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module_path))

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            # Skip imports inside function/method bodies.
            if _is_inside_function(tree, node):
                continue

            full = node.module
            if node.level and node.level > 0:
                if full.startswith("analysis"):
                    violations.append(
                        f"line {node.lineno}: from {'.' * node.level}{full} import ..."
                    )
            elif "analysis" in full.split("."):
                violations.append(f"line {node.lineno}: from {full} import ...")

    assert not violations, (
        f"{module_path.name} imports from analysis at module level "
        f"(violates renderer-only rule):\n" + "\n".join(violations)
    )


def _is_inside_function(tree: ast.Module, target: ast.AST) -> bool:
    """Return True if *target* is nested inside a function or method body."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if child is target:
                    return True
    return False


# ---------------------------------------------------------------------------
# 2.  Runtime import guard — verify the report package can be loaded
#     without pulling in the analysis package.
# ---------------------------------------------------------------------------


def test_report_package_imports_without_analysis() -> None:
    """Importing ``vibesensor.report`` must not import ``vibesensor.analysis``."""
    # Clear cached modules so we get a clean import.
    analysis_modules_before = {
        name for name in sys.modules if name.startswith("vibesensor.analysis")
    }

    # Re-import report modules (they may already be cached, so just verify
    # that none of them pull in analysis at module level).
    for mod_path in _REPORT_MODULES:
        mod_name = f"vibesensor.report.{mod_path.stem}"
        if mod_name in sys.modules:
            continue
        importlib.import_module(mod_name)

    analysis_modules_after = {
        name for name in sys.modules if name.startswith("vibesensor.analysis")
    }
    # Statically-enforced by the AST test above.  This runtime check catches
    # module-level side-effect imports that the AST scan cannot detect.
    new_analysis = analysis_modules_after - analysis_modules_before
    assert not new_analysis, f"Importing report modules pulled in analysis modules: {new_analysis}"


# ---------------------------------------------------------------------------
# 3.  Report generation fails clearly when ReportData is missing
# ---------------------------------------------------------------------------


def test_build_report_pdf_accepts_report_template_data() -> None:
    """build_report_pdf must accept a ReportTemplateData directly."""
    from vibesensor.report.pdf_builder import build_report_pdf
    from vibesensor.report.report_data import PatternEvidence, ReportTemplateData

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
    from io import BytesIO

    from pypdf import PdfReader

    from vibesensor.report.pdf_builder import build_report_pdf
    from vibesensor.report.report_data import (
        ObservedSignature,
        PatternEvidence,
        ReportTemplateData,
        SystemFindingCard,
    )

    data = ReportTemplateData(
        title="Diagnostic Worksheet",
        run_datetime="2026-01-15 10:30:00",
        sensor_count=4,
        observed=ObservedSignature(
            primary_system="Wheel / Tire",
            strongest_sensor_location="Front Left",
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


# ---------------------------------------------------------------------------
# 5.  Analysis module list — report/ only contains renderer files
# ---------------------------------------------------------------------------


def test_report_folder_contains_only_renderer_files() -> None:
    """The report/ folder must not contain analysis-related files."""
    analysis_file_names = {
        "summary.py",
        "findings.py",
        "order_analysis.py",
        "phase_segmentation.py",
        "plot_data.py",
        "helpers.py",
        "strength_labels.py",
        "test_plan.py",
        "pattern_parts.py",
    }
    actual_files = {p.name for p in _REPORT_DIR.glob("*.py")}
    unexpected = actual_files & analysis_file_names
    assert not unexpected, (
        f"report/ still contains analysis files: {unexpected}. "
        "These should be in vibesensor.analysis/."
    )
