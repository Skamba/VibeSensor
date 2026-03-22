"""Guardrail tests enforcing analysis-folder ownership and pipeline discipline.

These tests verify the architectural invariants:
1. Diagnostics exports app/domain analysis entry points only.
2. Boundary summary serialization lives outside ``use_cases.diagnostics``.
3. Post-stop analysis code lives exclusively in the analysis folder.
"""

from __future__ import annotations

import pytest
from _paths import SERVER_ROOT

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SERVER_PKG = SERVER_ROOT / "vibesensor"
# ---------------------------------------------------------------------------
# 1. diagnostics/__init__.py exports only app/domain analysis symbols
# ---------------------------------------------------------------------------

_EXPECTED_PUBLIC_SYMBOLS = [
    "AnalysisResult",
    "RunAnalysis",
    "build_findings_for_samples",
]


@pytest.mark.parametrize("symbol", _EXPECTED_PUBLIC_SYMBOLS)
def test_analysis_init_exports_app_level_symbol(symbol: str) -> None:
    """Each expected symbol must be importable from
    ``vibesensor.use_cases.diagnostics`` and listed in ``__all__``.
    """
    import vibesensor.use_cases.diagnostics as analysis

    assert hasattr(
        analysis,
        symbol,
    ), f"vibesensor.use_cases.diagnostics.__init__ must export '{symbol}'"
    assert symbol in analysis.__all__, (
        f"vibesensor.use_cases.diagnostics.__all__ is missing '{symbol}'"
    )


# ---------------------------------------------------------------------------
# 2. Boundary summary serialization is outside use_cases.diagnostics
# ---------------------------------------------------------------------------


def test_diagnostics_does_not_export_boundary_summary_helpers() -> None:
    """Boundary serializers should not be exported from diagnostics use cases."""
    import vibesensor.use_cases.diagnostics as analysis

    assert not hasattr(analysis, "summarize_run_data")
    assert not hasattr(analysis, "summarize_log")
    assert "summarize_run_data" not in analysis.__all__
    assert "summarize_log" not in analysis.__all__


def test_boundary_summarize_run_data_returns_expected_structure() -> None:
    """Boundary summarize_run_data produces a dict with the expected top-level keys."""
    from vibesensor.adapters.analysis_summary import summarize_run_data

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
# 3. No analysis module files exist outside the analysis folder
# ---------------------------------------------------------------------------

_ANALYSIS_ONLY_NAMES: frozenset[str] = frozenset(
    {
        "order_finding_builder.py",
        "order_match_rate.py",
        "order_matching.py",
        "order_scoring.py",
        "phase_segmentation.py",
        "plot_data.py",
        "strength_labels.py",
        "test_plan.py",
    },
)


def test_no_analysis_files_outside_analysis_folder() -> None:
    """Core analysis module names must not appear outside the analysis/ folder."""
    # Check vibesensor/ root
    root_files = {p.name for p in _SERVER_PKG.glob("*.py")}
    unexpected = root_files & _ANALYSIS_ONLY_NAMES
    assert not unexpected, f"Analysis files found outside analysis/ folder: {unexpected}"
    # Check report/ folder
    report_dir = _SERVER_PKG / "adapters" / "pdf"
    if report_dir.is_dir():
        report_files = {p.name for p in report_dir.glob("*.py")}
        unexpected = report_files & _ANALYSIS_ONLY_NAMES
        assert not unexpected, f"Analysis files found in report/ folder: {unexpected}"
