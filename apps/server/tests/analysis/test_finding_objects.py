"""Tests for FindingCollection, PeakBin, and PeakFindingAnalyzer."""

from __future__ import annotations

import pytest

from vibesensor.analysis._types import FindingPayload
from vibesensor.analysis.findings import (
    FindingCollection,
    PeakBin,
    PeakFindingAnalyzer,
)
from vibesensor.domain import Finding

# ---------------------------------------------------------------------------
# Fixtures: minimal FindingPayload dicts
# ---------------------------------------------------------------------------


def _ref_finding(finding_id: str = "REF_SPEED") -> FindingPayload:
    return {
        "finding_id": finding_id,
        "suspected_source": "unknown",
        "evidence_summary": {"_i18n_key": "TEST"},
        "frequency_hz_or_order": "n/a",
        "amplitude_metric": {"name": "n/a", "value": None, "units": "n/a", "definition": "n/a"},
        "confidence": None,
        "quick_checks": [],
    }


def _diag_finding(
    finding_id: str = "F_ORDER",
    confidence: float = 0.65,
    source: str = "wheel/tire",
    ranking_score: float = 1.0,
    location: str = "front_left",
) -> FindingPayload:
    return {
        "finding_id": finding_id,
        "suspected_source": source,
        "evidence_summary": {"_i18n_key": "TEST"},
        "frequency_hz_or_order": "1x wheel",
        "amplitude_metric": {
            "name": "vibration_strength_db",
            "value": 25.0,
            "units": "dB",
            "definition": {"_i18n_key": "METRIC"},
        },
        "confidence": confidence,
        "quick_checks": [],
        "_ranking_score": ranking_score,
        "strongest_location": location,
    }


def _info_finding(finding_id: str = "F_PEAK", confidence: float = 0.10) -> FindingPayload:
    f = _diag_finding(finding_id=finding_id, confidence=confidence)
    f["severity"] = "info"
    f["suspected_source"] = "transient_impact"
    return f


# ===========================================================================
# Domain Finding from payload (replaces former FindingRecord tests)
# ===========================================================================


class TestDomainFindingFromPayload:
    def test_finding_id(self) -> None:
        f = Finding.from_payload(_diag_finding(finding_id="F_ORDER"))
        assert f.finding_id == "F_ORDER"

    def test_is_reference(self) -> None:
        assert Finding.from_payload(_ref_finding()).is_reference is True
        assert Finding.from_payload(_diag_finding()).is_reference is False

    def test_is_informational(self) -> None:
        assert Finding.from_payload(_info_finding()).is_informational is True
        assert Finding.from_payload(_diag_finding()).is_informational is False

    def test_is_diagnostic(self) -> None:
        assert Finding.from_payload(_diag_finding()).is_diagnostic is True
        assert Finding.from_payload(_ref_finding()).is_diagnostic is False
        assert Finding.from_payload(_info_finding()).is_diagnostic is False

    def test_confidence_default(self) -> None:
        f = Finding.from_payload(_ref_finding())
        assert f.effective_confidence == 0.0

    def test_confidence_value(self) -> None:
        f = Finding.from_payload(_diag_finding(confidence=0.75))
        assert f.effective_confidence == 0.75

    def test_source_normalized(self) -> None:
        f = Finding.from_payload(_diag_finding(source="  Wheel/Tire  "))
        assert f.source_normalized == "wheel/tire"

    def test_strongest_location(self) -> None:
        f = Finding.from_payload(_diag_finding(location="front_left"))
        assert f.strongest_location == "front_left"

    def test_ranking_score(self) -> None:
        f = Finding.from_payload(_diag_finding(ranking_score=2.5))
        assert f.ranking_score == 2.5


# ===========================================================================
# FindingCollection
# ===========================================================================


class TestFindingCollection:
    def test_len(self) -> None:
        coll = FindingCollection([_diag_finding(), _ref_finding()])
        assert len(coll) == 2

    def test_iter(self) -> None:
        findings = [_diag_finding(), _ref_finding()]
        coll = FindingCollection(findings)
        assert list(coll) == findings

    def test_references(self) -> None:
        findings = [_ref_finding("REF_SPEED"), _diag_finding(), _ref_finding("REF_ENGINE")]
        coll = FindingCollection(findings)
        refs = coll.references()
        assert len(refs) == 2
        assert all(str(f["finding_id"]).startswith("REF_") for f in refs)

    def test_diagnostics(self) -> None:
        findings = [_ref_finding(), _diag_finding(), _info_finding()]
        coll = FindingCollection(findings)
        diags = coll.diagnostics()
        assert len(diags) == 1
        assert diags[0]["suspected_source"] == "wheel/tire"

    def test_informational(self) -> None:
        findings = [_ref_finding(), _diag_finding(), _info_finding()]
        coll = FindingCollection(findings)
        infos = coll.informational()
        assert len(infos) == 1
        assert infos[0].get("severity") == "info"

    def test_non_reference(self) -> None:
        findings = [_ref_finding(), _diag_finding(), _info_finding()]
        coll = FindingCollection(findings)
        non_ref = coll.non_reference()
        assert len(non_ref) == 2

    def test_finalize_ordering(self) -> None:
        """References come first, then diagnostics by confidence, then informational."""
        ref = _ref_finding()
        diag_high = _diag_finding(confidence=0.80, ranking_score=2.0)
        diag_low = _diag_finding(confidence=0.30, ranking_score=1.0)
        info = _info_finding(confidence=0.10)
        coll = FindingCollection([diag_low, info, ref, diag_high])
        ordered = coll.finalize()
        assert len(ordered) == 4
        # Reference first
        assert str(ordered[0]["finding_id"]).startswith("REF_")
        # Then high-confidence diagnostic
        assert ordered[1]["confidence"] == 0.80
        # Then low-confidence diagnostic
        assert ordered[2]["confidence"] == 0.30
        # Then informational
        assert ordered[3].get("severity") == "info"

    def test_finalize_assigns_sequential_ids(self) -> None:
        ref = _ref_finding("REF_SPEED")
        d1 = _diag_finding(confidence=0.80)
        d2 = _diag_finding(confidence=0.40)
        info = _info_finding()
        coll = FindingCollection([d2, info, ref, d1])
        ordered = coll.finalize()
        # Reference keeps its original ID
        assert ordered[0]["finding_id"] == "REF_SPEED"
        # Non-reference findings get sequential F### IDs
        assert ordered[1]["finding_id"] == "F001"
        assert ordered[2]["finding_id"] == "F002"
        assert ordered[3]["finding_id"] == "F003"

    def test_finalize_empty(self) -> None:
        coll = FindingCollection([])
        assert coll.finalize() == []

    def test_items_property(self) -> None:
        findings = [_diag_finding()]
        coll = FindingCollection(findings)
        assert coll.items is findings


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
