"""Focused regressions for the second Audi/BMW ratio-research wave."""

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


def test_wave2_exact_bmw_variant_overrides_resolve_official_values() -> None:
    x5 = resolve_variant(_entry_for("BMW", "X5 (G05, 2019-2026)"), "xDrive45e")
    assert x5["gearboxes"] == [
        {
            "name": "8-speed Steptronic transmission",
            "final_drive_ratio": pytest.approx(3.636),
            "top_gear_ratio": pytest.approx(0.667),
            "gear_ratios": pytest.approx([4.714, 3.143, 2.106, 1.667, 1.285, 1.0, 0.839, 0.667]),
        }
    ]
    assert x5["tire_options"] == [
        {
            "name": 'Standard 19"',
            "tire_width_mm": pytest.approx(265.0),
            "tire_aspect_pct": pytest.approx(50.0),
            "rim_in": pytest.approx(19.0),
        }
    ]

    m3 = resolve_variant(_entry_for("BMW", "M3 (G80, 2021-2026)"), "M3 Competition xDrive")
    assert m3["gearboxes"] == [
        {
            "name": "8-speed M Steptronic transmission with Drivelogic",
            "final_drive_ratio": pytest.approx(3.154),
            "top_gear_ratio": pytest.approx(0.64),
            "gear_ratios": pytest.approx([5.0, 3.2, 2.143, 1.72, 1.313, 1.0, 0.823, 0.64]),
        }
    ]
    assert m3["tire_options"] == [
        {
            "name": "Standard staggered setup",
            "tire_width_mm": pytest.approx(285.0),
            "tire_aspect_pct": pytest.approx(30.0),
            "rim_in": pytest.approx(20.0),
            "front": {"width_mm": pytest.approx(275.0), "aspect_pct": pytest.approx(35.0), "rim_in": pytest.approx(19.0)},  # noqa: E501
            "rear": {"width_mm": pytest.approx(285.0), "aspect_pct": pytest.approx(30.0), "rim_in": pytest.approx(20.0)},  # noqa: E501
            "default_axle_for_speed": "rear",
            "source_confidence": "official_exact",
        }
    ]


def test_wave2_ratio_source_rows_keep_source_only_findings_explicit() -> None:
    sources = _ratio_sources()

    assert "official_m50_exact_axle_ratios" in sources["BMW|i4 (G26, 2022-2026)"]["sources"]
    assert "official_8y_rs3_exact_ratios" in sources["Audi|RS 3 (8V/8Y, 2017-2026)"]["sources"]
    assert "official_50quattro_exact_axle_ratios" in sources["Audi|Q4 e-tron (FZ, 2022-2026)"]["sources"]  # noqa: E501

    assert sources["BMW|i4 (G26, 2022-2026)"]["unresolved"] == [
        {
            "item": "BMW i4 M50 exact axle-ratio applicability across the represented 2022-2026 span",  # noqa: E501
            "reason": "Official BMW launch specs show axle ratios 9.053 / 9.053 for the exact i4 M50, while official DE July 2024 technical data shows front 9.744 and rear 8.776 for the exact i4 M50 xDrive, so this pass did not choose one exact ratio set for the broad row.",  # noqa: E501
        },
        {
            "item": "BMW i4 M50 broad-row tire mapping and post-2025 naming continuity",
            "reason": "Official BMW sources prove staggered M50 tire packages and also show that M60 xDrive replaces the predecessor from July 2025, so the current broad 2022-2026 M50 row should not absorb one exact tire or ratio set without a row split.",  # noqa: E501
        },
    ]
    assert sources["Audi|RS 3 (8V/8Y, 2017-2026)"]["unresolved"] == [
        {
            "item": "Split the broad Audi RS 3 row into exact 8V/8Y body- and generation-specific entries",  # noqa: E501
            "reason": "Official Audi now provides exact 8Y Sedan and Sportback technical-data sheets with body-specific ratio and tire evidence, but the current mixed 8V/8Y row cannot absorb those numbers safely without splitting the row.",  # noqa: E501
        },
        {
            "item": "Audi RS 3 official transmission code and non-basic tire-option coverage",
            "reason": "The checked exact Audi sources prove the 7-speed S tronic ratio set, final drive, top gear, and the basic staggered 19-inch setup, but they do not publish a transmission code or the full optional wheel/tire matrix.",  # noqa: E501
        },
    ]
    assert sources["Audi|Q4 e-tron (FZ, 2022-2026)"]["unresolved"] == [
        {
            "item": "Encode axle-split EV reduction ratios for the exact Q4 50 e-tron quattro in repo schema",  # noqa: E501
            "reason": "Official Audi sources now prove rear 11.5:1 and front 10.0:1 one-speed reduction ratios for the exact launch-era 50 e-tron quattro, but the current broad row stores only one final_drive_ratio field and cannot safely represent the axle split.",  # noqa: E501
        },
        {
            "item": "Exact official numeric tire sizes and post-2024 naming continuity for the broad Q4 e-tron row",  # noqa: E501
            "reason": "Official Audi launch material confirms mixed-size tires with a wider rear axle, while later official updates rename the upper quattro variant to 55 e-tron quattro, so this pass did not project one exact tire or ratio package across the full 2022-2026 broad row.",  # noqa: E501
        },
    ]


def test_wave2_variant_source_docs_track_exact_bmw_overrides() -> None:
    content = _VARIANT_SOURCES_FILE.read_text(encoding="utf-8")
    assert (
        "| xDrive45e | B58 3.0L I6 Turbo PHEV | AWD | 8-speed Steptronic FD 3.636 | BMW DE technical data | High |"  # noqa: E501
        in content
    )
    assert (
        "| M3 Competition xDrive | S58 3.0L I6 Turbo | AWD | 8-speed M Steptronic FD 3.154 TG 0.640 | BMW PressClub technical data | High |"  # noqa: E501
        in content
    )
