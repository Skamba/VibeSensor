"""Focused regressions for the eighth Audi/BMW ratio-research wave."""

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


def test_wave8_x7_xdrive40i_uses_exact_official_variant_override() -> None:
    x7 = resolve_variant(_entry_for("BMW", "X7 (G07, 2019-2026)"), "xDrive40i")
    assert x7["gearboxes"] == [
        {
            "name": "8-speed Steptronic transmission",
            "final_drive_ratio": pytest.approx(3.636),
            "top_gear_ratio": pytest.approx(0.64),
            "gear_ratios": pytest.approx([5.25, 3.36, 2.172, 1.72, 1.316, 1.0, 0.822, 0.64]),
        }
    ]
    assert x7["tire_options"] == [
        {
            "name": 'Standard 20"',
            "tire_width_mm": pytest.approx(275.0),
            "tire_aspect_pct": pytest.approx(50.0),
            "rim_in": pytest.approx(20.0),
        },
        {
            "name": 'Optional 21"',
            "tire_width_mm": pytest.approx(285.0),
            "tire_aspect_pct": pytest.approx(45.0),
            "rim_in": pytest.approx(21.0),
        },
        {
            "name": 'Optional staggered 22"',
            "tire_width_mm": pytest.approx(315.0),
            "tire_aspect_pct": pytest.approx(35.0),
            "rim_in": pytest.approx(22.0),
            "front": {
                "width_mm": pytest.approx(275.0),
                "aspect_pct": pytest.approx(40.0),
                "rim_in": pytest.approx(22.0),
            },  # noqa: E501
            "rear": {
                "width_mm": pytest.approx(315.0),
                "aspect_pct": pytest.approx(35.0),
                "rim_in": pytest.approx(22.0),
            },  # noqa: E501
            "default_axle_for_speed": "rear",
            "source_confidence": "official_exact",
        },
        {
            "name": 'Optional staggered 23"',
            "tire_width_mm": pytest.approx(315.0),
            "tire_aspect_pct": pytest.approx(30.0),
            "rim_in": pytest.approx(23.0),
            "front": {
                "width_mm": pytest.approx(275.0),
                "aspect_pct": pytest.approx(35.0),
                "rim_in": pytest.approx(23.0),
            },  # noqa: E501
            "rear": {
                "width_mm": pytest.approx(315.0),
                "aspect_pct": pytest.approx(30.0),
                "rim_in": pytest.approx(23.0),
            },  # noqa: E501
            "default_axle_for_speed": "rear",
            "source_confidence": "official_exact",
        },
    ]


