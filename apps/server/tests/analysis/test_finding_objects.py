"""Tests for finalize_findings, PeakBin, and PeakFindingAnalyzer."""

from __future__ import annotations

import pytest

from tests.test_support.findings import make_finding_payload, make_info_finding, make_ref_finding
from vibesensor.analysis.findings import (
    PeakBin,
    PeakFindingAnalyzer,
    finalize_findings,
)
from vibesensor.boundaries.finding import finding_from_payload

# ===========================================================================
# Domain Finding from payload (replaces former FindingRecord tests)
# ===========================================================================


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
        ref = make_ref_finding()
        diag_high = make_finding_payload(confidence=0.80, ranking_score=2.0)
        diag_low = make_finding_payload(confidence=0.30, ranking_score=1.0)
        info = make_info_finding(confidence=0.10)
        ordered, domain_findings = finalize_findings([diag_low, info, ref, diag_high])
        assert len(ordered) == 4
        # Reference first
        assert str(ordered[0]["finding_id"]).startswith("REF_")
        # Then high-confidence diagnostic
        assert ordered[1]["confidence"] == 0.80
        # Then low-confidence diagnostic
        assert ordered[2]["confidence"] == 0.30
        # Then informational
        assert ordered[3].get("severity") == "info"
        # Domain findings match
        assert len(domain_findings) == 4
        assert domain_findings[0].is_reference
        assert domain_findings[1].is_diagnostic
        assert domain_findings[2].is_diagnostic
        assert domain_findings[3].is_informational

    def test_finalize_assigns_sequential_ids(self) -> None:
        ref = make_ref_finding("REF_SPEED")
        d1 = make_finding_payload(confidence=0.80)
        d2 = make_finding_payload(confidence=0.40)
        info = make_info_finding()
        ordered, domain_findings = finalize_findings([d2, info, ref, d1])
        # Reference keeps its original ID
        assert ordered[0]["finding_id"] == "REF_SPEED"
        # Non-reference findings get sequential F### IDs
        assert ordered[1]["finding_id"] == "F001"
        assert ordered[2]["finding_id"] == "F002"
        assert ordered[3]["finding_id"] == "F003"
        # Domain findings have matching IDs
        assert domain_findings[0].finding_id == "REF_SPEED"
        assert domain_findings[1].finding_id == "F001"

    def test_finalize_empty(self) -> None:
        payloads, domain_findings = finalize_findings([])
        assert payloads == []
        assert domain_findings == ()


# ===========================================================================
# PeakBin
# ===========================================================================


def _make_peak_bin(
    *,
    bin_center: float = 50.0,
    amps: list[float] | None = None,
    n_samples: int = 100,
    total_locations: set[str] | None = None,
    run_noise_baseline_g: float | None = 0.001,
) -> PeakBin:
    """Helper to build a PeakBin with sensible defaults."""
    if amps is None:
        amps = [0.05] * 50  # Moderate amplitude, 50% presence
    if total_locations is None:
        total_locations = {"front_left"}
    n = len(amps)
    return PeakBin(
        bin_center=bin_center,
        amps=amps,
        floor_vals=[0.005] * n,
        speed_amp_pairs=[(60.0, a) for a in amps],
        loc_counts_for_bin={"front_left": n},
        speed_bin_counts_for_bin={"60-80": n},
        phases_for_bin={},
        n_samples=n_samples,
        total_locations=total_locations,
        total_location_sample_counts={"front_left": n_samples},
        total_speed_bin_counts={"60-80": n_samples},
        run_noise_baseline_g=run_noise_baseline_g,
        has_phases=False,
    )


