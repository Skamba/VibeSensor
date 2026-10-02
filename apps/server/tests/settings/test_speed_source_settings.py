"""Focused tests for persisted speed-source settings."""

from __future__ import annotations

import pytest

from vibesensor.settings.services import build_settings_services
from vibesensor.speed.speed_source_config import _parse_manual_speed

_MANUAL_80 = {"speedSource": "manual", "manualSpeedKph": 80}


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        pytest.param(
            [_MANUAL_80],
            {"speedSource": "manual", "manualSpeedKph": 80.0},
            id="manual",
        ),
        pytest.param(
            [_MANUAL_80, {"speedSource": "gps", "manualSpeedKph": None}],
            {"speedSource": "gps", "manualSpeedKph": None},
            id="gps-clears-manual",
        ),
        pytest.param(
            [{"speedSource": "unknown"}],
            {"speedSource": "gps"},
            id="invalid-source-defaults-to-gps",
        ),
        pytest.param(
            [
                {
                    "speedSource": "obd2",
                    "obdDeviceMac": "02:00:00:00:00:4D",
                    "obdDeviceName": "OBDLink MX+ 80163",
                }
            ],
            {
                "speedSource": "obd2",
                "obdDeviceMac": "02000000004d",
                "obdDeviceName": "OBDLink MX+ 80163",
            },
            id="obd-device-config-normalized",
        ),
    ],
)
def test_speed_source_settings_update(
    updates: list[dict[str, object]], expected: dict[str, object]
) -> None:
    services = build_settings_services()
    for update in updates:
        result = services.speed_source_settings.update_speed_source(update)
    assert {key: result[key] for key in expected} == expected


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
            "obdDeviceMac": "02000000004d",
            "obdDeviceName": "OBDLink MX+",
        }
    )

    assert result["speedSource"] == "obd2"
    assert result["manualSpeedKph"] == pytest.approx(61.0)
    assert result["obdDeviceMac"] == "02000000004d"
    assert result["obdDeviceName"] == "OBDLink MX+"


def test_parse_manual_speed_returns_none_for_invalid() -> None:
    assert _parse_manual_speed(None) is None
    assert _parse_manual_speed("not_a_number") is None
    assert _parse_manual_speed(-5) is None
    assert _parse_manual_speed(0) is None
    assert _parse_manual_speed(60) == 60.0
