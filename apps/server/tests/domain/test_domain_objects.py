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

# ---------------------------------------------------------------------------
# Phase 1: SpeedSource
# ---------------------------------------------------------------------------


class TestSpeedSource:
    """Speed source value object."""

    def test_manual_speed_source(self) -> None:
        src = SpeedSource(kind="manual", manual_speed_kmh=80.0)
        assert src.is_manual
        assert not src.is_gps
        assert src.manual_speed_kmh == 80.0

    def test_frozen(self) -> None:
        src = SpeedSource()
        with pytest.raises(AttributeError):
            src.kind = "manual"

    def test_rejects_zero_manual_speed(self) -> None:
        with pytest.raises(ValueError, match="positive manual_speed_kmh"):
            SpeedSource(kind="manual", manual_speed_kmh=0.0)

    def test_rejects_negative_manual_speed(self) -> None:
        with pytest.raises(ValueError, match="positive manual_speed_kmh"):
            SpeedSource(kind="manual", manual_speed_kmh=-10.0)


# ---------------------------------------------------------------------------
# Phase 2: SensorPlacement
# ---------------------------------------------------------------------------


class TestSensorPlacement:
    """Sensor placement value object."""

    def test_non_wheel_location(self) -> None:
        p = SensorPlacement(code="engine_bay", label="Engine Bay")
        assert p.display_name == "Engine Bay"

    def test_frozen(self) -> None:
        p = SensorPlacement(code="trunk")
        with pytest.raises(AttributeError):
            p.code = "engine_bay"


# ---------------------------------------------------------------------------
# Phase 2: Sensor
# ---------------------------------------------------------------------------


class TestSensor:
    """Sensor domain object."""

    def test_sensor_with_placement(self) -> None:
        p = SensorPlacement(code="front_left_wheel", label="Front Left Wheel")
        s = Sensor(sensor_id="aabbccddeeff", name="FL", placement=p)
        assert s.is_placed
        assert s.location_code == "front_left_wheel"

    def test_frozen(self) -> None:
        s = Sensor(sensor_id="aabbccddeeff")
        with pytest.raises(AttributeError):
            s.name = "new"


# ---------------------------------------------------------------------------
# Phase 2: Car
# ---------------------------------------------------------------------------


class TestCar:
    """Car domain object."""

    def test_tire_aspects(self) -> None:
        car = Car(
            name="Test",
            aspects={"tire_width_mm": 225, "tire_aspect_pct": 45, "rim_in": 17},
        )
        assert car.tire_width_mm == 225
        assert car.tire_aspect_pct == 45
        assert car.rim_in == 17

    def test_missing_aspects(self) -> None:
        car = Car(name="Test")
        assert car.tire_width_mm is None
        assert car.tire_aspect_pct is None
        assert car.rim_in is None

    def test_frozen(self) -> None:
        car = Car()
        with pytest.raises(AttributeError):
            car.name = "new"

    def test_rejects_zero_tire_dimension(self) -> None:
        with pytest.raises(ValueError, match="positive finite"):
            Car(aspects={"tire_width_mm": 0.0})
        with pytest.raises(ValueError, match="positive finite"):
            Car(aspects={"tire_aspect_pct": 0.0})
        with pytest.raises(ValueError, match="positive finite"):
            Car(aspects={"rim_in": 0.0})


# ---------------------------------------------------------------------------
# Phase 3: Finding (domain object)
# ---------------------------------------------------------------------------


