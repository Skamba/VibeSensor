from __future__ import annotations

from vibesensor.adapters.persistence.car_library import (
    load_car_library,
    resolve_vehicle_configurations,
)
from vibesensor.adapters.persistence.vehicle_configurations import load_vehicle_configurations


def _entry_for(model: str) -> dict[str, object]:
    for entry in load_car_library():
        if entry["brand"] == "BMW" and entry["model"] == model:
            return entry
    raise AssertionError(f"BMW model not found: {model}")


def test_current_canonical_rows_classify_into_approximate_and_backlog_buckets() -> None:
    configs = {
        (
            config.model_name,
            config.variant_name,
            config.transmission_name,
        ): config.coverage_policy_classification
        for config in load_vehicle_configurations()
    }

    assert (
        configs[
            (
                "2 Series Active Tourer (F45, 2014-2021)",
                "220i",
                "7-speed Steptronic dual-clutch transmission",
            )
        ]
        == "approximate"
    )
    assert (
        configs[("3 Series (G20, 2019-2025)", "330i xDrive", "8-speed automatic (ZF 8HP)")]
        == "approximate"
    )
    assert (
        configs[("5 Series (G60, 2024-2026)", "i5 eDrive40", "Single-speed fixed gear (EV)")]
        == "approximate"
    )
    assert (
        configs[("A5 (B8, 2007-2016)", "2.0 TFSI", "7-speed S tronic (DL501)")]
        == "backlog_unverified"
    )


def test_derived_canonical_rows_remain_approximate_under_coverage_policy() -> None:
    configs = resolve_vehicle_configurations(
        _entry_for("3 Series (G20, 2019-2025)"),
        "330i",
    )

    assert len(configs) == 2
    assert {config.coverage_policy_classification for config in configs} == {"approximate"}
    assert {config.source_status for config in configs} == {"exact_row"}
