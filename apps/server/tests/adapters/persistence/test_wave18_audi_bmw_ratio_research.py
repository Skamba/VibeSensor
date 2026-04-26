"""Focused regressions for the eighteenth Audi/BMW ratio-research wave."""

from __future__ import annotations

import pytest

from vibesensor.adapters.persistence.car_library import load_car_library, resolve_variant
from vibesensor.adapters.persistence.car_library_source_evidence import load_car_source_registry
from vibesensor.adapters.persistence.vehicle_configurations import load_vehicle_configurations
from vibesensor.domain import VehicleConfiguration


def _entry_for(brand: str, model: str) -> dict[str, object]:
    for entry in load_car_library():
        if entry["brand"] == brand and entry["model"] == model:
            return entry
    raise AssertionError(f"Car-library entry not found: {brand} / {model}")


def _config_for(brand: str, model: str, variant: str) -> VehicleConfiguration:
    for config in load_vehicle_configurations():
        if config.brand == brand and config.model_name == model and config.variant_name == variant:
            return config
    raise AssertionError(f"Vehicle configuration not found: {brand} / {model} / {variant}")


def test_wave18_m3_and_m4_top_gears_use_official_m_dct_and_manual_values() -> None:
    m3 = resolve_variant(_entry_for("BMW", "M3 (F80, 2014-2018)"), "M3")
    m4 = resolve_variant(_entry_for("BMW", "M4 (F82, 2014-2020)"), "M4")

    for row in (m3, m4):
        row_gearboxes = {gearbox["name"]: gearbox for gearbox in row["gearboxes"]}

        assert row_gearboxes["7-speed dual-clutch (M-DCT)"]["top_gear_ratio"] == pytest.approx(
            0.671
        )
        assert row_gearboxes["7-speed dual-clutch (M-DCT)"]["gear_ratios"] == pytest.approx(
            [4.806, 2.593, 1.701, 1.277, 1.0, 0.844, 0.671]
        )

        assert row_gearboxes["6-speed manual"]["top_gear_ratio"] == pytest.approx(0.846)
        assert row_gearboxes["6-speed manual"]["gear_ratios"] == pytest.approx(
            [4.11, 2.315, 1.542, 1.179, 1.0, 0.846]
        )


def test_wave18_m5_uses_official_8_speed_top_gear() -> None:
    m5 = _entry_for("BMW", "M5 (F90, 2018-2024)")
    gearbox = m5["gearboxes"][0]

    assert gearbox["name"] == "8-speed automatic (ZF 8HP)"
    assert gearbox["final_drive_ratio"] == pytest.approx(3.154)
    assert gearbox["top_gear_ratio"] == pytest.approx(0.64)
    assert gearbox["gear_ratios"] == pytest.approx([5.0, 3.2, 2.143, 1.72, 1.313, 1.0, 0.823, 0.64])


def test_wave18_g15_variant_overrides_capture_m850i_and_m8_drivetrain_scope() -> None:
    coupe = _entry_for("BMW", "8 Series Coupe (G15, 2019-2025)")

    m850i = resolve_variant(coupe, "M850i xDrive")
    assert len(m850i["gearboxes"]) == 1
    gearbox = m850i["gearboxes"][0]
    assert gearbox["name"] == "8-speed automatic (ZF 8HP76 Sport)"
    assert gearbox["final_drive_ratio"] == pytest.approx(2.813)
    assert gearbox["top_gear_ratio"] == pytest.approx(0.64)
    assert gearbox["gear_ratios"] == pytest.approx([5.5, 3.52, 2.2, 1.72, 1.317, 1.0, 0.823, 0.64])

    assert resolve_variant(coupe, "M8")["drivetrain"] == "AWD"
    assert resolve_variant(coupe, "M8 Competition")["drivetrain"] == "AWD"


def test_wave18_g15_canonical_rows_preserve_official_bmw_evidence() -> None:
    registry = load_car_source_registry().sources
    m850i_refs = {
        "legacy_research_sources:3bf1daddf136",
        "legacy_research_sources:b3655e5aa9ee",
    }
    m8_refs = {
        "legacy_research_sources:52e2ccf0b07d",
        "legacy_research_sources:f3fe62f03e97",
    }

    m850i = _config_for("BMW", "8 Series Coupe (G15, 2019-2025)", "M850i xDrive")
    assert m850i.drivetrain == "AWD"
    assert m850i.transmission_name == "8-speed automatic (ZF 8HP76 Sport)"
    assert m850i.top_gear_ratio == pytest.approx(0.64)
    assert m850i.gear_ratios == pytest.approx([5.5, 3.52, 2.2, 1.72, 1.317, 1.0, 0.823, 0.64])
    assert m850i.final_drive_front == pytest.approx(2.813)
    assert m850i.final_drive_rear == pytest.approx(2.813)
    assert m850i.drivetrain_metadata is not None
    assert m850i.transmission_metadata is not None
    assert m850i.top_gear_ratio_metadata is not None
    assert m850i.gear_ratios_metadata is not None
    assert set(m850i.drivetrain_metadata.evidence_refs) == m850i_refs
    assert set(m850i.transmission_metadata.evidence_refs) == m850i_refs
    assert set(m850i.top_gear_ratio_metadata.evidence_refs) == m850i_refs
    assert set(m850i.gear_ratios_metadata.evidence_refs) == m850i_refs
    assert m850i.top_gear_ratio_metadata.confidence == "official_exact"

    m8 = _config_for("BMW", "8 Series Coupe (G15, 2019-2025)", "M8")
    m8_competition = _config_for("BMW", "8 Series Coupe (G15, 2019-2025)", "M8 Competition")
    for config in (m8, m8_competition):
        assert config.drivetrain == "AWD"
        assert config.drivetrain_metadata is not None
        assert config.final_drive_front == pytest.approx(3.077)
        assert config.final_drive_rear == pytest.approx(3.077)
        assert config.drivetrain_metadata.confidence == "official_exact"
        assert set(config.drivetrain_metadata.evidence_refs) == m8_refs
        assert (
            "Wave 18 added official BMW G15 and M8 technical-data evidence proving"
            in config.verification_notes[0].note
        )
        unresolved_items = {issue.item for issue in config.unresolved}
        assert "BMW G15 M8 Coupe final-drive numeric mapping in row schema" in unresolved_items

    for ref in m850i_refs | m8_refs:
        assert ref in registry
