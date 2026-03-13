"""Architecture guardrails: domain-first pipeline boundaries.

Ensures that core analysis modules operate on domain ``Finding`` objects
(not raw dicts) and that the ``RunAnalysisResult`` aggregate is the
canonical post-analysis result.  Prevents regression to the previous
payload-first flow.
"""

from __future__ import annotations

import importlib
import sys

import pytest

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


# ── Domain modules do not depend on analysis payload types ───────────────


def test_domain_modules_do_not_import_analysis_types_at_runtime() -> None:
    """Domain objects must not depend on analysis payload types at runtime.

    Validates by importing all domain modules and checking that
    ``vibesensor.analysis._types`` is not pulled in as a side effect.
    """
    analysis_types_key = "vibesensor.analysis._types"
    was_loaded = analysis_types_key in sys.modules

    if not was_loaded:
        # Clear cached domain imports to get a clean check
        domain_keys = [k for k in sys.modules if k.startswith("vibesensor.domain")]
        saved = {k: sys.modules.pop(k) for k in domain_keys}
        try:
            importlib.import_module("vibesensor.domain")
            assert analysis_types_key not in sys.modules, (
                "Domain modules must not import from vibesensor.analysis._types "
                "(payload types belong at boundaries only)"
            )
        finally:
            sys.modules.update(saved)


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


# ── RunAnalysisResult.from_summary() factory ─────────────────────────────


def test_run_analysis_result_from_summary_factory() -> None:
    """``from_summary()`` must construct a valid aggregate from a dict."""
    from tests.test_support.findings import make_finding_payload
    from vibesensor.domain import Finding, RunAnalysisResult

    summary = {
        "run_id": "test-from-summary",
        "findings": [
            make_finding_payload(finding_id="F001", confidence=0.80),
            make_finding_payload(finding_id="REF_SPEED", severity="reference", confidence=1.0),
        ],
        "top_causes": [
            make_finding_payload(finding_id="F001", confidence=0.80),
        ],
        "duration_s": 120.0,
        "rows": 500,
        "sensor_count_used": 3,
        "lang": "nl",
    }
    result = RunAnalysisResult.from_summary(summary)
    assert result.run_id == "test-from-summary"
    assert len(result.findings) == 2
    assert len(result.top_causes) == 1
    assert result.duration_s == 120.0
    assert result.sample_count == 500
    assert result.sensor_count == 3
    assert result.lang == "nl"
    assert all(isinstance(f, Finding) for f in result.findings)
    assert result.has_diagnostic_findings
    assert len(result.reference_findings) == 1


# ── RunAnalysisResult.has_relevant_reference_gap() ───────────────────────


def test_run_analysis_result_reference_gap_detection() -> None:
    """``has_relevant_reference_gap()`` detects source-relevant gaps."""
    from vibesensor.domain import Finding, RunAnalysisResult, VibrationSource

    ref_speed = Finding(finding_id="REF_SPEED", suspected_source="unknown")
    ref_wheel = Finding(finding_id="REF_WHEEL", suspected_source="unknown")
    ref_engine = Finding(finding_id="REF_ENGINE", suspected_source="unknown")
    diag = Finding(finding_id="F001", confidence=0.80, suspected_source="wheel/tire")

    # REF_SPEED is relevant for any source
    result = RunAnalysisResult(run_id="test", findings=(ref_speed, diag), top_causes=(diag,))
    assert result.has_relevant_reference_gap(VibrationSource.WHEEL_TIRE)
    assert result.has_relevant_reference_gap(VibrationSource.ENGINE)

    # REF_WHEEL is relevant for wheel/tire and driveline
    result2 = RunAnalysisResult(run_id="test", findings=(ref_wheel, diag), top_causes=(diag,))
    assert result2.has_relevant_reference_gap(VibrationSource.WHEEL_TIRE)
    assert result2.has_relevant_reference_gap(VibrationSource.DRIVELINE)
    assert not result2.has_relevant_reference_gap(VibrationSource.ENGINE)

    # REF_ENGINE is relevant for engine only
    result3 = RunAnalysisResult(run_id="test", findings=(ref_engine, diag), top_causes=(diag,))
    assert result3.has_relevant_reference_gap(VibrationSource.ENGINE)
    assert not result3.has_relevant_reference_gap(VibrationSource.WHEEL_TIRE)


