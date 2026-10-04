from __future__ import annotations

import pytest

from vibesensor.domain.vehicle_configuration import (
    VehicleDrivetrain,
    VehicleFieldConfidence,
    VehicleOrderAnalysisPolicy,
    VehicleOrderAnalysisPolicyOverride,
    apply_order_analysis_policy_override,
    derive_order_analysis_policy,
)


def test_derive_full_inputs_marks_all_kinds_feasible() -> None:
    policy = derive_order_analysis_policy(
        top_gear_ratio=0.7,
        top_gear_confidence="official_exact",
        final_drive_front=3.5,
        final_drive_front_confidence="family_default",
        final_drive_rear=3.5,
        final_drive_rear_confidence="family_default",
        drivetrain="AWD",
    )
    assert policy == VehicleOrderAnalysisPolicy(
        usable_for_engine_order=True,
        usable_for_driveshaft_order=True,
        usable_for_wheel_order=True,
        requires_manual_confirmation=True,
    )


@pytest.mark.parametrize(
    ("drivetrain", "front", "rear", "top_gear", "expected"),
    [
        # Only the driven final drive and the top gear count.
        ("FWD", "official_exact", "family_default", "official_derived", False),
        ("FWD", "unverified", "official_exact", "official_exact", True),
        ("RWD", "official_exact", "family_default", "official_exact", True),
        ("AWD", "family_default", "reputable_secondary_crosschecked", "official_exact", False),
        ("AWD", "official_exact", "official_exact", "family_default", True),
        ("RWD", "official_exact", "user_confirmed", "user_confirmed", False),
    ],
)
def test_derive_requires_confirmation_only_for_weak_ratios(
    drivetrain: VehicleDrivetrain,
    front: VehicleFieldConfidence,
    rear: VehicleFieldConfidence,
    top_gear: VehicleFieldConfidence,
    expected: bool,
) -> None:
    policy = derive_order_analysis_policy(
        top_gear_ratio=0.7,
        top_gear_confidence=top_gear,
        final_drive_front=3.5,
        final_drive_front_confidence=front,
        final_drive_rear=3.2,
        final_drive_rear_confidence=rear,
        drivetrain=drivetrain,
    )
    assert policy.requires_manual_confirmation is expected


def test_derive_missing_final_drive_is_not_a_weak_value() -> None:
    policy = derive_order_analysis_policy(
        top_gear_ratio=0.7,
        top_gear_confidence="official_exact",
        final_drive_front=None,
        final_drive_front_confidence=None,
        final_drive_rear=None,
        final_drive_rear_confidence=None,
        drivetrain="FWD",
    )
    assert policy.requires_manual_confirmation is False
    assert policy.usable_for_driveshaft_order is False


def test_derive_missing_top_gear_blocks_engine_order_only() -> None:
    policy = derive_order_analysis_policy(
        top_gear_ratio=None,
        top_gear_confidence="official_exact",
        final_drive_front=3.5,
        final_drive_front_confidence="official_exact",
        final_drive_rear=None,
        final_drive_rear_confidence="official_exact",
        drivetrain="FWD",
    )
    assert policy.usable_for_engine_order is False
    assert policy.usable_for_driveshaft_order is True
    assert policy.usable_for_wheel_order is True


def test_derive_fwd_uses_front_final_drive() -> None:
    policy = derive_order_analysis_policy(
        top_gear_ratio=0.7,
        top_gear_confidence="official_exact",
        final_drive_front=None,
        final_drive_front_confidence="official_exact",
        final_drive_rear=3.5,
        final_drive_rear_confidence="official_exact",
        drivetrain="FWD",
    )
    assert policy.usable_for_engine_order is False
    assert policy.usable_for_driveshaft_order is False


def test_derive_rwd_uses_rear_final_drive() -> None:
    policy = derive_order_analysis_policy(
        top_gear_ratio=0.7,
        top_gear_confidence="official_exact",
        final_drive_front=3.5,
        final_drive_front_confidence="official_exact",
        final_drive_rear=None,
        final_drive_rear_confidence="official_exact",
        drivetrain="RWD",
    )
    assert policy.usable_for_engine_order is False
    assert policy.usable_for_driveshaft_order is False


def test_derive_unknown_drivetrain_accepts_either_axle() -> None:
    policy = derive_order_analysis_policy(
        top_gear_ratio=0.7,
        top_gear_confidence="official_exact",
        final_drive_front=3.5,
        final_drive_front_confidence="official_exact",
        final_drive_rear=None,
        final_drive_rear_confidence="official_exact",
        drivetrain=None,
    )
    assert policy.usable_for_engine_order is True
    assert policy.usable_for_driveshaft_order is True


def test_apply_override_replaces_only_named_fields() -> None:
    derived = derive_order_analysis_policy(
        top_gear_ratio=0.7,
        top_gear_confidence="official_exact",
        final_drive_front=3.5,
        final_drive_front_confidence="family_default",
        final_drive_rear=3.5,
        final_drive_rear_confidence="family_default",
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
        top_gear_confidence="official_exact",
        final_drive_front=3.5,
        final_drive_front_confidence="family_default",
        final_drive_rear=3.5,
        final_drive_rear_confidence="family_default",
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
