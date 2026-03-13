"""Tests for the primary domain objects: Car, Sensor, SensorPlacement, Run,
Measurement, SpeedSource, AnalysisWindow, Finding, Report.

Validates that the simple domain names are properly defined, importable,
and carry the expected behavior.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vibesensor.domain import (
    AnalysisWindow,
    Car,
    Finding,
    Measurement,
    Report,
    Run,
    Sensor,
    SensorPlacement,
    SpeedBand,
    SpeedSource,
)

_NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Phase 1: Primary aliases (Run, Measurement)
# ---------------------------------------------------------------------------


class TestRunAlias:
    """Run is the primary domain name for a diagnostic session."""

    def test_run_creates_valid_session(self) -> None:
        run = Run()
        assert run.status.value == "pending"
        run.start()
        assert run.status.value == "running"


class TestMeasurement:
    """Measurement domain object tests."""

    def test_measurement_creates_valid_sample(self) -> None:
        m = Measurement(x=0.1, y=0.2, z=0.3, timestamp=_NOW, sample_rate_hz=4096)
        assert m.x == pytest.approx(0.1)
        assert m.y == pytest.approx(0.2)
        assert m.z == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# Phase 1: SpeedSource
# ---------------------------------------------------------------------------


class TestSpeedSource:
    """Speed source value object."""

    def test_default_is_gps(self) -> None:
        src = SpeedSource()
        assert src.kind == "gps"
        assert src.is_gps
        assert not src.is_manual

    def test_manual_speed_source(self) -> None:
        src = SpeedSource(kind="manual", manual_speed_kmh=80.0)
        assert src.is_manual
        assert not src.is_gps
        assert src.manual_speed_kmh == 80.0

    def test_label(self) -> None:
        assert SpeedSource(kind="gps").label == "GPS"
        assert SpeedSource(kind="obd2").label == "OBD-II"
        assert SpeedSource(kind="manual", manual_speed_kmh=0.0).label == "Manual"

    def test_frozen(self) -> None:
        src = SpeedSource()
        with pytest.raises(AttributeError):
            src.kind = "manual"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Phase 2: SensorPlacement
# ---------------------------------------------------------------------------


class TestSensorPlacement:
    """Sensor placement value object."""

    def test_wheel_location(self) -> None:
        p = SensorPlacement(code="front_left_wheel", label="Front Left Wheel")
        assert p.is_wheel
        assert p.display_name == "Front Left Wheel"

    def test_non_wheel_location(self) -> None:
        p = SensorPlacement(code="engine_bay", label="Engine Bay")
        assert not p.is_wheel
        assert p.display_name == "Engine Bay"

    def test_display_name_fallback(self) -> None:
        p = SensorPlacement(code="rear_subframe")
        assert p.display_name == "Rear Subframe"

    def test_frozen(self) -> None:
        p = SensorPlacement(code="trunk")
        with pytest.raises(AttributeError):
            p.code = "engine_bay"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Phase 2: Sensor
# ---------------------------------------------------------------------------


class TestSensor:
    """Sensor domain object."""

    def test_basic_sensor(self) -> None:
        s = Sensor(sensor_id="aabbccddeeff", name="Sensor 1")
        assert s.display_name == "Sensor 1"
        assert not s.is_placed
        assert s.location_code == ""

    def test_sensor_with_placement(self) -> None:
        p = SensorPlacement(code="front_left_wheel", label="Front Left Wheel")
        s = Sensor(sensor_id="aabbccddeeff", name="FL", placement=p)
        assert s.is_placed
        assert s.location_code == "front_left_wheel"

    def test_display_name_fallback(self) -> None:
        s = Sensor(sensor_id="aabbccddeeff")
        assert s.display_name == "aabbccddeeff"

    def test_frozen(self) -> None:
        s = Sensor(sensor_id="aabbccddeeff")
        with pytest.raises(AttributeError):
            s.name = "new"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Phase 2: Car
# ---------------------------------------------------------------------------


class TestCar:
    """Car domain object."""

    def test_default_car(self) -> None:
        car = Car()
        assert car.name == "Unnamed Car"
        assert car.car_type == "sedan"
        assert car.display_name == "Unnamed Car (sedan)"

    def test_car_with_type(self) -> None:
        car = Car(name="BMW 3 Series", car_type="suv")
        assert car.display_name == "BMW 3 Series (suv)"

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
            car.name = "new"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Phase 3: AnalysisWindow
# ---------------------------------------------------------------------------


class TestAnalysisWindow:
    """Analysis window value object."""

    def test_sample_count(self) -> None:
        w = AnalysisWindow(start_idx=10, end_idx=50)
        assert w.sample_count == 40

    def test_duration(self) -> None:
        w = AnalysisWindow(start_idx=0, end_idx=100, start_time_s=0.0, end_time_s=5.0)
        assert w.duration_s == pytest.approx(5.0)

    def test_duration_none_when_missing(self) -> None:
        w = AnalysisWindow(start_idx=0, end_idx=100)
        assert w.duration_s is None

    def test_phase_context(self) -> None:
        w = AnalysisWindow(
            start_idx=0,
            end_idx=50,
            phase="cruise",
            speed_min_kmh=80.0,
            speed_max_kmh=100.0,
        )
        assert w.phase == "cruise"
        assert w.speed_min_kmh == 80.0
        assert w.speed_max_kmh == 100.0

    def test_frozen(self) -> None:
        w = AnalysisWindow(start_idx=0, end_idx=10)
        with pytest.raises(AttributeError):
            w.start_idx = 5  # type: ignore[misc]


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

    def test_confidence_pct_none(self) -> None:
        f = Finding()
        assert f.confidence_pct is None

    def test_frozen(self) -> None:
        f = Finding(finding_id="F001")
        with pytest.raises(AttributeError):
            f.finding_id = "F002"  # type: ignore[misc]

    def test_from_payload(self) -> None:
        payload: dict[str, object] = {
            "finding_id": "F001",
            "suspected_source": "wheel/tire",
            "confidence": 0.85,
            "frequency_hz_or_order": 42.5,
            "order": "1x",
            "severity": "high",
            "strongest_location": "FL",
            "strongest_speed_band": "80-100 km/h",
            "peak_classification": "harmonic",
            # Extra payload-only fields should be ignored
            "evidence_summary": "some evidence",
            "quick_checks": [],
        }
        f = Finding.from_payload(payload)
        assert f.finding_id == "F001"
        assert f.suspected_source == "wheel/tire"
        assert f.confidence == 0.85
        assert f.frequency_hz == 42.5
        assert f.order == "1x"
        assert f.severity == "high"
        assert f.strongest_location == "FL"
        assert f.strongest_speed_band == SpeedBand(low_kmh=80, high_kmh=100)
        assert f.peak_classification == "harmonic"
        assert f.is_diagnostic
        assert f.confidence_pct == 85

    def test_from_payload_minimal(self) -> None:
        f = Finding.from_payload({"finding_id": "F001", "suspected_source": "engine"})
        assert f.finding_id == "F001"
        assert f.suspected_source == "engine"
        assert f.confidence is None
        assert f.frequency_hz is None

    def test_from_payload_reference(self) -> None:
        f = Finding.from_payload({"finding_id": "REF_SPEED", "suspected_source": ""})
        assert f.is_reference
        assert not f.is_diagnostic


# ---------------------------------------------------------------------------
# Phase 3: Report
# ---------------------------------------------------------------------------


class TestReport:
    """Report domain object."""

    def test_basic_report(self) -> None:
        r = Report(
            run_id="abc123",
            title="Diagnostic Report",
            lang="en",
            car_name="BMW 3 Series",
        )
        assert r.run_id == "abc123"
        assert r.lang == "en"
        assert r.car_name == "BMW 3 Series"

    def test_frozen(self) -> None:
        r = Report(run_id="abc")
        with pytest.raises(AttributeError):
            r.title = "new"  # type: ignore[misc]

    def test_from_summary(self) -> None:
        summary: dict[str, object] = {
            "run_id": "run-123",
            "lang": "de",
            "rows": 500,
            "duration_s": 125.0,
            "report_date": "2025-01-15",
            "sensor_count_used": 3,
            "findings": [
                {"finding_id": "F001", "suspected_source": "bearing"},
                {"finding_id": "F002", "suspected_source": "tire"},
            ],
            "metadata": {"car": {"name": "BMW 3", "car_type": "sedan"}},
        }
        r = Report.from_summary(summary)
        assert r.run_id == "run-123"
        assert r.lang == "de"
        assert r.sample_count == 500
        assert r.sensor_count == 3
        assert r.finding_count == 2
        assert r.car_name == "BMW 3"
        assert r.car_type == "sedan"
        assert r.report_date == "2025-01-15"
        assert r.duration_s == 125.0

    def test_from_summary_minimal(self) -> None:
        r = Report.from_summary({"run_id": "r1"})
        assert r.run_id == "r1"
        assert r.finding_count == 0
        assert r.sample_count == 0
        assert r.car_name is None

    def test_from_summary_short_duration(self) -> None:
        r = Report.from_summary({"run_id": "r1", "duration_s": 45.0})
        assert r.duration_s == 45.0


# ---------------------------------------------------------------------------
# Package-level imports
# ---------------------------------------------------------------------------


class TestPackageImports:
    """All primary domain objects must be importable from vibesensor.domain."""

    def test_all_ten_importable(self) -> None:
        from vibesensor.domain import (
            AnalysisWindow,
            Car,
            Finding,
            Measurement,
            Report,
            Run,
            Sensor,
            SensorPlacement,
            SpeedSource,
        )

        # Verify they are the expected types
        assert Run is not None
        assert Measurement is not None
        assert Car is not None
        assert Sensor is not None
        assert SensorPlacement is not None
        assert SpeedSource is not None
        assert AnalysisWindow is not None
        assert Finding is not None
        assert Report is not None


# ---------------------------------------------------------------------------
# Bridge method integration tests
# ---------------------------------------------------------------------------


class TestBridgeMethods:
    """Config objects bridge to domain objects correctly."""

    def test_car_config_to_car(self) -> None:
        from vibesensor.backend_types import CarConfig

        cfg = CarConfig(
            id="abc",
            name="BMW",
            car_type="suv",
            aspects={"rim_in": 19.0},
            variant="M3",
        )
        car = cfg.to_car()
        assert isinstance(car, Car)
        assert car.id == "abc"
        assert car.name == "BMW"
        assert car.car_type == "suv"
        assert car.rim_in == 19.0
        assert car.variant == "M3"
        assert car.display_name == "BMW (suv)"

    def test_sensor_config_to_sensor(self) -> None:
        from vibesensor.backend_types import SensorConfig

        cfg = SensorConfig(sensor_id="aabb", name="FL", location_code="front_left_wheel")
        sensor = cfg.to_sensor()
        assert isinstance(sensor, Sensor)
        assert sensor.sensor_id == "aabb"
        assert sensor.display_name == "FL"
        assert sensor.is_placed
        assert sensor.placement is not None
        assert sensor.placement.is_wheel
        assert sensor.placement.display_name == "Front Left Wheel"

    def test_sensor_config_to_sensor_empty_location(self) -> None:
        from vibesensor.backend_types import SensorConfig

        cfg = SensorConfig(sensor_id="aabb", name="Test", location_code="")
        sensor = cfg.to_sensor()
        assert not sensor.is_placed
        assert sensor.placement is None

    def test_speed_source_config_to_speed_source(self) -> None:
        from vibesensor.backend_types import SpeedSourceConfig

        cfg = SpeedSourceConfig.default()
        speed = cfg.to_speed_source()
        assert isinstance(speed, SpeedSource)
        assert speed.is_gps
        assert speed.label == "GPS"

    def test_sensor_placement_from_code(self) -> None:
        p = SensorPlacement.from_code("engine_bay")
        assert p.code == "engine_bay"
        assert p.label == "Engine Bay"
        assert not p.is_wheel

    def test_sensor_placement_from_code_unknown(self) -> None:
        p = SensorPlacement.from_code("custom_spot")
        assert p.code == "custom_spot"
        assert p.label == "Custom Spot"

    def test_phase_segment_to_analysis_window(self) -> None:
        from vibesensor.analysis.phase_segmentation import DrivingPhase, PhaseSegment

        seg = PhaseSegment(
            phase=DrivingPhase.CRUISE,
            start_idx=10,
            end_idx=50,
            start_t_s=1.0,
            end_t_s=5.0,
            speed_min_kmh=80.0,
            speed_max_kmh=100.0,
            sample_count=40,
        )
        aw = seg.to_analysis_window()
        assert isinstance(aw, AnalysisWindow)
        assert aw.phase == "cruise"
        assert aw.sample_count == 40
        assert aw.duration_s == pytest.approx(4.0)
        assert aw.speed_min_kmh == 80.0
        assert aw.speed_max_kmh == 100.0

    def test_settings_store_domain_accessors(self) -> None:
        from vibesensor.settings_store import SettingsStore

        store = SettingsStore()
        assert store.speed_source().is_gps
        assert store.active_car() is None
        assert store.sensors() == []

    def test_finding_payload_is_distinct_from_domain_finding(self) -> None:
        """FindingPayload is the analysis TypedDict; domain Finding is the dataclass."""
        from vibesensor.analysis._types import FindingPayload
        from vibesensor.domain import Finding as DomainFinding

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
        f = Finding(confidence=0.8, phase_evidence={"cruise_fraction": 1.0})
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
        f = Finding.from_payload(payload)
        assert f.ranking_score == 1.5
        assert f.dominance_ratio == 0.85
        assert f.diffuse_excitation is True
        assert f.weak_spatial_separation is True
        assert f.phase_evidence is not None
        assert f.phase_evidence.cruise_fraction == pytest.approx(0.6)


class TestAnalysisWindowEnrichments:
    """Tests for enriched AnalysisWindow domain object."""

    def test_is_cruising(self) -> None:
        aw = AnalysisWindow(start_idx=0, end_idx=100, phase="cruise")
        assert aw.is_cruising
        assert not aw.is_idle
        assert not aw.is_acceleration

    def test_is_idle(self) -> None:
        aw = AnalysisWindow(start_idx=0, end_idx=100, phase="idle")
        assert aw.is_idle
        assert not aw.is_cruising

    def test_is_acceleration(self) -> None:
        aw = AnalysisWindow(start_idx=0, end_idx=100, phase="acceleration")
        assert aw.is_acceleration

    def test_is_deceleration(self) -> None:
        aw = AnalysisWindow(start_idx=0, end_idx=100, phase="deceleration")
        assert aw.is_deceleration

    def test_is_analyzable(self) -> None:
        assert AnalysisWindow(start_idx=0, end_idx=100).is_analyzable
        assert not AnalysisWindow(start_idx=0, end_idx=0).is_analyzable

    def test_contains_speed(self) -> None:
        aw = AnalysisWindow(start_idx=0, end_idx=100, speed_min_kmh=80.0, speed_max_kmh=100.0)
        assert aw.contains_speed(90.0)
        assert aw.contains_speed(80.0)  # boundary
        assert aw.contains_speed(100.0)  # boundary
        assert not aw.contains_speed(120.0)
        assert not aw.contains_speed(60.0)

    def test_contains_speed_missing(self) -> None:
        aw = AnalysisWindow(start_idx=0, end_idx=100)
        assert not aw.contains_speed(90.0)

    def test_speed_range_text(self) -> None:
        aw = AnalysisWindow(start_idx=0, end_idx=100, speed_min_kmh=80.0, speed_max_kmh=100.0)
        assert aw.speed_range_text == "80\u2013100 km/h"

    def test_speed_range_text_missing(self) -> None:
        aw = AnalysisWindow(start_idx=0, end_idx=100)
        assert aw.speed_range_text is None


class TestReportEnrichments:
    """Tests for enriched Report domain object."""

    def test_has_findings(self) -> None:
        r = Report(run_id="r1", findings=(Finding(finding_id="F001"),))
        assert r.has_findings

    def test_no_findings(self) -> None:
        r = Report(run_id="r1")
        assert not r.has_findings
        assert r.is_empty

    def test_diagnostic_findings(self) -> None:
        findings = (
            Finding(finding_id="F001", severity="diagnostic"),
            Finding(finding_id="REF_SPEED", severity="info"),
            Finding(finding_id="F002", severity="high"),
        )
        r = Report(run_id="r1", findings=findings)
        diags = r.diagnostic_findings
        assert len(diags) == 2
        assert diags[0].finding_id == "F001"
        assert diags[1].finding_id == "F002"

    def test_primary_finding(self) -> None:
        findings = (
            Finding(finding_id="F001", severity="diagnostic"),
            Finding(finding_id="F002", severity="diagnostic"),
        )
        r = Report(run_id="r1", findings=findings)
        assert r.primary_finding is not None
        assert r.primary_finding.finding_id == "F001"

    def test_primary_finding_none(self) -> None:
        r = Report(run_id="r1", findings=(Finding(finding_id="REF_SPEED"),))
        assert r.primary_finding is None
        assert r.is_empty

    def test_from_summary_creates_domain_findings(self) -> None:
        summary: dict[str, object] = {
            "run_id": "run-1",
            "findings": [
                {
                    "finding_id": "F001",
                    "suspected_source": "bearing",
                    "confidence": 0.8,
                },
                {
                    "finding_id": "REF_SPEED",
                    "suspected_source": "speed",
                    "confidence": None,
                },
            ],
        }
        r = Report.from_summary(summary)
        assert len(r.findings) == 2
        assert r.findings[0].finding_id == "F001"
        assert r.findings[0].confidence == 0.8
        assert r.findings[1].is_reference


class TestRunEnrichments:
    """Tests for enriched Run domain object."""

    def test_lifecycle_pending_to_running(self) -> None:
        run = Run()
        assert run.status.value == "pending"
        run.start()
        assert run.status.value == "running"


class TestCarEnrichments:
    """Tests for enriched Car domain object."""

    def test_tire_circumference_full_spec(self) -> None:
        car = Car(
            name="Test",
            aspects={"tire_width_mm": 205, "tire_aspect_pct": 55, "rim_in": 16},
        )
        circ = car.tire_circumference_m
        assert circ is not None
        # 205/55 R16: diameter ≈ 632mm → circumference ≈ 1.985m
        assert 1.9 < circ < 2.1

    def test_tire_circumference_missing_aspect(self) -> None:
        car = Car(name="Test", aspects={"tire_width_mm": 205})
        assert car.tire_circumference_m is None

    def test_tire_circumference_zero_value(self) -> None:
        car = Car(aspects={"tire_width_mm": 0, "tire_aspect_pct": 55, "rim_in": 16})
        assert car.tire_circumference_m is None

    def test_tire_circumference_no_aspects(self) -> None:
        car = Car(name="No Tires")
        assert car.tire_circumference_m is None


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
        assert not SpeedSource(kind="manual", manual_speed_kmh=0.0).is_live

    def test_effective_speed_manual(self) -> None:
        ss = SpeedSource(kind="manual", manual_speed_kmh=80.0)
        assert ss.effective_speed_kmh == 80.0

    def test_effective_speed_gps(self) -> None:
        ss = SpeedSource(kind="gps")
        assert ss.effective_speed_kmh is None


class TestSensorPlacementEnrichments:
    """Tests for enriched SensorPlacement domain object."""

    def test_is_drivetrain(self) -> None:
        sp = SensorPlacement(code="transmission")
        assert sp.is_drivetrain
        assert not sp.is_wheel
        assert not sp.is_body

    def test_is_body(self) -> None:
        sp = SensorPlacement(code="driver_seat")
        assert sp.is_body
        assert not sp.is_wheel
        assert not sp.is_drivetrain

    def test_position_category_wheel(self) -> None:
        assert SensorPlacement(code="front_left_wheel").position_category == "wheel"

    def test_position_category_drivetrain(self) -> None:
        assert SensorPlacement(code="transmission").position_category == "drivetrain"

    def test_position_category_body(self) -> None:
        assert SensorPlacement(code="driver_seat").position_category == "body"

    def test_position_category_other(self) -> None:
        assert SensorPlacement(code="custom_location").position_category == "other"
