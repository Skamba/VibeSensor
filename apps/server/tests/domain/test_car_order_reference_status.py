"""Focused tests for car order-reference provenance rules."""

from __future__ import annotations

from vibesensor.domain import CarOrderReferenceStatus


def test_requires_manual_confirmation_includes_tire_confidence() -> None:
    assert (
        CarOrderReferenceStatus(
            selection_source_status="exact_row",
            tire_dimensions_confidence="family_default",
            final_drive_ratio_confidence="official_exact",
            current_gear_ratio_confidence="official_exact",
            transmission_confidence="official_exact",
        ).requires_manual_confirmation
        is True
    )


def test_order_analysis_car_data_confidence_uses_relevant_scope_fields() -> None:
    status = CarOrderReferenceStatus(
        selection_source_status="exact_row",
        tire_dimensions_confidence="user_confirmed",
        final_drive_ratio_confidence="reputable_secondary_crosschecked",
        current_gear_ratio_confidence="family_default",
        transmission_confidence="official_exact",
    )

    wheel = status.order_analysis_car_data_confidence(ref_sources=("speed+tire",))
    driveline = status.order_analysis_car_data_confidence(ref_sources=("speed+tire+final_drive",))
    engine = status.order_analysis_car_data_confidence(ref_sources=("speed+engine",))
    direct_engine = status.order_analysis_car_data_confidence(ref_sources=("obd2",))

    assert wheel is not None
    assert wheel.scope == "tire"
    assert wheel.confidence == "user_confirmed"
    assert driveline is not None
    assert driveline.scope == "driveline"
    assert driveline.confidence == "reputable_secondary_crosschecked"
    assert engine is not None
    assert engine.scope == "engine_speed_derived"
    assert engine.confidence == "family_default"
    assert direct_engine is None
