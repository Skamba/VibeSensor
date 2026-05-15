"""Tests: legacy boundary aliases are removed from finding_from_payload."""

from __future__ import annotations

from vibesensor.domain import Finding, FindingEvidence, VibrationSource
from vibesensor.shared.boundaries.summary_fields.finding import (
    finding_from_payload,
    finding_payload_from_domain,
)


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

    def test_projection_uses_only_canonical_snr_db_key(self) -> None:
        finding = Finding(
            finding_id="F-snr",
            suspected_source=VibrationSource.DRIVELINE,
            evidence=FindingEvidence(snr_db=12.5),
        )

        payload = finding_payload_from_domain(finding)

        evidence_metrics = payload["evidence_metrics"]
        assert isinstance(evidence_metrics, dict)
        assert evidence_metrics["snr_db"] == 12.5
        assert "snr_ratio" not in evidence_metrics


class TestRemovedSignalFallbacks:
    """Presentation-only signal labels no longer drive domain reconstruction."""

    def test_frequency_hz_or_order_only_does_not_restore_signal_fields(self) -> None:
        payload: dict[str, object] = {
            "finding_id": "F-freq",
            "severity": "diagnostic",
            "suspected_source": "wheel/tire",
            "frequency_hz_or_order": "41.0 Hz",
        }

        finding = finding_from_payload(payload)

        assert finding.frequency_hz is None
        assert finding.order == ""


class TestRemovedHotspotAliases:
    """Canonical hotspot decoding ignores removed alias keys."""

    def test_location_hotspot_uses_only_canonical_location_keys(self) -> None:
        payload: dict[str, object] = {
            "finding_id": "F-hotspot",
            "severity": "diagnostic",
            "suspected_source": "wheel/tire",
            "location_hotspot": {
                "top_location": "front-left",
                "ambiguous_locations": ["rear-left"],
                "location_count": 4,
                "second_location": "front-right",
                "location": "wrong-location",
                "ambiguous_location": True,
            },
        }

        finding = finding_from_payload(payload)

        assert finding.location is not None
        assert finding.location.strongest_location == "front-left"
        assert finding.location.alternative_locations == ("rear-left",)
        assert finding.location.location_count == 4
        assert finding.location.ambiguous is True
