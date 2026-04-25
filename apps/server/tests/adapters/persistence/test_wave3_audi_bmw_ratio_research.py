"""Focused regressions for the third Audi/BMW ratio-research wave."""

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


def test_wave3_exact_bmw_variant_overrides_resolve_official_values() -> None:
    x7 = resolve_variant(_entry_for("BMW", "X7 (G07, 2019-2026)"), "M60i xDrive")
    assert x7["gearboxes"] == [
        {
            "name": "8-speed Steptronic transmission",
            "final_drive_ratio": pytest.approx(3.385),
            "top_gear_ratio": pytest.approx(0.64),
            "gear_ratios": pytest.approx([5.501, 3.52, 2.2, 1.72, 1.301, 1.0, 0.833, 0.64]),
        }
    ]
    assert x7["tire_options"] == [
        {
            "name": 'Standard 21"',
            "tire_width_mm": pytest.approx(285.0),
            "tire_aspect_pct": pytest.approx(45.0),
            "rim_in": pytest.approx(21.0),
        },
        {
            "name": 'Optional staggered 22"',
            "tire_width_mm": pytest.approx(315.0),
            "tire_aspect_pct": pytest.approx(35.0),
            "rim_in": pytest.approx(22.0),
            "front": {"width_mm": pytest.approx(275.0), "aspect_pct": pytest.approx(40.0), "rim_in": pytest.approx(22.0)},
            "rear": {"width_mm": pytest.approx(315.0), "aspect_pct": pytest.approx(35.0), "rim_in": pytest.approx(22.0)},
            "default_axle_for_speed": "rear",
            "source_confidence": "official_exact",
        },
        {
            "name": 'Optional staggered 23"',
            "tire_width_mm": pytest.approx(315.0),
            "tire_aspect_pct": pytest.approx(30.0),
            "rim_in": pytest.approx(23.0),
            "front": {"width_mm": pytest.approx(275.0), "aspect_pct": pytest.approx(35.0), "rim_in": pytest.approx(23.0)},
            "rear": {"width_mm": pytest.approx(315.0), "aspect_pct": pytest.approx(30.0), "rim_in": pytest.approx(23.0)},
            "default_axle_for_speed": "rear",
            "source_confidence": "official_exact",
        },
    ]

    m4 = resolve_variant(_entry_for("BMW", "M4 (G82, 2021-2026)"), "M4 Competition xDrive")
    assert m4["gearboxes"] == [
        {
            "name": "8-speed M Steptronic transmission with Drivelogic",
            "final_drive_ratio": pytest.approx(3.154),
            "top_gear_ratio": pytest.approx(0.64),
            "gear_ratios": pytest.approx([5.0, 3.2, 2.143, 1.72, 1.313, 1.0, 0.823, 0.64]),
        }
    ]
    assert m4["tire_options"] == [
        {
            "name": "Standard staggered setup",
            "tire_width_mm": pytest.approx(285.0),
            "tire_aspect_pct": pytest.approx(30.0),
            "rim_in": pytest.approx(20.0),
            "front": {"width_mm": pytest.approx(275.0), "aspect_pct": pytest.approx(35.0), "rim_in": pytest.approx(19.0)},
            "rear": {"width_mm": pytest.approx(285.0), "aspect_pct": pytest.approx(30.0), "rim_in": pytest.approx(20.0)},
            "default_axle_for_speed": "rear",
            "source_confidence": "official_exact",
        }
    ]


def test_wave3_ratio_source_rows_keep_source_only_findings_explicit() -> None:
    sources = _ratio_sources()

    assert "official_m60_exact_tire_context" in sources["BMW|iX (I20, 2022-2026)"]["sources"]
    assert "official_rs6_exact_ratios" in sources["Audi|RS 6 Avant (C8, 2020-2026)"]["sources"]
    assert "official_rs7_exact_ratios" in sources["Audi|RS 7 Sportback (C8, 2020-2026)"]["sources"]

    assert sources["BMW|iX (I20, 2022-2026)"]["unresolved"] == [
        {
            "item": "BMW iX M60 exact front/rear overall ratios or final-drive ratio values",
            "reason": "Exact official M60 sources checked in this pass confirmed drivetrain context and tire sizes, but they did not yield machine-readable exact front/rear or overall reduction ratios for the M60.",
        },
        {
            "item": "BMW iX M60 numeric top-gear ratio and broad-row applicability across 2022-2026",
            "reason": "Exact official M60 sources use single-speed wording rather than a numeric top-gear ratio, and this pass did not prove one exact EV ratio package across the broad 2022-2026 row.",
        },
    ]
    assert sources["Audi|RS 6 Avant (C8, 2020-2026)"]["unresolved"] == [
        {
            "item": "Audi RS 6 Avant exact production-data applicability across the full 2020-2026 row span",
            "reason": "This pass found exact Germany-market proof for 2023-2025 documents, but it did not retrieve matching official launch-year and full-span documents that prove one unchanged ratio and tire package across the entire row.",
        },
        {
            "item": "Audi RS 6 Avant public gearbox-family naming beyond '8-speed tiptronic'",
            "reason": "Official Audi exact sources confirm the transmission as 8-speed tiptronic but do not explicitly name the gearbox family as ZF 8HP.",
        },
    ]
    assert sources["Audi|RS 7 Sportback (C8, 2020-2026)"]["unresolved"] == [
        {
            "item": "Audi RS 7 Sportback exact 22-inch base-variant tire-option proof",
            "reason": "Checked official Audi family and supplier sources point to 285/30 R22, but this pass did not retrieve a base-RS7 Germany-market technical-data sheet that explicitly lists the optional 22-inch size.",
        },
        {
            "item": "Audi RS 7 Sportback production-data applicability across the full 2020-2026 row span",
            "reason": "This pass found matching launch-era 2020 and later 2024 Germany-market ratio documents, but the current Audi MediaCenter model hub labels the model family through 2025, so the repo's full 2020-2026 span still is not fully closed.",
        },
    ]


def test_wave3_variant_source_docs_track_exact_bmw_overrides() -> None:
    content = _VARIANT_SOURCES_FILE.read_text(encoding="utf-8")
    assert (
        "| M60i xDrive | S68 4.4L V8 Turbo | AWD | 8-speed Steptronic FD 3.385 TG 0.640 | BMW PressClub technical data | High |"
        in content
    )
    assert (
        "| M4 Competition xDrive | S58 3.0L I6 Turbo | AWD | 8-speed M Steptronic FD 3.154 TG 0.640 | BMW PressClub technical data | High |"
        in content
    )
