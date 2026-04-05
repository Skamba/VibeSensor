"""Tests for the evidence-metrics builder used by the finding boundary codec."""

from __future__ import annotations

from vibesensor.domain import Finding, FindingEvidence, VibrationSource
from vibesensor.shared.boundaries.summary_fields.evidence_metrics import build_evidence_metrics


class TestBuildEvidenceMetrics:
    """build_evidence_metrics covers the three branches: evidence, strength-only, none."""

    def test_returns_none_when_no_evidence_and_no_strength(self) -> None:
        finding = Finding(finding_id="F1", suspected_source=VibrationSource.UNKNOWN)
        assert build_evidence_metrics(finding) is None

    def test_returns_strength_only_when_no_evidence(self) -> None:
        finding = Finding(
            finding_id="F2",
            suspected_source=VibrationSource.WHEEL_TIRE,
            vibration_strength_db=18.5,
        )
        result = build_evidence_metrics(finding)
        assert result == {"vibration_strength_db": 18.5}

    def test_returns_full_metrics_from_evidence(self) -> None:
        evidence = FindingEvidence(
            match_rate=0.75,
            presence_ratio=0.85,
            burstiness=0.12,
            spatial_concentration=0.6,
            frequency_correlation=0.7,
            speed_uniformity=0.5,
            spatial_uniformity=0.4,
            snr_db=14.0,
            vibration_strength_db=20.0,
        )
        finding = Finding(
            finding_id="F3",
            suspected_source=VibrationSource.DRIVELINE,
            evidence=evidence,
        )
        result = build_evidence_metrics(finding)
        assert result is not None
        assert result["match_rate"] == 0.75
        assert result["presence_ratio"] == 0.85
        assert result["burstiness"] == 0.12
        assert result["spatial_concentration"] == 0.6
        assert result["frequency_correlation"] == 0.7
        assert result["speed_uniformity"] == 0.5
        assert result["spatial_uniformity"] == 0.4
        assert result["snr_db"] == 14.0
        assert result["vibration_strength_db"] == 20.0

    def test_evidence_strength_falls_back_to_finding_strength(self) -> None:
        evidence = FindingEvidence(
            match_rate=0.6,
            presence_ratio=0.7,
            burstiness=0.2,
            spatial_concentration=0.5,
            frequency_correlation=0.4,
            speed_uniformity=0.3,
            spatial_uniformity=0.2,
        )
        finding = Finding(
            finding_id="F4",
            suspected_source=VibrationSource.WHEEL_TIRE,
            vibration_strength_db=22.3,
            evidence=evidence,
        )
        result = build_evidence_metrics(finding)
        assert result is not None
        assert result["vibration_strength_db"] == 22.3

    def test_optional_fields_omitted_when_none(self) -> None:
        evidence = FindingEvidence(
            match_rate=0.5,
            presence_ratio=0.6,
            burstiness=0.1,
            spatial_concentration=0.4,
            frequency_correlation=0.3,
            speed_uniformity=0.2,
            spatial_uniformity=0.1,
        )
        finding = Finding(
            finding_id="F5",
            suspected_source=VibrationSource.UNKNOWN,
            evidence=evidence,
        )
        result = build_evidence_metrics(finding)
        assert result is not None
        assert "global_match_rate" not in result
        assert "focused_speed_band" not in result
        assert "mean_relative_error" not in result
        assert "mean_noise_floor_db" not in result
        assert "possible_samples" not in result
        assert "matched_samples" not in result
        assert "snr_db" not in result
        assert "vibration_strength_db" not in result
        assert "phases_with_evidence" not in result
        assert "per_phase_confidence" not in result

    def test_optional_fields_present_when_set(self) -> None:
        evidence = FindingEvidence(
            match_rate=0.8,
            global_match_rate=0.7,
            focused_speed_band="60-80 km/h",
            mean_relative_error=0.02,
            mean_noise_floor_db=5.0,
            possible_samples=100,
            matched_samples=80,
            snr_db=12.0,
            vibration_strength_db=18.0,
            presence_ratio=0.9,
            burstiness=0.05,
            spatial_concentration=0.8,
            frequency_correlation=0.9,
            speed_uniformity=0.7,
            spatial_uniformity=0.6,
            phases_with_evidence=3,
            phase_confidences=(("cruise", 0.9), ("accel", 0.7)),
        )
        finding = Finding(
            finding_id="F6",
            suspected_source=VibrationSource.WHEEL_TIRE,
            evidence=evidence,
        )
        result = build_evidence_metrics(finding)
        assert result is not None
        assert result["global_match_rate"] == 0.7
        assert result["focused_speed_band"] == "60-80 km/h"
        assert result["mean_relative_error"] == 0.02
        assert result["mean_noise_floor_db"] == 5.0
        assert result["possible_samples"] == 100
        assert result["matched_samples"] == 80
        assert result["phases_with_evidence"] == 3
        assert result["per_phase_confidence"] == {"cruise": 0.9, "accel": 0.7}
