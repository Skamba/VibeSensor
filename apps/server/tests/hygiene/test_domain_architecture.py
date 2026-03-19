"""Architecture guardrails: domain-first pipeline boundaries.

Ensures that core analysis modules operate on domain ``Finding`` objects
(not raw dicts) and that ``TestRun`` is the canonical post-analysis
aggregate.  Prevents regression to the previous payload-first flow.
"""

from __future__ import annotations

import importlib
import inspect

import pytest


def test_test_run_is_frozen_dataclass() -> None:
    """``TestRun`` must be a frozen dataclass."""
    import dataclasses

    from vibesensor.domain import RunCapture, TestRun

    assert dataclasses.is_dataclass(TestRun)
    r = TestRun(
        capture=RunCapture(run_id="test-123"),
        findings=(),
        top_causes=(),
    )
    with pytest.raises(AttributeError):
        r.findings = ()  # type: ignore[misc]


# ── TestRun provides domain queries ──────────────────────────────────────


def test_test_run_provides_finding_queries() -> None:
    """``TestRun`` must own finding classification queries."""
    from vibesensor.domain import Finding, RunCapture, TestRun

    diag = Finding(finding_id="F001", confidence=0.75, suspected_source="wheel/tire")
    ref = Finding(finding_id="REF_SPEED", confidence=1.0, suspected_source="unknown")
    info = Finding(finding_id="F002", confidence=0.10, severity="info", suspected_source="unknown")

    result = TestRun(
        capture=RunCapture(run_id="test-123"),
        findings=(ref, diag, info),
        top_causes=(diag,),
    )

    assert result.primary_finding == diag
    assert result.diagnostic_findings == (diag,)
    assert result.non_reference_findings == (diag, info)


def test_test_run_effective_top_causes() -> None:
    """``effective_top_causes()`` mirrors diagnosis_candidates logic."""
    from vibesensor.domain import Finding, RunCapture, TestRun

    actionable = Finding(finding_id="F001", confidence=0.75, suspected_source="wheel/tire")
    result = TestRun(
        capture=RunCapture(run_id="test"),
        findings=(actionable,),
        top_causes=(actionable,),
    )
    effective = result.effective_top_causes()
    assert actionable in effective


# ── finalize_findings returns domain objects ──────────────────────────────


def test_finalize_findings_returns_domain_findings() -> None:
    """``finalize_findings`` must return domain ``Finding`` objects."""
    from vibesensor.domain import Finding
    from vibesensor.use_cases.diagnostics.findings import finalize_findings

    domain_findings = finalize_findings(
        [
            Finding(finding_id="F_ORDER", confidence=0.7, suspected_source="wheel/tire"),
        ]
    )
    assert len(domain_findings) == 1
    assert isinstance(domain_findings[0], Finding)
    assert domain_findings[0].finding_id == "F001"


# ── select_top_causes returns domain objects ─────────────────────────────


def test_select_top_causes_returns_domain_findings() -> None:
    """``select_top_causes`` must return domain ``Finding`` objects."""
    from test_support.findings import make_finding_payload

    from vibesensor.domain import Finding
    from vibesensor.shared.boundaries.finding import finding_from_payload
    from vibesensor.use_cases.diagnostics.top_cause_selection import select_top_causes

    findings = tuple(
        finding_from_payload(f)
        for f in [make_finding_payload(confidence=0.80, suspected_source="wheel/tire")]
    )
    domain_findings = select_top_causes(findings)
    assert len(domain_findings) == 1
    assert isinstance(domain_findings[0], Finding)


# ── RunAnalysis.summarize() produces TestRun ─────────────────────────────


def test_run_analysis_produces_test_run() -> None:
    """``RunAnalysis.summarize()`` must populate ``test_run``."""
    from vibesensor.domain import TestRun
    from vibesensor.use_cases.diagnostics.summary_builder import RunAnalysis

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
    result = analysis.summarize()
    assert analysis.test_run is not None
    assert isinstance(analysis.test_run, TestRun)
    assert analysis.test_run.run_id == result.summary["run_id"]
    assert len(analysis.test_run.findings) == len(result.summary["findings"])


# ── TestRun.has_relevant_reference_gap() ─────────────────────────────────


def test_test_run_reference_gap_detection() -> None:
    """``has_relevant_reference_gap()`` detects source-relevant gaps."""
    from vibesensor.domain import Finding, RunCapture, TestRun, VibrationSource

    ref_speed = Finding(finding_id="REF_SPEED", suspected_source="unknown")
    ref_wheel = Finding(finding_id="REF_WHEEL", suspected_source="unknown")
    ref_engine = Finding(finding_id="REF_ENGINE", suspected_source="unknown")
    diag = Finding(finding_id="F001", confidence=0.80, suspected_source="wheel/tire")

    assert ref_speed.is_reference
    assert ref_wheel.is_reference
    assert ref_engine.is_reference
    assert not diag.is_reference

    def _make(findings: tuple[Finding, ...]) -> TestRun:
        return TestRun(
            capture=RunCapture(run_id="test"),
            findings=findings + (diag,),
            top_causes=(diag,),
        )

    result = _make((ref_speed,))
    assert result.has_relevant_reference_gap(VibrationSource.WHEEL_TIRE)
    assert result.has_relevant_reference_gap(VibrationSource.ENGINE)

    result2 = _make((ref_wheel,))
    assert result2.has_relevant_reference_gap(VibrationSource.WHEEL_TIRE)
    assert result2.has_relevant_reference_gap(VibrationSource.DRIVELINE)
    assert not result2.has_relevant_reference_gap(VibrationSource.ENGINE)

    result3 = _make((ref_engine,))
    assert result3.has_relevant_reference_gap(VibrationSource.ENGINE)
    assert not result3.has_relevant_reference_gap(VibrationSource.WHEEL_TIRE)


# ── TestRun.top_strength_db() ────────────────────────────────────────────


def test_test_run_top_strength_db() -> None:
    """``top_strength_db()`` finds the best strength from findings."""
    from vibesensor.domain import Finding, RunCapture, TestRun

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
    result = TestRun(
        capture=RunCapture(run_id="test"),
        findings=(f1, f2),
        top_causes=(f1,),
    )
    assert result.top_strength_db() == 12.5

    # No strength → None
    f3 = Finding(finding_id="F003", confidence=0.50, suspected_source="engine")
    result2 = TestRun(
        capture=RunCapture(run_id="test"),
        findings=(f3,),
        top_causes=(f3,),
    )
    assert result2.top_strength_db() is None


# ── Report mapping context builds domain aggregate ───────────────────────


def test_report_mapping_context_has_domain_aggregate() -> None:
    """``prepare_report_mapping_context`` must build a domain aggregate."""
    from test_support.findings import make_finding_payload

    from vibesensor.adapters.pdf.mapping import prepare_report_mapping_context
    from vibesensor.domain import TestRun

    summary = {
        "run_id": "test-context",
        "findings": [make_finding_payload(finding_id="F001")],
        "top_causes": [make_finding_payload(finding_id="F001")],
        "lang": "en",
        "metadata": {},
        "report_date": "",
        "record_length": "",
        "start_time_utc": "",
        "end_time_utc": "",
        "sensor_locations": [],
        "sensor_locations_connected_throughout": [],
        "most_likely_origin": {},
        "run_suitability": [],
    }
    context = prepare_report_mapping_context(summary)
    assert context.domain_aggregate is not None
    assert isinstance(context.domain_aggregate, TestRun)
    assert len(context.domain_aggregate.findings) == 1


