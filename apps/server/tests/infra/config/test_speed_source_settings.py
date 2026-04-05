"""Focused tests for persisted speed-source settings."""

from __future__ import annotations

import pytest
from test_support.settings_services import build_settings_services

from vibesensor.shared.types.speed_source_config import _parse_manual_speed


def test_speed_source_settings_update_manual() -> None:
    services = build_settings_services()
    result = services.speed_source_settings.update_speed_source(
        {"speedSource": "manual", "manualSpeedKph": 80}
    )
    assert result["speedSource"] == "manual"
    assert result["manualSpeedKph"] == 80.0


def test_speed_source_settings_update_gps_clears_manual() -> None:
    services = build_settings_services()
    services.speed_source_settings.update_speed_source(
        {"speedSource": "manual", "manualSpeedKph": 80}
    )
    result = services.speed_source_settings.update_speed_source(
        {"speedSource": "gps", "manualSpeedKph": None}
    )
    assert result["speedSource"] == "gps"
    assert result["manualSpeedKph"] is None


def test_speed_source_settings_invalid_source_defaults_to_gps() -> None:
    services = build_settings_services()
    result = services.speed_source_settings.update_speed_source({"speedSource": "unknown"})
    assert result["speedSource"] == "gps"


def test_speed_source_settings_persists_obd_device_config() -> None:
    services = build_settings_services()
    result = services.speed_source_settings.update_speed_source(
        {
            "speedSource": "obd2",
            "obdDeviceMac": "00:04:3E:5A:4A:4D",
            "obdDeviceName": "OBDLink MX+ 80163",
        }
    )
    assert result["speedSource"] == "obd2"
    assert result["obdDeviceMac"] == "00043e5a4a4d"
    assert result["obdDeviceName"] == "OBDLink MX+ 80163"


def test_speed_source_settings_exposes_canonical_config_copy() -> None:
    services = build_settings_services()
    snapshot = services.speed_source_settings.speed_source_config()

    snapshot.speed_source = "manual"

    assert services.speed_source_settings.get_speed_source()["speedSource"] == "gps"


def test_speed_source_settings_persist_speed_source_replaces_runtime_config() -> None:
    services = build_settings_services()
    persisted = services.speed_source_settings.persist_speed_source(
        services.speed_source_settings.preview_speed_source_update(
            {
                "speedSource": "manual",
                "manualSpeedKph": 80,
                "staleTimeoutS": 17,
            }
        )
    )

    assert persisted.manual_source_selected is True
    assert persisted.manual_speed_kph == pytest.approx(80.0)
    assert services.speed_source_settings.get_speed_source()["staleTimeoutS"] == pytest.approx(17.0)


def test_speed_source_settings_update_keeps_boundary_payload_shape() -> None:
    services = build_settings_services()
    result = services.speed_source_settings.update_speed_source(
        {
            "speedSource": "obd2",
            "manualSpeedKph": 61,
            "staleTimeoutS": 14,
            "obdDeviceMac": "00043e5a4a4d",
            "obdDeviceName": "OBDLink MX+",
        }
    )

    assert result["speedSource"] == "obd2"
    assert result["manualSpeedKph"] == pytest.approx(61.0)
    assert result["obdDeviceMac"] == "00043e5a4a4d"
    assert result["obdDeviceName"] == "OBDLink MX+"


def test_parse_manual_speed_returns_none_for_invalid() -> None:
    assert _parse_manual_speed(None) is None
    assert _parse_manual_speed("not_a_number") is None
    assert _parse_manual_speed(-5) is None
    assert _parse_manual_speed(0) is None
    assert _parse_manual_speed(60) == 60.0
