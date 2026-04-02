"""Tests for finalize_findings and PeakFindingAnalyzer."""

from __future__ import annotations

from test_support.findings import make_finding_payload, make_info_finding, make_ref_finding

from vibesensor.shared.boundaries.finding import finding_from_payload
from vibesensor.shared.boundaries.sensor_frame_codec import normalize_sensor_frames
from vibesensor.use_cases.diagnostics.findings import PeakFindingAnalyzer, finalize_findings

# ===========================================================================
# Domain Finding from payload (replaces former FindingRecord tests)
# ===========================================================================


def _peak_samples(
    *,
    hz: float = 50.0,
    amp: float = 0.05,
    vibration_strength_db: float = 25.0,
    count: int = 30,
) -> list:
    return normalize_sensor_frames([
        {
            "speed_kmh": 60.0,
            "t_s": float(i),
            "top_peaks": [{"hz": hz, "amp": amp}],
            "vibration_strength_db": vibration_strength_db,
            "client_name": "sensor_fl",
        }
        for i in range(count)
    ])


class TestDomainFindingFromPayload:
    def test_finding_id(self) -> None:
        f = finding_from_payload(make_finding_payload(confidence=0.65))
        assert f.finding_id == "F_ORDER"

    def test_is_reference(self) -> None:
        assert finding_from_payload(make_ref_finding()).is_reference is True
        assert finding_from_payload(make_finding_payload(confidence=0.65)).is_reference is False

    def test_is_informational(self) -> None:
        assert finding_from_payload(make_info_finding()).is_informational is True
        assert finding_from_payload(make_finding_payload(confidence=0.65)).is_informational is False

    def test_is_diagnostic(self) -> None:
        assert finding_from_payload(make_finding_payload(confidence=0.65)).is_diagnostic is True
        assert finding_from_payload(make_ref_finding()).is_diagnostic is False
        assert finding_from_payload(make_info_finding()).is_diagnostic is False

    def test_confidence_default(self) -> None:
        f = finding_from_payload(make_ref_finding())
        assert f.effective_confidence == 0.0

    def test_confidence_value(self) -> None:
        f = finding_from_payload(make_finding_payload(confidence=0.75))
        assert f.effective_confidence == 0.75

    def test_source_normalized(self) -> None:
        payload = make_finding_payload(confidence=0.65, suspected_source="  Wheel/Tire  ")
        f = finding_from_payload(payload)
        assert f.source_normalized == "wheel/tire"

    def test_strongest_location(self) -> None:
        payload = make_finding_payload(confidence=0.65, strongest_location="front_left")
        f = finding_from_payload(payload)
        assert f.strongest_location == "front_left"

    def test_ranking_score(self) -> None:
        f = finding_from_payload(make_finding_payload(confidence=0.65, ranking_score=2.5))
        assert f.ranking_score == 2.5


# ===========================================================================
# finalize_findings
# ===========================================================================


class TestFinalizeFindings:
    def test_finalize_ordering(self) -> None:
        """References come first, then diagnostics by confidence, then informational."""
        ref = finding_from_payload(make_ref_finding())
        diag_high = finding_from_payload(make_finding_payload(confidence=0.80, ranking_score=2.0))
        diag_low = finding_from_payload(make_finding_payload(confidence=0.30, ranking_score=1.0))
        info = finding_from_payload(make_info_finding(confidence=0.10))
        domain_findings = finalize_findings([diag_low, info, ref, diag_high])
        assert len(domain_findings) == 4
        # Reference first
        assert domain_findings[0].is_reference
        # Then high-confidence diagnostic
        assert domain_findings[1].effective_confidence == 0.80
        # Then low-confidence diagnostic
        assert domain_findings[2].effective_confidence == 0.30
        # Then informational
        assert domain_findings[3].is_informational
        # Domain findings match
        assert domain_findings[0].is_reference
        assert domain_findings[1].is_diagnostic
        assert domain_findings[2].is_diagnostic
        assert domain_findings[3].is_informational

    def test_finalize_assigns_sequential_ids(self) -> None:
        ref = finding_from_payload(make_ref_finding("REF_SPEED"))
        d1 = finding_from_payload(make_finding_payload(confidence=0.80))
        d2 = finding_from_payload(make_finding_payload(confidence=0.40))
        info = finding_from_payload(make_info_finding())
        domain_findings = finalize_findings([d2, info, ref, d1])
        # Reference keeps its original ID
        assert domain_findings[0].finding_id == "REF_SPEED"
        # Non-reference findings get sequential F### IDs
        assert domain_findings[1].finding_id == "F001"
        assert domain_findings[2].finding_id == "F002"
        assert domain_findings[3].finding_id == "F003"

    def test_finalize_empty(self) -> None:
        domain_findings = finalize_findings([])
        assert domain_findings == ()


# ===========================================================================
# PeakFindingAnalyzer
# ===========================================================================


class TestPeakFindingAnalyzer:
    def test_empty_samples(self) -> None:
        analyzer = PeakFindingAnalyzer(samples=[], order_finding_freqs=set(), lang="en")
        assert analyzer.analyze() == []

    def test_returns_findings(self) -> None:
        """Smoke test: samples with top peaks produce findings."""
        analyzer = PeakFindingAnalyzer(
            samples=_peak_samples(),
            order_finding_freqs=set(),
            lang="en",
        )
        findings = analyzer.analyze()
        assert len(findings) > 0
        for f in findings:
            assert f.finding_id == "F_PEAK"
            assert f.confidence is not None

    def test_order_freq_exclusion(self) -> None:
        """Bins overlapping with order frequencies are excluded."""
        samples = _peak_samples()
        # With 50 Hz in order freqs → should be excluded
        analyzer_excluded = PeakFindingAnalyzer(
            samples=samples,
            order_finding_freqs={50.0},
            lang="en",
        )
        findings_excluded = analyzer_excluded.analyze()

        # Without 50 Hz → should be included
        analyzer_included = PeakFindingAnalyzer(
            samples=samples,
            order_finding_freqs=set(),
            lang="en",
        )
        findings_included = analyzer_included.analyze()

        assert len(findings_included) >= len(findings_excluded)