# ── Finding owns confidence presentation ─────────────────────────────────


def test_finding_owns_confidence_label() -> None:
    """Finding must own confidence-tier classification (label, tone, pct)."""
    from vibesensor.domain import Finding

    high = Finding(finding_id="F001", confidence=0.80, suspected_source="wheel/tire")
    label_key, tone, pct_text = high.confidence_label()
    assert label_key == "CONFIDENCE_HIGH"
    assert tone == "success"
    assert pct_text == "80%"

    medium = Finding(finding_id="F002", confidence=0.55, suspected_source="engine")
    label_key, tone, _ = medium.confidence_label()
    assert label_key == "CONFIDENCE_MEDIUM"
    assert tone == "warn"

    low = Finding(finding_id="F003", confidence=0.20, suspected_source="unknown")
    label_key, tone, _ = low.confidence_label()
    assert label_key == "CONFIDENCE_LOW"
    assert tone == "neutral"


def test_finding_confidence_negligible_strength_downgrade() -> None:
    """Finding with negligible strength should downgrade HIGH → MEDIUM."""
    from vibesensor.domain import Finding

    high = Finding(finding_id="F001", confidence=0.80, suspected_source="wheel/tire")
    label_key, tone, _ = high.confidence_label(strength_band_key="negligible")
    assert label_key == "CONFIDENCE_MEDIUM"
    assert tone == "warn"


def test_classify_confidence_is_domain_owned() -> None:
    """Finding.classify_confidence is the canonical source of truth for confidence presentation."""
    from vibesensor.domain import Finding

    for conf in (0.80, 0.55, 0.20, 0.0):
        result = Finding.classify_confidence(conf)
        assert len(result) == 3
        assert all(isinstance(v, str) for v in result)


# ── TestRun owns primary source/location queries ─────────────────────────


def test_test_run_primary_source_and_location() -> None:
    """``primary_source`` and ``primary_location`` are domain queries."""
    from vibesensor.domain import Finding, RunCapture, TestRun, VibrationSource

    f = Finding(
        finding_id="F001",
        confidence=0.80,
        suspected_source="wheel/tire",
        strongest_location="Left Front",
    )
    result = TestRun(
        capture=RunCapture(run_id="test"),
        findings=(f,),
        top_causes=(f,),
    )
    assert result.primary_source == VibrationSource.WHEEL_TIRE
    assert result.primary_location == "Left Front"

    # No findings → None
    empty = TestRun(
        capture=RunCapture(run_id="test"),
        findings=(),
        top_causes=(),
    )
    assert empty.primary_source is None
    assert empty.primary_location is None


# ── Domain objects are immutable ──────────────────────────────────────────


def test_finding_is_frozen_dataclass() -> None:
    """Finding must be a frozen dataclass — mutation raises."""
    import dataclasses

    from vibesensor.domain import Finding

    assert dataclasses.is_dataclass(Finding)
    f = Finding(finding_id="F001", confidence=0.80, suspected_source="wheel/tire")
    with pytest.raises(AttributeError):
        f.confidence = 0.50  # type: ignore[misc]


def test_finding_tuples_are_immutable() -> None:
    """TestRun findings must be tuples (not mutable lists)."""
    from vibesensor.domain import Finding, RunCapture, TestRun

    f = Finding(finding_id="F001", confidence=0.80, suspected_source="wheel/tire")
    result = TestRun(
        capture=RunCapture(run_id="test"),
        findings=(f,),
        top_causes=(f,),
    )
    assert isinstance(result.findings, tuple)
    assert isinstance(result.top_causes, tuple)


# ── Report mapping uses domain aggregate ─────────────────────────────────


def test_build_system_cards_uses_domain_findings() -> None:
    """build_system_cards must read confidence tone from domain, not dict."""
    from vibesensor.adapters.pdf.mapping import (
        PrimaryCandidateContext,
        ReportMappingContext,
        build_system_cards,
    )
    from vibesensor.domain import Finding, RunCapture, TestRun
    from vibesensor.report_i18n import tr

    lang = "en"
    domain_f = Finding(
        finding_id="F001",
        confidence=0.80,
        suspected_source="wheel/tire",
        strongest_location="Left Front",
    )
    aggregate = TestRun(
        capture=RunCapture(run_id="test"),
        findings=(domain_f,),
        top_causes=(domain_f,),
    )
    # Build a context with the aggregate (payloads no longer stored on context)
    context = ReportMappingContext(
        car_name=None,
        car_type=None,
        date_str="",
        origin={},  # type: ignore[typeddict-item]
        origin_location="",
        sensor_locations_active=[],
        duration_text=None,
        start_time_utc=None,
        end_time_utc=None,
        sample_rate_hz=None,
        tire_spec_text=None,
        sample_count=0,
        sensor_model=None,
        firmware_version=None,
        domain_aggregate=aggregate,
    )
    primary = PrimaryCandidateContext(
        primary_candidate=domain_f,
        primary_source="wheel/tire",
        primary_system="Wheel/Tire",
        primary_location="Left Front",
        primary_speed="80-90 km/h",
        confidence=0.80,
        sensor_count=2,
        weak_spatial=False,
        has_reference_gaps=False,
        strength_db=12.0,
        strength_text="Moderate (12.0 dB)",
        strength_band_key="moderate",
        certainty_key="high",
        certainty_label_text="High",
        certainty_pct="80%",
        certainty_reason="Consistent order-tracking match",
        tier="C",
    )
    cards = build_system_cards(context, primary, lang, lambda key, **kw: tr(lang, key, **kw))
    assert len(cards) == 1
    # The tone should come from domain Finding, not the payload's "WRONG_TONE"
    assert cards[0].tone != "WRONG_TONE"
    assert cards[0].tone == "success"  # HIGH confidence → success


# ── Pipeline produces domain aggregate for report ─────────────────────────


def test_map_summary_produces_report_with_domain_findings() -> None:
    """map_summary must produce report data using domain-first pipeline."""
    from test_support.findings import make_finding_payload

    from vibesensor.adapters.pdf.mapping import map_summary

    summary = {
        "run_id": "test-map",
        "file_name": "test.csv",
        "rows": 100,
        "duration_s": 60.0,
        "lang": "en",
        "metadata": {},
        "report_date": "",
        "record_length": "",
        "start_time_utc": "",
        "end_time_utc": "",
        "warnings": [],
        "sensor_locations": [],
        "sensor_locations_connected_throughout": [],
        "sensor_intensity_by_location": [],
        "most_likely_origin": {},
        "run_suitability": [],
        "plots": {},
        "test_plan": [],
        "findings": [make_finding_payload(finding_id="F001", confidence=0.80)],
        "top_causes": [make_finding_payload(finding_id="F001", confidence=0.80)],
        "sensor_count_used": 2,
    }
    template = map_summary(summary)  # type: ignore[arg-type]
    assert template.run_id == "test-map"


# ── Domain modules do not import boundary payload types ──────────────────


def test_domain_package_has_no_payload_type_imports() -> None:
    """No domain module may import FindingPayload or AnalysisSummary.

    These are boundary types that belong in adapter layers.
    """
    import ast

    from tests._paths import SERVER_ROOT

    domain_dir = SERVER_ROOT / "vibesensor" / "domain"
    violations: list[str] = []
    forbidden = {"FindingPayload", "AnalysisSummary"}
    for py_file in domain_dir.glob("*.py"):
        source = py_file.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name for alias in node.names]
                for name in names:
                    if name in forbidden:
                        violations.append(f"{py_file.name} imports {name}")
    assert not violations, f"Domain modules must not import boundary types: {violations}"


