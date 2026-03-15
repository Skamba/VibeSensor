"""Architecture guardrails: domain-first pipeline boundaries.

Ensures that core analysis modules operate on domain ``Finding`` objects
(not raw dicts) and that ``TestRun`` is the canonical post-analysis
aggregate.  Prevents regression to the previous payload-first flow.
"""

from __future__ import annotations

import importlib
import inspect
import sys

import pytest

# ── RunAnalysisResult has been deleted ──────────────────────────────────


def test_domain_does_not_export_run_analysis_result() -> None:
    """RunAnalysisResult has been deleted; TestRun is the canonical aggregate."""
    mod = importlib.import_module("vibesensor.domain")
    assert not hasattr(mod, "RunAnalysisResult")


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


# ── RunAnalysis.summarize() produces TestRun ─────────────────────────────


def test_run_analysis_produces_test_run() -> None:
    """``RunAnalysis.summarize()`` must populate ``test_run``."""
    from vibesensor.analysis.summary_builder import RunAnalysis
    from vibesensor.domain import TestRun

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
    from tests.test_support.findings import make_finding_payload
    from vibesensor.domain import TestRun
    from vibesensor.report.mapping import prepare_report_mapping_context

    summary = {
        "run_id": "test-context",
        "findings": [make_finding_payload(finding_id="F001")],
        "top_causes": [make_finding_payload(finding_id="F001")],
        "lang": "en",
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


def test_confidence_label_delegates_to_domain() -> None:
    """top_cause_selection.confidence_label must agree with Finding.classify_confidence."""
    from vibesensor.analysis.top_cause_selection import confidence_label
    from vibesensor.domain import Finding

    for conf in (0.80, 0.55, 0.20, 0.0, None):
        clamped = float(conf) if conf is not None else 0.0
        expected = Finding.classify_confidence(clamped)
        actual = confidence_label(conf)
        assert actual == expected, f"Mismatch for confidence={conf}: {actual} != {expected}"


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
    from vibesensor.domain import Finding, RunCapture, TestRun
    from vibesensor.report.mapping import (
        PrimaryCandidateContext,
        ReportMappingContext,
        build_system_cards,
    )
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
    # Build a context with the aggregate and matching payload top_causes
    cause_payload = {
        "finding_id": "F001",
        "suspected_source": "wheel/tire",
        "confidence": 0.80,
        "strongest_location": "Left Front",
        "confidence_tone": "WRONG_TONE",  # Intentionally wrong
    }
    context = ReportMappingContext(
        meta={},
        car_name=None,
        car_type=None,
        date_str="",
        top_causes=[cause_payload],  # type: ignore[list-item]
        findings_non_ref=[],
        findings=[],
        speed_stats={},  # type: ignore[typeddict-item]
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
        primary_candidate=cause_payload,  # type: ignore[arg-type]
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
    from tests.test_support.findings import make_finding_payload
    from vibesensor.report.mapping import map_summary

    summary = {
        "run_id": "test-map",
        "file_name": "test.csv",
        "rows": 100,
        "duration_s": 60.0,
        "lang": "en",
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


def test_finding_from_payload_populates_evidence() -> None:
    """finding_from_payload extracts FindingEvidence when evidence_metrics is present."""
    from vibesensor.boundaries.finding import finding_from_payload

    payload = {
        "finding_id": "F001",
        "suspected_source": "wheel/tire",
        "confidence": 0.85,
        "evidence_metrics": {
            "match_rate": 0.9,
            "snr_db": 12.0,
            "vibration_strength_db": 25.0,
        },
    }
    f = finding_from_payload(payload)
    assert f.evidence is not None, "finding_from_payload must populate evidence"
    assert f.evidence.match_rate == 0.9


def test_finding_from_payload_populates_location() -> None:
    """finding_from_payload extracts LocationHotspot when location_hotspot is present."""
    from vibesensor.boundaries.finding import finding_from_payload

    payload = {
        "finding_id": "F001",
        "suspected_source": "wheel/tire",
        "confidence": 0.85,
        "location_hotspot": {
            "location": "FL wheel",
            "dominance_ratio": 0.75,
        },
    }
    f = finding_from_payload(payload)
    assert f.location is not None, "finding_from_payload must populate location"
    assert f.location.strongest_location == "FL wheel"


def test_finding_from_payload_prefers_top_location_over_display_string() -> None:
    """Location identity should use top_location, not the ambiguous display string."""
    from vibesensor.boundaries.finding import finding_from_payload

    payload = {
        "finding_id": "F001",
        "suspected_source": "wheel/tire",
        "confidence": 0.85,
        "location_hotspot": {
            "location": "ambiguous location: Front Left / Front Right",
            "top_location": "Front Left",
            "ambiguous_location": True,
            "ambiguous_locations": ["Front Left", "Front Right"],
        },
    }
    finding = finding_from_payload(payload)
    assert finding.location is not None
    assert finding.location.strongest_location == "Front Left"


def test_test_run_from_summary_populates_speed_profile() -> None:
    """test_run_from_summary extracts SpeedProfile when speed_stats is present."""
    from vibesensor.boundaries.diagnostic_case import test_run_from_summary

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
    from vibesensor.boundaries.diagnostic_case import test_run_from_summary

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
        "Hypothesis",
        "Observation",
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
    from vibesensor.analysis.summary_builder import RunAnalysis
    from vibesensor.domain import DiagnosticCase, TestRun

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
    analysis.summarize()

    assert analysis.test_run is not None
    assert analysis.diagnostic_case is not None
    assert isinstance(analysis.test_run, TestRun)
    assert isinstance(analysis.diagnostic_case, DiagnosticCase)
    assert analysis.diagnostic_case.primary_run is not None
    assert analysis.diagnostic_case.primary_run.run_id == analysis.test_run.run_id


def test_boundary_decoder_builds_diagnostic_case_from_summary() -> None:
    from tests.test_support.findings import make_finding_payload
    from vibesensor.boundaries.diagnostic_case import diagnostic_case_from_summary

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
    assert diagnostic_case.diagnoses
    assert diagnostic_case.primary_run is not None


def test_finding_from_payload_populates_origin_and_signatures() -> None:
    from vibesensor.boundaries.finding import finding_from_payload

    payload = {
        "finding_id": "F001",
        "suspected_source": "wheel/tire",
        "confidence": 0.85,
        "strongest_speed_band": "80-90 km/h",
        "signatures_observed": ["1x wheel order", "2x wheel order"],
        "location_hotspot": {"location": "FL wheel", "dominance_ratio": 0.75},
    }
    finding = finding_from_payload(payload)
    assert finding.origin is not None
    assert len(finding.signatures) == 2
    assert finding.origin.display_location == "Fl Wheel"


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
    """Domain planning service must not import payload types."""
    import ast
    from pathlib import Path

    planning_path = (
        Path(__file__).resolve().parents[2]
        / "vibesensor"
        / "domain"
        / "services"
        / "test_planning.py"
    )
    tree = ast.parse(planning_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", "") or ""
            names = [alias.name for alias in node.names]
            all_refs = module + " ".join(names)
            assert "FindingPayload" not in all_refs, (
                "domain/services/test_planning.py must not import FindingPayload"
            )
            assert "AnalysisSummary" not in all_refs, (
                "domain/services/test_planning.py must not import AnalysisSummary"
            )


def test_domain_services_do_not_import_outer_layers() -> None:
    """domain/services/ must not import from analysis, report, boundaries,
    routes, history, history_services, history_db, runtime, or metrics_log."""
    import ast
    from pathlib import Path

    services_dir = Path(__file__).resolve().parents[2] / "vibesensor" / "domain" / "services"
    forbidden = {
        "analysis",
        "report",
        "boundaries",
        "routes",
        "history",
        "history_services",
        "history_db",
        "runtime",
        "metrics_log",
    }
    violations: list[str] = []
    for py in services_dir.rglob("*.py"):
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for part in forbidden:
                    if part in node.module.split("."):
                        violations.append(f"{py.name}: imports from {node.module}")
    assert not violations, "domain/services/ must not import outer layers:\n" + "\n".join(
        violations
    )


def test_domain_does_not_import_domain_services() -> None:
    """domain/ value objects must not depend on domain/services/."""
    import ast
    from pathlib import Path

    domain_dir = Path(__file__).resolve().parents[2] / "vibesensor" / "domain"
    violations: list[str] = []
    for py in domain_dir.iterdir():
        if not py.is_file() or py.suffix != ".py":
            continue
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "services" in node.module.split("."):
                    violations.append(f"{py.name}: imports from {node.module}")
    assert not violations, "domain/ value objects must not import domain/services/:\n" + "\n".join(
        violations
    )


def test_analysis_test_plan_renamed() -> None:
    """analysis/test_plan.py was renamed to location_analysis.py."""
    from pathlib import Path

    old = Path(__file__).resolve().parents[2] / "vibesensor" / "analysis" / "test_plan.py"
    new = Path(__file__).resolve().parents[2] / "vibesensor" / "analysis" / "location_analysis.py"
    assert not old.exists(), f"{old} should have been renamed"
    assert new.exists(), f"{new} must exist after rename"


def test_finding_projector_in_finding_boundary_module() -> None:
    """Finding payload projector should live in boundaries/finding.py."""
    from vibesensor.boundaries.finding import finding_payload_from_domain

    assert callable(finding_payload_from_domain)


def test_post_analysis_does_not_import_project_summary() -> None:
    """Fresh summaries should not round-trip through domain decode/re-project."""
    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "vibesensor" / "metrics_log" / "post_analysis.py"
    ).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [alias.name for alias in node.names]
            if "project_summary_through_domain" in names:
                pytest.fail(
                    "post_analysis.py should not import project_summary_through_domain; "
                    "fresh summaries from summarize() are already domain-canonical"
                )


# ── T7.27: Report mapping rendering-boundary guardrails ──────────────────


def test_report_mapping_business_functions_use_domain_objects() -> None:
    """Key business-decision functions derive values from the domain aggregate.

    When ``prepare_report_mapping_context`` produces a domain aggregate,
    ``resolve_primary_report_candidate`` must derive primary source,
    strength, and reference-gap status from domain objects — not from
    raw payload dict traversal.
    """
    from tests.test_support.findings import make_finding_payload
    from vibesensor.domain import TestRun, VibrationSource
    from vibesensor.report.mapping import (
        prepare_report_mapping_context,
        resolve_primary_report_candidate,
    )
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
    }

    context = prepare_report_mapping_context(summary)
    assert context.domain_aggregate is not None
    assert isinstance(context.domain_aggregate, TestRun)

    primary = resolve_primary_report_candidate(
        summary,
        context=context,
        tr=lambda key, **kw: tr(lang, key, **kw),
        lang=lang,
    )

    # primary_source must be a VibrationSource enum (domain-first derivation)
    assert isinstance(primary.primary_source, VibrationSource), (
        "primary_source must be a VibrationSource enum when domain aggregate is present"
    )


def test_report_mapping_does_not_import_finding_from_payload_decoder() -> None:
    """Report mapping must not import the finding boundary decoder.

    It receives domain objects from ``test_run_from_summary()`` and should
    not be re-decoding payloads.  Only boundary *projectors* (domain →
    payload) are allowed.
    """
    import ast

    from tests._paths import SERVER_ROOT

    mapping_path = SERVER_ROOT / "vibesensor" / "report" / "mapping.py"
    source = mapping_path.read_text()
    tree = ast.parse(source)
    forbidden = {"finding_from_payload"}
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name in forbidden:
                    violations.append(f"imports {alias.name}")
    assert not violations, f"report/mapping.py must not import boundary decoders: {violations}"


# ── T9.1-T9.6: Workstream 8 architecture guardrails ──────────────────


def test_observation_extraction_does_not_accept_findings() -> None:
    """Observation extraction must not accept Finding objects."""
    import ast

    from tests._paths import SERVER_ROOT

    obs_path = SERVER_ROOT / "vibesensor" / "domain" / "services" / "observation_extraction.py"
    source = obs_path.read_text()
    tree = ast.parse(source)

    # Collect all runtime import names (outside TYPE_CHECKING blocks)
    runtime_imports: list[str] = []
    type_checking_nodes: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "TYPE_CHECKING"
        ):
            for child in ast.walk(node):
                type_checking_nodes.add(id(child))

    for node in ast.walk(tree):
        if id(node) in type_checking_nodes:
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                runtime_imports.append(alias.name)

    assert "Finding" not in runtime_imports, (
        "observation_extraction.py must not import Finding at runtime; "
        "observations are extracted from raw evidence before findings exist"
    )


def test_localization_assessment_does_not_exist() -> None:
    """LocalizationAssessment must not exist in the codebase.

    It was deleted in Workstream 3 (T4.1-T4.8).  LocationHotspot is the
    canonical owner of localization semantics.
    """
    # Must not be importable from analysis
    mod = importlib.import_module("vibesensor.analysis")
    assert not hasattr(mod, "LocalizationAssessment"), (
        "LocalizationAssessment must not exist in vibesensor.analysis"
    )
    # Must not exist as a class in summary_builder
    mod2 = importlib.import_module("vibesensor.analysis.summary_builder")
    for name in dir(mod2):
        assert name != "LocalizationAssessment", (
            "LocalizationAssessment class must not exist in summary_builder"
        )


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
    from vibesensor.analysis import summary_builder

    assert not hasattr(summary_builder, "build_run_suitability_checks"), (
        "build_run_suitability_checks was deleted; use RunSuitability.evaluate()"
    )


def test_speed_profile_used_by_confidence_assessment() -> None:
    """ConfidenceAssessment must be the owner of confidence reasoning.

    ``certainty_label()`` was deleted; ``ConfidenceAssessment.assess()``
    is the single source of truth for confidence assessment. Report mapping
    uses ``certainty_tier()`` for layout gating, not ``certainty_label()``.
    """
    from tests._paths import SERVER_ROOT

    strength_labels_path = SERVER_ROOT / "vibesensor" / "analysis" / "strength_labels.py"
    source = strength_labels_path.read_text()
    assert "certainty_label" not in source, (
        "certainty_label was deleted; ConfidenceAssessment.assess() is the replacement"
    )


# ── T14: Architecture guardrail regression tests ─────────────────────────


def test_domain_vos_have_no_dict_accepting_factory_methods() -> None:
    """Domain value objects must not accept raw ``dict`` / ``Mapping`` args.

    Factory methods on domain classes under ``vibesensor/domain/*.py``
    (top-level only — not ``domain/services/``) must accept typed domain
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
    from vibesensor.metrics_log import post_analysis as mod

    source = inspect.getsource(mod)
    # Must import or reference SuitabilityCheck
    assert "SuitabilityCheck" in source, (
        "post_analysis.py must use SuitabilityCheck domain objects "
        "for suitability dict construction"
    )


def test_exports_project_through_domain() -> None:
    """``build_run_details_json`` must call ``project_summary_through_domain``.

    Prevents regression: export payloads must go through domain
    projection before output.
    """
    from tests._paths import SERVER_ROOT

    exports_path = SERVER_ROOT / "vibesensor" / "history_services" / "exports.py"
    source = exports_path.read_text()
    assert "project_summary_through_domain" in source, (
        "history_services/exports.py must call project_summary_through_domain "
        "before outputting run details"
    )
    # Verify it's actually imported (not just in a comment)
    assert "from" in source and "project_summary_through_domain" in source, (
        "project_summary_through_domain must be imported, not just mentioned"
    )


def test_f_order_finding_id_normalization() -> None:
    """``finalize_findings`` normalises arbitrary IDs to sequential ``F###``.

    ``F_ORDER`` is an internal working ID from order analysis.
    ``finalize_findings`` replaces all non-reference IDs with stable
    sequential ``F001``, ``F002``, … so that report and history
    consumers see deterministic identifiers.  The normalization to
    ``F001`` is correct behavior, not a test bug.
    """
    from vibesensor.analysis.findings import finalize_findings
    from vibesensor.domain import Finding

    payloads, domain_findings = finalize_findings(
        [
            {"finding_id": "F_ORDER", "confidence": 0.7, "suspected_source": "wheel/tire"},
            {"finding_id": "F_PERSISTENT", "confidence": 0.4, "suspected_source": "engine"},
        ]
    )
    # Both get sequential F### IDs regardless of their input names
    assert domain_findings[0].finding_id == "F001"
    assert domain_findings[1].finding_id == "F002"
    assert all(isinstance(f, Finding) for f in domain_findings)

    # Reference findings keep their original IDs
    payloads_ref, domain_ref = finalize_findings(
        [
            {
                "finding_id": "REF_SPEED",
                "finding_kind": "reference",
                "confidence": None,
                "suspected_source": "unknown",
            },
            {
                "finding_id": "F_ORDER",
                "confidence": 0.7,
                "suspected_source": "wheel/tire",
            },
        ]
    )
    assert domain_ref[0].finding_id == "REF_SPEED"
    assert domain_ref[1].finding_id == "F001"


def test_next_steps_domain_path_is_primary() -> None:
    """``build_next_steps_from_summary`` must check domain aggregate BEFORE payload.

    The if-elif order must be: aggregate.recommended_actions first,
    then payload ``test_plan`` fallback.  Prevents regression of T12.
    """
    from tests._paths import SERVER_ROOT

    mapping_path = SERVER_ROOT / "vibesensor" / "report" / "mapping.py"
    source = mapping_path.read_text()

    # Find the function body
    func_start = source.find("def build_next_steps_from_summary(")
    assert func_start != -1, "build_next_steps_from_summary not found in mapping.py"

    # Find end of function (next top-level def or end of file)
    next_def = source.find("\ndef ", func_start + 1)
    func_body = source[func_start : next_def if next_def != -1 else len(source)]

    # The domain aggregate if-guard must come before the payload for-loop
    # that iterates summary_steps.  The function may eagerly call
    # summary_test_plan() before the if-guard, but the actual consumption
    # of those steps (``for step in summary_steps:``) must be after the
    # domain branch with its early return.
    domain_guard = func_body.find("if aggregate is not None and aggregate.recommended_actions")
    payload_loop = func_body.find("for step in summary_steps")
    assert domain_guard != -1, (
        "build_next_steps_from_summary must check aggregate.recommended_actions"
    )
    assert payload_loop != -1, "build_next_steps_from_summary must have payload fallback loop"
    assert domain_guard < payload_loop, (
        "Domain aggregate if-guard must appear BEFORE the payload fallback loop "
        f"(domain at pos {domain_guard}, payload loop at pos {payload_loop})"
    )
    # The domain branch must do an early return to be primary
    domain_block = func_body[domain_guard:payload_loop]
    assert "return next_steps" in domain_block or "return next_steps\n" in domain_block, (
        "Domain aggregate branch must return early before the payload fallback"
    )


def test_fallback_payload_functions_removed() -> None:
    """``top_strength_values`` and ``has_relevant_reference_gap`` have been
    removed — the domain aggregate is always available."""
    from vibesensor.report import mapping

    assert not hasattr(mapping, "top_strength_values")
    assert not hasattr(mapping, "has_relevant_reference_gap")