# ── RunAnalysisResult.top_strength_db() ──────────────────────────────────


def test_run_analysis_result_top_strength_db() -> None:
    """``top_strength_db()`` finds the best strength from findings."""
    from vibesensor.domain import Finding, RunAnalysisResult

    f1 = Finding(
        finding_id="F001",
        confidence=0.80,
        suspected_source="wheel/tire",
        vibration_strength_db=12.5,
    )
    f2 = Finding(
        finding_id="F002",
        confidence=0.60,
        suspected_source="engine",
        vibration_strength_db=8.0,
    )
    result = RunAnalysisResult(run_id="test", findings=(f1, f2), top_causes=(f1,))
    assert result.top_strength_db() == 12.5

    # No strength → None
    f3 = Finding(finding_id="F003", confidence=0.50, suspected_source="engine")
    result2 = RunAnalysisResult(run_id="test", findings=(f3,), top_causes=(f3,))
    assert result2.top_strength_db() is None


# ── diagnosis_candidates delegates to RunAnalysisResult ──────────────────


def test_diagnosis_candidates_delegates_to_domain_aggregate() -> None:
    """``select_effective_top_causes`` must produce identical results to
    ``RunAnalysisResult.effective_top_causes()`` for the same data."""
    from tests.test_support.findings import make_finding_payload, make_ref_finding
    from vibesensor.analysis.diagnosis_candidates import select_effective_top_causes
    from vibesensor.domain import Finding, RunAnalysisResult

    diag1 = make_finding_payload(finding_id="F001", confidence=0.80, suspected_source="wheel/tire")
    diag2 = make_finding_payload(finding_id="F002", confidence=0.60, suspected_source="engine")
    ref = make_ref_finding(finding_id="REF_SPEED")

    # Build domain aggregate for comparison
    domain_findings = tuple(Finding.from_payload(f) for f in [diag1, diag2, ref])
    domain_tc = tuple(Finding.from_payload(f) for f in [diag1])
    aggregate = RunAnalysisResult(run_id="test", findings=domain_findings, top_causes=domain_tc)
    domain_effective_ids = {f.finding_id for f in aggregate.effective_top_causes()}

    # Run boundary function
    _all, _non_ref, _tc_all, effective = select_effective_top_causes([diag1], [diag1, diag2, ref])
    boundary_effective_ids = {str(f.get("finding_id", "")) for f in effective}

    assert boundary_effective_ids == domain_effective_ids


# ── Report mapping context builds domain aggregate ───────────────────────


def test_report_mapping_context_has_domain_aggregate() -> None:
    """``prepare_report_mapping_context`` must build a domain aggregate."""
    from tests.test_support.findings import make_finding_payload
    from vibesensor.domain import RunAnalysisResult
    from vibesensor.report.mapping import prepare_report_mapping_context

    summary = {
        "run_id": "test-context",
        "findings": [make_finding_payload(finding_id="F001")],
        "top_causes": [make_finding_payload(finding_id="F001")],
        "lang": "en",
    }
    context = prepare_report_mapping_context(summary)
    assert context.domain_aggregate is not None
    assert isinstance(context.domain_aggregate, RunAnalysisResult)
    assert len(context.domain_aggregate.findings) == 1


# ── non_reference_findings uses domain classification ────────────────────


def test_non_reference_findings_uses_domain_classification() -> None:
    """``non_reference_findings`` must use domain ``Finding.is_reference``."""
    from tests.test_support.findings import make_finding_payload, make_ref_finding
    from vibesensor.analysis.diagnosis_candidates import non_reference_findings

    findings = [
        make_finding_payload(finding_id="F001"),
        make_ref_finding(finding_id="REF_SPEED"),
        make_finding_payload(finding_id="F002"),
    ]
    result = non_reference_findings(findings)
    ids = [str(f.get("finding_id", "")) for f in result]
    assert "F001" in ids
    assert "F002" in ids
    assert "REF_SPEED" not in ids
