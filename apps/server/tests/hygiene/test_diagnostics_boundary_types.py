"""Guard diagnostics internals against drifting back to boundary payload TypedDicts."""

from __future__ import annotations

import ast

from _paths import SERVER_ROOT

_DIAGNOSTICS_DIR = SERVER_ROOT / "vibesensor" / "use_cases" / "diagnostics"
_INTERNAL_MODULES = (
    "signal_aggregation.py",
    "run_data_preparation.py",
    "peak_table.py",
    "spectrogram.py",
    "plots.py",
    "summary_builder.py",
)
_FORBIDDEN_ANALYSIS_PAYLOAD_NAMES = frozenset(
    {
        "AmpVsPhaseRow",
        "FindingPayload",
        "FreqVsSpeedByFindingSeries",
        "MatchedAmpVsSpeedSeries",
        "PeakTableRow",
        "PhaseBoundary",
        "PhaseSegmentOut",
        "PhaseSpeedBreakdownRow",
        "PlotDataResult",
        "SpectrogramResult",
        "SpeedBreakdownRow",
    }
)


def _forbidden_analysis_payload_imports(path_name: str) -> list[str]:
    path = _DIAGNOSTICS_DIR / path_name
    tree = ast.parse(path.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != "vibesensor.shared.boundaries.analysis_payload":
            continue
        bad = sorted(
            alias.name for alias in node.names if alias.name in _FORBIDDEN_ANALYSIS_PAYLOAD_NAMES
        )
        if bad:
            violations.append(f"{path_name}: {', '.join(bad)}")
    return violations


def test_diagnostics_internal_modules_do_not_import_boundary_output_typed_dicts() -> None:
    violations = [
        violation
        for path_name in _INTERNAL_MODULES
        for violation in _forbidden_analysis_payload_imports(path_name)
    ]
    assert not violations, (
        "Diagnostics internals must use diagnostics-local value objects instead of "
        "analysis_payload TypedDicts:\n  " + "\n  ".join(violations)
    )


def test_summary_builder_keeps_finding_projection_in_serializer_seam() -> None:
    path = _DIAGNOSTICS_DIR / "summary_builder.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "vibesensor.shared.boundaries.finding"
            and any(alias.name == "finding_payload_from_domain" for alias in node.names)
        ):
            violations.append(f"L{node.lineno}: finding_payload_from_domain")
    assert not violations, (
        "summary_builder.py must leave finding serialization in the boundary serializer seam:\n  "
        + "\n  ".join(violations)
    )
