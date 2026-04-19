"""Tests for the primary domain objects: Car, Sensor, SensorPlacement, Run,
Measurement, SpeedSource, Finding, Report.

Validates that the simple domain names are properly defined, importable,
and carry the expected behavior.
"""

from __future__ import annotations

import pytest

from vibesensor.domain import (
    Car,
    Finding,
    Sensor,
    SensorPlacement,
    SpeedSource,
)
from vibesensor.shared.boundaries.reporting.document import Report
from vibesensor.shared.boundaries.summary_fields.finding import finding_from_payload


def _tire_aspects(**overrides: float) -> dict[str, float]:
    aspects = {"tire_width_mm": 225.0, "tire_aspect_pct": 45.0, "rim_in": 17.0}
    aspects.update(overrides)
    return aspects


@pytest.mark.parametrize(
    ("factory", "attribute", "new_value"),
    [
        pytest.param(
            lambda: SpeedSource(kind="manual", manual_speed_kmh=80.0),
            "kind",
            "gps",
            id="speed-source",
        ),
        pytest.param(
            lambda: SensorPlacement.from_code("trunk"),
            "code",
            "engine_bay",
            id="sensor-placement",
        ),
        pytest.param(
            lambda: Sensor(sensor_id="aabbccddeeff"),
            "name",
            "new",
            id="sensor",
        ),
        pytest.param(lambda: Car(), "name", "new", id="car"),
        pytest.param(lambda: Finding(finding_id="F001"), "finding_id", "F002", id="finding"),
        pytest.param(lambda: Report(run_id="abc"), "title", "new", id="report"),
    ],
)
def test_domain_objects_are_immutable(factory, attribute: str, new_value: object) -> None:
    obj = factory()

    with pytest.raises(AttributeError):
        setattr(obj, attribute, new_value)


@pytest.mark.parametrize(
    (
        "kwargs",
        "expected_label",
        "expected_is_gps",
        "expected_is_obd2",
        "expected_is_manual",
        "expected_is_live",
        "expected_effective_speed_kmh",
    ),
    [
        pytest.param({}, "GPS", True, False, False, True, None, id="default-gps"),
        pytest.param(
            {"kind": "obd2"},
            "OBD-II",
            False,
            True,
            False,
            True,
            None,
            id="obd2",
        ),
        pytest.param(
            {"kind": "manual", "manual_speed_kmh": 80.0},
            "Manual",
            False,
            False,
            True,
            False,
            80.0,
            id="manual",
        ),
    ],
)
def test_speed_source_modes(
    kwargs: dict[str, object],
    expected_label: str,
    expected_is_gps: bool,
    expected_is_obd2: bool,
    expected_is_manual: bool,
    expected_is_live: bool,
    expected_effective_speed_kmh: float | None,
) -> None:
    src = SpeedSource(**kwargs)

    assert src.label == expected_label
    assert src.is_gps is expected_is_gps
    assert src.is_obd2 is expected_is_obd2
    assert src.is_manual is expected_is_manual
    assert src.is_live is expected_is_live
    if expected_effective_speed_kmh is None:
        assert src.effective_speed_kmh is None
    else:
        assert src.effective_speed_kmh == pytest.approx(expected_effective_speed_kmh)


@pytest.mark.parametrize(
    "manual_speed_kmh",
    [
        pytest.param(0.0, id="zero"),
        pytest.param(-10.0, id="negative"),
    ],
)
def test_speed_source_rejects_zero_or_negative_manual_speed(manual_speed_kmh: float) -> None:
    with pytest.raises(ValueError, match="positive manual_speed_kmh"):
        SpeedSource(kind="manual", manual_speed_kmh=manual_speed_kmh)


