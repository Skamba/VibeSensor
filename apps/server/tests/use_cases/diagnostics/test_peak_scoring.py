from __future__ import annotations

import pytest

from vibesensor.use_cases.diagnostics.peaks.finding_builder import assemble_peak_finding
from vibesensor.use_cases.diagnostics.peaks.scoring import PeakBin


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
        amps = [0.05] * 50
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
    )


class TestPeakBin:
    def test_bin_center(self) -> None:
        peak_bin = _make_peak_bin(bin_center=42.0)
        assert peak_bin.bin_center == 42.0

    def test_presence_ratio(self) -> None:
        peak_bin = _make_peak_bin(amps=[0.05] * 50, n_samples=100)
        assert peak_bin.presence_ratio == pytest.approx(0.50)
        assert peak_bin.sample_count == 50
        assert peak_bin.total_sample_count == 100

    def test_burstiness_uniform(self) -> None:
        peak_bin = _make_peak_bin(amps=[0.05] * 20)
        assert peak_bin.burstiness == pytest.approx(1.0)

    def test_burstiness_spiky(self) -> None:
        peak_bin = _make_peak_bin(amps=[0.01] * 19 + [1.0])
        assert peak_bin.burstiness > 5.0

    def test_snr_positive(self) -> None:
        peak_bin = _make_peak_bin()
        assert peak_bin.snr > 0.0

    def test_peak_type_patterned(self) -> None:
        peak_bin = _make_peak_bin(amps=[0.05] * 80, n_samples=100)
        assert peak_bin.peak_type == "patterned"

    def test_peak_type_transient(self) -> None:
        peak_bin = _make_peak_bin(amps=[0.05] * 5, n_samples=100)
        assert peak_bin.peak_type == "transient"

    def test_is_transient_property(self) -> None:
        peak_bin = _make_peak_bin(amps=[0.05] * 5, n_samples=100)
        assert peak_bin.is_transient is True

    def test_confidence_bounded(self) -> None:
        peak_bin = _make_peak_bin()
        assert 0.0 <= peak_bin.confidence <= 1.0

    def test_ranking_score_positive(self) -> None:
        peak_bin = _make_peak_bin()
        assert peak_bin.ranking_score > 0.0

    def test_spatial_uniformity_single_location(self) -> None:
        peak_bin = _make_peak_bin(total_locations={"front_left"})
        assert peak_bin.spatial_uniformity is None

    def test_spatial_uniformity_multi_location(self) -> None:
        peak_bin = PeakBin(
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
        )
        assert peak_bin.spatial_uniformity is not None
        assert peak_bin.spatial_uniformity == pytest.approx(0.50)


class TestAssemblePeakFinding:
    def test_has_required_fields(self) -> None:
        finding = assemble_peak_finding(_make_peak_bin())
        assert finding.finding_id == "F_PEAK"
        assert str(finding.suspected_source)
        assert finding.confidence is not None
        assert finding.kind is not None

    def test_preserves_bin_center(self) -> None:
        finding = assemble_peak_finding(_make_peak_bin(bin_center=42.0))
        assert finding.order == "42.0 Hz"

    def test_includes_evidence_metrics(self) -> None:
        finding = assemble_peak_finding(_make_peak_bin())
        metrics = finding.evidence
        assert metrics is not None
        assert metrics.presence_ratio > 0.0
        assert metrics.matched_samples == 50
        assert metrics.possible_samples == 100
        assert metrics.match_rate == pytest.approx(metrics.presence_ratio)
        assert metrics.burstiness >= 0.0
        assert metrics.spatial_concentration > 0.0
