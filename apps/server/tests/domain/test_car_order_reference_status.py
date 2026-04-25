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