@pytest.mark.parametrize(
    ("factory", "expected_code", "expected_label", "expected_display_name"),
    [
        pytest.param(
            lambda: SensorPlacement(code="engine_bay", label="Engine Bay"),
            "engine_bay",
            "Engine Bay",
            "Engine Bay",
            id="explicit-label",
        ),
        pytest.param(
            lambda: SensorPlacement.from_code("front_left_wheel"),
            "front_left_wheel",
            "Front Left Wheel",
            "Front Left Wheel",
            id="known-wheel-code",
        ),
        pytest.param(
            lambda: SensorPlacement.from_code("custom_mount"),
            "custom_mount",
            "Custom Mount",
            "Custom Mount",
            id="custom-fallback",
        ),
    ],
)
def test_sensor_placement_display_name_cases(
    factory,
    expected_code: str,
    expected_label: str,
    expected_display_name: str,
) -> None:
    placement = factory()

    assert placement.code == expected_code
    assert placement.label == expected_label
    assert placement.display_name == expected_display_name


@pytest.mark.parametrize(
    ("sensor", "expected_display_name", "expected_is_placed", "expected_location_code"),
    [
        pytest.param(
            Sensor(
                sensor_id="aabbccddeeff",
                name="FL",
                placement=SensorPlacement.from_code("front_left_wheel"),
            ),
            "FL",
            True,
            "front_left_wheel",
            id="named-and-placed",
        ),
        pytest.param(
            Sensor(
                sensor_id="112233445566",
                placement=SensorPlacement.from_code("rear_subframe"),
            ),
            "112233445566",
            True,
            "rear_subframe",
            id="unnamed-but-placed",
        ),
        pytest.param(
            Sensor(sensor_id="778899aabbcc", name="Cabin"),
            "Cabin",
            False,
            "",
            id="named-unplaced",
        ),
    ],
)
def test_sensor_derived_fields(
    sensor: Sensor,
    expected_display_name: str,
    expected_is_placed: bool,
    expected_location_code: str,
) -> None:
    assert sensor.display_name == expected_display_name
    assert sensor.is_placed is expected_is_placed
    assert sensor.location_code == expected_location_code


@pytest.mark.parametrize(
    (
        "car",
        "expected_name",
        "expected_car_type",
        "expected_display_name",
        "expected_tire_width_mm",
        "expected_tire_aspect_pct",
        "expected_rim_in",
    ),
    [
        pytest.param(
            Car(),
            "Unnamed Car",
            "sedan",
            "Unnamed Car (sedan)",
            None,
            None,
            None,
            id="defaults",
        ),
        pytest.param(
            Car(name="Track Tool", car_type="coupe"),
            "Track Tool",
            "coupe",
            "Track Tool (coupe)",
            None,
            None,
            None,
            id="custom-type",
        ),
        pytest.param(
            Car(name="Test", aspects=_tire_aspects()),
            "Test",
            "sedan",
            "Test (sedan)",
            225.0,
            45.0,
            17.0,
            id="tire-aspects",
        ),
    ],
)
def test_car_derived_properties(
    car: Car,
    expected_name: str,
    expected_car_type: str,
    expected_display_name: str,
    expected_tire_width_mm: float | None,
    expected_tire_aspect_pct: float | None,
    expected_rim_in: float | None,
) -> None:
    assert car.name == expected_name
    assert car.car_type == expected_car_type
    assert car.display_name == expected_display_name
    assert car.tire_width_mm == expected_tire_width_mm
    assert car.tire_aspect_pct == expected_tire_aspect_pct
    assert car.rim_in == expected_rim_in


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("tire_width_mm", id="width"),
        pytest.param("tire_aspect_pct", id="aspect"),
        pytest.param("rim_in", id="rim"),
    ],
)
def test_car_rejects_zero_tire_dimension(key: str) -> None:
    with pytest.raises(ValueError, match="positive finite"):
        Car(aspects={key: 0.0})


# ---------------------------------------------------------------------------
# Phase 3: Finding (domain object)
# ---------------------------------------------------------------------------


