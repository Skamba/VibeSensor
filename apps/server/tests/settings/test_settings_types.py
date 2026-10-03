from __future__ import annotations

from vibesensor.settings.services import build_settings_services
from vibesensor.settings.settings_types import (
    analysis_settings_payload_from_mapping,
)


def test_analysis_settings_payload_projection_keeps_only_supported_keys() -> None:
    payload = analysis_settings_payload_from_mapping(
        {
            "tire_width_mm": 255.0,
            "rim_in": 19.0,
            "unsupported_key": 999.0,
        }
    )

    assert payload == {
        "tire_width_mm": 255.0,
        "rim_in": 19.0,
    }


def test_active_car_aspect_updates_are_clamped_and_reject_negative_uncertainty() -> None:
    services = build_settings_services()
    created = services.car_settings.add_car({"name": "Bounds"})
    services.car_settings.set_active_car(created.cars[0]["id"])
    before = services.analysis_settings.analysis_settings_snapshot()

    services.analysis_settings.update_active_car_aspects(
        {"tire_width_mm": 900.0, "rim_in": 5.0, "speed_uncertainty_pct": -1.0}
    )

    after = services.analysis_settings.analysis_settings_snapshot()
    assert after.tire_width_mm == 500.0
    assert after.rim_in == 10.0
    assert after.speed_uncertainty_pct == before.speed_uncertainty_pct


def test_uncertainty_only_updates_keep_the_order_reference_status() -> None:
    services = build_settings_services()
    created = services.car_settings.add_car({"name": "Status"})
    services.car_settings.set_active_car(created.cars[0]["id"])
    services.analysis_settings.update_active_car_aspects({"tire_width_mm": 255.0})
    before = services.car_settings.get_cars().cars[0].get("order_reference_status")

    services.analysis_settings.update_active_car_aspects({"speed_uncertainty_pct": 2.0})

    assert before is not None
    assert services.car_settings.get_cars().cars[0].get("order_reference_status") == before
