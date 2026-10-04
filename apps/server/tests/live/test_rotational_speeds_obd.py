from __future__ import annotations

import pytest
from test_support.core import TEST_CAR_ASPECTS

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.live.rotational_speeds import (
    build_rotational_speeds_payload,
    rotational_basis_speed_source,
)


def test_rotational_basis_speed_source_prefers_manual_fallback_for_obd() -> None:
    assert (
        rotational_basis_speed_source(
            "obd2",
            gps_enabled=True,
            resolution_source="fallback_manual",
        )
        == "fallback_manual"
    )


def test_build_rotational_speeds_payload_uses_measured_obd_engine_rpm() -> None:
    payload = build_rotational_speeds_payload(
        basis_speed_source="obd2",
        speed_mps=15.0,
        measured_engine_rpm=2450.0,
        analysis_settings=AnalysisSettingsSnapshot(**TEST_CAR_ASPECTS),
    )

    assert payload["wheel"]["mode"] == "calculated"
    assert payload["engine"]["mode"] == "measured"
    assert payload["engine"]["rpm"] == pytest.approx(2450.0)


def test_build_rotational_speeds_payload_rejects_bool_engine_rpm() -> None:
    payload = build_rotational_speeds_payload(
        basis_speed_source="obd2",
        speed_mps=15.0,
        measured_engine_rpm=True,
        analysis_settings=AnalysisSettingsSnapshot(**TEST_CAR_ASPECTS),
    )

    assert payload["engine"]["mode"] == "calculated"
    assert payload["engine"]["rpm"] is not None


def test_build_rotational_speeds_payload_blanks_only_the_family_missing_a_reference() -> None:
    tire_only = {
        key: value
        for key, value in TEST_CAR_ASPECTS.items()
        if key not in {"final_drive_ratio", "current_gear_ratio"}
    }
    payload = build_rotational_speeds_payload(
        basis_speed_source="gps",
        speed_mps=15.0,
        analysis_settings=AnalysisSettingsSnapshot(**tire_only),
    )

    assert payload["wheel"]["rpm"] is not None
    assert payload["driveshaft"] == {
        "rpm": None,
        "mode": "calculated",
        "reason": "missing_reference",
    }
    assert payload["engine"]["reason"] == "missing_reference"
    assert [band["key"] for band in payload["order_bands"] or []] == ["wheel_1x", "wheel_2x"]