class TestFindingDomainObject:
    """Finding domain object (distinct from the TypedDict payload)."""

    @pytest.mark.parametrize(
        (
            "finding",
            "expected_is_diagnostic",
            "expected_is_reference",
            "expected_is_info",
            "expected_confidence_pct",
        ),
        [
            pytest.param(
                Finding(
                    finding_id="F001",
                    suspected_source="wheel/tire",
                    confidence=0.85,
                    severity="high",
                ),
                True,
                False,
                False,
                85,
                id="diagnostic-finding",
            ),
            pytest.param(
                Finding(finding_id="REF_SPEED"),
                False,
                True,
                False,
                None,
                id="reference-finding",
            ),
            pytest.param(
                Finding(finding_id="F010", severity="info"),
                False,
                False,
                True,
                None,
                id="informational-finding",
            ),
        ],
    )
    def test_finding_kind_cases(
        self,
        finding: Finding,
        expected_is_diagnostic: bool,
        expected_is_reference: bool,
        expected_is_info: bool,
        expected_confidence_pct: int | None,
    ) -> None:
        assert finding.is_diagnostic is expected_is_diagnostic
        assert finding.is_reference is expected_is_reference
        assert finding.is_informational is expected_is_info
        assert finding.confidence_pct == expected_confidence_pct

    def test_source_normalized(self) -> None:
        f = Finding(suspected_source=" Wheel/Tire ")
        assert f.source_normalized == "wheel/tire"

    def test_ref_prefix_override_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """When explicit kind overrides REF_ prefix, a warning is logged."""
        payload: dict[str, object] = {
            "finding_id": "REF_SPEED",
            "suspected_source": "engine",
            "finding_kind": "diagnostic",
        }
        f = finding_from_payload(payload)
        assert f.is_diagnostic  # explicit kind wins
        assert "REF_ prefix" in caplog.text

    def test_from_payload(self) -> None:
        payload: dict[str, object] = {
            "finding_id": "F001",
            "suspected_source": "wheel/tire",
            "confidence": 0.85,
            "frequency_hz": 42.5,
            "order": "1x",
            "severity": "high",
            "strongest_location": "FL",
            "strongest_speed_band": "80-100 km/h",
            "peak_classification": "harmonic",
            # Extra payload-only fields should be ignored
            "evidence_summary": "some evidence",
            "legacy_unused_field": [],
        }
        f = finding_from_payload(payload)
        assert f.finding_id == "F001"
        assert f.suspected_source == "wheel/tire"
        assert f.confidence == 0.85
        assert f.frequency_hz == 42.5
        assert f.order == "1x"
        assert f.severity == "high"
        assert f.strongest_location == "FL"
        assert f.strongest_speed_band == "80-100 km/h"
        assert f.peaks.classification == "harmonic"
        assert f.is_diagnostic
        assert f.confidence_pct == 85

    def test_from_payload_minimal(self) -> None:
        f = finding_from_payload({"finding_id": "F001", "suspected_source": "engine"})
        assert f.finding_id == "F001"
        assert f.suspected_source == "engine"
        assert f.confidence is None
        assert f.frequency_hz is None

    def test_from_payload_reference(self) -> None:
        f = finding_from_payload({"finding_id": "REF_SPEED", "suspected_source": ""})
        assert f.is_reference
        assert not f.is_diagnostic


# ---------------------------------------------------------------------------
# Phase 3: Report
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Bridge method integration tests
# ---------------------------------------------------------------------------


class TestBridgeMethods:
    """Config objects bridge to domain objects correctly."""

    def test_finding_payload_is_distinct_from_domain_finding(self) -> None:
        """FindingPayload is the analysis TypedDict; domain Finding is the dataclass."""
        from vibesensor.domain import Finding as DomainFinding
        from vibesensor.shared.types.history_analysis_contracts import FindingPayload

        # They must be distinct types — no name collision
        assert DomainFinding is not FindingPayload


# ---------------------------------------------------------------------------
# New enrichment tests
# ---------------------------------------------------------------------------