def test_wave8_ratio_source_rows_capture_a7_a8_r8_x7_context() -> None:
    sources = _ratio_sources()

    assert (
        "official_55tfsi_quattro_exact_ratios"
        in sources["Audi|A7 Sportback (C8, 2019-2026)"]["sources"]
    )  # noqa: E501
    assert "official_55tfsi_quattro_exact_ratios" in sources["Audi|A8 (D5, 2018-2026)"]["sources"]
    assert "official_v10_quattro_exact_mapping" in sources["Audi|R8 (4S, 2015-2024)"]["sources"]
    assert "official_xdrive40i_exact_ratios" in sources["BMW|X7 (G07, 2019-2026)"]["sources"]
    assert "official_xdrive40i_tire_context" in sources["BMW|X7 (G07, 2019-2026)"]["sources"]
    assert "official_sdrive30i_exact_ratios" in sources["BMW|Z4 (G29, 2019-2026)"]["sources"]
    assert "official_sdrive30i_current_context" in sources["BMW|Z4 (G29, 2019-2026)"]["sources"]

    assert sources["Audi|A7 Sportback (C8, 2019-2026)"]["unresolved"] == [
        {
            "item": "Audi A7 Sportback 45 TFSI quattro production-data applicability across the full C8 row span",  # noqa: E501
            "reason": "Checked exact Germany-market evidence resolves the late-cycle 195 kW 45 TFSI quattro mapping, but this pass did not recover a launch-year or 2026 technical-data sheet that proves the same package across the full 2019-2026 row span.",  # noqa: E501
        },
        {
            "item": "Audi A7 Sportback 55 TFSI quattro production-data applicability across the full C8 row span",  # noqa: E501
            "reason": "Checked exact Germany-market evidence resolves the late-cycle 250 kW 55 TFSI quattro mapping, but this pass did not recover an exact 2019-era technical-data sheet proving the same package across the full 2019-2026 row span.",  # noqa: E501
        },
        {
            "item": "Mixed 45/55 TFSI row applicability for exact A7 Sportback quattro data",
            "reason": "The broad production row still mixes 45 TFSI quattro and 55 TFSI quattro variants, so the checked exact ratio and tire packages should remain source-ledger-only until the row shape is split or variant-scoped continuity is proved.",  # noqa: E501
        },
        {
            "item": "Audi A7 Sportback exact transmission-code and optional tire-matrix confirmation",  # noqa: E501
            "reason": "Official Audi exact material proves the 7-speed S tronic wording, full ratio sets, final drive 4.410, and the basic 225/55 R18 fitment, but it does not publish the transmission code or the full optional wheel and tire matrix.",  # noqa: E501
        },
    ]
    _assert_contains_unresolved(
        sources["Audi|A8 (D5, 2018-2026)"],
        [
            {
                "item": "Audi A8 55 TFSI quattro production-data applicability across the full D5 row span",  # noqa: E501
                "reason": "Checked exact Germany-market evidence resolves the late-cycle 55 TFSI quattro mapping for 2025-2026, but this pass did not recover official 2018-2024 technical-data sheets proving the same ratio and tire package across the full represented span.",  # noqa: E501
            },
            {
                "item": "Audi A8 55 TFSI quattro exact transmission-code and non-basic tire-option coverage",  # noqa: E501
                "reason": "Official Audi exact material proves 8-speed tiptronic wording, the full ratio set, final drive 3.076, and the 235/55 R18 basic tire, but it does not publish a gearbox-family code, an exact staggered setup, or a full optional wheel/tire matrix for the target.",  # noqa: E501
            },
        ],
    )
    assert sources["Audi|R8 (4S, 2015-2024)"]["unresolved"] == [
        {
            "item": "Audi R8 V10 quattro production-data applicability across the full 2015-2024 row span",  # noqa: E501
            "reason": "Checked official material cleanly proves the V10 quattro naming and exact mapping from the 2019 facelift onward, but this pass did not recover a non-contradictory official pre-facelift AWD technical-data sheet proving the same package across the full represented span.",  # noqa: E501
        },
        {
            "item": "Schema-safe encoding of exact Audi R8 V10 quattro final-drive and ratio data",
            "reason": "The checked official 2019+ V10 quattro technical-data sheet publishes dual final-drive values 1.848 / 1.488 and Audi-form ratio data that do not map safely into the current single final_drive_ratio and top_gear_ratio fields without interpretation.",  # noqa: E501
        },
    ]
    assert sources["BMW|X7 (G07, 2019-2026)"]["unresolved"] == [
        {
            "item": "BMW X7 (G07, 2019-2026) full EU variant matrix beyond the exact xDrive40i and M60i xDrive mappings",  # noqa: E501
            "reason": "This pass resolved exact official xDrive40i and M60i xDrive transmissions, final drives, and tire fitments, but it did not establish the full official matrix for every other G07 variant represented by the broad row, especially xDrive40d.",  # noqa: E501
        },
        {
            "item": "BMW X7 xDrive40i and M60i xDrive public gearbox naming/subtype consistency",
            "reason": "Official BMW sources align on the numeric ratio sets, but public wording varies between '8-speed Steptronic transmission', '8-Gang Steptronic Getriebe', and later sport-oriented wording, and no checked official source publishes a subtype code.",  # noqa: E501
        },
    ]
    assert sources["BMW|Z4 (G29, 2019-2026)"]["unresolved"] == [
        {
            "item": "BMW Z4 M40i exact DE/EU manual final-drive and ratio confirmation",
            "reason": "Checked official BMW sources now prove that the Pure Impulse edition reintroduced a 6-speed manual for the Z4 M40i, but this pass did not recover an exact Germany or ACEA technical-data source with numeric manual ratios, top gear, or final drive.",  # noqa: E501
        },
        {
            "item": "Broad-row promotion of exact Z4 sDrive30i and M40i automatic ratios",
            "reason": "The current production row still mixes sDrive20i, sDrive30i, and M40i variants and also spans both automatic-only and later manual-capable M40i years, so the exact sDrive30i and M40i automatic mappings should remain source-ledger-only until the row shape is split or variant-scoped continuity is proved.",  # noqa: E501
        },
        {
            "item": "BMW Z4 sDrive30i later-year tire continuity and M40i optional tire-matrix coverage",  # noqa: E501
            "reason": "Official ACEA automatic specs prove the exact sDrive30i 17-inch staggered base setup and the M40i 18-inch staggered base setup, while checked later BMW material confirms ongoing sDrive30i automatic continuity and Pure Impulse-era M40i wheel context, but this pass did not recover one official Germany-market matrix that safely unifies the full 2019-2026 tire coverage.",  # noqa: E501
        },
    ]


def test_wave8_variant_source_doc_tracks_x7_override_update() -> None:
    assert (
        "| xDrive40i | B58 3.0L I6 Turbo | AWD | 8-speed Steptronic FD 3.636 TG 0.640 | BMW PressClub technical data | High |"  # noqa: E501
        in _VARIANT_SOURCES_FILE.read_text(encoding="utf-8")
    )
