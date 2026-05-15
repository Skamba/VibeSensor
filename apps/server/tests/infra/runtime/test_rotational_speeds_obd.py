from __future__ import annotations

import pytest

from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.infra.runtime.rotational_speeds import (
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
        analysis_settings=AnalysisSettingsSnapshot(**AnalysisSettingsSnapshot.DEFAULTS),
    )

    assert payload["wheel"]["mode"] == "calculated"
    assert payload["engine"]["mode"] == "measured"
    assert payload["engine"]["rpm"] == pytest.approx(2450.0)


def test_build_rotational_speeds_payload_rejects_bool_engine_rpm() -> None:
    payload = build_rotational_speeds_payload(
        basis_speed_source="obd2",
        speed_mps=15.0,
        measured_engine_rpm=True,
        analysis_settings=AnalysisSettingsSnapshot(**AnalysisSettingsSnapshot.DEFAULTS),
    )

    assert payload["engine"]["mode"] == "calculated"
    assert payload["engine"]["rpm"] is not None
