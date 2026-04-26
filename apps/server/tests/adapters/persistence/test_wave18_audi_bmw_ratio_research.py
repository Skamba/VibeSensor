"""Focused regressions for the eighteenth Audi/BMW ratio-research wave."""

from __future__ import annotations

import json

import pytest

from vibesensor.adapters.persistence.car_library import _DATA_FILE, load_car_library, resolve_variant

_RATIO_SOURCES_FILE = _DATA_FILE.with_name("car_library_ratio_sources.json")
_VARIANT_SOURCES_FILE = _DATA_FILE.with_name("CAR_VARIANT_SOURCES.md")


def _entry_for(brand: str, model: str) -> dict[str, object]:
    for entry in load_car_library():
        if entry["brand"] == brand and entry["model"] == model:
            return entry
    raise AssertionError(f"Car-library entry not found: {brand} / {model}")


def _ratio_sources() -> dict[str, dict[str, object]]:
    with _RATIO_SOURCES_FILE.open(encoding="utf-8") as fh:
        return json.load(fh)["cars"]


def test_wave18_m3_and_m4_top_gears_use_official_m_dct_and_manual_values() -> None:
    m3 = _entry_for("BMW", "M3 (F80, 2014-2018)")
    m4 = _entry_for("BMW", "M4 (F82, 2014-2020)")

    for row in (m3, m4):
        row_gearboxes = {gearbox["name"]: gearbox for gearbox in row["gearboxes"]}

        assert row_gearboxes["7-speed dual-clutch (M-DCT)"]["top_gear_ratio"] == pytest.approx(0.671)
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
    assert m850i["gearboxes"] == [
        {
            "name": "8-speed automatic (ZF 8HP76 Sport)",
            "final_drive_ratio": pytest.approx(2.813),
            "top_gear_ratio": pytest.approx(0.64),
            "gear_ratios": pytest.approx([5.5, 3.52, 2.2, 1.72, 1.317, 1.0, 0.823, 0.64]),
        }
    ]

    assert resolve_variant(coupe, "M8")["drivetrain"] == "AWD"
    assert resolve_variant(coupe, "M8 Competition")["drivetrain"] == "AWD"


def test_wave18_ratio_source_rows_capture_new_official_bmw_evidence() -> None:
    sources = _ratio_sources()

    assert "official_m3_my18_tech_specs" in sources["BMW|M3 (F80, 2014-2018)"]["sources"]
    assert "official_m4_2018_exact_ratios" in sources["BMW|M4 (F82, 2014-2020)"]["sources"]
    assert "official_m5_2020_exact_ratios" in sources["BMW|M5 (F90, 2018-2024)"]["sources"]
    assert "official_g15_m850i_ratio_context" in sources["BMW|8 Series Coupe (G15, 2019-2025)"]["sources"]
    assert "official_m8_awd_context" in sources["BMW|8 Series Coupe (G15, 2019-2025)"]["sources"]


def test_wave18_variant_source_doc_tracks_updated_m_rows() -> None:
    text = _VARIANT_SOURCES_FILE.read_text(encoding="utf-8")

    assert (
        "| M3 | S55 3.0L I6 Turbo | RWD | 7-speed M-DCT TG 0.671 / 6-speed manual TG 0.846 | BMW technical data (MY18) | High |"
        in text
    )
    assert (
        "| M4 | S55 3.0L I6 Turbo | RWD | 7-speed M-DCT TG 0.671 / 6-speed manual TG 0.846 | BMW technical data (09/2018) | High |"
        in text
    )
    assert (
        "| M5 Competition | S63 4.4L V8 Turbo | AWD | 8-speed M Steptronic FD 3.154 TG 0.640 | BMW technical data (06/2020) | High |"
        in text
    )
    assert (
        "| M8 Competition | 4.4L V8 Turbo | AWD | – | BMW M technical data | High |" in text
    )
