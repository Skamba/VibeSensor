from __future__ import annotations

from vibesensor.adapters.http.analysis_settings_request_codec import (
    analysis_settings_payload_from_request,
)
from vibesensor.adapters.http.models import AnalysisSettingsRequest


def test_analysis_settings_payload_from_request_omits_none_fields() -> None:
    payload = analysis_settings_payload_from_request(
        AnalysisSettingsRequest(
            tire_width_mm=255.0,
            speed_uncertainty_pct=2.5,
            gear_uncertainty_pct=1.5,
        )
    )

    assert payload == {
        "tire_width_mm": 255.0,
        "speed_uncertainty_pct": 2.5,
        "gear_uncertainty_pct": 1.5,
    }


def test_analysis_settings_payload_from_request_projects_all_supported_fields() -> None:
    payload = analysis_settings_payload_from_request(
        AnalysisSettingsRequest(
            tire_width_mm=255.0,
            tire_aspect_pct=40.0,
            rim_in=19.0,
            final_drive_ratio=3.73,
            current_gear_ratio=1.0,
            wheel_bandwidth_pct=12.0,
            driveshaft_bandwidth_pct=10.0,
            engine_bandwidth_pct=8.0,
            speed_uncertainty_pct=2.0,
            tire_diameter_uncertainty_pct=1.5,
            final_drive_uncertainty_pct=1.25,
            gear_uncertainty_pct=1.0,
            min_abs_band_hz=4.5,
            max_band_half_width_pct=25.0,
            tire_deflection_factor=0.92,
        )
    )

    assert payload == {
        "tire_width_mm": 255.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 19.0,
        "final_drive_ratio": 3.73,
        "current_gear_ratio": 1.0,
        "wheel_bandwidth_pct": 12.0,
        "driveshaft_bandwidth_pct": 10.0,
        "engine_bandwidth_pct": 8.0,
        "speed_uncertainty_pct": 2.0,
        "tire_diameter_uncertainty_pct": 1.5,
        "final_drive_uncertainty_pct": 1.25,
        "gear_uncertainty_pct": 1.0,
        "min_abs_band_hz": 4.5,
        "max_band_half_width_pct": 25.0,
        "tire_deflection_factor": 0.92,
    }
