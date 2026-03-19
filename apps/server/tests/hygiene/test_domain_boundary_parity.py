"""Hygiene tests: field parity between domain objects and boundary TypedDicts.

Boundary serializers (``finding_payload_from_domain``, ``finding_from_payload``,
etc.) manually bridge domain dataclass fields to boundary TypedDict keys.
Without compile-time enforcement, adding a field on one side and forgetting the
other creates silent data loss.  These tests catch drift immediately.

Three test patterns are used depending on the mapping complexity:

* **Strict** — domain fields and payload keys are identical sets.
* **Mapped** — explicit rename map + documented extra-only sets on each side.
* **Structural** — domain uses rich nested objects that the payload "explodes"
  into multiple flat keys; an explicit coverage map verifies every domain field
  is accounted for.
"""

from __future__ import annotations

import dataclasses

from vibesensor.domain.finding import Finding, FindingEvidence
from vibesensor.domain.location_hotspot import LocationHotspot
from vibesensor.domain.order_match import OrderMatchObservation
from vibesensor.domain.run_suitability import SuitabilityCheck
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.boundaries.analysis_payload import (
    FindingEvidenceMetrics,
    FindingPayload,
    LocationHotspotPayload,
    MatchedPoint,
    RunSuitabilityCheck,
)
from vibesensor.shared.boundaries.vibration_origin import SuspectedVibrationOrigin


def _dc_fields(cls: type) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


def _td_fields(cls: type) -> set[str]:
    return set(cls.__required_keys__ | cls.__optional_keys__)


# ---------------------------------------------------------------------------
# 1. OrderMatchObservation ↔ MatchedPoint  (strict 1:1)
# ---------------------------------------------------------------------------


class TestOrderMatchObservationParity:
    """MatchedPoint payload must have the same fields as OrderMatchObservation."""

    def test_field_names_match(self) -> None:
        dc = _dc_fields(OrderMatchObservation)
        td = _td_fields(MatchedPoint)
        assert dc == td, (
            f"OrderMatchObservation ↔ MatchedPoint field drift!\n"
            f"  domain-only: {dc - td}\n"
            f"  payload-only: {td - dc}"
        )


# ---------------------------------------------------------------------------
# 2. FindingEvidence ↔ FindingEvidenceMetrics  (mapped + extras)
# ---------------------------------------------------------------------------


class TestFindingEvidenceParity:
    """FindingEvidenceMetrics payload fields must cover FindingEvidence domain fields."""

    # Domain field → payload key renames
    RENAME_MAP: dict[str, str] = {
        "phase_confidences": "per_phase_confidence",
    }
    # Domain fields with no payload counterpart (intentional)
    DOMAIN_ONLY: set[str] = {
        "snr_db",  # not serialised to payload
    }
    # Payload keys with no domain counterpart (pipeline-produced metrics)
    PAYLOAD_ONLY: set[str] = {
        "median_intensity_db",
        "p95_intensity_db",
        "max_intensity_db",
        "run_noise_baseline_db",
        "median_relative_to_run_noise",
        "p95_relative_to_run_noise",
        "sample_count",
        "total_samples",
    }

    def test_all_domain_fields_covered(self) -> None:
        dc = _dc_fields(FindingEvidence)
        td = _td_fields(FindingEvidenceMetrics)
        mapped_dc = {self.RENAME_MAP.get(f, f) for f in dc} - self.DOMAIN_ONLY
        uncovered = mapped_dc - td - self.DOMAIN_ONLY
        assert not uncovered, f"Domain fields missing from FindingEvidenceMetrics: {uncovered}"

    def test_no_unexpected_payload_keys(self) -> None:
        dc = _dc_fields(FindingEvidence)
        td = _td_fields(FindingEvidenceMetrics)
        reverse_rename = {v: k for k, v in self.RENAME_MAP.items()}
        mapped_td = {reverse_rename.get(f, f) for f in td}
        unexpected = mapped_td - dc - self.PAYLOAD_ONLY
        assert not unexpected, (
            f"Payload keys with no domain counterpart and not in PAYLOAD_ONLY: {unexpected}"
        )


# ---------------------------------------------------------------------------
# 3. LocationHotspot ↔ LocationHotspotPayload  (mapped + extras)
# ---------------------------------------------------------------------------


class TestLocationHotspotParity:
    """LocationHotspotPayload fields must cover LocationHotspot domain fields."""

    RENAME_MAP: dict[str, str] = {
        "strongest_location": "top_location",
        "ambiguous": "ambiguous_location",
        "alternative_locations": "ambiguous_locations",
    }
    PAYLOAD_ONLY: set[str] = {
        "second_location",  # derived from alternatives during serialisation
    }

    def test_all_domain_fields_covered(self) -> None:
        dc = _dc_fields(LocationHotspot)
        td = _td_fields(LocationHotspotPayload)
        mapped_dc = {self.RENAME_MAP.get(f, f) for f in dc}
        uncovered = mapped_dc - td
        assert not uncovered, f"Domain fields missing from LocationHotspotPayload: {uncovered}"

    def test_no_unexpected_payload_keys(self) -> None:
        dc = _dc_fields(LocationHotspot)
        td = _td_fields(LocationHotspotPayload)
        reverse_rename = {v: k for k, v in self.RENAME_MAP.items()}
        mapped_td = {reverse_rename.get(f, f) for f in td}
        unexpected = mapped_td - dc - self.PAYLOAD_ONLY
        assert not unexpected, f"Payload keys not in domain or PAYLOAD_ONLY: {unexpected}"


# ---------------------------------------------------------------------------
# 4. SuitabilityCheck ↔ RunSuitabilityCheck  (mapped + extras)
# ---------------------------------------------------------------------------


