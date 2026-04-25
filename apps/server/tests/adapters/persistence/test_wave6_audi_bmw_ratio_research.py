"""Focused regressions for the sixth Audi/BMW ratio-research wave."""

from __future__ import annotations

import json

from vibesensor.adapters.persistence.car_library import _DATA_FILE

_RATIO_SOURCES_FILE = _DATA_FILE.with_name("car_library_ratio_sources.json")


def _ratio_sources() -> dict[str, dict[str, object]]:
    with _RATIO_SOURCES_FILE.open(encoding="utf-8") as fh:
        return json.load(fh)["cars"]


def test_wave6_ratio_source_rows_capture_exact_audi_and_z4_context_without_overwriting_broad_rows() -> None:
    sources = _ratio_sources()

    assert "official_45tfsi_quattro_exact_ratios" in sources["Audi|A6 (C8, 2019-2026)"]["sources"]
    assert "official_55tfsi_quattro_exact_ratios" in sources["Audi|A6 (C8, 2019-2026)"]["sources"]
    assert "official_45tfsi_quattro_exact_ratios" in sources["Audi|A7 Sportback (C8, 2019-2026)"]["sources"]
    assert "official_55tfsi_quattro_exact_ratios" in sources["Audi|Q8 (4M8, 2019-2026)"]["sources"]
    assert "official_m40i_automatic_exact_ratios" in sources["BMW|Z4 (G29, 2019-2026)"]["sources"]
    assert "official_m40i_manual_context" in sources["BMW|Z4 (G29, 2019-2026)"]["sources"]

    assert sources["Audi|A6 (C8, 2019-2026)"]["unresolved"] == [
        {
            "item": "Audi A6 45 TFSI quattro production-data applicability across the full C8 row span",
            "reason": "Checked exact 2024 Germany-market evidence resolves the late-cycle 195 kW 45 TFSI quattro ratio and basic-tire mapping, but this pass did not recover an earlier exact 180 kW or launch-era technical-data sheet that proves the same package across the full 2019-2026 span.",
        },
        {
            "item": "Audi A6 55 TFSI quattro production-data applicability across the full C8 row span",
            "reason": "Checked exact 2024 Germany-market evidence resolves the late-cycle 250 kW 55 TFSI quattro mapping, but a related 2026-era official sedan sheet already changes the upper ratios, so a broad-row overwrite would be unsafe without a proven year split.",
        },
        {
            "item": "Audi A6 exact transmission-code and optional tire-matrix confirmation",
            "reason": "Official Audi sheets prove the 7-speed S tronic wording, full ratio sets, and basic tires for the checked exact variants, but they do not publish the transmission code or the full optional wheel and tire matrix.",
        },
    ]
    assert sources["Audi|A7 Sportback (C8, 2019-2026)"]["unresolved"] == [
        {
            "item": "Audi A7 Sportback 45 TFSI quattro production-data applicability across the full C8 row span",
            "reason": "Checked exact Germany-market evidence resolves the late-cycle 195 kW 45 TFSI quattro mapping, but this pass did not recover a launch-year or 2026 technical-data sheet that proves the same package across the full 2019-2026 row span.",
        },
        {
            "item": "Mixed 45/55 TFSI row applicability for exact A7 Sportback 45 TFSI quattro data",
            "reason": "The broad production row still mixes 45 TFSI quattro and 55 TFSI quattro variants, so the checked exact 45 TFSI quattro ratio and tire package should remain source-ledger-only until the row shape is split or variant-scoped continuity is proved.",
        },
        {
            "item": "Audi A7 Sportback exact transmission-code and optional tire-matrix confirmation",
            "reason": "Official Audi exact material proves the 7-speed S tronic wording, full ratio set, final drive 4.410, and the basic 225/55 R18 fitment, but it does not publish the transmission code or the full optional wheel and tire matrix.",
        },
    ]
    assert sources["Audi|Q8 (4M8, 2019-2026)"]["unresolved"] == [
        {
            "item": "Schema-safe encoding of the official Audi Q8 final-drive expression",
            "reason": "The checked exact Audi technical-data sheet prints the final-drive field as 3.504 / 1.000 rather than one scalar value, so the current single final_drive_ratio field cannot safely absorb it without a documented mapping rule.",
        },
        {
            "item": "Audi Q8 exact tire-baseline and option continuity across the full 2019-2026 row span",
            "reason": "The checked exact technical-data sheet proves a 265/55 R19 basic tire, while later official market material uses different base or option sizes, so this pass did not prove one representative tire baseline for the full row.",
        },
        {
            "item": "Audi Q8 exact gearbox-family naming and early Germany-market continuity",
            "reason": "Official Audi sources prove 8-speed tiptronic wording, top gear 0.640, and the exact forward ratio set, but this pass did not recover an early Germany-market ratio sheet or an explicit gearbox-family code such as ZF 8HP.",
        },
    ]
    assert sources["BMW|Z4 (G29, 2019-2026)"]["unresolved"] == [
        {
            "item": "BMW Z4 M40i exact DE/EU manual final-drive and ratio confirmation",
            "reason": "Checked official BMW sources now prove that the Pure Impulse edition reintroduced a 6-speed manual for the Z4 M40i, but this pass did not recover an exact Germany or ACEA technical-data source with numeric manual ratios, top gear, or final drive.",
        },
        {
            "item": "Broad-row promotion of exact Z4 M40i automatic ratios",
            "reason": "The current production row still mixes sDrive20i, sDrive30i, and M40i variants and also spans both automatic-only and later manual-capable M40i years, so the exact M40i automatic mapping should remain source-ledger-only until the row shape is split or variant-scoped continuity is proved.",
        },
        {
            "item": "BMW Z4 M40i official optional tire-matrix continuity across automatic and Pure Impulse eras",
            "reason": "Official ACEA automatic specs prove the staggered 18-inch base setup, while the checked Pure Impulse material proves later mixed 19/20-inch wheel context, but this pass did not recover one official Germany-market matrix that safely unifies the full 2019-2026 tire coverage.",
        },
    ]
