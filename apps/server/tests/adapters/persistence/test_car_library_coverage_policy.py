from __future__ import annotations

from vibesensor.adapters.persistence.car_library import (
    load_car_library,
    load_vehicle_configurations,
    resolve_vehicle_configurations,
)


def _entry_for(model: str) -> dict[str, object]:
    for entry in load_car_library():
        if entry["brand"] == "BMW" and entry["model"] == model:
            return entry
    raise AssertionError(f"BMW model not found: {model}")


def test_current_exact_rows_classify_into_approximate_and_backlog_buckets() -> None:
    configs = {
        (config.model_name, config.variant_name): config.coverage_policy_classification
        for config in load_vehicle_configurations()
    }

    assert configs[("2 Series Active Tourer (F45, 2014-2021)", "220i")] == "approximate"
    assert configs[("2 Series Active Tourer (F45, 2014-2021)", "225xe")] == "approximate"
    assert configs[("3 Series (G20, 2019-2025)", "330i xDrive")] == "approximate"
    assert configs[("5 Series (G60, 2024-2026)", "i5 eDrive40")] == "approximate"
    assert configs[("4 Series (G22, 2021-2026)", "420i")] == "backlog_unverified"


def test_compat_projection_rows_remain_approximate_under_coverage_policy() -> None:
    configs = resolve_vehicle_configurations(
        _entry_for("3 Series (G20, 2019-2025)"),
        "330i",
    )

    assert len(configs) == 2
    assert {config.coverage_policy_classification for config in configs} == {"approximate"}