class TestPeakBin:
    def test_bin_center(self) -> None:
        pb = _make_peak_bin(bin_center=42.0)
        assert pb.bin_center == 42.0

    def test_presence_ratio(self) -> None:
        # 50 amps out of 100 samples = 0.50
        pb = _make_peak_bin(amps=[0.05] * 50, n_samples=100)
        assert pb.presence_ratio == pytest.approx(0.50)

    def test_burstiness_uniform(self) -> None:
        # All same amplitude → burstiness = 1.0
        pb = _make_peak_bin(amps=[0.05] * 20)
        assert pb.burstiness == pytest.approx(1.0)

    def test_burstiness_spiky(self) -> None:
        # One spike, rest low → high burstiness
        amps = [0.01] * 19 + [1.0]
        pb = _make_peak_bin(amps=amps)
        assert pb.burstiness > 5.0

    def test_snr_positive(self) -> None:
        pb = _make_peak_bin()
        assert pb.snr > 0.0

    def test_peak_type_patterned(self) -> None:
        # High presence, low burstiness, good SNR → patterned
        pb = _make_peak_bin(amps=[0.05] * 80, n_samples=100)
        assert pb.peak_type == "patterned"

    def test_peak_type_transient(self) -> None:
        # Very low presence → transient
        pb = _make_peak_bin(amps=[0.05] * 5, n_samples=100)
        assert pb.peak_type == "transient"

    def test_is_transient_property(self) -> None:
        pb = _make_peak_bin(amps=[0.05] * 5, n_samples=100)
        assert pb.is_transient is True

    def test_confidence_bounded(self) -> None:
        pb = _make_peak_bin()
        assert 0.0 <= pb.confidence <= 1.0

    def test_ranking_score_positive(self) -> None:
        pb = _make_peak_bin()
        assert pb.ranking_score > 0.0

    def test_to_finding_has_required_keys(self) -> None:
        pb = _make_peak_bin()
        finding = pb.to_finding()
        required_keys = {
            "finding_id",
            "suspected_source",
            "evidence_summary",
            "frequency_hz_or_order",
            "amplitude_metric",
            "confidence",
            "quick_checks",
        }
        assert required_keys.issubset(set(finding.keys()))

    def test_to_finding_preserves_bin_center(self) -> None:
        pb = _make_peak_bin(bin_center=42.0)
        finding = pb.to_finding()
        assert "42.0 Hz" in str(finding["frequency_hz_or_order"])

    def test_to_finding_includes_evidence_metrics(self) -> None:
        pb = _make_peak_bin()
        finding = pb.to_finding()
        metrics = finding.get("evidence_metrics")
        assert isinstance(metrics, dict)
        assert "presence_ratio" in metrics
        assert "burstiness" in metrics
        assert "spatial_concentration" in metrics

    def test_spatial_uniformity_single_location(self) -> None:
        pb = _make_peak_bin(total_locations={"front_left"})
        assert pb.spatial_uniformity is None

    def test_spatial_uniformity_multi_location(self) -> None:
        pb = PeakBin(
            bin_center=50.0,
            amps=[0.05] * 40,
            floor_vals=[0.005] * 40,
            speed_amp_pairs=[(60.0, 0.05)] * 40,
            loc_counts_for_bin={"front_left": 20, "front_right": 20},
            speed_bin_counts_for_bin={"60-80": 40},
            phases_for_bin={},
            n_samples=100,
            total_locations={"front_left", "front_right", "rear_left", "rear_right"},
            total_location_sample_counts={
                "front_left": 25,
                "front_right": 25,
                "rear_left": 25,
                "rear_right": 25,
            },
            total_speed_bin_counts={"60-80": 100},
            run_noise_baseline_g=0.001,
            has_phases=False,
        )
        assert pb.spatial_uniformity is not None
        assert pb.spatial_uniformity == pytest.approx(0.50)


# ===========================================================================
# PeakFindingAnalyzer
# ===========================================================================


class TestPeakFindingAnalyzer:
    def test_empty_samples(self) -> None:
        analyzer = PeakFindingAnalyzer(samples=[], order_finding_freqs=set(), lang="en")
        assert analyzer.analyze() == []

    def test_returns_findings(self) -> None:
        """Smoke test: samples with top peaks produce findings."""
        samples = [
            {
                "speed_kmh": 60.0,
                "t_s": float(i),
                "top_peaks": [{"hz": 50.0, "amp": 0.05}],
                "vibration_strength_db": 25.0,
                "client_name": "sensor_fl",
            }
            for i in range(30)
        ]
        analyzer = PeakFindingAnalyzer(
            samples=samples,
            order_finding_freqs=set(),
            lang="en",
        )
        findings = analyzer.analyze()
        assert len(findings) > 0
        for f in findings:
            assert "finding_id" in f
            assert "confidence" in f

    def test_order_freq_exclusion(self) -> None:
        """Bins overlapping with order frequencies are excluded."""
        samples = [
            {
                "speed_kmh": 60.0,
                "t_s": float(i),
                "top_peaks": [{"hz": 50.0, "amp": 0.05}],
                "vibration_strength_db": 25.0,
                "client_name": "sensor_fl",
            }
            for i in range(30)
        ]
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