class TestSuitabilityCheckParity:
    """RunSuitabilityCheck payload must cover SuitabilityCheck domain fields."""

    RENAME_MAP: dict[str, str] = {
        "details": "explanation",  # details → i18n explanation
    }
    PAYLOAD_ONLY: set[str] = {
        "check",  # legacy alias of check_key
    }

    def test_all_domain_fields_covered(self) -> None:
        dc = _dc_fields(SuitabilityCheck)
        td = _td_fields(RunSuitabilityCheck)
        mapped_dc = {self.RENAME_MAP.get(f, f) for f in dc}
        uncovered = mapped_dc - td
        assert not uncovered, f"Domain fields missing from RunSuitabilityCheck: {uncovered}"

    def test_no_unexpected_payload_keys(self) -> None:
        dc = _dc_fields(SuitabilityCheck)
        td = _td_fields(RunSuitabilityCheck)
        reverse_rename = {v: k for k, v in self.RENAME_MAP.items()}
        mapped_td = {reverse_rename.get(f, f) for f in td}
        unexpected = mapped_td - dc - self.PAYLOAD_ONLY
        assert not unexpected, f"Payload keys not in domain or PAYLOAD_ONLY: {unexpected}"


# ---------------------------------------------------------------------------
# 5. VibrationOrigin ↔ SuspectedVibrationOrigin  (mapped + extras)
# ---------------------------------------------------------------------------


class TestVibrationOriginParity:
    """SuspectedVibrationOrigin payload must cover VibrationOrigin domain fields."""

    RENAME_MAP: dict[str, str] = {
        "reason": "explanation",
    }
    # hotspot is a rich domain object exploded into flat payload keys
    DOMAIN_ONLY: set[str] = {
        "hotspot",
    }
    PAYLOAD_ONLY: set[str] = {
        "location",  # derived from hotspot.strongest_location
        "alternative_locations",  # derived from hotspot.alternative_locations
        "weak_spatial_separation",  # derived from hotspot
    }

    def test_all_domain_fields_covered(self) -> None:
        dc = _dc_fields(VibrationOrigin)
        td = _td_fields(SuspectedVibrationOrigin)
        mapped_dc = {self.RENAME_MAP.get(f, f) for f in dc} - self.DOMAIN_ONLY
        uncovered = mapped_dc - td
        assert not uncovered, f"Domain fields missing from SuspectedVibrationOrigin: {uncovered}"

    def test_no_unexpected_payload_keys(self) -> None:
        dc = _dc_fields(VibrationOrigin)
        td = _td_fields(SuspectedVibrationOrigin)
        reverse_rename = {v: k for k, v in self.RENAME_MAP.items()}
        mapped_td = {reverse_rename.get(f, f) for f in td}
        unexpected = mapped_td - dc - self.PAYLOAD_ONLY
        assert not unexpected, f"Payload keys not in domain or PAYLOAD_ONLY: {unexpected}"


# ---------------------------------------------------------------------------
# 6. Finding ↔ FindingPayload  (structural coverage map)
# ---------------------------------------------------------------------------


class TestFindingPayloadCoverage:
    """Every Finding domain field must be accounted for in FindingPayload.

    The mapping is not 1:1 — domain uses rich nested objects while the
    payload flattens them into multiple keys.  This test verifies that
    every domain field falls into exactly one of:

    * Direct-mapped (same name or explicit rename in payload)
    * Exploded (a nested object whose child fields appear as flat keys)
    """

    # Domain field name → payload key(s) it maps to.
    # For exploded objects, the list of resulting payload keys.
    DOMAIN_TO_PAYLOAD: dict[str, list[str]] = {
        "finding_id": ["finding_id"],
        "finding_key": ["finding_key"],
        "suspected_source": ["suspected_source"],
        "confidence": ["confidence"],
        "frequency_hz": ["frequency_hz_or_order"],
        "order": ["order"],
        "severity": ["severity"],
        "strongest_location": ["strongest_location"],
        "strongest_speed_band": ["strongest_speed_band"],
        "peak_classification": ["peak_classification"],
        "kind": ["finding_kind"],
        "dominant_phase": ["dominant_phase"],
        "ranking_score": ["ranking_score"],
        "dominance_ratio": ["dominance_ratio"],
        "diffuse_excitation": ["diffuse_excitation"],
        "weak_spatial_separation": ["weak_spatial_separation"],
        "vibration_strength_db": [],  # nested inside amplitude_metric
        "cruise_fraction": ["phase_evidence"],
        "phases_detected": ["phase_evidence"],
        "matched_points": ["matched_points"],
        # Rich objects exploded into flat payload keys
        "evidence": ["evidence_metrics"],
        "location": ["location_hotspot"],
        "confidence_assessment": [
            "confidence_label_key",
            "confidence_tone",
            "confidence_pct",
        ],
        "origin": [],  # serialised via separate origin boundary
        "signatures": ["signatures_observed"],
    }

    def test_all_domain_fields_accounted_for(self) -> None:
        dc = _dc_fields(Finding)
        accounted = set(self.DOMAIN_TO_PAYLOAD.keys())
        missing = dc - accounted
        assert not missing, (
            f"Finding domain fields not in DOMAIN_TO_PAYLOAD map: {missing}\n"
            "Add them to the coverage map with their payload key(s)."
        )

    def test_mapped_payload_keys_exist(self) -> None:
        td = _td_fields(FindingPayload)
        for domain_field, payload_keys in self.DOMAIN_TO_PAYLOAD.items():
            for pk in payload_keys:
                assert pk in td, (
                    f"Domain field '{domain_field}' maps to payload key "
                    f"'{pk}' which does not exist in FindingPayload"
                )
