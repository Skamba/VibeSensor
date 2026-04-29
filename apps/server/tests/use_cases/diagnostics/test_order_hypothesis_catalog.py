"""Focused regressions for shared whole-run order-hypothesis catalog helpers."""

from __future__ import annotations

from vibesensor.use_cases.diagnostics.orders._hypothesis_catalog import (
    order_hypotheses_by_key,
    order_hypothesis_path_compliance_by_key,
    ordered_order_hypothesis_keys,
)


def test_ordered_order_hypothesis_keys_preserves_catalog_order_and_unknown_tail() -> None:
    assert ordered_order_hypothesis_keys(
        ("engine_2x", "custom_b", "wheel_1x", "driveshaft_2x", "custom_a")
    ) == (
        "wheel_1x",
        "driveshaft_2x",
        "engine_2x",
        "custom_a",
        "custom_b",
    )


def test_order_hypothesis_catalog_helpers_follow_physics_catalog() -> None:
    hypotheses_by_key = order_hypotheses_by_key()
    path_compliance_by_key = order_hypothesis_path_compliance_by_key()

    assert hypotheses_by_key["wheel_1x"].order_label_base == "wheel"
    assert hypotheses_by_key["engine_2x"].order == 2
    assert path_compliance_by_key["wheel_1x"] == 1.5
    assert path_compliance_by_key["engine_1x"] == 1.0
