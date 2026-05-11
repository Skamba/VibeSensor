"""Guardrail tests enforcing diagnostics-folder ownership and pipeline discipline.

These tests verify the architectural invariants:
1. ``vibesensor.use_cases.diagnostics`` is a package marker, not a facade export surface.
2. Boundary summary serialization lives outside ``use_cases.diagnostics``.
3. Post-stop diagnostics code lives exclusively in the diagnostics folder.
"""

from __future__ import annotations

from _paths import SERVER_ROOT

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SERVER_PKG = SERVER_ROOT / "vibesensor"
# ---------------------------------------------------------------------------
# 1. diagnostics/__init__.py stays a package marker only
# ---------------------------------------------------------------------------


def test_diagnostics_package_is_marker_only() -> None:
    import vibesensor.use_cases.diagnostics as diagnostics

    assert diagnostics.__all__ == []


def test_canonical_analysis_symbols_live_in_run_analysis() -> None:
    from vibesensor.adapters.analysis_summary import build_findings_for_samples
    from vibesensor.use_cases.diagnostics.run_analysis import AnalysisResult, RunAnalysis

    assert isinstance(AnalysisResult, type)
    assert isinstance(RunAnalysis, type)
    assert callable(build_findings_for_samples)


# ---------------------------------------------------------------------------
# 2. Boundary summary serialization is outside use_cases.diagnostics
# ---------------------------------------------------------------------------


def test_diagnostics_does_not_export_boundary_summary_helpers() -> None:
    """Boundary serializers should not be exported from diagnostics use cases."""
    import vibesensor.use_cases.diagnostics as diagnostics

    assert not hasattr(diagnostics, "summarize_run_data")
    assert not hasattr(diagnostics, "summarize_log")
    assert "summarize_run_data" not in diagnostics.__all__
    assert "summarize_log" not in diagnostics.__all__


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
    assert isinstance(summary["findings"], list)
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
    }
)


def test_no_analysis_files_outside_analysis_folder() -> None:
    """Core analysis module names must not appear outside the analysis/ folder."""
    root_files = {p.name for p in _SERVER_PKG.glob("*.py")}
    unexpected = root_files & _ANALYSIS_ONLY_NAMES
    assert not unexpected, f"Analysis files found outside analysis/ folder: {unexpected}"
    report_dir = _SERVER_PKG / "adapters" / "pdf"
    if report_dir.is_dir():
        report_files = {p.name for p in report_dir.glob("*.py")}
        unexpected = report_files & _ANALYSIS_ONLY_NAMES
        assert not unexpected, f"Analysis files found in report/ folder: {unexpected}"
