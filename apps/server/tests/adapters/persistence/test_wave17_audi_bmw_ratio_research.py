"""Focused regressions for the seventeenth Audi/BMW ratio-research wave."""

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


def _assert_contains_unresolved(entry: dict[str, object], expected: list[dict[str, str]]) -> None:
    unresolved = entry["unresolved"]
    for item in expected:
        assert item in unresolved


def test_wave17_g60_520i_uses_exact_variant_override() -> None:
    sedan = resolve_variant(_entry_for("BMW", "5 Series (G60, 2024-2026)"), "520i")

    gearbox = sedan["gearboxes"][0]
    assert gearbox["name"] == "8-speed Steptronic transmission"
    assert gearbox["final_drive_ratio"] == pytest.approx(3.077)
    assert gearbox["top_gear_ratio"] == pytest.approx(0.64)
    assert gearbox["gear_ratios"] == pytest.approx(
        [5.25, 3.36, 2.172, 1.72, 1.316, 1.0, 0.822, 0.64]
    )  # noqa: E501

    assert sedan["tire_options"] == [
        {
            "name": 'Standard 18"',
            "tire_width_mm": pytest.approx(225.0),
            "tire_aspect_pct": pytest.approx(55.0),
            "rim_in": pytest.approx(18.0),
        }
    ]
    assert sedan["tire_width_mm"] == pytest.approx(225.0)
    assert sedan["tire_aspect_pct"] == pytest.approx(55.0)
    assert sedan["rim_in"] == pytest.approx(18.0)


def test_wave17_g32_640i_xdrive_uses_exact_variant_gearbox_override() -> None:
    fastback = resolve_variant(
        _entry_for("BMW", "6 Series Gran Turismo (G32, 2018-2024)"), "640i xDrive"
    )  # noqa: E501

    assert fastback["gearboxes"] == [
        {
            "name": "8-speed Steptronic transmission",
            "final_drive_ratio": pytest.approx(3.077),
            "top_gear_ratio": pytest.approx(0.64),
        }
    ]


def test_wave17_ratio_source_rows_capture_bmw_and_audi_context() -> None:
    sources = _ratio_sources()

    assert "official_520i_exact_context" in sources["BMW|5 Series (G30, 2017-2023)"]["sources"]
    assert "official_520i_exact_context" in sources["BMW|5 Series (G60, 2024-2026)"]["sources"]
    assert (
        "official_640i_xdrive_exact_context"
        in sources["BMW|6 Series Gran Turismo (G32, 2018-2024)"]["sources"]
    )  # noqa: E501
    assert (
        "official_30tfsi_quattro_early_0b5_context" in sources["Audi|A6 (C7, 2011-2018)"]["sources"]
    )  # noqa: E501
    assert (
        "official_30tdi_quattro_launch_context"
        in sources["Audi|A7 Sportback (C7, 2011-2018)"]["sources"]
    )  # noqa: E501

    _assert_contains_unresolved(
        sources["BMW|5 Series (G30, 2017-2023)"],
        [
            {
                "item": "BMW G30 520i one exact final-drive and full-ratio set across the represented row span",  # noqa: E501
                "reason": "Official BMW Germany 07/2017, 09/2018, 05/2020, 11/2020, and 03/2021 technical-data sheets agree on 8-Gang Steptronic wording, top gear 0.640, and a 225/55 R17 baseline tire, but they split the final drive between 2.929 and 2.813, publish different forward and reverse ratio sets, and this pass did not recover a 2022-2023 Germany sheet to close end-of-span continuity.",  # noqa: E501
            }
        ],
    )
    assert {
        "item": "Exact BMW 520i optional wheel and tire matrix",
        "reason": "Official BMW launch material confirms 18-inch wheels as standard for combustion G60 models, but this pass did not recover a parseable per-variant BMW Germany wheel matrix safe enough to promote exact 19/20/21-inch 520i tire sizes into production data.",  # noqa: E501
    } in sources["BMW|5 Series (G60, 2024-2026)"]["known_limits"]
    _assert_contains_unresolved(
        sources["BMW|6 Series Gran Turismo (G32, 2018-2024)"],
        [
            {
                "item": "BMW G32 640i xDrive one exact full-ratio and reverse-ratio set across the represented row span",  # noqa: E501
                "reason": "Official BMW 2018 and 11/2020 technical-data sheets for the exact 640i xDrive agree on AWD, Eight-speed Steptronic wording, final drive 3.077, and top gear 0.640, but they publish different 1st-6th and reverse ratios, so this pass promotes only the stable exact fields.",  # noqa: E501
            }
        ],
    )
    _assert_contains_unresolved(
        sources["Audi|A6 (C7, 2011-2018)"],
        [
            {
                "item": "Audi A6 C7 3.0 TFSI quattro exact facelift EU-DE gearbox code and numeric ratio set",  # noqa: E501
                "reason": "Checked official Audi material establishes the early 0B5 S tronic mapping and shows that the recovered 0BK automatic allocation belongs to non-EU markets, but this pass did not recover an exact Audi Germany-market facelift technical-data or workshop allocation sheet for the 245 kW sedan.",  # noqa: E501
            }
        ],
    )
    _assert_contains_unresolved(
        sources["Audi|A7 Sportback (C7, 2011-2018)"],
        [
            {
                "item": "Exact EU-DE official transmission and ratio mapping for Audi A7 Sportback C7 3.0 TDI quattro",  # noqa: E501
                "reason": "Official Audi launch material proves only that the 180 kW / 245 PS diesel launch state used S tronic quattro and 17-inch standard wheels with 18- to 20-inch options, while this pass did not recover an exact Germany-market technical-data or workshop table publishing final drive, top gear, full ratios, or reverse for the diesel target.",  # noqa: E501
            }
        ],
    )


def test_wave17_variant_source_doc_tracks_g60_and_g32_updates() -> None:
    text = _VARIANT_SOURCES_FILE.read_text(encoding="utf-8")

    assert (
        "| 520i | B48 2.0L I4 Turbo | RWD | 8-speed Steptronic transmission FD 3.077 TG 0.640 | BMW press release / technical data | High |"  # noqa: E501
        in text
    )
    assert (
        "| 640i xDrive | B58 3.0L I6 Turbo | AWD | 8-speed Steptronic transmission FD 3.077 TG 0.640 | BMW technical data / DE price list | High |"  # noqa: E501
        in text
    )
