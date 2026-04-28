from __future__ import annotations

from vibesensor.domain import (
    TireSpec,
    VehicleConfiguration,
    VehicleFieldConfidence,
    VehicleFieldMetadata,
)


def _default_tire() -> TireSpec:
    tire = TireSpec.from_aspects(
        {
            "tire_width_mm": 225.0,
            "tire_aspect_pct": 45.0,
            "rim_in": 18.0,
        }
    )
    assert tire is not None
    return tire


def _metadata(confidence: VehicleFieldConfidence) -> VehicleFieldMetadata:
    evidence_refs = ("test:source",) if confidence not in {"family_default", "unverified"} else ()
    return VehicleFieldMetadata(confidence=confidence, evidence_refs=evidence_refs)


def _make_exact_configuration(
    *,
    final_drive_confidence: VehicleFieldConfidence = "official_exact",
    top_gear_confidence: VehicleFieldConfidence = "official_exact",
    transmission_confidence: VehicleFieldConfidence = "official_exact",
    drivetrain_confidence: VehicleFieldConfidence = "official_exact",
    tire_confidence: VehicleFieldConfidence = "official_exact",
) -> VehicleConfiguration:
    return VehicleConfiguration(
        brand="BMW",
        car_type="Sedan",
        model_name="3 Series (G20, 2019-2025)",
        variant_name="330i",
        drivetrain="RWD",
        transmission_name="8-speed automatic (ZF 8HP)",
        top_gear_ratio=0.67,
        default_tire=_default_tire(),
        tire_options=(),
        final_drive_rear=2.81,
        drivetrain_metadata=_metadata(drivetrain_confidence),
        tire_metadata=_metadata(tire_confidence),
        transmission_metadata=_metadata(transmission_confidence),
        top_gear_ratio_metadata=_metadata(top_gear_confidence),
        final_drive_rear_metadata=_metadata(final_drive_confidence),
    )


def test_exact_row_with_source_backed_critical_fields_is_research_complete() -> None:
    config = _make_exact_configuration(top_gear_confidence="reputable_secondary_crosschecked")

    assert config.coverage_policy_fields == (
        "drivetrain",
        "tire_dimensions",
        "transmission_name",
        "top_gear_ratio",
        "final_drive_rear",
    )
    assert config.research_completeness == "trusted"
    assert config.order_reference_trust == "trusted"
    assert config.order_reference_trust_for("wheel_order") == "trusted"
    assert config.order_reference_trust_for("driveshaft_order") == "trusted"
    assert config.order_reference_trust_for("engine_order") == "trusted"


def test_family_default_critical_field_marks_exact_row_approximate() -> None:
    config = _make_exact_configuration(top_gear_confidence="family_default")

    # research_completeness still includes top_gear_ratio
    assert config.research_completeness == "approximate"
    # engine_order trust depends on top_gear_ratio so it is approximate too
    assert config.order_reference_trust_for("engine_order") == "approximate"
    # wheel/driveshaft trust ignores top_gear_ratio
    assert config.order_reference_trust_for("wheel_order") == "trusted"
    assert config.order_reference_trust_for("driveshaft_order") == "trusted"


def test_unverified_critical_field_marks_exact_row_backlog_unverified() -> None:
    config = _make_exact_configuration(final_drive_confidence="unverified")

    assert config.research_completeness == "backlog_unverified"
    assert config.order_reference_trust_for("driveshaft_order") == "backlog_unverified"
    assert config.order_reference_trust_for("engine_order") == "backlog_unverified"
    # wheel order does not depend on the final drive
    assert config.order_reference_trust_for("wheel_order") == "trusted"


def test_weak_transmission_metadata_does_not_drop_order_reference_trust() -> None:
    """Issue #3272: non-math transmission_name must not block order-reference trust."""

    config = _make_exact_configuration(transmission_confidence="unverified")

    assert config.research_completeness == "backlog_unverified"
    # Math inputs are still strong, so trust stays "trusted"
    assert config.order_reference_trust == "trusted"
    assert config.order_reference_trust_for("engine_order") == "trusted"
    assert config.order_reference_trust_for("driveshaft_order") == "trusted"
    assert config.order_reference_trust_for("wheel_order") == "trusted"


def test_weak_drivetrain_label_does_not_drop_order_reference_trust() -> None:
    """drivetrain field is non-math metadata for trust purposes."""

    config = _make_exact_configuration(drivetrain_confidence="family_default")

    assert config.research_completeness == "approximate"
    assert config.order_reference_trust == "trusted"
