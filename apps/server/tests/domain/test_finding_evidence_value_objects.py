from __future__ import annotations

import pytest

from vibesensor.summary.finding_fields import finding_evidence_from_mapping


class TestFindingEvidence:
    def test_boundary_decode_full(self) -> None:
        evidence = finding_evidence_from_mapping(
            {
                "match_rate": 0.85,
                "snr_db": 12.5,
                "presence_ratio": 0.7,
                "burstiness": 0.1,
                "spatial_concentration": 0.9,
                "frequency_correlation": 0.95,
                "speed_uniformity": 0.8,
                "spatial_uniformity": 0.7,
                "per_phase_confidence": {"cruise": 0.9, "accel": 0.6},
                "vibration_strength_db": 25.3,
            }
        )

        assert evidence.match_rate == 0.85
        assert evidence.snr_db == 12.5
        assert evidence.presence_ratio == 0.7
        assert evidence.burstiness == 0.1
        assert evidence.spatial_concentration == 0.9
        assert evidence.vibration_strength_db == 25.3
        assert ("accel", 0.6) in evidence.phase_confidences
        assert ("cruise", 0.9) in evidence.phase_confidences

    def test_boundary_decode_empty(self) -> None:
        evidence = finding_evidence_from_mapping({})
        assert evidence.match_rate == 0.0
        assert evidence.snr_db is None
        assert evidence.phase_confidences == ()

    @pytest.mark.parametrize(
        ("payload", "expected_snr_db"),
        [
            pytest.param({"snr_ratio": 8.0}, None, id="noncanonical-key-ignored"),
            pytest.param({"snr_db": 8.0}, 8.0, id="canonical-key-used"),
        ],
    )
    def test_boundary_decode_snr_keys(
        self,
        payload: dict[str, float],
        expected_snr_db: float | None,
    ) -> None:
        evidence = finding_evidence_from_mapping(payload)
        assert evidence.snr_db == expected_snr_db
