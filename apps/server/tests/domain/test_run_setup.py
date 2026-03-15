"""Tests for the RunSetup domain value object."""

from __future__ import annotations

import pytest

from vibesensor.domain import (
    ConfigurationSnapshot,
    RunSetup,
    Sensor,
    SpeedSource,
    SpeedSourceKind,
)


class TestRunSetupConstruction:
    def test_defaults(self) -> None:
        setup = RunSetup()
        assert setup.sensors == ()
        assert setup.speed_source == SpeedSource()
        assert setup.configuration_snapshot == ConfigurationSnapshot()

    def test_explicit_values(self) -> None:
        sensor = Sensor(sensor_id="AA:BB:CC:DD:EE:FF", name="front")
        speed = SpeedSource(kind=SpeedSourceKind.OBD2)
        config = ConfigurationSnapshot(sensor_model="MPU6050", raw_sample_rate_hz=500.0)

        setup = RunSetup(
            sensors=(sensor,),
            speed_source=speed,
            configuration_snapshot=config,
        )

        assert setup.sensors == (sensor,)
        assert setup.speed_source is speed
        assert setup.configuration_snapshot is config

    def test_fields_accessible(self) -> None:
        setup = RunSetup()
        assert setup.speed_source.kind is SpeedSourceKind.GPS
        assert setup.configuration_snapshot.sensor_model is None


class TestRunSetupImmutability:
    def test_frozen(self) -> None:
        setup = RunSetup()
        with pytest.raises(AttributeError):
            setup.sensors = (Sensor(sensor_id="AA:BB:CC:DD:EE:FF"),)  # type: ignore[misc]