class TestFindingEnrichments:
    """Tests for enriched Finding domain object behaviour."""

    @pytest.mark.parametrize(
        ("confidence", "expected"),
        [
            pytest.param(0.75, 0.75, id="explicit-confidence"),
            pytest.param(None, 0.0, id="missing-confidence"),
        ],
    )
    def test_effective_confidence_cases(
        self,
        confidence: float | None,
        expected: float,
    ) -> None:
        finding = Finding(confidence=confidence)
        assert finding.effective_confidence == expected

    @pytest.mark.parametrize(
        ("finding", "expected"),
        [
            pytest.param(
                Finding(suspected_source="wheel/tire"),
                True,
                id="known-source",
            ),
            pytest.param(
                Finding(suspected_source="unknown"),
                False,
                id="placeholder-no-location",
            ),
            pytest.param(
                Finding(suspected_source="unknown", strongest_location="front_left_wheel"),
                True,
                id="placeholder-with-location",
            ),
            pytest.param(
                Finding(suspected_source="unknown_resonance"),
                False,
                id="unknown-resonance",
            ),
        ],
    )
    def test_is_actionable_cases(self, finding: Finding, expected: bool) -> None:
        assert finding.is_actionable is expected

    @pytest.mark.parametrize(
        ("finding", "expected"),
        [
            pytest.param(
                Finding(confidence=0.5, severity="diagnostic"),
                True,
                id="diagnostic",
            ),
            pytest.param(
                Finding(confidence=0.1, severity="diagnostic"),
                False,
                id="low-confidence",
            ),
            pytest.param(
                Finding(finding_id="REF_SPEED", confidence=0.9),
                False,
                id="reference",
            ),
            pytest.param(
                Finding(confidence=0.8, severity="info"),
                False,
                id="informational",
            ),
        ],
    )
    def test_should_surface_cases(self, finding: Finding, expected: bool) -> None:
        assert finding.should_surface is expected

    def test_rank_key_quantised(self) -> None:
        f1 = Finding(confidence=0.751, ranking_score=1.0)
        f2 = Finding(confidence=0.759, ranking_score=1.0)
        # Both should quantise to 0.76 (step=0.02)
        assert f1.rank_key == f2.rank_key

    def test_rank_key_different_scores(self) -> None:
        f1 = Finding(confidence=0.5, ranking_score=2.0)
        f2 = Finding(confidence=0.5, ranking_score=1.0)
        assert f1.rank_key > f2.rank_key

    @pytest.mark.parametrize(
        ("finding", "expected"),
        [
            pytest.param(
                Finding(confidence=0.8),
                pytest.approx(0.8 * 0.85),
                id="no-phase",
            ),
            pytest.param(
                Finding(confidence=0.8, cruise_fraction=1.0),
                pytest.approx(0.8 * 1.0),
                id="full-cruise",
            ),
        ],
    )
    def test_phase_adjusted_score_cases(self, finding: Finding, expected: float) -> None:
        assert finding.phase_adjusted_score == expected

    def test_is_stronger_than(self) -> None:
        f1 = Finding(confidence=0.8, ranking_score=1.0)
        f2 = Finding(confidence=0.5, ranking_score=1.0)
        assert f1.is_stronger_than(f2)
        assert not f2.is_stronger_than(f1)

    def test_with_id(self) -> None:
        f = Finding(finding_id="F001", suspected_source="engine", confidence=0.7)
        f2 = f.with_id("F002")
        assert f2.finding_id == "F002"
        assert f2.suspected_source == "engine"
        assert f2.confidence == 0.7
        assert f.finding_id == "F001"  # original unchanged

    def test_from_payload_extracts_evidence_fields(self) -> None:
        payload: dict[str, object] = {
            "finding_id": "F001",
            "suspected_source": "bearing",
            "ranking_score": 1.5,
            "dominance_ratio": 0.85,
            "diffuse_excitation": True,
            "weak_spatial_separation": True,
            "phase_evidence": {"cruise_fraction": 0.6},
        }
        f = finding_from_payload(payload)
        assert f.ranking_score == 1.5
        assert f.dominance_ratio == 0.85
        assert f.diffuse_excitation is True
        assert f.weak_spatial_separation is True
        assert f.cruise_fraction == pytest.approx(0.6)


class TestReportValidation:
    """Tests for Report __post_init__ validation."""

    def test_empty_run_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="run_id must be non-empty"):
            Report(run_id="")

    def test_negative_duration_rejected(self) -> None:
        with pytest.raises(ValueError, match="duration_s must be non-negative"):
            Report(run_id="r1", duration_s=-1.0)

    def test_zero_duration_allowed(self) -> None:
        r = Report(run_id="r1", duration_s=0.0)
        assert r.duration_s == 0.0


class TestRunEnrichments:
    """Tests for enriched Run domain object."""