class TestFindingDomainObject:
    """Finding domain object (distinct from the TypedDict payload)."""

    def test_diagnostic_finding(self) -> None:
        f = Finding(
            finding_id="F001",
            suspected_source="wheel/tire",
            confidence=0.85,
            severity="high",
        )
        assert f.is_diagnostic
        assert not f.is_reference
        assert not f.is_informational
        assert f.confidence_pct == 85

    def test_reference_finding(self) -> None:
        f = Finding(finding_id="REF_SPEED")
        assert f.is_reference
        assert not f.is_diagnostic

    def test_informational_finding(self) -> None:
        f = Finding(finding_id="F010", severity="info")
        assert f.is_informational
        assert not f.is_diagnostic

    def test_source_normalized(self) -> None:
        f = Finding(suspected_source=" Wheel/Tire ")
        assert f.source_normalized == "wheel/tire"

    def test_frozen(self) -> None:
        f = Finding(finding_id="F001")
        with pytest.raises(AttributeError):
            f.finding_id = "F002"

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


class TestReport:
    """Report domain object."""

    def test_frozen(self) -> None:
        r = Report(run_id="abc")
        with pytest.raises(AttributeError):
            r.title = "new"


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

    def test_effective_confidence(self) -> None:
        f = Finding(confidence=0.75)
        assert f.effective_confidence == 0.75

    def test_effective_confidence_none(self) -> None:
        f = Finding(confidence=None)
        assert f.effective_confidence == 0.0

    def test_is_actionable_known_source(self) -> None:
        f = Finding(suspected_source="wheel/tire")
        assert f.is_actionable

    def test_is_actionable_placeholder_source_no_location(self) -> None:
        f = Finding(suspected_source="unknown")
        assert not f.is_actionable

    def test_is_actionable_placeholder_source_with_location(self) -> None:
        f = Finding(suspected_source="unknown", strongest_location="front_left_wheel")
        assert f.is_actionable

    def test_is_actionable_unknown_resonance(self) -> None:
        f = Finding(suspected_source="unknown_resonance")
        assert not f.is_actionable

    def test_should_surface_diagnostic(self) -> None:
        f = Finding(confidence=0.5, severity="diagnostic")
        assert f.should_surface

    def test_should_surface_low_confidence(self) -> None:
        f = Finding(confidence=0.1, severity="diagnostic")
        assert not f.should_surface

    def test_should_surface_reference(self) -> None:
        f = Finding(finding_id="REF_SPEED", confidence=0.9)
        assert not f.should_surface

    def test_should_surface_informational(self) -> None:
        f = Finding(confidence=0.8, severity="info")
        assert not f.should_surface

    def test_rank_key_quantised(self) -> None:
        f1 = Finding(confidence=0.751, ranking_score=1.0)
        f2 = Finding(confidence=0.759, ranking_score=1.0)
        # Both should quantise to 0.76 (step=0.02)
        assert f1.rank_key == f2.rank_key

    def test_rank_key_different_scores(self) -> None:
        f1 = Finding(confidence=0.5, ranking_score=2.0)
        f2 = Finding(confidence=0.5, ranking_score=1.0)
        assert f1.rank_key > f2.rank_key

    def test_phase_adjusted_score_no_phase(self) -> None:
        f = Finding(confidence=0.8)
        assert f.phase_adjusted_score == pytest.approx(0.8 * 0.85)

    def test_phase_adjusted_score_full_cruise(self) -> None:
        f = Finding(confidence=0.8, cruise_fraction=1.0)
        assert f.phase_adjusted_score == pytest.approx(0.8 * 1.0)

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


class TestSpeedSourceEnrichments:
    """Tests for enriched SpeedSource domain object."""

    def test_is_obd2(self) -> None:
        ss = SpeedSource(kind="obd2")
        assert ss.is_obd2
        assert not ss.is_gps
        assert not ss.is_manual

    def test_is_live(self) -> None:
        assert SpeedSource(kind="gps").is_live
        assert SpeedSource(kind="obd2").is_live
        assert not SpeedSource(kind="manual", manual_speed_kmh=1.0).is_live

    def test_effective_speed_manual(self) -> None:
        ss = SpeedSource(kind="manual", manual_speed_kmh=80.0)
        assert ss.effective_speed_kmh == 80.0

    def test_effective_speed_gps(self) -> None:
        ss = SpeedSource(kind="gps")
        assert ss.effective_speed_kmh is None
