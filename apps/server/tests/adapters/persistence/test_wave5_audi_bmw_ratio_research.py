"""Focused regressions for the fifth Audi/BMW ratio-research wave."""

from __future__ import annotations

import json

import pytest

from vibesensor.adapters.persistence.car_library import (
    _DATA_FILE,
    load_car_library,
    resolve_variant,
)

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


def test_wave5_q5_45tfsi_quattro_uses_exact_official_top_gear_and_ratio_set() -> None:
    q5 = resolve_variant(_entry_for("Audi", "Q5 (FY, 2017-2026)"), "45 TFSI quattro")
    assert q5["gearboxes"] == [
        {
            "name": "7-speed S tronic",
            "final_drive_ratio": pytest.approx(5.302),
            "top_gear_ratio": pytest.approx(0.433),
            "gear_ratios": pytest.approx([3.188, 2.19, 1.517, 1.057, 0.738, 0.557, 0.433]),
        }
    ]


def test_wave5_ratio_source_rows_capture_exact_g70_q7_q4_context_without_overwriting_broad_rows() -> None:
    sources = _ratio_sources()

    assert "exact_45tfsi_quattro_official_ratios" in sources["Audi|Q5 (FY, 2017-2026)"]["sources"]
    assert "official_750e_de_context" in sources["BMW|7 Series (G70, 2023-2026)"]["sources"]
    assert "official_m760e_de_context" in sources["BMW|7 Series (G70, 2023-2026)"]["sources"]
    assert "official_55tfsi_e_quattro_exact_ratios" in sources["Audi|Q7 (4M, 2016-2026)"]["sources"]
    assert "official_40e_exact_rear_ratio" in sources["Audi|Q4 e-tron (FZ, 2022-2026)"]["sources"]

    assert sources["Audi|Q7 (4M, 2016-2026)"]["unresolved"] == [
        {
            "item": "Audi Q7 55 TFSI e quattro production-data applicability across the full 4M row span",
            "reason": "Checked exact official Germany-market evidence resolved the current facelift-era 55 TFSI e quattro values, but this pass did not prove the same ratio and final-drive mapping across the full 2016-2026 row span.",
        },
        {
            "item": "Audi Q7 55 TFSI e quattro exact optional tire matrix and gearbox-family naming",
            "reason": "Official Audi exact sources prove the base 255/55 R19 fitment and 8-speed tiptronic wording, but this pass did not recover the full optional tire matrix or explicit official ZF 8HP naming.",
        },
    ]


def test_wave5_variant_source_doc_tracks_q5_override_update() -> None:
    assert (
        "| 45 TFSI quattro | 2.0L I4 TFSI Turbo | AWD | 7-speed S tronic FD 5.302 TG 0.433 | Audi MediaCenter eTD technical data (2019, 2024) | High |"
        in _VARIANT_SOURCES_FILE.read_text(encoding="utf-8")
    )
