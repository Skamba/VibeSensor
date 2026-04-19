"""Domain value-object tests for findings and vibration origin metadata."""

from __future__ import annotations

import dataclasses

import pytest

from vibesensor.domain import (
    Finding,
    FindingEvidence,
    LocationHotspot,
    VibrationOrigin,
    VibrationSource,
)
from vibesensor.shared.boundaries.codecs import finding_evidence_from_mapping
from vibesensor.shared.boundaries.summary_fields.origin import (
    location_hotspot_from_payload,
    origin_payload_from_finding,
    vibration_origin_from_payload,
)


class TestFindingEvidence:
    def test_frozen(self) -> None:
        e = FindingEvidence()
        with pytest.raises(dataclasses.FrozenInstanceError):
            e.match_rate = 0.5

    def test_defaults(self) -> None:
        e = FindingEvidence()
        assert e.match_rate == 0.0
        assert e.snr_db is None
        assert e.presence_ratio == 0.0
        assert e.phase_confidences == ()
        assert e.vibration_strength_db is None

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
        d = {
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
        e = finding_evidence_from_mapping(d)
        assert e.match_rate == 0.85
        assert e.snr_db == 12.5
        assert e.presence_ratio == 0.7
        assert e.burstiness == 0.1
        assert e.spatial_concentration == 0.9
        assert e.vibration_strength_db == 25.3
        assert ("accel", 0.6) in e.phase_confidences
        assert ("cruise", 0.9) in e.phase_confidences

    def test_boundary_decode_empty(self) -> None:
        e = finding_evidence_from_mapping({})
        assert e.match_rate == 0.0
        assert e.snr_db is None
        assert e.phase_confidences == ()

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


class TestLocationHotspot:
    def test_frozen(self) -> None:
        h = LocationHotspot()
        with pytest.raises(dataclasses.FrozenInstanceError):
            h.strongest_location = "foo"

    def test_defaults(self) -> None:
        h = LocationHotspot()
        assert h.strongest_location == ""
        assert h.dominance_ratio is None
        assert not h.weak_spatial_separation
        assert not h.ambiguous
        assert h.alternative_locations == ()

    @pytest.mark.parametrize(
        ("hotspot", "expected"),
        [
            pytest.param(
                LocationHotspot(
                    strongest_location="front_left",
                    dominance_ratio=0.8,
                    weak_spatial_separation=False,
                    ambiguous=False,
                ),
                True,
                id="clear-location",
            ),
            pytest.param(
                LocationHotspot(strongest_location="unknown"),
                False,
                id="unknown-location",
            ),
            pytest.param(
                LocationHotspot(
                    strongest_location="front_left",
                    weak_spatial_separation=True,
                ),
                False,
                id="weak-spatial-separation",
            ),
        ],
    )
    def test_is_well_localized_cases(self, hotspot: LocationHotspot, expected: bool) -> None:
        assert hotspot.is_well_localized is expected

    @pytest.mark.parametrize(
        ("hotspot", "expected"),
        [
            pytest.param(LocationHotspot(strongest_location="FL wheel"), True, id="known-location"),
            pytest.param(LocationHotspot(strongest_location=""), False, id="blank-location"),
            pytest.param(
                LocationHotspot(strongest_location="unknown"),
                False,
                id="unknown-location",
            ),
            pytest.param(
                LocationHotspot(strongest_location="FL wheel", ambiguous=True),
                False,
                id="ambiguous-location",
            ),
        ],
    )
    def test_is_actionable_cases(self, hotspot: LocationHotspot, expected: bool) -> None:
        assert hotspot.is_actionable is expected

    @pytest.mark.parametrize(
        ("hotspot", "expected"),
        [
            pytest.param(
                LocationHotspot(strongest_location="front_left"),
                "Front Left",
                id="known-location",
            ),
            pytest.param(LocationHotspot(strongest_location=""), "Unknown", id="blank-location"),
            pytest.param(
                LocationHotspot(strongest_location="unknown"),
                "Unknown",
                id="unknown-location",
            ),
        ],
    )
    def test_display_location_cases(self, hotspot: LocationHotspot, expected: str) -> None:
        assert hotspot.display_location == expected

    def test_has_clear_separation_false_for_ambiguous_hotspot(self) -> None:
        hotspot = LocationHotspot(strongest_location="front_left", ambiguous=True)
        assert hotspot.has_clear_separation is False

    def test_confidence_band_uses_domain_thresholds(self) -> None:
        assert LocationHotspot(localization_confidence=0.8).confidence_band == "high"
        assert LocationHotspot(localization_confidence=0.55).confidence_band == "medium"
        assert LocationHotspot(localization_confidence=0.2).confidence_band == "low"

    def test_supporting_locations_excludes_primary_and_dedupes(self) -> None:
        hotspot = LocationHotspot(
            strongest_location="front_left",
            alternative_locations=("front_left", "front_right", "front_right", "rear_left"),
        )
        assert hotspot.supporting_locations == ("front_right", "rear_left")

    def test_summary_location_joins_supporting_locations_when_ambiguous(self) -> None:
        hotspot = LocationHotspot(
            strongest_location="front_left",
            ambiguous=True,
            alternative_locations=("front_right",),
        )
        assert hotspot.summary_location == "front_left / front_right"

    def test_location_hotspot_from_payload_full(self) -> None:
        d = {
            "top_location": "FL wheel",
            "dominance_ratio": 0.75,
            "localization_confidence": 0.9,
            "weak_spatial_separation": True,
            "ambiguous_location": False,
            "ambiguous_locations": ["FR wheel", "RL wheel"],
        }
        h = location_hotspot_from_payload(d)
        assert h.strongest_location == "FL wheel"
        assert h.dominance_ratio == 0.75
        assert h.localization_confidence == 0.9
        assert h.weak_spatial_separation is True
        assert h.ambiguous is False
        assert h.alternative_locations == ("FR wheel", "RL wheel")

    def test_location_hotspot_from_payload_empty(self) -> None:
        h = location_hotspot_from_payload({})
        assert h.strongest_location == ""
        assert h.dominance_ratio is None

    def test_location_hotspot_from_payload_top_location_fallback(self) -> None:
        h = location_hotspot_from_payload({"top_location": "center"})
        assert h.strongest_location == "center"

    def test_location_hotspot_from_payload_prefers_top_location_identity(self) -> None:
        hotspot = location_hotspot_from_payload(
            {
                "top_location": "Front Left",
                "ambiguous_location": True,
                "ambiguous_locations": ["Front Left", "Front Right"],
            }
        )
        assert hotspot.strongest_location == "Front Left"
        assert hotspot.ambiguous is True
        assert hotspot.alternative_locations == ("Front Left", "Front Right")
        assert not hotspot.is_actionable
        assert not hotspot.is_well_localized

    @pytest.mark.parametrize(
        ("location_count", "expected"),
        [
            pytest.param(None, LocationHotspot.WEAK_SPATIAL_BASELINE, id="none-count"),
            pytest.param(2, LocationHotspot.WEAK_SPATIAL_BASELINE, id="two-locations"),
            pytest.param(1, LocationHotspot.WEAK_SPATIAL_BASELINE, id="one-location-clamped"),
            pytest.param(0, LocationHotspot.WEAK_SPATIAL_BASELINE, id="zero-location-clamped"),
            pytest.param(
                3,
                LocationHotspot.WEAK_SPATIAL_BASELINE * 1.1,
                id="three-locations-scaled",
            ),
            pytest.param(
                4,
                LocationHotspot.WEAK_SPATIAL_BASELINE * 1.2,
                id="four-locations-scaled",
            ),
        ],
    )
    def test_weak_spatial_threshold_cases(
        self,
        location_count: int | None,
        expected: float,
    ) -> None:
        assert LocationHotspot.weak_spatial_threshold(location_count) == pytest.approx(
            expected,
            rel=1e-6,
        )

    def test_weak_spatial_threshold_monotonically_increasing(self) -> None:
        thresholds = [LocationHotspot.weak_spatial_threshold(n) for n in range(2, 8)]
        for low, high in zip(thresholds, thresholds[1:], strict=False):
            assert high > low

    def test_from_analysis_inputs_full(self) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            dominance_ratio=2.5,
            localization_confidence=0.8,
            weak_spatial_separation=False,
            ambiguous=False,
            alternative_locations=["front_right"],
        )
        assert hotspot.strongest_location == "front_left"
        assert hotspot.dominance_ratio == pytest.approx(2.5)
        assert hotspot.localization_confidence == pytest.approx(0.8)
        assert hotspot.alternative_locations == ("front_right",)

    def test_from_analysis_inputs_defaults(self) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(strongest_location="rear_left")
        assert hotspot.strongest_location == "rear_left"
        assert hotspot.dominance_ratio is None
        assert hotspot.localization_confidence is None
        assert hotspot.alternative_locations == ()

    def test_from_analysis_inputs_filters_empty_alternatives(self) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(
            strongest_location="rear_right",
            alternative_locations=["rear_left", "", "front_left"],
        )
        assert hotspot.alternative_locations == ("rear_left", "front_left")

    def test_from_analysis_inputs_matches_direct_construction(self) -> None:
        direct = LocationHotspot(
            strongest_location="rear_right",
            dominance_ratio=1.8,
            localization_confidence=0.6,
            weak_spatial_separation=False,
            ambiguous=False,
            alternative_locations=("rear_left",),
        )
        via_factory = LocationHotspot.from_analysis_inputs(
            strongest_location="rear_right",
            dominance_ratio=1.8,
            localization_confidence=0.6,
            weak_spatial_separation=False,
            ambiguous=False,
            alternative_locations=["rear_left"],
        )
        assert via_factory == direct

    def test_from_analysis_inputs_near_tie_is_domain_owned(self) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            dominance_ratio=1.05,
            localization_confidence=0.35,
            weak_spatial_separation=True,
            ambiguous=True,
            alternative_locations=["front_right"],
        )
        assert hotspot.strongest_location == "front_left"
        assert hotspot.ambiguous is True
        assert hotspot.alternative_locations == ("front_right",)
        assert not hotspot.is_actionable
        assert not hotspot.is_well_localized

    def test_from_analysis_inputs_actionable_when_clear_and_known(self) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(
            strongest_location="rear_left",
            dominance_ratio=2.0,
            localization_confidence=0.9,
            weak_spatial_separation=False,
            ambiguous=False,
        )
        assert hotspot.is_actionable
        assert hotspot.is_well_localized


