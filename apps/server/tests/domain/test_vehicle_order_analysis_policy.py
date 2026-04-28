from __future__ import annotations

import pytest

from vibesensor.domain import (
    VehicleOrderAnalysisPolicy,
    VehicleOrderAnalysisPolicyOverride,
    apply_order_analysis_policy_override,
    derive_order_analysis_policy,
)


def test_derive_full_inputs_marks_all_kinds_feasible() -> None:
    policy = derive_order_analysis_policy(
        top_gear_ratio=0.7,
        final_drive_front=3.5,
        final_drive_rear=3.5,
        drivetrain="AWD",
    )
    assert policy == VehicleOrderAnalysisPolicy(
        usable_for_engine_order=True,
        usable_for_driveshaft_order=True,
        usable_for_wheel_order=True,
        requires_manual_confirmation=True,
    )


def test_derive_missing_top_gear_blocks_engine_order_only() -> None:
    policy = derive_order_analysis_policy(
        top_gear_ratio=None,
        final_drive_front=3.5,
        final_drive_rear=None,
        drivetrain="FWD",
    )
    assert policy.usable_for_engine_order is False
    assert policy.usable_for_driveshaft_order is True
    assert policy.usable_for_wheel_order is True


def test_derive_fwd_uses_front_final_drive() -> None:
    policy = derive_order_analysis_policy(
        top_gear_ratio=0.7,
        final_drive_front=None,
        final_drive_rear=3.5,
        drivetrain="FWD",
    )
    assert policy.usable_for_engine_order is False
    assert policy.usable_for_driveshaft_order is False


def test_derive_rwd_uses_rear_final_drive() -> None:
    policy = derive_order_analysis_policy(
        top_gear_ratio=0.7,
        final_drive_front=3.5,
        final_drive_rear=None,
        drivetrain="RWD",
    )
    assert policy.usable_for_engine_order is False
    assert policy.usable_for_driveshaft_order is False


def test_derive_unknown_drivetrain_accepts_either_axle() -> None:
    policy = derive_order_analysis_policy(
        top_gear_ratio=0.7,
        final_drive_front=3.5,
        final_drive_rear=None,
        drivetrain=None,
    )
    assert policy.usable_for_engine_order is True
    assert policy.usable_for_driveshaft_order is True


def test_apply_override_replaces_only_named_fields() -> None:
    derived = derive_order_analysis_policy(
        top_gear_ratio=0.7,
        final_drive_front=3.5,
        final_drive_rear=3.5,
        drivetrain="AWD",
    )
    override = VehicleOrderAnalysisPolicyOverride(
        reason="row-known-not-tested-on-wheel-order",
        usable_for_wheel_order=False,
    )
    final = apply_order_analysis_policy_override(derived, override)
    assert final.usable_for_wheel_order is False
    assert final.usable_for_engine_order is True
    assert final.usable_for_driveshaft_order is True
    assert final.requires_manual_confirmation is True


def test_apply_override_none_returns_derived() -> None:
    derived = derive_order_analysis_policy(
        top_gear_ratio=0.7,
        final_drive_front=3.5,
        final_drive_rear=3.5,
        drivetrain="AWD",
    )
    assert apply_order_analysis_policy_override(derived, None) is derived


@pytest.mark.parametrize(
    "field,value",
    [
        ("usable_for_engine_order", False),
        ("usable_for_driveshaft_order", False),
        ("requires_manual_confirmation", False),
    ],
)
def test_each_override_field_independently_replaces(field: str, value: bool) -> None:
    derived = VehicleOrderAnalysisPolicy(
        usable_for_engine_order=True,
        usable_for_driveshaft_order=True,
        usable_for_wheel_order=True,
        requires_manual_confirmation=True,
    )
    override = VehicleOrderAnalysisPolicyOverride(reason="test", **{field: value})
    final = apply_order_analysis_policy_override(derived, override)
    assert getattr(final, field) is value
    for other in (
        "usable_for_engine_order",
        "usable_for_driveshaft_order",
        "usable_for_wheel_order",
        "requires_manual_confirmation",
    ):
        if other != field:
            assert getattr(final, other) is True
