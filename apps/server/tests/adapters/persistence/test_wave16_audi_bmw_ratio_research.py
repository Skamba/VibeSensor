"""Focused regressions for the sixteenth Audi/BMW ratio-research wave."""

from __future__ import annotations

import json

import pytest

from vibesensor.adapters.persistence.car_library import _DATA_FILE, load_car_library, resolve_variant  # noqa: E501

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


def test_wave16_g30_540i_uses_exact_variant_override() -> None:
    sedan = resolve_variant(_entry_for("BMW", "5 Series (G30, 2017-2023)"), "540i")

    assert sedan["gearboxes"] == [
        {
            "name": "8-speed Steptronic transmission",
            "final_drive_ratio": pytest.approx(2.929),
            "top_gear_ratio": pytest.approx(0.64),
        }
    ]
    assert sedan["tire_options"] == [
        {
            "name": 'Standard 17"',
            "tire_width_mm": pytest.approx(225.0),
            "tire_aspect_pct": pytest.approx(55.0),
            "rim_in": pytest.approx(17.0),
        }
    ]


def test_wave16_g60_i5_edrive40_uses_exact_tire_context() -> None:
    sedan = resolve_variant(_entry_for("BMW", "5 Series (G60, 2024-2026)"), "i5 eDrive40")

    assert sedan["gearboxes"] == [
        {
            "name": "Single-speed fixed gear (EV)",
            "final_drive_ratio": pytest.approx(11.115),
            "top_gear_ratio": pytest.approx(1.0),
        }
    ]
    assert sedan["tire_options"] == [
        {
            "name": 'Standard 19"',
            "tire_width_mm": pytest.approx(245.0),
            "tire_aspect_pct": pytest.approx(45.0),
            "rim_in": pytest.approx(19.0),
        },
        {
            "name": 'Optional staggered 21"',
            "tire_width_mm": pytest.approx(285.0),
            "tire_aspect_pct": pytest.approx(30.0),
            "rim_in": pytest.approx(21.0),
            "front": {
                "width_mm": pytest.approx(255.0),
                "aspect_pct": pytest.approx(35.0),
                "rim_in": pytest.approx(21.0),
            },
            "rear": {
                "width_mm": pytest.approx(285.0),
                "aspect_pct": pytest.approx(30.0),
                "rim_in": pytest.approx(21.0),
            },
            "default_axle_for_speed": "rear",
            "source_confidence": "official_exact",
        },
    ]


def test_wave16_ratio_source_rows_capture_g30_g60_a7_a8_context() -> None:
    sources = _ratio_sources()

    assert "official_530i_xdrive_exact_context" in sources["BMW|5 Series (G30, 2017-2023)"]["sources"]  # noqa: E501
    assert "official_540i_exact_context" in sources["BMW|5 Series (G30, 2017-2023)"]["sources"]
    assert "official_i5_edrive40_tire_context" in sources["BMW|5 Series (G60, 2024-2026)"]["sources"]  # noqa: E501
    assert "official_us_service_mapping_contradiction" in sources["Audi|A7 Sportback (C7, 2011-2018)"]["sources"]  # noqa: E501
    assert "secondary_exact_40tfsi_quattro_context" in sources["Audi|A8 (D4, 2011-2017)"]["sources"]

    _assert_contains_unresolved(
        sources["BMW|5 Series (G30, 2017-2023)"],
        [
            {
                "item": "BMW G30 530i xDrive one exact final-drive and full-ratio set across the represented row span",  # noqa: E501
                "reason": "Official BMW Germany technical-data sheets now prove 530i xDrive AWD, 8-Gang Steptronic wording, top gear 0.640, and a 225/55 R17 baseline tire, but the 11/2016 sheet publishes final drive 2.929 while the 05/2020, 11/2020, and 03/2021 sheets publish 2.813 and different forward-ratio sets.",  # noqa: E501
            },
            {
                "item": "BMW G30 540i one exact full-ratio set across the represented row span",
                "reason": "Official BMW Germany 11/2016, 05/2020, and 11/2020 technical-data sheets agree on 540i RWD, 8-Gang Steptronic wording, final drive 2.929, top gear 0.640, and a 225/55 R17 baseline tire, but they publish different forward and reverse ratio sets, so this pass promotes only the stable exact fields.",  # noqa: E501
            },
        ],
    )
    _assert_contains_unresolved(
        sources["Audi|A7 Sportback (C7, 2011-2018)"],
        [
            {
                "item": "Exact EU-DE official transmission mapping for Audi A7 Sportback C7 3.0 TFSI quattro",  # noqa: E501
                "reason": "Official Audi OEM service books published via NHTSA show a MY2011 3.0 TFSI 0BK AWD automatic mapping, while reputable secondary EU-style pages describe 7-speed S tronic states, and this pass did not recover an exact Audi Germany-market technical-data or price-list document that resolves the market-specific transmission shape.",  # noqa: E501
            }
        ],
    )
    _assert_contains_unresolved(
        sources["Audi|A8 (D4, 2011-2017)"],
        [
            {
                "item": "Audi A8 D4 4.0 TFSI quattro exact tire-baseline and year-split continuity",
                "reason": "Reputable secondary exact pages distinguish at least two 4.0 TFSI quattro states with 235/60 R17 and 235/55 R18 baseline tires, contradicting the current 255/40 R20 default, but this pass did not recover an exact official Germany-market tire matrix that proves one safe production baseline.",  # noqa: E501
            }
        ],
    )


def test_wave16_variant_source_doc_tracks_g30_and_g60_updates() -> None:
    text = _VARIANT_SOURCES_FILE.read_text(encoding="utf-8")

    assert (
        "| 540i | B58 3.0L I6 Turbo | RWD | 8-speed Steptronic transmission FD 2.929 TG 0.640 | BMW PressClub technical data | High |"  # noqa: E501
        in text
    )
    assert (
        "| i5 eDrive40 | Electric Single Motor | RWD | Single-speed fixed gear (EV) overall 11.115 | BMW technical data / DE price list | High |"  # noqa: E501
        in text
    )