class TestVibrationOrigin:
    def test_from_analysis_inputs_preserves_typed_contract(self) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            ambiguous=True,
            alternative_locations=["front_right"],
        )
        origin = VibrationOrigin.from_analysis_inputs(
            suspected_source=Finding(suspected_source="wheel/tire").suspected_source,
            hotspot=hotspot,
            dominance_ratio=1.05,
            speed_band="80-90 km/h",
            dominant_phase="acceleration",
            reason="ranked from wheel order evidence",
        )
        assert origin.is_ambiguous is True
        assert origin.summary_location == "front_left / front_right"
        assert origin.alternative_locations == ("front_right",)
        assert origin.weak_spatial_separation is True

    def test_vibration_origin_from_payload_uses_boundary_decode(self) -> None:
        origin = vibration_origin_from_payload(
            {
                "suspected_source": "wheel/tire",
                "strongest_speed_band": "80-90 km/h",
                "dominant_phase": "acceleration",
                "evidence_summary": "payload rationale",
                "dominance_ratio": 1.1,
                "location_hotspot": {
                    "top_location": "rear_left",
                    "ambiguous_location": True,
                    "ambiguous_locations": ["rear_left", "rear_right"],
                },
            }
        )
        assert origin.summary_location == "rear_left / rear_right"
        assert origin.alternative_locations == ("rear_right",)
        assert origin.speed_band == "80-90 km/h"
        assert origin.reason == "payload rationale"

    def test_origin_payload_from_finding_projects_canonical_boundary_shape(self) -> None:
        finding = Finding(
            finding_id="F001",
            suspected_source="wheel/tire",
            strongest_location="front_left",
            strongest_speed_band="80-90 km/h",
            dominance_ratio=1.05,
            weak_spatial_separation=True,
            location=LocationHotspot.from_analysis_inputs(
                strongest_location="front_left",
                ambiguous=True,
                alternative_locations=["front_right"],
                dominance_ratio=1.05,
            ),
            origin=VibrationOrigin.from_analysis_inputs(
                suspected_source=Finding(suspected_source="wheel/tire").suspected_source,
                hotspot=LocationHotspot.from_analysis_inputs(
                    strongest_location="front_left",
                    ambiguous=True,
                    alternative_locations=["front_right"],
                    dominance_ratio=1.05,
                ),
                dominance_ratio=1.05,
                speed_band="80-90 km/h",
                dominant_phase="acceleration",
                reason="domain rationale",
            ),
        )
        payload = origin_payload_from_finding(finding)
        assert payload["location"] == "Front Left / Front Right"
        assert payload["alternative_locations"] == ["front_right"]
        assert payload["suspected_source"] == "wheel/tire"
        assert payload["speed_band"] == "80-90 km/h"
        assert payload["dominant_phase"] == "acceleration"
        assert payload["explanation"] == (
            "domain rationale; speed band 80-90 km/h; dominant phase acceleration"
        )

    def test_origin_payload_from_finding_returns_empty_when_no_origin(self) -> None:
        """When a Finding has no origin or location, pure serialization returns empty payload."""
        finding = Finding(finding_id="F002", suspected_source="unknown")
        payload = origin_payload_from_finding(finding)
        assert payload == {}

    def test_from_finding_returns_existing_origin(self) -> None:
        """from_finding() returns the finding's origin when already set."""
        existing_origin = VibrationOrigin.from_analysis_inputs(
            suspected_source=VibrationSource.WHEEL_TIRE,
            dominance_ratio=1.2,
            speed_band="80-90 km/h",
            reason="pre-existing",
        )
        finding = Finding(
            finding_id="F001",
            suspected_source="wheel/tire",
            origin=existing_origin,
        )
        result = VibrationOrigin.from_finding(finding)
        assert result is existing_origin

    def test_from_finding_constructs_from_location_hotspot(self) -> None:
        """from_finding() constructs origin from hotspot when no origin is set."""
        hotspot = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            ambiguous=False,
        )
        finding = Finding(
            finding_id="F002",
            suspected_source="wheel/tire",
            strongest_speed_band="80-90 km/h",
            dominance_ratio=1.3,
            location=hotspot,
        )
        result = VibrationOrigin.from_finding(finding)
        assert result is not None
        assert result.hotspot is hotspot
        assert result.suspected_source == VibrationSource.WHEEL_TIRE
        assert result.speed_band == "80-90 km/h"
        assert result.dominance_ratio == 1.3

    def test_from_finding_constructs_from_strongest_location(self) -> None:
        """from_finding() constructs minimal origin from strongest_location."""
        finding = Finding(
            finding_id="F003",
            suspected_source="engine",
            strongest_location="rear",
            strongest_speed_band="60-70 km/h",
            dominance_ratio=0.9,
        )
        result = VibrationOrigin.from_finding(finding)
        assert result is not None
        assert result.hotspot is None
        assert result.suspected_source == VibrationSource.ENGINE
        assert result.speed_band == "60-70 km/h"

    def test_from_finding_returns_none_when_no_data(self) -> None:
        """from_finding() returns None for a finding with no origin data."""
        finding = Finding(finding_id="F004", suspected_source="unknown")
        assert VibrationOrigin.from_finding(finding) is None

    def test_suspected_vibration_origin_is_boundary_type(self) -> None:
        """SuspectedVibrationOrigin is importable from boundaries, not analysis."""
        from vibesensor.shared.boundaries.summary_fields.origin import SuspectedVibrationOrigin

        origin: SuspectedVibrationOrigin = {
            "location": "front_left",
            "suspected_source": "wheel/tire",
        }
        assert origin["location"] == "front_left"
