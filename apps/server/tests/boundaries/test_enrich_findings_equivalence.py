"""Equivalence test: _enrich_findings delegates to finding_from_payload.

After deduplication, _enrich_findings() is a thin wrapper around
finding_from_payload(). This test confirms that the output is identical
to calling finding_from_payload() directly.
"""

from __future__ import annotations

from tests.test_support.findings import make_finding_payload, make_info_finding, make_ref_finding
from vibesensor.boundaries.diagnostic_case import _enrich_findings
from vibesensor.boundaries.finding import finding_from_payload


def _enriched_finding(payload: dict) -> object:
    """Run _enrich_findings on a single payload."""
    results = _enrich_findings([payload])
    assert len(results) == 1
    return results[0]


class TestEnrichFindingsEquivalence:
    """Confirm that _enrich_findings produces the same origin and signatures
    as finding_from_payload alone (the double-construction is redundant)."""

    def test_diagnostic_finding_origin_equivalent(self) -> None:
        payload = make_finding_payload(
            strongest_location="front-left",
            signatures_observed=["1x wheel", "harmonic pattern"],
            location_hotspot={
                "best_location": "front-left",
                "alternative_locations": ["front-right"],
                "dominance_ratio": 2.5,
                "weak_spatial_separation": False,
            },
            dominance_ratio=2.5,
            strongest_speed_band="60-80 km/h",
            evidence_summary="Test reason",
        )
        direct = finding_from_payload(payload)
        enriched = _enriched_finding(payload)

        assert direct.origin is not None
        assert enriched.origin is not None
        assert direct.origin == enriched.origin

    def test_diagnostic_finding_signatures_equivalent(self) -> None:
        payload = make_finding_payload(
            signatures_observed=["1x wheel", "harmonic pattern", "speed-dependent"],
        )
        direct = finding_from_payload(payload)
        enriched = _enriched_finding(payload)

        assert len(direct.signatures) == len(enriched.signatures)
        for d, e in zip(direct.signatures, enriched.signatures, strict=True):
            assert d.key == e.key
            assert d.source == e.source
            assert d.label == e.label
            assert d.support_score == e.support_score

    def test_reference_finding_equivalent(self) -> None:
        payload = make_ref_finding(
            signatures_observed=["baseline noise"],
        )
        direct = finding_from_payload(payload)
        enriched = _enriched_finding(payload)

        assert direct.origin == enriched.origin
        assert direct.signatures == enriched.signatures

    def test_info_finding_equivalent(self) -> None:
        payload = make_info_finding(
            signatures_observed=["transient peak"],
            strongest_speed_band="40-60 km/h",
        )
        direct = finding_from_payload(payload)
        enriched = _enriched_finding(payload)

        assert direct.origin == enriched.origin
        assert direct.signatures == enriched.signatures

    def test_no_signatures_equivalent(self) -> None:
        payload = make_finding_payload()  # no signatures_observed key
        direct = finding_from_payload(payload)
        enriched = _enriched_finding(payload)

        assert direct.signatures == enriched.signatures == ()
        assert direct.origin == enriched.origin

    def test_no_location_hotspot_equivalent(self) -> None:
        payload = make_finding_payload(
            signatures_observed=["1x wheel"],
        )
        direct = finding_from_payload(payload)
        enriched = _enriched_finding(payload)

        assert direct.origin == enriched.origin
        assert direct.signatures == enriched.signatures

    def test_none_confidence_equivalent(self) -> None:
        payload = make_finding_payload(
            confidence=None,
            signatures_observed=["noisy signal"],
        )
        direct = finding_from_payload(payload)
        enriched = _enriched_finding(payload)

        assert direct.origin == enriched.origin
        assert direct.signatures == enriched.signatures

    def test_full_finding_complete_equivalence(self) -> None:
        """Full payload with all fields — the entire Finding must be equal."""
        payload = make_finding_payload(
            finding_id="F_WHEEL_ORDER",
            suspected_source="wheel/tire",
            confidence=0.82,
            strongest_location="rear-right",
            strongest_speed_band="80-100 km/h",
            dominance_ratio=3.1,
            signatures_observed=["1x wheel", "2x wheel"],
            location_hotspot={
                "best_location": "rear-right",
                "alternative_locations": ["rear-left"],
                "dominance_ratio": 3.1,
                "weak_spatial_separation": False,
            },
            evidence_summary="Strong wheel-order correlation",
            dominant_phase="cruise",
        )
        direct = finding_from_payload(payload)
        enriched = _enriched_finding(payload)

        # The entire Finding should be equal (frozen dataclass)
        assert direct == enriched
