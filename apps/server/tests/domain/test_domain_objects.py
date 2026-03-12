"""Tests for the primary domain objects: Car, Sensor, SensorPlacement, Run,
Measurement, SpeedSource, AnalysisWindow, Finding, Report, HistoryRecord.

Validates that the simple domain names are properly defined, importable,
and carry the expected behavior.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vibesensor.domain.core import (
    # Backward compatibility aliases
    AccelerationSample,
    AnalysisWindow,
    Car,
    DiagnosticSession,
    Finding,
    HistoryRecord,
    Measurement,
    Report,
    Run,
    Sensor,
    SensorPlacement,
    SpeedSource,
)

_NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Phase 1: Primary aliases (Run, Measurement)
# ---------------------------------------------------------------------------


class TestRunAlias:
    """Run is the primary domain name for DiagnosticSession."""

    def test_run_is_diagnostic_session(self) -> None:
        assert Run is DiagnosticSession

    def test_run_creates_valid_session(self) -> None:
        run = Run()
        assert run.status.value == "pending"
        run.start()
        assert run.status.value == "running"
        run.stop()
        assert run.status.value == "stopped"


class TestMeasurementAlias:
    """Measurement is the primary domain name for AccelerationSample."""

    def test_measurement_is_acceleration_sample(self) -> None:
        assert Measurement is AccelerationSample

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
        assert SpeedSource(kind="manual").label == "Manual"

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
        assert car.display_name == "Unnamed Car"

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
            suspected_source="wheel_bearing",
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
        f = Finding(suspected_source=" Wheel Bearing ")
        assert f.source_normalized == "wheel bearing"

    def test_confidence_pct_none(self) -> None:
        f = Finding()
        assert f.confidence_pct is None

    def test_frozen(self) -> None:
        f = Finding(finding_id="F001")
        with pytest.raises(AttributeError):
            f.finding_id = "F002"  # type: ignore[misc]


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


# ---------------------------------------------------------------------------
# Phase 3: HistoryRecord
# ---------------------------------------------------------------------------


class TestHistoryRecord:
    """HistoryRecord domain object."""

    def test_complete_record(self) -> None:
        rec = HistoryRecord(run_id="r1", status="complete", sample_count=500)
        assert rec.is_complete
        assert not rec.is_recording
        assert not rec.has_error
        assert rec.is_analyzable

    def test_recording_record(self) -> None:
        rec = HistoryRecord(run_id="r2", status="recording")
        assert rec.is_recording
        assert not rec.is_complete
        assert not rec.is_analyzable

    def test_error_record(self) -> None:
        rec = HistoryRecord(
            run_id="r3",
            status="error",
            sample_count=100,
            error_message="timeout",
        )
        assert rec.has_error
        assert rec.is_analyzable

    def test_error_record_no_samples(self) -> None:
        rec = HistoryRecord(run_id="r4", status="error", sample_count=0)
        assert not rec.is_analyzable

    def test_frozen(self) -> None:
        rec = HistoryRecord(run_id="r1")
        with pytest.raises(AttributeError):
            rec.status = "complete"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Package-level imports
# ---------------------------------------------------------------------------


class TestPackageImports:
    """All 10 domain objects must be importable from vibesensor.domain."""

    def test_all_ten_importable(self) -> None:
        from vibesensor.domain import (
            AnalysisWindow,
            Car,
            Finding,
            HistoryRecord,
            Measurement,
            Report,
            Run,
            Sensor,
            SensorPlacement,
            SpeedSource,
        )

        # Verify they are the expected types
        assert Run is DiagnosticSession
        assert Measurement is AccelerationSample
        assert Car is not None
        assert Sensor is not None
        assert SensorPlacement is not None
        assert SpeedSource is not None
        assert AnalysisWindow is not None
        assert Finding is not None
        assert Report is not None
        assert HistoryRecord is not None


# ---------------------------------------------------------------------------
# Bridge method integration tests
# ---------------------------------------------------------------------------


class TestBridgeMethods:
    """Config objects bridge to domain objects correctly."""

    def test_car_config_to_car(self) -> None:
        from vibesensor.domain_models import CarConfig

        cfg = CarConfig(id="abc", name="BMW", type="suv", aspects={"rim_in": 19.0}, variant="M3")
        car = cfg.to_car()
        assert isinstance(car, Car)
        assert car.id == "abc"
        assert car.name == "BMW"
        assert car.car_type == "suv"
        assert car.rim_in == 19.0
        assert car.variant == "M3"
        assert car.display_name == "BMW (suv)"

    def test_sensor_config_to_sensor(self) -> None:
        from vibesensor.domain_models import SensorConfig

        cfg = SensorConfig(sensor_id="aabb", name="FL", location="front_left_wheel")
        sensor = cfg.to_sensor()
        assert isinstance(sensor, Sensor)
        assert sensor.sensor_id == "aabb"
        assert sensor.display_name == "FL"
        assert sensor.is_placed
        assert sensor.placement is not None
        assert sensor.placement.is_wheel
        assert sensor.placement.display_name == "Front Left Wheel"

    def test_sensor_config_to_sensor_empty_location(self) -> None:
        from vibesensor.domain_models import SensorConfig

        cfg = SensorConfig(sensor_id="aabb", name="Test", location="")
        sensor = cfg.to_sensor()
        assert not sensor.is_placed
        assert sensor.placement is None

    def test_speed_source_config_to_speed_source(self) -> None:
        from vibesensor.domain_models import SpeedSourceConfig

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

    def test_finding_payload_alias(self) -> None:
        """FindingPayload is the analysis TypedDict; Finding alias still works."""
        from vibesensor.analysis._types import Finding as FindingAlias
        from vibesensor.analysis._types import FindingPayload

        assert FindingAlias is FindingPayload