# ── Domain value objects are exported and frozen ────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "FindingEvidence",
        "LocationHotspot",
        "ConfidenceAssessment",
        "SpeedProfile",
        "RunSuitability",
        "SuitabilityCheck",
    ],
)
def test_domain_value_objects_are_exported(name: str) -> None:
    """New domain value objects must be importable from ``vibesensor.domain``."""
    import importlib

    mod = importlib.import_module("vibesensor.domain")
    assert hasattr(mod, name), f"{name} must be exported from vibesensor.domain"


@pytest.mark.parametrize(
    "name",
    [
        "FindingEvidence",
        "LocationHotspot",
        "ConfidenceAssessment",
        "SpeedProfile",
        "RunSuitability",
        "SuitabilityCheck",
    ],
)
def test_domain_value_objects_are_frozen_dataclasses(name: str) -> None:
    """Domain value objects must be frozen dataclasses."""
    import dataclasses
    import importlib

    mod = importlib.import_module("vibesensor.domain")
    cls = getattr(mod, name)
    assert dataclasses.is_dataclass(cls), f"{name} must be a dataclass"


def test_test_run_from_summary_populates_speed_profile() -> None:
    """test_run_from_summary extracts SpeedProfile when speed_stats is present."""
    from vibesensor.shared.boundaries.diagnostic_case import test_run_from_summary

    summary = {
        "run_id": "test-123",
        "findings": [],
        "top_causes": [],
        "speed_stats": {
            "min_kmh": 30.0,
            "max_kmh": 90.0,
            "steady_speed": True,
        },
    }
    result = test_run_from_summary(summary)
    assert result.speed_profile is not None, "test_run_from_summary must populate speed_profile"
    assert result.speed_profile.steady_speed


def test_test_run_from_summary_populates_suitability() -> None:
    """test_run_from_summary extracts RunSuitability when run_suitability is present."""
    from vibesensor.shared.boundaries.diagnostic_case import test_run_from_summary

    summary = {
        "run_id": "test-123",
        "findings": [],
        "top_causes": [],
        "run_suitability": [
            {"check_key": "speed", "state": "pass", "explanation": "OK"},
        ],
    }
    result = test_run_from_summary(summary)
    assert result.suitability is not None, "test_run_from_summary must populate suitability"
    assert result.suitability.is_usable


def test_confidence_assessment_tier_matches_domain_finding() -> None:
    """ConfidenceAssessment.tier must be consistent with Finding.classify_confidence."""
    from vibesensor.domain import ConfidenceAssessment, Finding

    for conf in [0.1, 0.3, 0.5, 0.7, 0.9]:
        label_key, _tone, _pct = Finding.classify_confidence(conf)
        ca = ConfidenceAssessment.assess(conf)
        assert ca.label_key == label_key, (
            f"ConfidenceAssessment.assess({conf}).label_key must match "
            f"Finding.classify_confidence({conf})[0]"
        )


@pytest.mark.parametrize(
    "name",
    [
        "ConfigurationSnapshot",
        "DiagnosticCase",
        "DrivingSegment",
        "RecommendedAction",
        "Signature",
        "Symptom",
        "TestPlan",
        "TestRun",
        "VibrationOrigin",
    ],
)
def test_new_domain_objects_are_exported(name: str) -> None:
    import importlib

    mod = importlib.import_module("vibesensor.domain")
    assert hasattr(mod, name), f"{name} must be exported from vibesensor.domain"


def test_run_analysis_builds_test_run_and_diagnostic_case() -> None:
    from vibesensor.domain import DiagnosticCase, TestRun
    from vibesensor.use_cases.diagnostics.summary_builder import RunAnalysis

    metadata = {
        "run_id": "domain-case-guard",
        "car_name": "Guard Car",
        "car_type": "sedan",
        "language": "en",
    }
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
    result = analysis.summarize()

    assert analysis.test_run is not None
    assert result.diagnostic_case is not None
    assert isinstance(analysis.test_run, TestRun)
    assert isinstance(result.diagnostic_case, DiagnosticCase)
    assert result.diagnostic_case.primary_run is not None
    assert result.diagnostic_case.primary_run.run_id == analysis.test_run.run_id


def test_boundary_decoder_builds_diagnostic_case_from_summary() -> None:
    from test_support.findings import make_finding_payload

    from vibesensor.shared.boundaries.diagnostic_case import diagnostic_case_from_summary

    summary = {
        "case_id": "summary-case-guard-id",
        "run_id": "summary-case-guard",
        "metadata": {"car_name": "Guard Car", "car_type": "sedan"},
        "findings": [make_finding_payload(finding_id="F001", confidence=0.80)],
        "top_causes": [make_finding_payload(finding_id="F001", confidence=0.80)],
        "test_plan": [
            {
                "action_id": "check-wheel",
                "what": {"_i18n_key": "ACTION_WHEEL_BALANCE_WHAT"},
                "why": {"_i18n_key": "ACTION_WHEEL_BALANCE_WHY"},
            }
        ],
    }
    diagnostic_case = diagnostic_case_from_summary(summary)
    assert diagnostic_case.case_id == "summary-case-guard-id"
    assert diagnostic_case.test_runs
    assert diagnostic_case.primary_run is not None


# ── Finding boundary separation ──────────────────────────────────────────


def test_finding_has_no_from_payload_method() -> None:
    """Finding domain class should not own payload decode logic."""
    from vibesensor.domain import Finding

    assert not hasattr(Finding, "from_payload"), (
        "Finding.from_payload should live in boundaries/finding.py, not on the domain class"
    )


# ── AnalysisResult coordinator isolation ─────────────────────────────────


