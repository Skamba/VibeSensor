"""Guardrail tests enforcing analysis-folder ownership and pipeline discipline.

These tests verify the architectural invariants:
1. External code imports analysis symbols only through ``vibesensor.analysis``
   (the package ``__init__.py``), never from sub-modules directly.
2. The analysis pipeline has a single clear entrypoint (``summarize_run_data``).
3. Post-stop analysis code lives exclusively in the analysis folder.
4. Live signal processing (``processing.py``) does not depend on analysis.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SERVER_PKG = Path(__file__).resolve().parents[1] / "vibesensor"
_ANALYSIS_PKG = _SERVER_PKG / "analysis"

# All Python files in vibesensor/ that are NOT inside analysis/
_EXTERNAL_MODULES = [p for p in _SERVER_PKG.glob("*.py") if p.name != "__init__.py"]


# ---------------------------------------------------------------------------
# 1. External code must not import from analysis sub-modules directly
# ---------------------------------------------------------------------------


def _analysis_submodule_imports(source: str, filename: str) -> list[str]:
    """Return a list of analysis-submodule import violations in *source*."""
    tree = ast.parse(source, filename=filename)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        mod = node.module
        level = node.level or 0

        if level > 0:
            # Relative import: `from .analysis.xyz import …` is a violation;
            # `from .analysis import …` is fine.
            if mod.startswith("analysis.") and "." in mod[len("analysis.") :]:
                # e.g. "analysis.summary" → sub-module access
                violations.append(f"line {node.lineno}: from {'.' * level}{mod} import ...")
            elif mod.startswith("analysis."):
                # "analysis.summary" with exactly one dot after "analysis"
                violations.append(f"line {node.lineno}: from {'.' * level}{mod} import ...")
        else:
            # Absolute import: `from vibesensor.analysis.xyz import …`
            parts = mod.split(".")
            if "analysis" in parts:
                idx = parts.index("analysis")
                if idx + 1 < len(parts):
                    violations.append(f"line {node.lineno}: from {mod} import ...")
    return violations


@pytest.mark.parametrize("module_path", _EXTERNAL_MODULES, ids=lambda p: p.name)
def test_external_module_uses_analysis_public_api(module_path: Path) -> None:
    """Files outside analysis/ must import from ``vibesensor.analysis``, not sub-modules."""
    source = module_path.read_text(encoding="utf-8")
    violations = _analysis_submodule_imports(source, str(module_path))
    assert not violations, (
        f"{module_path.name} imports from analysis sub-modules directly "
        f"(must use 'from .analysis import …' or 'from vibesensor.analysis import …'):\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# 2. analysis/__init__.py exports all publicly used symbols
# ---------------------------------------------------------------------------


def test_analysis_init_exports_core_symbols() -> None:
    """The analysis public API must export the key symbols used externally."""
    from vibesensor import analysis

    expected_names = [
        "summarize_run_data",
        "summarize_log",
        "build_findings_for_samples",
        "confidence_label",
        "select_top_causes",
        "map_summary",
        "DrivingPhase",
        "classify_sample_phase",
    ]
    for name in expected_names:
        assert hasattr(analysis, name), f"vibesensor.analysis.__init__ must export '{name}'"
    # __all__ must list them
    assert set(expected_names) <= set(analysis.__all__), (
        f"vibesensor.analysis.__all__ is missing: {set(expected_names) - set(analysis.__all__)}"
    )


# ---------------------------------------------------------------------------
# 3. summarize_run_data is the single pipeline entrypoint
# ---------------------------------------------------------------------------


def test_summarize_run_data_returns_expected_structure() -> None:
    """summarize_run_data produces a dict with the expected top-level keys."""
    from vibesensor.analysis import summarize_run_data

    metadata = {
        "run_id": "test-arch",
        "start_time_utc": "2026-01-01T00:00:00Z",
        "end_time_utc": "2026-01-01T00:05:00Z",
    }
    samples = [
        {
            "ts": 0.0,
            "speed_kmh": 80.0,
            "vibration_strength_db": 45.0,
            "location": "Front Left",
        },
        {
            "ts": 1.0,
            "speed_kmh": 80.0,
            "vibration_strength_db": 48.0,
            "location": "Front Left",
        },
    ]
    summary = summarize_run_data(metadata, samples, lang="en", include_samples=False)

    # Must be a dict
    assert isinstance(summary, dict)

    # Must contain core pipeline output keys
    required_keys = {
        "run_id",
        "duration_s",
        "findings",
        "top_causes",
        "speed_stats",
        "run_suitability",
        "data_quality",
    }
    missing = required_keys - set(summary.keys())
    assert not missing, f"summarize_run_data result missing keys: {missing}"

    # Findings must be a list
    assert isinstance(summary["findings"], list)
    # Top causes must be a list
    assert isinstance(summary["top_causes"], list)


# ---------------------------------------------------------------------------
# 4. No analysis module files exist outside the analysis folder
# ---------------------------------------------------------------------------


def test_no_analysis_files_outside_analysis_folder() -> None:
    """Core analysis module names must not appear outside the analysis/ folder."""
    analysis_only_names = {
        "findings.py",
        "order_analysis.py",
        "phase_segmentation.py",
        "plot_data.py",
        "strength_labels.py",
        "test_plan.py",
        "pattern_parts.py",
        "report_data_builder.py",
    }
    # Check vibesensor/ root
    root_files = {p.name for p in _SERVER_PKG.glob("*.py")}
    unexpected = root_files & analysis_only_names
    assert not unexpected, f"Analysis files found outside analysis/ folder: {unexpected}"
    # Check report/ folder
    report_dir = _SERVER_PKG / "report"
    if report_dir.is_dir():
        report_files = {p.name for p in report_dir.glob("*.py")}
        unexpected = report_files & analysis_only_names
        assert not unexpected, f"Analysis files found in report/ folder: {unexpected}"


# ---------------------------------------------------------------------------
# 5. processing.py (live signal processing) does not import analysis
# ---------------------------------------------------------------------------


def _live_processing_files() -> list[str]:
    """Collect live signal-processing files to check.

    ``processing`` is now a package; scan all ``.py`` files inside it plus
    the standalone ``udp_data_rx.py`` module.
    """
    files: list[str] = []
    processing_dir = _SERVER_PKG / "processing"
    if processing_dir.is_dir():
        for p in sorted(processing_dir.glob("*.py")):
            files.append(f"processing/{p.name}")
    else:
        # Fallback for legacy single-file layout.
        files.append("processing.py")
    files.append("udp_data_rx.py")
    return files


_LIVE_PROCESSING_FILES = _live_processing_files()


@pytest.mark.parametrize("filename", _LIVE_PROCESSING_FILES)
def test_live_processing_does_not_import_analysis(filename: str) -> None:
    """Live signal-processing modules must not depend on the analysis package.

    These modules produce the raw metrics that analysis consumes.
    A dependency in the other direction would create a circular
    coupling between the live pipeline and the post-stop pipeline.
    """
    source = (_SERVER_PKG / filename).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=filename)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        mod = node.module
        level = node.level or 0
        full = ("." * level) + mod
        if "analysis" in mod.split("."):
            violations.append(f"line {node.lineno}: from {full} import ...")
    assert not violations, (
        f"{filename} imports from the analysis package. "
        "Live signal processing must not depend on post-stop analysis:\n" + "\n".join(violations)
    )
