"""Architecture guardrails: domain-first pipeline boundaries.

Ensures that core analysis modules operate on domain ``Finding`` objects
(not raw dicts) and that the ``RunAnalysisResult`` aggregate is the
canonical post-analysis result.  Prevents regression to the previous
payload-first flow.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest
from _paths import SERVER_ROOT

# ── Import boundary: domain objects must not import analysis payloads ─────

_DOMAIN_DIR = SERVER_ROOT / "vibesensor" / "domain"


def _imports_analysis_types(path: Path) -> list[str]:
    """Return import lines that reference ``analysis/_types``."""
    source = path.read_text(encoding="utf-8")
    violations: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "analysis._types" in module or "analysis._types" in module.replace("..", ""):
                violations.append(f"{path.name}: from {module} import ...")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "analysis._types" in alias.name:
                    violations.append(f"{path.name}: import {alias.name}")
    return violations


def test_domain_modules_do_not_import_analysis_payload_types() -> None:
    """Domain objects must not depend on analysis payload types."""
    violations: list[str] = []
    for py_file in sorted(_DOMAIN_DIR.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        violations.extend(_imports_analysis_types(py_file))
    assert not violations, (
        "Domain modules must not import from analysis._types "
        "(payload types belong at boundaries only): " + "; ".join(violations)
    )


# ── RunAnalysisResult is available and exported ─────────────────────────


def test_run_analysis_result_is_exported_from_domain() -> None:
    """``RunAnalysisResult`` must be importable from ``vibesensor.domain``."""
    mod = importlib.import_module("vibesensor.domain")
    assert hasattr(mod, "RunAnalysisResult"), (
        "RunAnalysisResult must be exported from vibesensor.domain"
    )


def test_run_analysis_result_is_frozen_dataclass() -> None:
    """``RunAnalysisResult`` must be a frozen dataclass."""
    import dataclasses

    from vibesensor.domain import RunAnalysisResult

    assert dataclasses.is_dataclass(RunAnalysisResult)
    # Frozen check: assignment should raise
    r = RunAnalysisResult(
        run_id="test-123",
        findings=(),
        top_causes=(),
    )
    with pytest.raises(AttributeError):
        r.run_id = "other"  # type: ignore[misc]


# ── RunAnalysisResult provides domain queries ────────────────────────────


def test_run_analysis_result_provides_finding_queries() -> None:
    """``RunAnalysisResult`` must own finding classification queries."""
    from vibesensor.domain import Finding, RunAnalysisResult

    diag = Finding(finding_id="F001", confidence=0.75, suspected_source="wheel/tire")
    ref = Finding(finding_id="REF_SPEED", confidence=1.0, suspected_source="unknown")
    info = Finding(finding_id="F002", confidence=0.10, severity="info", suspected_source="unknown")

    result = RunAnalysisResult(
        run_id="test-123",
        findings=(ref, diag, info),
        top_causes=(diag,),
    )

    assert result.primary_finding == diag
    assert result.has_findings
    assert result.has_diagnostic_findings
    assert result.diagnostic_findings == (diag,)
    assert result.reference_findings == (ref,)
    assert result.informational_findings == (info,)
    assert result.non_reference_findings == (diag, info)
    assert diag in result.surfaceable_findings


def test_run_analysis_result_effective_top_causes() -> None:
    """``effective_top_causes()`` mirrors diagnosis_candidates logic."""
    from vibesensor.domain import Finding, RunAnalysisResult

    actionable = Finding(finding_id="F001", confidence=0.75, suspected_source="wheel/tire")
    result = RunAnalysisResult(
        run_id="test",
        findings=(actionable,),
        top_causes=(actionable,),
    )
    effective = result.effective_top_causes()
    assert actionable in effective


# ── finalize_findings returns domain objects ──────────────────────────────


def test_finalize_findings_returns_domain_findings() -> None:
    """``finalize_findings`` must return domain ``Finding`` objects."""
    from vibesensor.analysis.findings import finalize_findings
    from vibesensor.domain import Finding

    payloads, domain_findings = finalize_findings(
        [
            {"finding_id": "F_ORDER", "confidence": 0.7, "suspected_source": "wheel/tire"},
        ]
    )
    assert len(payloads) == 1
    assert len(domain_findings) == 1
    assert isinstance(domain_findings[0], Finding)
    assert domain_findings[0].finding_id == "F001"


# ── select_top_causes returns domain objects ─────────────────────────────


def test_select_top_causes_returns_domain_findings() -> None:
    """``select_top_causes`` must return domain ``Finding`` objects."""
    from tests.test_support.findings import make_finding_payload
    from vibesensor.analysis.top_cause_selection import select_top_causes
    from vibesensor.domain import Finding

    findings = [make_finding_payload(confidence=0.80, suspected_source="wheel/tire")]
    payloads, domain_findings = select_top_causes(findings)
    assert len(payloads) == 1
    assert len(domain_findings) == 1
    assert isinstance(domain_findings[0], Finding)


# ── RunAnalysis.summarize() produces RunAnalysisResult ───────────────────


def test_run_analysis_produces_analysis_result() -> None:
    """``RunAnalysis.summarize()`` must populate ``analysis_result``."""
    from vibesensor.analysis.summary_builder import RunAnalysis
    from vibesensor.domain import RunAnalysisResult

    metadata = {"run_id": "test-guard", "car_type": "sedan"}
    samples = [
        {
            "t_s": float(i),
            "accel_x": 0.01,
            "accel_y": 0.01,
            "accel_z": 1.0,
            "accel_mag": 1.0,
            "speed_kmh": 80.0,
            "vibration_strength_db": 5.0,
        }
        for i in range(30)
    ]
    analysis = RunAnalysis(metadata, samples)
    summary = analysis.summarize()
    assert analysis.analysis_result is not None
    assert isinstance(analysis.analysis_result, RunAnalysisResult)
    assert analysis.analysis_result.run_id == summary["run_id"]
    assert len(analysis.analysis_result.findings) == len(summary["findings"])
