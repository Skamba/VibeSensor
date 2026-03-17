"""Tests: legacy boundary aliases are removed from finding_from_payload."""

from __future__ import annotations

from vibesensor.domain.finding import VibrationSource
from vibesensor.shared.boundaries.finding import finding_from_payload


class TestLegacySourceAlias:
    """Legacy dicts using ``source`` instead of ``suspected_source``."""

    def test_legacy_source_key_produces_unknown(self) -> None:
        """A dict with only ``source`` (no ``suspected_source``) => UNKNOWN."""
        payload: dict[str, object] = {
            "finding_id": "F-legacy",
            "severity": "diagnostic",
            "source": "wheel/tire",
        }
        finding = finding_from_payload(payload)
        assert finding.suspected_source is VibrationSource.UNKNOWN

    def test_suspected_source_key_works(self) -> None:
        """A dict with ``suspected_source`` still resolves correctly."""
        payload: dict[str, object] = {
            "finding_id": "F-current",
            "severity": "diagnostic",
            "suspected_source": "wheel/tire",
        }
        finding = finding_from_payload(payload)
        assert finding.suspected_source is VibrationSource.WHEEL_TIRE


class TestLegacySnrRatioAlias:
    """Legacy ``snr_ratio`` key is no longer normalized to ``snr_db``."""

    def test_snr_ratio_only_does_not_populate_snr_db(self) -> None:
        payload: dict[str, object] = {
            "finding_id": "F-snr",
            "severity": "diagnostic",
            "suspected_source": "driveline",
            "evidence_metrics": {"snr_ratio": 12.5},
        }
        finding = finding_from_payload(payload)
        # snr_db should be None because the normalization was removed
        assert finding.evidence is not None
        assert finding.evidence.snr_db is None
