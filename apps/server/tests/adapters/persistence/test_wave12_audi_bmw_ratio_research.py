"""Focused regressions for the twelfth Audi/BMW ratio-research wave."""

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


def test_wave12_g42_220i_uses_exact_official_variant_override() -> None:
    coupe = resolve_variant(_entry_for("BMW", "2 Series Coupe (G42, 2022-2026)"), "220i")

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
        {
            "name": 'Optional staggered sport 19"',
            "tire_width_mm": pytest.approx(255.0),
            "tire_aspect_pct": pytest.approx(35.0),
            "rim_in": pytest.approx(19.0),
            "front": {
                "width_mm": pytest.approx(245.0),
                "aspect_pct": pytest.approx(35.0),
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


def test_wave12_g42_220i_uses_exact_vehicle_configuration_row() -> None:
    configs = resolve_vehicle_configurations(
        _entry_for("BMW", "2 Series Coupe (G42, 2022-2026)"),
        "220i",
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


def test_wave12_ratio_source_rows_capture_g22_g42_a3_a4_q5_context() -> None:
    sources = _ratio_sources()

    assert "official_220i_exact_ratios" in sources["BMW|2 Series Coupe (G42, 2022-2026)"]["sources"]
    assert "official_420i_exact_ratios" in sources["BMW|4 Series (G22, 2021-2026)"]["sources"]
    assert "official_35tfsi_limousine_2026_de" in sources["Audi|A3 (8Y, 2021-2026)"]["sources"]
    assert "exact_35tdi_late_b9_ratios" in sources["Audi|A4 (B9, 2016-2025)"]["sources"]
    assert "exact_35tdi_fwd_states" in sources["Audi|Q5 (FY, 2017-2026)"]["sources"]

    _assert_contains_unresolved(
        sources["BMW|2 Series Coupe (G42, 2022-2026)"],
        [
            {
                "item": "Whether BMW 230i xDrive belongs in the G42 row at all",
                "reason": "Checked official BMW Germany/EU sources now consistently show 230i as rear-wheel drive and reserve xDrive for M240i xDrive, but this pass did not recover enough official non-Germany market evidence to prove whether the existing AWD 230i variant is an intentional non-EU/global carry-over or simply unsupported library data.",
            },
            {
                "item": "BMW G42 230i and M240i xDrive numeric ratio evidence",
                "reason": "Wave 12 resolves the exact 220i ratio package, but this pass still did not recover one official numeric final-drive, top-gear, and forward-ratio table for the remaining 230i and M240i xDrive variants represented by the broad row.",
            },
        ],
    )
    _assert_contains_unresolved(
        sources["BMW|4 Series (G22, 2021-2026)"],
        [
            {
                "item": "BMW 420i production-data applicability across the full G22 row span",
                "reason": "Checked official 03/2021 and 01/2024 EU-market technical-data PDFs agree on the exact 420i ratio set, reverse ratio 3.712, final drive 2.813, and standard 225/50 R17 tire, but this pass did not recover an official 2025-2026 exact table or one full year-spanning optional wheel matrix proving the same package across the full represented row.",
            },
            {
                "item": "BMW 430i xDrive exact numeric ratios and production-data applicability across the full G22 row span",
                "reason": "Official BMW sources now prove the current Germany-market 430i xDrive naming, model code 51HB, drivetrain, transmission wording, and current 17/18/19-inch tire matrix, but the checked 03/2021 launch technical-data PDF does not list 430i xDrive and this pass did not recover any official exact 430i xDrive final-drive, top-gear, forward-ratio, or reverse-ratio table.",
            },
        ],
    )
    _assert_contains_unresolved(
        sources["Audi|A3 (8Y, 2021-2026)"],
        [
            {
                "item": "Broad-row Audi A3 8Y 35 TFSI production-data applicability across the represented span",
                "reason": "Checked exact Germany-market MY2026 35 TFSI Limousine sources now prove both manual and S tronic ratio packages, but this pass did not recover year-by-year official sheets proving one unchanged 2021-2026 production mapping.",
            },
            {
                "item": "Schema-safe encoding of Audi A3 8Y 35 TFSI transmission-specific final drives",
                "reason": "The checked official 35 TFSI manuals publish 4.235 / 4.235 final drives and the S tronic PDFs publish 4.800 / 3.429, but the current broad row only stores one final_drive_ratio per gearbox entry and cannot safely represent both exact transmission-specific packages without a variant split.",
            },
        ],
    )
    _assert_contains_unresolved(
        sources["Audi|A4 (B9, 2016-2025)"],
        [
            {
                "item": "Broad-row Audi A4 B9 35 TDI production-data applicability across the represented span",
                "reason": "Checked exact late-B9 Germany 35 TDI sedan PDFs resolve a 120 kW S tronic ratio package with final drive 4.048 and basic tire 205/60 R16, but this pass did not recover year-spanning official sheets proving the same package across the full represented 2019-2025 state.",
            },
            {
                "item": "Audi A4 B9 35 TDI gearbox-family code, optional tire matrix, and 2025 Germany continuity",
                "reason": "Official Audi exact material proves the late-B9 35 TDI drivetrain, full ratio set, reverse ratio, final drive 4.048, and the 205/60 R16 basic tire, but it does not publish a gearbox-family code, a full optional wheel/tire matrix, or an exact checked Germany 2025 carry-over document.",
            },
        ],
    )
    _assert_contains_unresolved(
        sources["Audi|Q5 (FY, 2017-2026)"],
        [
            {
                "item": "Whether Audi Q5 FY 35 TDI quattro belongs in the broad row at all",
                "reason": "Checked official Germany-market FY 35 TDI technical-data sheets from 2019 and 2024 both describe front-wheel-drive Q5 35 TDI S tronic states and this pass did not recover any official Germany evidence for a 35 TDI quattro configuration.",
            },
            {
                "item": "Broad-row Audi Q5 FY 35 TDI production-data applicability, final-drive continuity, and tire-matrix scope",
                "reason": "Official Audi exact material now proves two front-wheel-drive 35 TDI FY states with the same forward ratio set, reverse ratio, and 235/65 R17 basic tire but different final drives 5.302 and 4.885, while Audi's own model page still scopes FY Q5 only 'bis 2024'; no safe broad production mapping or full optional wheel/tire matrix is closed yet.",
            },
        ],
    )


def test_wave12_variant_source_doc_tracks_g42_220i_override() -> None:
    assert (
        "| 220i | B48 2.0L I4 Turbo | RWD | 8-speed Steptronic transmission FD 2.813 TG 0.640 | BMW PressClub technical data / DE price lists | High |"
        in _VARIANT_SOURCES_FILE.read_text(encoding="utf-8")
    )