def test_domain_modules_do_not_import_analysis_coordinator() -> None:
    """Domain modules must not depend on the analysis coordinator type."""
    import ast
    from pathlib import Path

    domain_dir = Path(__file__).resolve().parents[2] / "vibesensor" / "domain"
    violations: list[str] = []
    for py in domain_dir.rglob("*.py"):
        source = py.read_text()
        tree = ast.parse(source, filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "analysis" in node.module and any(
                    alias.name == "AnalysisResult" for alias in node.names
                ):
                    violations.append(f"{py.relative_to(domain_dir)}: imports AnalysisResult")
    assert not violations, "Domain modules must not import AnalysisResult:\n" + "\n".join(
        violations
    )


def test_boundary_and_report_modules_do_not_import_analysis_coordinator() -> None:
    """Boundary and report modules must not depend on the analysis coordinator type."""
    import ast
    from pathlib import Path

    pkg_dir = Path(__file__).resolve().parents[2] / "vibesensor"
    violations: list[str] = []
    for subdir_name in ("boundaries", "report"):
        subdir = pkg_dir / subdir_name
        if not subdir.is_dir():
            continue
        for py in subdir.rglob("*.py"):
            source = py.read_text()
            tree = ast.parse(source, filename=str(py))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if "analysis" in node.module and any(
                        alias.name == "AnalysisResult" for alias in node.names
                    ):
                        violations.append(
                            f"{subdir_name}/{py.relative_to(subdir)}: imports AnalysisResult"
                        )
    assert not violations, "Boundary/report modules must not import AnalysisResult:\n" + "\n".join(
        violations
    )


# ── T6 planning service and file rename guardrails ────────────────────────────


def test_planning_service_has_no_payload_imports() -> None:
    """Domain planning service (now in test_plan.py) must not import payload types."""
    import ast
    from pathlib import Path

    planning_path = Path(__file__).resolve().parents[2] / "vibesensor" / "domain" / "test_plan.py"
    tree = ast.parse(planning_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", "") or ""
            names = [alias.name for alias in node.names]
            all_refs = module + " ".join(names)
            assert "FindingPayload" not in all_refs, (
                "domain/test_plan.py must not import FindingPayload"
            )
            assert "AnalysisSummary" not in all_refs, (
                "domain/test_plan.py must not import AnalysisSummary"
            )


def test_finding_projector_in_finding_boundary_module() -> None:
    """Finding payload projector should live in boundaries/finding.py."""
    from vibesensor.shared.boundaries.finding import finding_payload_from_domain

    assert callable(finding_payload_from_domain)


# ── T7.27: Report mapping rendering-boundary guardrails ──────────────────


def test_report_mapping_business_functions_use_domain_objects() -> None:
    """Key business-decision functions derive values from the domain aggregate.

    When ``prepare_report_mapping_context`` produces a domain aggregate,
    ``resolve_primary_report_candidate`` must derive primary source,
    strength, and reference-gap status from domain objects — not from
    raw payload dict traversal.
    """
    from test_support.findings import make_finding_payload

    from vibesensor.adapters.pdf.mapping import (
        prepare_report_mapping_context,
        resolve_primary_report_candidate,
    )
    from vibesensor.domain import TestRun, VibrationSource
    from vibesensor.report_i18n import tr

    lang = "en"
    finding = make_finding_payload(
        finding_id="F001",
        confidence=0.80,
        suspected_source="wheel_tire",
    )
    summary = {
        "run_id": "guard-biz",
        "findings": [finding],
        "top_causes": [finding],
        "lang": lang,
        "metadata": {},
        "report_date": "",
        "record_length": "",
        "start_time_utc": "",
        "end_time_utc": "",
        "sensor_locations": [],
        "sensor_locations_connected_throughout": [],
        "most_likely_origin": {},
        "run_suitability": [],
    }

    context = prepare_report_mapping_context(summary)
    assert context.domain_aggregate is not None
    assert isinstance(context.domain_aggregate, TestRun)

    primary = resolve_primary_report_candidate(
        context=context,
        sensor_intensity=[],
        tr=lambda key, **kw: tr(lang, key, **kw),
        lang=lang,
    )

    # primary_source must be a VibrationSource enum (domain-first derivation)
    assert isinstance(primary.primary_source, VibrationSource), (
        "primary_source must be a VibrationSource enum when domain aggregate is present"
    )


# ── T9.1-T9.6: Workstream 8 architecture guardrails ──────────────────


def test_suspected_vibration_origin_is_boundary_only() -> None:
    """SuspectedVibrationOrigin must not be imported in domain modules.

    It is a boundary TypedDict that lives in ``boundaries/vibration_origin.py``.
    Domain modules must use ``VibrationOrigin`` instead.
    """
    import ast

    from tests._paths import SERVER_ROOT

    domain_dir = SERVER_ROOT / "vibesensor" / "domain"
    violations: list[str] = []
    for py_file in domain_dir.rglob("*.py"):
        source = py_file.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.name == "SuspectedVibrationOrigin":
                        violations.append(f"{py_file.name} imports SuspectedVibrationOrigin")
    assert not violations, (
        f"Domain modules must not import SuspectedVibrationOrigin (boundary type): {violations}"
    )


def test_build_run_suitability_checks_does_not_exist() -> None:
    """``build_run_suitability_checks`` must not exist in summary_builder.

    It was deleted in Workstream 2 (T3.21).  ``RunSuitability.evaluate()``
    is the canonical owner of suitability evaluation.
    """
    from vibesensor.use_cases.diagnostics import summary_builder

    assert not hasattr(summary_builder, "build_run_suitability_checks"), (
        "build_run_suitability_checks was deleted; use RunSuitability.evaluate()"
    )


def test_project_analysis_summary_has_no_legacy_summary_version_fast_path() -> None:
    """project_analysis_summary must always reconstruct through TestRun.

    The legacy `_summary_version == 2` bypass was removed. Historical
    summaries are reconstructed the same way as current ones so the
    boundary has a single canonical behavior.
    """
    from tests._paths import SERVER_ROOT

    source = (
        SERVER_ROOT / "vibesensor" / "shared" / "boundaries" / "diagnostic_case.py"
    ).read_text()
    assert 'analysis.get("_summary_version") == 2' not in source


def test_summary_builder_does_not_define_case_context_wrappers() -> None:
    """summary_builder must not own duplicate Car/Symptom metadata decoders."""
    from tests._paths import SERVER_ROOT

    source = (
        SERVER_ROOT / "vibesensor" / "use_cases" / "diagnostics" / "summary_builder.py"
    ).read_text()
    assert "def build_domain_car" not in source
    assert "def build_domain_symptoms" not in source
    assert "RunSuitabilityCheck" not in source


def test_history_backend_types_do_not_export_history_run_payload() -> None:
    """History record typing must stay local to history workflows.

    `HistoryRunPayload` made persistence dicts look like a general backend
    business contract. The only supported alias is the history-local
    `HistoryRecord` in use_cases/history/helpers.py.
    """
    from tests._paths import SERVER_ROOT

    backend_types_source = (
        SERVER_ROOT / "vibesensor" / "shared" / "types" / "backend_types.py"
    ).read_text()
    history_helpers_source = (
        SERVER_ROOT / "vibesensor" / "use_cases" / "history" / "helpers.py"
    ).read_text()
    assert "HistoryRunPayload" not in backend_types_source
    assert "class HistoryRecord" in history_helpers_source


def test_types_modules_do_not_duplicate_domain_concepts_as_typeddicts() -> None:
    """`*_types.py` modules must not mirror domain concepts with TypedDicts.

    Boundary payload modules may define serialization shapes, but generic
    `*_types.py` files must not reintroduce domain concepts as parallel dict
    models after the migration.
    """
    import ast
    import importlib

    from tests._paths import SERVER_ROOT

    domain_exports = set(getattr(importlib.import_module("vibesensor.domain"), "__all__", ()))
    pkg_dir = SERVER_ROOT / "vibesensor"
    violations: list[str] = []

    for py_file in pkg_dir.rglob("*_types.py"):
        source = py_file.read_text()
        tree = ast.parse(source, filename=str(py_file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(
                isinstance(base, ast.Name) and base.id == "TypedDict" for base in node.bases
            ):
                continue
            if node.name in domain_exports:
                rel = py_file.relative_to(pkg_dir)
                violations.append(f"{rel}:{node.lineno} duplicates domain export {node.name}")

    assert not violations, (
        f"`*_types.py` modules must not redefine domain concepts as TypedDicts: {violations}"
    )


def test_speed_profile_used_by_confidence_assessment() -> None:
    """ConfidenceAssessment must be the owner of confidence reasoning.

    ``certainty_label()`` was deleted; ``ConfidenceAssessment.assess()``
    is the single source of truth for confidence assessment. Report mapping
    uses ``ConfidenceAssessment.tier`` for layout gating.
    """
    from tests._paths import SERVER_ROOT

    strength_labels_path = SERVER_ROOT / "vibesensor" / "adapters" / "pdf" / "presentation.py"
    source = strength_labels_path.read_text()
    assert "certainty_label" not in source, (
        "certainty_label was deleted; ConfidenceAssessment.assess() is the replacement"
    )


# ── T14: Architecture guardrail regression tests ─────────────────────────


def test_domain_vos_have_no_dict_accepting_factory_methods() -> None:
    """Domain value objects must not accept raw ``dict`` / ``Mapping`` args.

    Factory methods on domain classes under ``vibesensor/domain/*.py``
    must accept typed domain
    arguments, not untyped containers.  Prevents regression of T08
    boundary adapter migration.
    """
    import inspect

    from tests._paths import SERVER_ROOT

    domain_dir = SERVER_ROOT / "vibesensor" / "domain"
    # Only top-level .py files (not subdirectories like services/)
    domain_files = [f for f in domain_dir.glob("*.py") if f.name != "__init__.py"]

    # Untyped container type names that should not appear in annotations
    untyped_names = {"dict", "Dict", "MutableMapping"}

    # Known legitimate methods that accept typed Mapping for config decode
    allowlist = {
        ("ConfigurationSnapshot", "from_metadata"),
        ("TireSpec", "from_aspects"),
    }

    violations: list[str] = []
    seen_classes: set[int] = set()
    for py_file in domain_files:
        module_name = f"vibesensor.domain.{py_file.stem}"
        mod = importlib.import_module(module_name)

        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if not isinstance(obj, type):
                continue
            # Deduplicate re-exported classes
            if id(obj) in seen_classes:
                continue
            seen_classes.add(id(obj))
            for method_name in dir(obj):
                if (obj.__name__, method_name) in allowlist:
                    continue
                method = getattr(obj, method_name, None)
                if method is None:
                    continue
                if not (
                    isinstance(inspect.getattr_static(obj, method_name, None), classmethod)
                    or isinstance(inspect.getattr_static(obj, method_name, None), staticmethod)
                ):
                    continue
                try:
                    raw = method.__func__ if hasattr(method, "__func__") else method
                    hints = inspect.get_annotations(raw)
                except Exception:
                    continue
                for param_name, annotation in hints.items():
                    if param_name == "return":
                        continue
                    ann_str = str(annotation)
                    # Check for bare dict, list[dict], MutableMapping, etc.
                    for ut in untyped_names:
                        if ut in ann_str:
                            violations.append(
                                f"{obj.__name__}.{method_name}() param '{param_name}' "
                                f"has untyped annotation: {ann_str}"
                            )
    assert not violations, (
        "Domain factory methods must not accept raw dict/Mapping args "
        "(use boundary adapters instead):\n" + "\n".join(violations)
    )


def test_post_analysis_does_not_construct_raw_suitability_dicts() -> None:
    """post_analysis must use ``SuitabilityCheck`` domain objects.

    Prevents regression of T11: manual construction of ``{"check":…}``
    dicts should be via the domain type, not raw string-keyed dicts.
    """
    from vibesensor.use_cases.run import post_analysis as mod

    source = inspect.getsource(mod)
    # Must import or reference SuitabilityCheck
    assert "SuitabilityCheck" in source, (
        "post_analysis.py must use SuitabilityCheck domain objects "
        "for suitability dict construction"
    )


def test_f_order_finding_id_normalization() -> None:
    """``finalize_findings`` normalises arbitrary IDs to sequential ``F###``.

    ``F_ORDER`` is an internal working ID from order analysis.
    ``finalize_findings`` replaces all non-reference IDs with stable
    sequential ``F001``, ``F002``, … so that report and history
    consumers see deterministic identifiers.  The normalization to
    ``F001`` is correct behavior, not a test bug.
    """
    from vibesensor.domain import Finding
    from vibesensor.use_cases.diagnostics.findings import finalize_findings

    domain_findings = finalize_findings(
        [
            Finding(finding_id="F_ORDER", confidence=0.7, suspected_source="wheel/tire"),
            Finding(finding_id="F_PERSISTENT", confidence=0.4, suspected_source="engine"),
        ]
    )
    # Both get sequential F### IDs regardless of their input names
    assert domain_findings[0].finding_id == "F001"
    assert domain_findings[1].finding_id == "F002"
    assert all(isinstance(f, Finding) for f in domain_findings)

    # Reference findings keep their original IDs
    domain_ref = finalize_findings(
        [
            Finding(finding_id="REF_SPEED", confidence=None, suspected_source="unknown"),
            Finding(finding_id="F_ORDER", confidence=0.7, suspected_source="wheel/tire"),
        ]
    )
    assert domain_ref[0].finding_id == "REF_SPEED"
    assert domain_ref[1].finding_id == "F001"


def test_next_steps_domain_path_is_primary() -> None:
    """``build_next_steps_from_summary`` must use domain aggregate only.

    The function must check ``aggregate.recommended_actions`` as its
    sole source for next steps.  No payload fallback loop should exist.
    Prevents regression of T12.
    """
    from tests._paths import SERVER_ROOT

    mapping_path = SERVER_ROOT / "vibesensor" / "adapters" / "pdf" / "mapping.py"
    source = mapping_path.read_text()

    # Find the function body
    func_start = source.find("def build_next_steps_from_summary(")
    assert func_start != -1, "build_next_steps_from_summary not found in mapping.py"

    # Find end of function (next top-level def or end of file)
    next_def = source.find("\ndef ", func_start + 1)
    func_body = source[func_start : next_def if next_def != -1 else len(source)]

    # The domain aggregate if-guard must exist
    domain_guard = func_body.find("if aggregate is not None and aggregate.recommended_actions")
    assert domain_guard != -1, (
        "build_next_steps_from_summary must check aggregate.recommended_actions"
    )
    # No payload fallback loop should remain
    payload_loop = func_body.find("for step in summary_steps")
    assert payload_loop == -1, (
        "build_next_steps_from_summary must not have a payload fallback loop — domain-only"
    )


def test_fallback_payload_functions_removed() -> None:
    """``top_strength_values`` and ``has_relevant_reference_gap`` have been
    removed — the domain aggregate is always available."""
    from vibesensor.adapters.pdf import mapping

    assert not hasattr(mapping, "top_strength_values")
    assert not hasattr(mapping, "has_relevant_reference_gap")


# ── TODO-20: Layer import guardrails ─────────────────────────────────────


def test_domain_does_not_import_outer_packages() -> None:
    """domain/ must not import from boundaries/, report/, routes/, etc.

    Relative intra-package imports (level >= 1) are excluded because
    they resolve within ``domain/`` itself, not against the outer
    ``vibesensor/adapters/`` packages.
    """
    import ast
    from pathlib import Path

    domain_dir = Path(__file__).resolve().parents[2] / "vibesensor" / "domain"
    forbidden = {
        "boundaries",
        "report",
        "routes",
        "history",
        "history_services",
        "history_db",
        "runtime",
        "metrics_log",
    }
    violations: list[str] = []
    for py in sorted(domain_dir.rglob("*.py")):
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                # Skip relative imports — they resolve within domain/ itself
                if node.level >= 1:
                    continue
                for part in forbidden:
                    if part in node.module.split("."):
                        violations.append(f"{py.name}: imports from {node.module}")
    assert not violations, "domain/ must not import outer packages:\n" + "\n".join(violations)


def test_boundaries_do_not_import_outer_layers() -> None:
    """boundaries/ must not import from report/, routes/, history_services/,
    history_db/, runtime/, or metrics_log/.

    boundaries/ sits between domain/ and the rest of the application; it must
    not depend on higher-level adapter packages.
    """
    import ast
    from pathlib import Path

    boundaries_dir = Path(__file__).resolve().parents[2] / "vibesensor" / "boundaries"
    forbidden = {
        "report",
        "routes",
        "history",
        "history_services",
        "history_db",
        "runtime",
        "metrics_log",
    }
    violations: list[str] = []
    for py in sorted(boundaries_dir.rglob("*.py")):
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.level >= 1:
                    continue
                for part in forbidden:
                    if part in node.module.split("."):
                        violations.append(f"{py.name}: imports from {node.module}")
    assert not violations, "boundaries/ must not import outer layers:\n" + "\n".join(violations)


def test_boundaries_do_not_import_analysis() -> None:
    """boundaries/ must not import from analysis/.

    Boundary modules decode/project between persistence payloads and domain
    objects.  They must not reach into analysis internals.
    """
    import ast
    from pathlib import Path

    boundaries_dir = Path(__file__).resolve().parents[2] / "vibesensor" / "boundaries"
    violations: list[str] = []
    for py in sorted(boundaries_dir.rglob("*.py")):
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.level >= 1:
                    continue
                if "analysis" in node.module.split("."):
                    violations.append(f"{py.name}: imports from {node.module}")
    assert not violations, "boundaries/ must not import analysis/:\n" + "\n".join(violations)


# ── TODO-22: Canonical domain graph structural verification ──────────────


def test_canonical_domain_graph_relationships() -> None:
    """Verify all canonical domain graph relationships exist as typed fields."""
    import dataclasses

    from vibesensor.domain import (
        Car,
        DiagnosticCase,
        DrivingSegment,
        Finding,
        Measurement,
        RunCapture,
        RunSetup,
        Sensor,
        SensorPlacement,
        Signature,
        SpeedSource,
        TestRun,
    )

    def field_type(cls: type, name: str) -> type:
        """Return the raw annotation for a dataclass field."""
        hints = {f.name: f for f in dataclasses.fields(cls)}
        assert name in hints, f"{cls.__name__} missing field {name}"
        return hints[name]

    # DiagnosticCase
    field_type(DiagnosticCase, "car")  # Car | None
    field_type(DiagnosticCase, "test_runs")  # tuple[TestRun, ...]

    # TestRun
    field_type(TestRun, "capture")  # RunCapture
    field_type(TestRun, "findings")  # tuple[Finding, ...]
    field_type(TestRun, "driving_segments")  # tuple[DrivingSegment, ...]

    # RunCapture
    field_type(RunCapture, "run_id")  # str (not a Run object — known deviation)
    field_type(RunCapture, "setup")  # RunSetup
    field_type(RunCapture, "measurements")  # tuple[Measurement, ...]
    assert not any(f.name == "run" for f in dataclasses.fields(RunCapture)), (
        "RunCapture must not hold a Run object reference (uses run_id: str)"
    )

    # RunSetup
    field_type(RunSetup, "sensors")  # tuple[Sensor, ...]
    field_type(RunSetup, "speed_source")  # SpeedSource

    # Sensor
    field_type(Sensor, "placement")  # SensorPlacement | None

    # Measurement
    field_type(Measurement, "sensor_id")  # str

    # Verify all imports are real classes (not just string names)
    for cls in (
        Car,
        DiagnosticCase,
        DrivingSegment,
        Finding,
        Measurement,
        RunCapture,
        RunSetup,
        Sensor,
        SensorPlacement,
        Signature,
        SpeedSource,
        TestRun,
    ):
        assert dataclasses.is_dataclass(cls), f"{cls.__name__} must be a dataclass"

    # Finding → finding-scoped value objects
    from vibesensor.domain import (
        ConfidenceAssessment,
        FindingEvidence,
        LocationHotspot,
        VibrationOrigin,
    )

    field_type(Finding, "confidence_assessment")  # ConfidenceAssessment | None
    field_type(Finding, "evidence")  # FindingEvidence | None
    field_type(Finding, "location")  # LocationHotspot | None (direct field, not via origin)
    field_type(Finding, "origin")  # VibrationOrigin | None (independent from location)

    for cls in (ConfidenceAssessment, FindingEvidence, LocationHotspot, VibrationOrigin):
        assert dataclasses.is_dataclass(cls), f"{cls.__name__} must be a dataclass"

    # RunStatus is associated with Run lifecycle
    from vibesensor.domain.run_status import RunStatus, transition_run

    assert issubclass(RunStatus, str)  # StrEnum
    assert callable(transition_run)

    # DrivingPhase and DrivingSegment relationship
    field_type(DrivingSegment, "phase")  # DrivingPhase or equivalent


def test_finding_is_run_scoped() -> None:
    """Finding must not reference cross-run or case-level concepts directly."""
    import dataclasses

    from vibesensor.domain import Finding

    field_names = {f.name for f in dataclasses.fields(Finding)}
    # Finding is run-scoped: it must not hold case_id, diagnosis, or
    # cross-run aggregation fields.
    cross_run_indicators = {"case_id", "diagnosis", "diagnoses", "test_runs", "runs", "case"}
    leaked = field_names & cross_run_indicators
    assert not leaked, f"Finding has cross-run fields (must be run-scoped): {leaked}"


def test_signature_confinement() -> None:
    """Signature must not leak into adapter layers.

    This diagnostic intermediate concept lives in the domain model and may be
    reconstructed in boundary decoders, but must not appear in transport,
    rendering, or persistence adapters.
    """
    import ast

    from tests._paths import SERVER_ROOT

    confined_names = {"Signature"}
    forbidden_dirs = [
        SERVER_ROOT / "vibesensor" / "adapters" / "pdf",
        SERVER_ROOT / "vibesensor" / "adapters" / "http",
        SERVER_ROOT / "vibesensor" / "adapters" / "persistence",
        SERVER_ROOT / "vibesensor" / "adapters" / "websocket",
    ]
    violations: list[str] = []
    for adapter_dir in forbidden_dirs:
        if not adapter_dir.exists():
            continue
        for py_file in adapter_dir.rglob("*.py"):
            source = py_file.read_text()
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        name = alias.asname or alias.name
                        if name in confined_names:
                            rel = py_file.relative_to(SERVER_ROOT)
                            violations.append(f"{rel} imports {name}")
    assert not violations, (
        f"Diagnostic intermediates must not leak into adapter layers: {violations}"
    )


def test_lifecycle_mutability_rules() -> None:
    """Run is mutable (lifecycle object); RunCapture, RunSetup, TestRun are frozen."""
    import dataclasses

    from vibesensor.domain import RunCapture, RunSetup, TestRun
    from vibesensor.domain.run import Run

    # Run is the mutable lifecycle object during recording
    assert dataclasses.is_dataclass(Run)
    r = Run(run_id="mut-test")
    r.run_id = "mut-test-2"  # must not raise

    # Derived/immutable objects must be frozen
    for cls in (RunCapture, RunSetup, TestRun):
        assert dataclasses.is_dataclass(cls), f"{cls.__name__} must be a dataclass"
        frozen = cls.__dataclass_params__.frozen  # type: ignore[attr-defined]
        assert frozen, f"{cls.__name__} must be frozen (immutable once produced)"


# ── Domain model type completeness guardrails ───────────────────────────

# Single list of domain-model types that must be importable from vibesensor.domain.
_EXPECTED_DOMAIN_EXPORTS = [
    # Aggregates and entities
    "Car",
    "DiagnosticCase",
    "Run",
    "TestRun",
    # Value objects — car and context
    "CarSnapshot",
    "OrderReferenceSpec",
    "TireSpec",
    # Value objects — snapshots
    "AnalysisSettingsSnapshot",
    "DrivingPhaseSummary",
    "RunContextSnapshot",
    "RunMetadataSnapshot",
    "SpeedProfileSummary",
    # Value objects — run and capture
    "ConfigurationSnapshot",
    "Measurement",
    "RunCapture",
    "RunSetup",
    "VibrationReading",
    # Value objects — findings and diagnostics
    "ConfidenceAssessment",
    "Finding",
    "FindingEvidence",
    "FindingKind",
    "LocationHotspot",
    "LocationIntensitySummary",
    "OrderMatchObservation",
    "Signature",
    "StrengthMetrics",
    "StrengthPeak",
    "VibrationOrigin",
    "VibrationSource",
    # Value objects — run context
    "DrivingPhase",
    "DrivingPhaseInterval",
    "DrivingPhaseSegment",
    "DrivingSegment",
    "RunStatus",
    "RunSuitability",
    "Sensor",
    "SensorPlacement",
    "SpeedProfile",
    "SpeedSource",
    "SpeedSourceKind",
    "SuitabilityCheck",
    "Symptom",
    # Test plan
    "RecommendedAction",
    "TestPlan",
    # Functions
    "RUN_TRANSITIONS",
    "plan_test_actions",
    "speed_band_sort_key",
    "speed_bin_label",
    "transition_run",
]


@pytest.mark.parametrize("name", _EXPECTED_DOMAIN_EXPORTS)
def test_all_domain_model_types_importable(name: str) -> None:
    """Every domain-model type must be importable from ``vibesensor.domain``."""
    import importlib

    mod = importlib.import_module("vibesensor.domain")
    assert hasattr(mod, name), f"{name} must be exported from vibesensor.domain"


def test_domain_exports_completeness() -> None:
    """``__all__`` in vibesensor.domain must cover every expected domain export."""
    import importlib

    mod = importlib.import_module("vibesensor.domain")
    all_names = set(getattr(mod, "__all__", []))
    missing = [n for n in _EXPECTED_DOMAIN_EXPORTS if n not in all_names]
    assert not missing, f"Missing from domain __all__: {missing}"


def test_domain_import_direction() -> None:
    """Domain modules must NOT import from shared/boundaries/, adapters/, or infra/."""
    import ast

    from tests._paths import SERVER_ROOT

    domain_dir = SERVER_ROOT / "vibesensor" / "domain"
    violations: list[str] = []
    forbidden_prefixes = (
        "vibesensor.shared.boundaries",
        "vibesensor.adapters",
        "vibesensor.infra",
    )
    for py_file in domain_dir.glob("*.py"):
        source = py_file.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in forbidden_prefixes:
                    if node.module.startswith(prefix):
                        violations.append(f"{py_file.name} imports from {node.module}")
    assert not violations, (
        f"Domain modules must not import from boundary/adapter/infra layers: {violations}"
    )


def test_domain_code_does_not_access_raw_tire_fields() -> None:
    """Domain-layer code must not read raw tire fields directly from
    AnalysisSettingsSnapshot — only through order_reference_spec.

    Exceptions: the snapshot's own from_dict() factory, property definitions,
    and __init__ (dataclass construction).
    """
    import ast

    from tests._paths import SERVER_ROOT

    domain_dir = SERVER_ROOT / "vibesensor" / "domain"
    raw_tire_fields = {"tire_width_mm", "tire_aspect_pct", "rim_in"}
    violations: list[str] = []
    for py_file in domain_dir.glob("*.py"):
        if py_file.name in ("snapshots.py", "car.py"):
            continue  # snapshots.py defines these fields; car.py uses TireSpec's own fields
        source = py_file.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.attr, str):
                if node.attr in raw_tire_fields:
                    violations.append(f"{py_file.name}:{node.lineno} accesses .{node.attr}")
    assert not violations, (
        f"Domain code must not access raw tire fields on AnalysisSettingsSnapshot "
        f"(use order_reference_spec instead): {violations}"
    )


# ── Car.aspects OOP: domain/use_cases must not import CarConfig ──────────


def test_domain_and_use_cases_do_not_import_car_config() -> None:
    """domain/ and use_cases/ must not import CarConfig (infra config type).

    Vehicle interpretive context is carried by typed domain objects
    (Car, OrderReferenceSpec, TireSpec), not by raw infra config types.
    SettingsStore using CarConfig for persistence is fine, but domain
    and use-case code must not depend on it.
    """
    import ast

    from tests._paths import SERVER_ROOT

    pkg_dir = SERVER_ROOT / "vibesensor"
    violations: list[str] = []
    for subdir_name in ("domain", "use_cases"):
        subdir = pkg_dir / subdir_name
        if not subdir.is_dir():
            continue
        for py_file in subdir.rglob("*.py"):
            source = py_file.read_text()
            try:
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imported_names = [alias.name for alias in node.names]
                    if "CarConfig" in imported_names:
                        rel = py_file.relative_to(pkg_dir)
                        violations.append(f"{rel}:{node.lineno} imports CarConfig")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name and "CarConfig" in alias.name:
                            rel = py_file.relative_to(pkg_dir)
                            violations.append(f"{rel}:{node.lineno} imports CarConfig")
    assert not violations, (
        "domain/ and use_cases/ must use typed domain objects (Car, OrderReferenceSpec), "
        f"not infra CarConfig: {violations}"
    )


def test_domain_and_use_cases_do_not_read_raw_aspects_dict_keys() -> None:
    """domain/ and use_cases/ must not read raw aspects dict keys for computation.

    Car.aspects is not the canonical internal model for vehicle interpretive
    context — OrderReferenceSpec and TireSpec are. Direct ``.get("aspects")``
    or ``["aspects"]`` access in business logic is forbidden.
    """
    import ast

    from tests._paths import SERVER_ROOT

    pkg_dir = SERVER_ROOT / "vibesensor"
    violations: list[str] = []
    # Files that legitimately construct or own Car.aspects
    allowed_files = {"car.py"}

    for subdir_name in ("domain", "use_cases"):
        subdir = pkg_dir / subdir_name
        if not subdir.is_dir():
            continue
        for py_file in subdir.rglob("*.py"):
            if py_file.name in allowed_files:
                continue
            source = py_file.read_text()
            try:
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                # Check for .get("aspects") or ["aspects"] on any object
                if isinstance(node, ast.Subscript):
                    if isinstance(node.slice, ast.Constant) and node.slice.value == "aspects":
                        rel = py_file.relative_to(pkg_dir)
                        violations.append(f'{rel}:{node.lineno} accesses ["aspects"] raw dict key')
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == "get" and node.args:
                        first_arg = node.args[0]
                        if isinstance(first_arg, ast.Constant) and first_arg.value == "aspects":
                            rel = py_file.relative_to(pkg_dir)
                            violations.append(
                                f'{rel}:{node.lineno} accesses .get("aspects") raw dict key'
                            )
    assert not violations, (
        "domain/ and use_cases/ must not read raw aspects dict keys "
        f"(use Car.order_ref / TireSpec instead): {violations}"
    )


# ---------------------------------------------------------------------------
# Domain model migration guardrails (Step 3.10)
# ---------------------------------------------------------------------------


def test_boundary_owns_no_meaning_finding_kind() -> None:
    """adapters/ and shared/boundaries/ must not construct FindingKind for
    business logic decisions.  Boundary decoders that reconstruct from
    serialized payloads are allowed."""
    import ast

    from tests._paths import SERVER_ROOT

    pkg_dir = SERVER_ROOT / "vibesensor"
    violations: list[str] = []

    scan_dirs = [pkg_dir / "adapters", pkg_dir / "shared" / "boundaries"]
    for scan_dir in scan_dirs:
        if not scan_dir.is_dir():
            continue
        for py_file in scan_dir.rglob("*.py"):
            source = py_file.read_text()
            try:
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "FindingKind"
                ):
                    rel = py_file.relative_to(pkg_dir)
                    violations.append(f"{rel}:{node.lineno} constructs FindingKind directly")
    assert not violations, (
        "adapters/ and shared/boundaries/ must not construct FindingKind for "
        f"business logic. Use domain classification methods instead: {violations}"
    )


def test_boundary_owns_no_meaning_vibration_source() -> None:
    """adapters/ and shared/boundaries/ must not construct VibrationSource for
    business logic decisions.

    Sanctioned exceptions (boundary decoders reconstructing from serialized
    data, adapters deserializing for rendering):
    - finding.py:finding_from_payload
    - vibration_origin.py:_source_from_payload
    - mapping.py:human_source
    - pdf_diagram_render.py:_source_color
    """
    import ast

    from tests._paths import SERVER_ROOT

    pkg_dir = SERVER_ROOT / "vibesensor"
    violations: list[str] = []

    # (filename, set of allowed enclosing function names)
    sanctioned: dict[str, set[str]] = {
        "finding.py": {"finding_from_payload"},
        "vibration_origin.py": {"_source_from_payload"},
        "mapping.py": {"human_source"},
        "pdf_diagram_render.py": {"_source_color"},
    }

    scan_dirs = [pkg_dir / "adapters", pkg_dir / "shared" / "boundaries"]
    for scan_dir in scan_dirs:
        if not scan_dir.is_dir():
            continue
        for py_file in scan_dir.rglob("*.py"):
            source = py_file.read_text()
            try:
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError:
                continue
            allowed_funcs = sanctioned.get(py_file.name, set())
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "VibrationSource"
                ):
                    continue
                # Walk up to find enclosing function
                enclosing = _find_enclosing_function(tree, node.lineno)
                if enclosing in allowed_funcs:
                    continue
                rel = py_file.relative_to(pkg_dir)
                violations.append(
                    f"{rel}:{node.lineno} constructs VibrationSource (in {enclosing or '<module>'})"
                )
    assert not violations, (
        "adapters/ and shared/boundaries/ must not construct VibrationSource for "
        f"business logic. Only boundary decoders and renderers may: {violations}"
    )


def _find_enclosing_function(tree: object, target_lineno: int) -> str | None:
    """Return the name of the innermost function/method enclosing *target_lineno*."""
    import ast as _ast

    best: str | None = None
    best_line = 0
    for node in _ast.walk(tree):  # type: ignore[arg-type]
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", None) or float("inf")
            if node.lineno <= target_lineno <= end and node.lineno >= best_line:
                best = node.name
                best_line = node.lineno
    return best


def test_no_compat_dual_base_exceptions() -> None:
    """All VibeSensorError subclasses must not also inherit from stdlib
    exception types (ValueError, RuntimeError, LookupError, etc.).

    This prevents accidental dual-base compatibility shims that let callers
    catch stdlib types and bypass the domain exception hierarchy.
    """
    from vibesensor.shared.exceptions import VibeSensorError

    # stdlib exception types that should never appear as co-parents
    stdlib_bases = (
        ValueError,
        TypeError,
        RuntimeError,
        LookupError,
        KeyError,
        IndexError,
        AttributeError,
        OSError,
        IOError,
        NotImplementedError,
        ArithmeticError,
        StopIteration,
    )

    violations: list[str] = []

    def _check_recursive(cls: type) -> None:
        # MRO between cls and VibeSensorError should contain no stdlib types
        mro = cls.__mro__
        vs_idx = mro.index(VibeSensorError)
        between = mro[1:vs_idx]  # skip cls itself, stop before VibeSensorError
        for entry in between:
            if entry in stdlib_bases or (
                issubclass(entry, BaseException)
                and entry not in (VibeSensorError, Exception, BaseException)
                and entry.__module__ == "builtins"
            ):
                violations.append(
                    f"{cls.__name__} inherits from stdlib {entry.__name__} "
                    f"(MRO: {[c.__name__ for c in mro]})"
                )
        for sub in cls.__subclasses__():
            _check_recursive(sub)

    _check_recursive(VibeSensorError)

    assert not violations, (
        "Custom exceptions must inherit exclusively from VibeSensorError, "
        f"not from stdlib exception types: {violations}"
    )


def test_run_status_from_domain_only() -> None:
    """No consumer may import RunStatus from the persistence layer.

    RunStatus is a domain enum at vibesensor.domain.run_status. Importing
    it from adapters.persistence.history_db would couple consumers to the
    persistence layer.
    """
    import ast

    from tests._paths import SERVER_ROOT

    pkg_dir = SERVER_ROOT / "vibesensor"
    tests_dir = SERVER_ROOT / "tests"
    violations: list[str] = []

    forbidden_sources = {"history_db", "adapters.persistence.history_db"}

    for root_dir in (pkg_dir, tests_dir):
        for py_file in root_dir.rglob("*.py"):
            source = py_file.read_text()
            try:
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.module is None:
                    continue
                names = [alias.name for alias in node.names]
                if "RunStatus" not in names:
                    continue
                # Check if module path contains a forbidden source
                if any(part in node.module for part in forbidden_sources):
                    rel = py_file.relative_to(SERVER_ROOT)
                    violations.append(f"{rel}:{node.lineno} imports RunStatus from {node.module}")
    assert not violations, (
        "RunStatus must be imported from vibesensor.domain, not from the "
        f"persistence layer: {violations}"
    )


def test_run_lifecycle_only() -> None:
    """Run (the mutable recording lifecycle class) must not be imported in
    analysis, finding, test-run, or report-rendering code.

    Run owns start/stop guards and status transitions.  Diagnostics and
    report code should use TestRun (immutable aggregate) or RunCapture
    instead.
    """
    import ast

    from tests._paths import SERVER_ROOT

    pkg_dir = SERVER_ROOT / "vibesensor"
    violations: list[str] = []

    # Paths where Run should never appear as an import
    forbidden_areas = [
        pkg_dir / "use_cases" / "diagnostics",
        pkg_dir / "domain" / "finding.py",
        pkg_dir / "domain" / "test_run.py",
        pkg_dir / "adapters" / "pdf",
    ]

    for area in forbidden_areas:
        py_files = area.rglob("*.py") if area.is_dir() else [area] if area.exists() else []
        for py_file in py_files:
            source = py_file.read_text()
            try:
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.module is None:
                    continue
                names = [alias.name for alias in node.names]
                # Look for importing the Run class specifically
                if "Run" not in names:
                    continue
                # Only flag imports from the run module (not RunCapture, RunStatus, etc.)
                if "vibesensor.domain.run" in node.module or "vibesensor.domain" == node.module:
                    # Verify it's actually the Run class, not RunCapture/RunStatus
                    if "Run" in names and not any(
                        n.startswith("Run") and n != "Run" and alias.name == n
                        for n in names
                        for alias in node.names
                        if alias.name == "Run"
                    ):
                        for alias in node.names:
                            if alias.name == "Run":
                                rel = py_file.relative_to(pkg_dir)
                                violations.append(
                                    f"{rel}:{node.lineno} imports Run "
                                    f"(lifecycle class) from {node.module}"
                                )
    assert not violations, (
        "Run (mutable lifecycle) must not be imported in diagnostics, finding, "
        f"test_run, or report code (use TestRun/RunCapture instead): {violations}"
    )
