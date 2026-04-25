"""Focused regressions for the first Audi/BMW ratio-research wave."""

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


def test_g20_330i_xdrive_uses_exact_wave1_official_top_gear_and_ratio_set() -> None:
    entry = _entry_for("BMW", "3 Series (G20, 2019-2025)")
    resolved = resolve_variant(entry, "330i xDrive")

    assert resolved["gearboxes"] == [
        {
            "name": "8-speed automatic (ZF 8HP)",
            "final_drive_ratio": pytest.approx(2.813),
            "top_gear_ratio": pytest.approx(0.64),
            "gear_ratios": pytest.approx([5.25, 3.36, 2.172, 1.72, 1.316, 1.0, 0.822, 0.64]),
        }
    ]


def test_wave1_ratio_source_rows_capture_exact_audi_bmw_evidence_without_guessing() -> None:
    sources = _ratio_sources()

    assert "m135i_xdrive_8at_ratios" in sources["BMW|1 Series (F40, 2019-2025)"]["sources"]
    assert "official_330i_xdrive_exact_ratios" in sources["BMW|3 Series (G20, 2019-2025)"][
        "sources"
    ]
    assert "exact_45tfsi_quattro_late_b9_ratios" in sources["Audi|A4 (B9, 2016-2025)"][
        "sources"
    ]
    assert "exact_45tfsi_quattro_late_b9_ratios" in sources["Audi|A5 (B9, 2017-2024)"][
        "sources"
    ]
    assert "exact_55tfsi_e_quattro_late_fy_ratios" in sources["Audi|Q5 (FY, 2017-2026)"][
        "sources"
    ]

    unresolved_a4 = sources["Audi|A4 (B9, 2016-2025)"]["unresolved"]
    unresolved_a5 = sources["Audi|A5 (B9, 2017-2024)"]["unresolved"]
    unresolved_q5 = sources["Audi|Q5 (FY, 2017-2026)"]["unresolved"]

    assert unresolved_a4 == [
        {
            "item": "Broad-row Audi A4 B9 45 TFSI quattro top_gear_ratio applicability across the full represented span",
            "reason": "Official Audi MediaCenter eTD PDFs now prove top gear 0.433 and the full gear-ratio set for the later 195 kW DE sedan, but this pass did not verify whether the earlier 180 kW years use the same exact mapping.",
        }
    ]
    assert unresolved_a5 == [
        {
            "item": "Broad-row Audi A5 B9 45 TFSI quattro top_gear_ratio applicability across the full represented span",
            "reason": "Official Audi MediaCenter eTD PDFs now prove top gear 0.433 and the full gear-ratio set for the later 195 kW Coupe and Sportback, but this pass did not verify whether the earlier years in the broad row use the same exact mapping.",
        }
    ]
    assert unresolved_q5 == [
        {
            "item": "Broad-row Audi Q5 FY 55 TFSI e quattro top_gear_ratio applicability across the represented span",
            "reason": "Official Audi MediaCenter eTD PDFs now prove top gear 0.433 and the full gear-ratio set for the later 270 kW 55 TFSI e quattro configuration, but this pass did not verify whether every year represented by the broad FY row uses the same exact mapping.",
        }
    ]


def test_g20_variant_source_doc_tracks_wave1_override_update() -> None:
    assert (
        "| 330i xDrive | B48 2.0L I4 Turbo | AWD | 8-speed automatic (ZF 8HP) FD 2.813 TG 0.640 | BMW PressClub technical data (03/2021, 07/2022) | High |"
        in _VARIANT_SOURCES_FILE.read_text(encoding="utf-8")
    )
