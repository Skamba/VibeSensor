"""Focused tests for persisted car and active-car analysis settings."""

from __future__ import annotations

import pytest
from test_support.settings_services import build_settings_services

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.shared.types.car_config import car_from_persistence_dict, car_to_persistence_dict

DEFAULT_CAR_ASPECTS = AnalysisSettingsSnapshot.DEFAULTS


def test_validate_car_fills_defaults() -> None:
    car = car_to_persistence_dict(car_from_persistence_dict({}))
    assert car["name"] == "Unnamed Car"
    assert car["type"] == "sedan"
    assert car["id"]
    assert car["aspects"] == DEFAULT_CAR_ASPECTS


def test_validate_car_preserves_aspects() -> None:
    car = car_to_persistence_dict(car_from_persistence_dict({"aspects": {"tire_width_mm": 245.0}}))
    assert car["aspects"]["tire_width_mm"] == 245.0
    assert car["aspects"]["rim_in"] == DEFAULT_CAR_ASPECTS["rim_in"]


def test_validate_car_truncates_name() -> None:
    car = car_to_persistence_dict(car_from_persistence_dict({"name": "x" * 100}))
    assert len(car["name"]) <= 64


def test_car_settings_default_has_no_cars() -> None:
    services = build_settings_services()
    snapshot = services.car_settings.get_cars()
    assert snapshot.cars == []
    assert snapshot.active_car_id is None


def test_car_settings_add_and_delete_car() -> None:
    services = build_settings_services()
    services.car_settings.add_car({"name": "Track Car", "type": "coupe"})
    services.car_settings.add_car({"name": "Daily Car", "type": "sedan"})
    snapshot = services.car_settings.get_cars()
    assert len(snapshot.cars) == 2
    first_car = snapshot.cars[0]
    assert first_car["name"] == "Track Car"
    assert first_car["type"] == "coupe"

    services.car_settings.set_active_car(first_car["id"])
    services.car_settings.delete_car(first_car["id"])
    remaining = services.car_settings.get_cars()
    assert len(remaining.cars) == 1
    assert remaining.active_car_id == remaining.cars[0]["id"]


def test_car_settings_cannot_delete_last_car() -> None:
    services = build_settings_services()
    created = services.car_settings.add_car({"name": "Temporary"})
    car_id = created.cars[0]["id"]
    services.car_settings.set_active_car(car_id)
    with pytest.raises(ValueError, match="Cannot delete the last car"):
        services.car_settings.delete_car(car_id)


def test_car_settings_update_car_aspects() -> None:
    services = build_settings_services()
    created = services.car_settings.add_car({"name": "Aspect Car"})
    car_id = created.cars[0]["id"]
    services.car_settings.set_active_car(car_id)
    services.car_settings.update_car(car_id, {"aspects": {"tire_width_mm": 245.0}})
    aspects = services.car_settings.active_car_aspects() or {}
    assert aspects["tire_width_mm"] == 245.0
    assert aspects["rim_in"] == DEFAULT_CAR_ASPECTS["rim_in"]


def test_car_settings_update_car_decodes_order_reference_status_payload() -> None:
    services = build_settings_services()
    created = services.car_settings.add_car({"name": "Library Car"})
    car_id = created.cars[0]["id"]

    updated = services.car_settings.update_car(
        car_id,
        {
            "order_reference_status": {
                "selection_source_status": "compat_projection",
                "final_drive_ratio_confidence": "family_default",
                "current_gear_ratio_confidence": "family_default",
                "transmission_name": "8-speed automatic",
                "transmission_confidence": "family_default",
            }
        },
    )

    persisted = next(car for car in updated.cars if car["id"] == car_id)["order_reference_status"]
    assert persisted["selection_source_status"] == "compat_projection"
    assert persisted["requires_manual_confirmation"] is True
    assert persisted["transmission_name"] == "8-speed automatic"


