"""Focused regressions for the thirteenth Audi/BMW ratio-research wave."""

from __future__ import annotations

import json

import pytest

from vibesensor.adapters.persistence.car_library import (
    _DATA_FILE,
    load_car_library,
    resolve_variant,
    resolve_vehicle_configurations,
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


def test_wave13_g42_230i_uses_exact_official_variant_override() -> None:
    coupe = resolve_variant(_entry_for("BMW", "2 Series Coupe (G42, 2022-2026)"), "230i")

    assert coupe["gearboxes"] == [
        {
            "name": "8-speed Steptronic transmission",
            "final_drive_ratio": pytest.approx(2.813),
            "top_gear_ratio": pytest.approx(0.64),
            "gear_ratios": pytest.approx([5.25, 3.36, 2.172, 1.72, 1.316, 1.0, 0.822, 0.64]),
        }
    ]
    assert coupe["tire_options"] == [
        {
            "name": 'Standard 17"',
            "tire_width_mm": pytest.approx(225.0),
            "tire_aspect_pct": pytest.approx(50.0),
            "rim_in": pytest.approx(17.0),
        },
        {
            "name": 'M Sport standard 18"',
            "tire_width_mm": pytest.approx(225.0),
            "tire_aspect_pct": pytest.approx(45.0),
            "rim_in": pytest.approx(18.0),
        },
        {
            "name": 'Optional staggered 18"',
            "tire_width_mm": pytest.approx(255.0),
            "tire_aspect_pct": pytest.approx(40.0),
            "rim_in": pytest.approx(18.0),
            "front": {
                "width_mm": pytest.approx(225.0),
                "aspect_pct": pytest.approx(45.0),
                "rim_in": pytest.approx(18.0),
            },
            "rear": {
                "width_mm": pytest.approx(255.0),
                "aspect_pct": pytest.approx(40.0),
                "rim_in": pytest.approx(18.0),
            },
            "default_axle_for_speed": "rear",
            "source_confidence": "official_exact",
        },
        {
            "name": 'Optional staggered 19"',
            "tire_width_mm": pytest.approx(255.0),
            "tire_aspect_pct": pytest.approx(35.0),
            "rim_in": pytest.approx(19.0),
            "front": {
                "width_mm": pytest.approx(225.0),
                "aspect_pct": pytest.approx(40.0),
                "rim_in": pytest.approx(19.0),
            },
            "rear": {
                "width_mm": pytest.approx(255.0),
                "aspect_pct": pytest.approx(35.0),
                "rim_in": pytest.approx(19.0),
            },
            "default_axle_for_speed": "rear",
            "source_confidence": "official_exact",
        },
    ]


def test_wave13_g42_230i_uses_exact_vehicle_configuration_row() -> None:
    configs = resolve_vehicle_configurations(
        _entry_for("BMW", "2 Series Coupe (G42, 2022-2026)"),
        "230i",
    )

    assert len(configs) == 1
    config = configs[0]
    assert config.source_status == "exact_row"
    assert config.transmission_name == "8-speed Steptronic transmission"
    assert config.final_drive_rear == pytest.approx(2.813)
    assert config.gear_ratios == pytest.approx((5.25, 3.36, 2.172, 1.72, 1.316, 1.0, 0.822, 0.64))
    assert config.default_tire.width_mm == pytest.approx(225.0)
    assert config.default_tire.aspect_pct == pytest.approx(50.0)
    assert config.default_tire.rim_in == pytest.approx(17.0)
    assert config.provenance_for("final_drive_rear") is not None
    assert config.provenance_for("top_gear_ratio") is not None
    assert config.provenance_for("gear_ratios") is not None
    assert config.provenance_for("drivetrain") is not None
    assert config.provenance_for("tire_dimensions") is not None
    assert config.order_reference_confidence("transmission_name") == "official_exact"


def test_wave13_ratio_source_rows_capture_g42_a3_a5_q3_context() -> None:
    sources = _ratio_sources()

    assert "official_230i_exact_ratios" in sources["BMW|2 Series Coupe (G42, 2022-2026)"]["sources"]
    assert "official_m240i_xdrive_launch_exact_ratios" in sources["BMW|2 Series Coupe (G42, 2022-2026)"]["sources"]
    assert "official_35tdi_limousine_exact_ratios" in sources["Audi|A3 (8Y, 2021-2026)"]["sources"]
    assert "exact_35tdi_late_b9_ratios" in sources["Audi|A5 (B9, 2017-2024)"]["sources"]
    assert "official_35tfsi_exact_states" in sources["Audi|Q3 (F3, 2019-2026)"]["sources"]

    _assert_contains_unresolved(
        sources["BMW|2 Series Coupe (G42, 2022-2026)"],
        [
            {
                "item": "Whether BMW 230i xDrive belongs in the G42 row at all",
                "reason": "Checked official BMW Germany/EU sources now consistently show 230i as rear-wheel drive and reserve xDrive for M240i xDrive, but this pass did not recover enough official non-Germany market evidence to prove whether the existing AWD 230i variant is an intentional non-EU/global carry-over or simply unsupported library data.",
            },
            {
                "item": "BMW M240i xDrive production-data applicability across the full G42 row span",
                "reason": "Wave 13 now proves the exact launch M240i xDrive ratio set, reverse ratio 3.712, final drive 2.813, and standard staggered 225/40 R19 front + 255/35 R19 rear tires, but the checked current Germany market material is already a later 48V mild-hybrid state and this pass did not recover a current exact numeric ratio table proving one unchanged 2022-2026 package.",
            },
        ],
    )
    _assert_contains_unresolved(
        sources["Audi|A3 (8Y, 2021-2026)"],
        [
            {
                "item": "Broad-row Audi A3 8Y 35 TDI production-data applicability across the represented span",
                "reason": "Checked exact Germany-market 2024 35 TDI Limousine evidence proves one S tronic ratio package and the MY2026 Germany price list confirms later market presence, but this pass did not recover year-by-year official sheets proving one unchanged 2021-2026 production mapping.",
            },
            {
                "item": "Schema-safe encoding of Audi A3 8Y 35 TDI split final drives and trim-linked tires",
                "reason": "The checked official 35 TDI technical-data PDF publishes two final-drive values 4.167 / 3.125 and only the 205/55 R16 basic tire, while the current row shape cannot safely encode split final drives or the MY2026 price list's trim-specific standard tire progression.",
            },
        ],
    )
    _assert_contains_unresolved(
        sources["Audi|A5 (B9, 2017-2024)"],
        [
            {
                "item": "Broad-row Audi A5 B9 35 TDI production-data applicability across the full represented span",
                "reason": "Checked exact late-B9 Germany Coupé and Sportback PDFs resolve the 120 kW 35 TDI mapping, but this pass did not recover a year-by-year official chain proving one unchanged 2019-2024 package.",
            },
            {
                "item": "Audi A5 B9 35 TDI gearbox-family code and optional tire-matrix confirmation",
                "reason": "Official Audi exact material now proves the late-B9 35 TDI drivetrain, full ratio set, reverse ratio, final drive 4.048, and the 225/50 R17 basic tire, but it does not publish the gearbox-family code or a full optional wheel/tire matrix for the exact 35 TDI target.",
            },
        ],
    )
    _assert_contains_unresolved(
        sources["Audi|Q3 (F3, 2019-2026)"],
        [
            {
                "item": "Audi Q3 35 TFSI production-data applicability across the represented old-generation row span",
                "reason": "Checked exact Germany-market 2025 manual and S tronic Q3 35 TFSI technical-data PDFs resolve old-generation front-wheel-drive states, but this pass did not recover year-by-year official sheets proving one unchanged 2019-2025 package.",
            },
            {
                "item": "Schema-safe encoding of exact Audi Q3 35 TFSI manual and S tronic states",
                "reason": "The checked official 35 TFSI manual PDF publishes final drives 4.563 / 4.563 while the 35 TFSI S tronic PDFs publish 5.200 / 3.900, and the current row cannot safely encode both transmission-specific exact states plus their split final drives.",
            },
        ],
    )


def test_wave13_variant_source_doc_tracks_g42_230i_override() -> None:
    assert (
        "| 230i | B48 2.0L I4 Turbo | RWD | 8-speed Steptronic transmission FD 2.813 TG 0.640 | BMW PressClub technical data / DE price lists | High |"
        in _VARIANT_SOURCES_FILE.read_text(encoding="utf-8")
    )
