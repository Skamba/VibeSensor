from __future__ import annotations

import pytest

from vibesensor.domain import FindingEvidence
from vibesensor.shared.boundaries.codecs import finding_evidence_from_mapping


class TestFindingEvidence:
    def test_defaults(self) -> None:
        evidence = FindingEvidence()
        assert evidence.match_rate == 0.0
        assert evidence.snr_db is None
        assert evidence.presence_ratio == 0.0
        assert evidence.phase_confidences == ()
        assert evidence.vibration_strength_db is None

    @pytest.mark.parametrize(
        ("evidence", "expected"),
        [
            pytest.param(
                FindingEvidence(match_rate=0.8, snr_db=10.0),
                True,
                id="strong-evidence",
            ),
            pytest.param(
                FindingEvidence(match_rate=0.5, snr_db=10.0),
                False,
                id="low-match-rate",
            ),
            pytest.param(
                FindingEvidence(match_rate=0.8, snr_db=None),
                False,
                id="missing-snr",
            ),
        ],
    )
    def test_is_strong_cases(self, evidence: FindingEvidence, expected: bool) -> None:
        assert evidence.is_strong is expected

    @pytest.mark.parametrize(
        ("evidence", "expected"),
        [
            pytest.param(
                FindingEvidence(burstiness=0.1, presence_ratio=0.7),
                True,
                id="consistent",
            ),
            pytest.param(
                FindingEvidence(burstiness=0.5, presence_ratio=0.3),
                False,
                id="inconsistent",
            ),
        ],
    )
    def test_is_consistent_cases(self, evidence: FindingEvidence, expected: bool) -> None:
        assert evidence.is_consistent is expected

    @pytest.mark.parametrize(
        ("evidence", "expected"),
        [
            pytest.param(
                FindingEvidence(spatial_concentration=0.8),
                True,
                id="well-localized",
            ),
            pytest.param(
                FindingEvidence(spatial_concentration=0.3),
                False,
                id="diffuse",
            ),
        ],
    )
    def test_is_well_localized_cases(self, evidence: FindingEvidence, expected: bool) -> None:
        assert evidence.is_well_localized is expected

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
