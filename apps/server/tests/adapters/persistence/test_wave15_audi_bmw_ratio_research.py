"""Focused regressions for the fifteenth Audi/BMW ratio-research wave."""

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


def test_wave15_g30_variant_overrides_capture_exact_bmw_context() -> None:
    sedan = _entry_for("BMW", "5 Series (G30, 2017-2023)")

    xdrive_540i = resolve_variant(sedan, "540i xDrive")
    assert xdrive_540i["gearboxes"] == [
        {
            "name": "8-speed Steptronic transmission",
            "final_drive_ratio": pytest.approx(2.929),
            "top_gear_ratio": pytest.approx(0.64),
        }
    ]
    assert xdrive_540i["tire_options"] == [
        {
            "name": 'Standard 17"',
            "tire_width_mm": pytest.approx(225.0),
            "tire_aspect_pct": pytest.approx(55.0),
            "rim_in": pytest.approx(17.0),
        }
    ]

    xdrive_545e = resolve_variant(sedan, "545e xDrive")
    assert xdrive_545e["gearboxes"] == [
        {
            "name": "8-speed Steptronic transmission",
            "final_drive_ratio": pytest.approx(3.231),
            "top_gear_ratio": pytest.approx(0.667),
            "gear_ratios": pytest.approx([4.714, 3.143, 2.106, 1.667, 1.285, 1.0, 0.839, 0.667]),
        }
    ]
    assert xdrive_545e["tire_options"] == [
        {
            "name": 'Standard 17"',
            "tire_width_mm": pytest.approx(225.0),
            "tire_aspect_pct": pytest.approx(55.0),
            "rim_in": pytest.approx(17.0),
        }
    ]


def test_wave15_g70_i7_edrive50_uses_exact_standard_tire_override() -> None:
    sedan = resolve_variant(_entry_for("BMW", "7 Series (G70, 2023-2026)"), "i7 eDrive50")

    assert sedan["gearboxes"] == [
        {
            "name": "Single-speed fixed gear (EV)",
            "final_drive_ratio": pytest.approx(11.1),
            "top_gear_ratio": pytest.approx(1.0),
        }
    ]
    assert sedan["tire_options"] == [
        {
            "name": 'Standard 19"',
            "tire_width_mm": pytest.approx(245.0),
            "tire_aspect_pct": pytest.approx(50.0),
            "rim_in": pytest.approx(19.0),
        }
    ]


def test_wave15_ratio_source_rows_capture_g30_g70_a8_q8_context() -> None:
    sources = _ratio_sources()

    assert "official_540i_xdrive_exact_context" in sources["BMW|5 Series (G30, 2017-2023)"]["sources"]  # noqa: E501
    assert "official_545e_xdrive_exact_ratios" in sources["BMW|5 Series (G30, 2017-2023)"]["sources"]  # noqa: E501
    assert "official_i7_edrive50_de_context" in sources["BMW|7 Series (G70, 2023-2026)"]["sources"]
    assert "official_60tfsie_quattro_exact_late_cycle" in sources["Audi|A8 (D5, 2018-2026)"]["sources"]  # noqa: E501
    assert "official_60tfsie_quattro_exact_ratios" in sources["Audi|Q8 (4M8, 2019-2026)"]["sources"]

    _assert_contains_unresolved(
        sources["BMW|5 Series (G30, 2017-2023)"],
        [
            {
                "item": "BMW G30 540i xDrive one exact full-ratio set across the represented row span",  # noqa: E501
                "reason": "Official BMW Germany 11/2016 and 11/2020 technical-data sheets agree on 540i xDrive AWD, 8-Gang Steptronic wording, final drive 2.929, top gear 0.640, and a 225/55 R17 baseline tire, but they publish different forward and reverse ratio sets, so this pass promotes only the stable exact fields.",  # noqa: E501
            },
            {
                "item": "BMW G30 545e xDrive front-axle/transfer-case detail and full option tire matrix",  # noqa: E501
                "reason": "Official BMW Germany 11/2020 technical data and the DE price list prove 545e xDrive AWD, 8-Gang Steptronic, the exact forward ratios, final drive 3.231, and a 225/55 R17 baseline tire, but the checked sources do not publish a separate front final drive, transfer-case ratio, or a full 545e-specific optional wheel/tire matrix.",  # noqa: E501
            },
        ],
    )
    _assert_contains_unresolved(
        sources["BMW|7 Series (G70, 2023-2026)"],
        [
            {
                "item": "Exact i7 eDrive50 numeric reduction ratio and top-gear equivalent",
                "reason": "Official BMW Germany catalogs now prove the i7 eDrive50 as the rear-wheel-drive 1-Gang automatic EV with a 245/50 R19 standard tire, but the checked exact sources still do not publish a numeric reduction ratio or overall-drive value for this variant.",  # noqa: E501
            }
        ],
    )
    _assert_contains_unresolved(
        sources["Audi|A8 (D5, 2018-2026)"],
        [
            {
                "item": "Audi A8 60 TFSI e quattro production-data applicability across the represented D5 row span",  # noqa: E501
                "reason": "Official facelift-era Germany-market documents now prove exact A8 60 TFSI e quattro AWD, 8-speed tiptronic, forward ratios 4.714 / 3.143 / 2.106 / 1.667 / 1.285 / 1.000 / 0.839 / 0.667, reverse 3.317, final drive 3.076, and a 255/45 R19 basic tire, but this pass did not recover launch-era or year-spanning sheets proving one unchanged mapping across the represented row.",  # noqa: E501
            }
        ],
    )
    _assert_contains_unresolved(
        sources["Audi|Q8 (4M8, 2019-2026)"],
        [
            {
                "item": "Audi Q8 60 TFSI e quattro production-data applicability across the full 2019-2026 row span",  # noqa: E501
                "reason": "Official 2020 and current Audi technical-data sheets now agree on exact Q8 60 TFSI e quattro AWD, 8-speed tiptronic, forward ratios 4.714 / 3.143 / 2.106 / 1.667 / 1.285 / 1.000 / 0.839 / 0.667, reverse 3.317, final drive 3.204, and a 265/55 R19 basic tire, but this pass did not recover year-spanning material proving one unchanged mapping across the represented row.",  # noqa: E501
            }
        ],
    )


def test_wave15_variant_source_doc_tracks_g30_overrides() -> None:
    text = _VARIANT_SOURCES_FILE.read_text(encoding="utf-8")

    assert (
        "| 540i xDrive | B58 3.0L I6 Turbo | AWD | 8-speed Steptronic transmission FD 2.929 TG 0.640 | BMW PressClub technical data | High |"  # noqa: E501
        in text
    )
    assert (
        "| 545e xDrive | 3.0L I6 Turbo | AWD | 8-speed Steptronic transmission FD 3.231 TG 0.667 | BMW PressClub technical data / DE price list | High |"  # noqa: E501
        in text
    )
