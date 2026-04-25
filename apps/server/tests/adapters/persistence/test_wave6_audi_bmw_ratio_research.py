"""Focused regressions for the sixth Audi/BMW ratio-research wave."""

from __future__ import annotations

import json

from vibesensor.adapters.persistence.car_library import _DATA_FILE

_RATIO_SOURCES_FILE = _DATA_FILE.with_name("car_library_ratio_sources.json")


def _ratio_sources() -> dict[str, dict[str, object]]:
    with _RATIO_SOURCES_FILE.open(encoding="utf-8") as fh:
        return json.load(fh)["cars"]


def _assert_contains_unresolved(entry: dict[str, object], expected: list[dict[str, str]]) -> None:
    unresolved = entry["unresolved"]
    for item in expected:
        assert item in unresolved


def test_wave6_ratio_source_rows_capture_exact_audi_and_z4_context_without_overwriting_broad_rows() -> (
    None
):  # noqa: E501
    sources = _ratio_sources()

    assert "official_45tfsi_quattro_exact_ratios" in sources["Audi|A6 (C8, 2019-2026)"]["sources"]
    assert "official_55tfsi_quattro_exact_ratios" in sources["Audi|A6 (C8, 2019-2026)"]["sources"]
    assert (
        "official_45tfsi_quattro_exact_ratios"
        in sources["Audi|A7 Sportback (C8, 2019-2026)"]["sources"]
    )  # noqa: E501
    assert "official_55tfsi_quattro_exact_ratios" in sources["Audi|Q8 (4M8, 2019-2026)"]["sources"]
    assert "official_m40i_automatic_exact_ratios" in sources["BMW|Z4 (G29, 2019-2026)"]["sources"]
    assert "official_m40i_manual_context" in sources["BMW|Z4 (G29, 2019-2026)"]["sources"]

    assert sources["Audi|A6 (C8, 2019-2026)"]["unresolved"] == [
        {
            "item": "Audi A6 45 TFSI quattro production-data applicability across the full C8 row span",  # noqa: E501
            "reason": "Checked exact 2024 Germany-market evidence resolves the late-cycle 195 kW 45 TFSI quattro ratio and basic-tire mapping, but this pass did not recover an earlier exact 180 kW or launch-era technical-data sheet that proves the same package across the full 2019-2026 span.",  # noqa: E501
        },
        {
            "item": "Audi A6 55 TFSI quattro production-data applicability across the full C8 row span",  # noqa: E501
            "reason": "Checked exact 2024 Germany-market evidence resolves the late-cycle 250 kW 55 TFSI quattro mapping, but a related 2026-era official sedan sheet already changes the upper ratios, so a broad-row overwrite would be unsafe without a proven year split.",  # noqa: E501
        },
        {
            "item": "Audi A6 exact transmission-code and optional tire-matrix confirmation",
            "reason": "Official Audi sheets prove the 7-speed S tronic wording, full ratio sets, and basic tires for the checked exact variants, but they do not publish the transmission code or the full optional wheel and tire matrix.",  # noqa: E501
        },
    ]
    _assert_contains_unresolved(
        sources["Audi|A7 Sportback (C8, 2019-2026)"],
        [
            {
                "item": "Audi A7 Sportback 45 TFSI quattro production-data applicability across the full C8 row span",  # noqa: E501
                "reason": "Checked exact Germany-market evidence resolves the late-cycle 195 kW 45 TFSI quattro mapping, but this pass did not recover a launch-year or 2026 technical-data sheet that proves the same package across the full 2019-2026 row span.",  # noqa: E501
            },
            {
                "item": "Audi A7 Sportback exact transmission-code and optional tire-matrix confirmation",  # noqa: E501
                "reason": "Official Audi exact material proves the 7-speed S tronic wording, full ratio sets, final drive 4.410, and the basic 225/55 R18 fitment, but it does not publish the transmission code or the full optional wheel and tire matrix.",  # noqa: E501
            },
        ],
    )
    _assert_contains_unresolved(
        sources["Audi|Q8 (4M8, 2019-2026)"],
        [
            {
                "item": "Schema-safe encoding of the official Audi Q8 final-drive expression",
                "reason": "The checked exact Audi technical-data sheet prints the final-drive field as 3.504 / 1.000 rather than one scalar value, so the current single final_drive_ratio field cannot safely absorb it without a documented mapping rule.",  # noqa: E501
            },
            {
                "item": "Audi Q8 exact tire-baseline and option continuity across the full 2019-2026 row span",  # noqa: E501
                "reason": "The checked exact technical-data sheet proves a 265/55 R19 basic tire, while later official market material uses different base or option sizes, so this pass did not prove one representative tire baseline for the full row.",  # noqa: E501
            },
            {
                "item": "Audi Q8 exact gearbox-family naming and early Germany-market continuity",
                "reason": "Official Audi sources prove 8-speed tiptronic wording, top gear 0.640, and the exact forward ratio set, but this pass did not recover an early Germany-market ratio sheet or an explicit gearbox-family code such as ZF 8HP.",  # noqa: E501
            },
        ],
    )
    _assert_contains_unresolved(
        sources["BMW|Z4 (G29, 2019-2026)"],
        [
            {
                "item": "BMW Z4 M40i exact DE/EU manual final-drive and ratio confirmation",
                "reason": "Checked official BMW sources now prove that the Pure Impulse edition reintroduced a 6-speed manual for the Z4 M40i, but this pass did not recover an exact Germany or ACEA technical-data source with numeric manual ratios, top gear, or final drive.",  # noqa: E501
            },
            {
                "item": "BMW Z4 sDrive30i later-year tire continuity and M40i optional tire-matrix coverage",  # noqa: E501
                "reason": "Official ACEA automatic specs prove the exact sDrive30i 17-inch staggered base setup and the M40i 18-inch staggered base setup, while checked later BMW material confirms ongoing sDrive30i automatic continuity and Pure Impulse-era M40i wheel context, but this pass did not recover one official Germany-market matrix that safely unifies the full 2019-2026 tire coverage.",  # noqa: E501
            },
        ],
    )