def test_analysis_settings_update_marks_manual_ratio_overrides_user_confirmed() -> None:
    services = build_settings_services()
    created = services.car_settings.add_car(
        {
            "name": "Approximate",
            "order_reference_status": {
                "selection_source_status": "exact_row",
                "final_drive_ratio_confidence": "family_default",
                "current_gear_ratio_confidence": "family_default",
                "transmission_name": "8-speed automatic",
                "transmission_confidence": "official_exact",
            },
        }
    )
    car_id = created.cars[0]["id"]
    services.car_settings.set_active_car(car_id)

    services.analysis_settings.update_active_car_aspects(
        {"final_drive_ratio": 3.91, "current_gear_ratio": 0.82}
    )

    snapshot = services.car_settings.active_car_snapshot()
    assert snapshot is not None
    assert snapshot.order_reference_status is not None
    assert snapshot.order_reference_status.final_drive_ratio_confidence == "user_confirmed"
    assert snapshot.order_reference_status.current_gear_ratio_confidence == "user_confirmed"
    assert snapshot.order_reference_status.transmission_confidence == "official_exact"
    assert snapshot.order_reference_status.requires_manual_confirmation is False


def test_analysis_settings_update_active_car_aspects() -> None:
    services = build_settings_services()
    created = services.car_settings.add_car({"name": "Editable"})
    services.car_settings.set_active_car(created.cars[0]["id"])
    updated = services.analysis_settings.update_active_car_aspects(
        {"tire_width_mm": 255.0, "rim_in": 19.0}
    )
    assert updated["tire_width_mm"] == 255.0
    assert updated["rim_in"] == 19.0
    assert (services.car_settings.active_car_aspects() or {})["tire_width_mm"] == 255.0


def test_analysis_settings_update_without_selection_raises() -> None:
    services = build_settings_services()
    with pytest.raises(ValueError, match="No active car configured"):
        services.analysis_settings.update_active_car_aspects({"tire_width_mm": 255.0})


def test_car_settings_set_active_car() -> None:
    services = build_settings_services()
    services.car_settings.add_car({"name": "First Car"})
    services.car_settings.add_car({"name": "Second Car"})
    second_id = services.car_settings.get_cars().cars[1]["id"]
    services.car_settings.set_active_car(second_id)
    assert services.car_settings.get_cars().active_car_id == second_id


def test_car_settings_add_car_does_not_auto_select_active_car() -> None:
    services = build_settings_services()
    services.car_settings.add_car({"name": "Unselected Car"})
    assert services.car_settings.get_cars().active_car_id is None


def test_car_settings_set_active_car_unknown_raises() -> None:
    services = build_settings_services()
    with pytest.raises(ValueError, match="Unknown car id"):
        services.car_settings.set_active_car("nonexistent-id")


def test_car_settings_update_car_name_and_type() -> None:
    services = build_settings_services()
    cars = services.car_settings.add_car({"name": "Original"}).cars
    car_id = cars[0]["id"]
    result = services.car_settings.update_car(car_id, {"name": "Updated", "type": "SUV"})
    updated = next(car for car in result.cars if car["id"] == car_id)
    assert updated["name"] == "Updated"
    assert updated["type"] == "SUV"


def test_car_settings_update_car_unknown_raises() -> None:
    services = build_settings_services()
    with pytest.raises(ValueError, match="Unknown car id"):
        services.car_settings.update_car("nonexistent", {"name": "X"})


def test_car_settings_delete_selected_car_auto_selects_remaining() -> None:
    services = build_settings_services()
    services.car_settings.add_car({"name": "First"})
    added = services.car_settings.add_car({"name": "Second"})
    car_ids = [car["id"] for car in added.cars]
    services.car_settings.set_active_car(car_ids[1])
    result = services.car_settings.delete_car(car_ids[1])
    assert len(result.cars) == 1
    assert result.active_car_id == car_ids[0]


def test_car_settings_delete_car_unknown_raises() -> None:
    services = build_settings_services()
    services.car_settings.add_car({"name": "Extra"})
    with pytest.raises(ValueError, match="Unknown car id"):
        services.car_settings.delete_car("nonexistent")


def test_car_settings_active_car_aspects_no_active_car() -> None:
    services = build_settings_services()
    assert services.car_settings.active_car_aspects() is None


def test_car_settings_active_car_aspects_with_active_car() -> None:
    services = build_settings_services()
    result = services.car_settings.add_car({"name": "Test", "type": "sedan"})
    car_id = result.cars[0]["id"]
    services.car_settings.set_active_car(car_id)
    aspects = services.car_settings.active_car_aspects()
    assert aspects is not None
    assert isinstance(aspects, dict)
    assert aspects == DEFAULT_CAR_ASPECTS
