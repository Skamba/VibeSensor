"""SensorConfig persistence codec."""

from __future__ import annotations

from vibesensor.settings.sensor_config import SensorConfig


def test_roundtrip_keeps_name_location_and_orientation() -> None:
    config = SensorConfig.from_dict(
        "id1", {"name": "Test", "location_code": "rear", "mount_orientation": "axial"}
    )
    assert config.sensor_id == "id1"
    assert config.to_dict() == {
        **config.to_dict(),
        "name": "Test",
        "location_code": "rear",
        "mount_orientation": "axial",
    }
    assert SensorConfig.from_dict("id1", config.to_dict()) == config


def test_missing_fields_default_to_the_sensor_id_and_no_location() -> None:
    config = SensorConfig.from_dict("abc123", {})
    assert config.name == "abc123"
    assert config.location_code == ""
    assert config.mount_orientation is None


def test_name_truncated_at_64() -> None:
    assert len(SensorConfig.from_dict("id", {"name": "X" * 100}).name) == 64
