"""Focused regressions for the fourteenth Audi/BMW ratio-research wave."""

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


def test_wave14_ratio_source_rows_capture_g20_g30_a8_q7_context() -> None:
    sources = _ratio_sources()

    assert "official_320i_exact_ratios" in sources["BMW|3 Series (G20, 2019-2025)"]["sources"]
    assert "official_330i_rwd_exact_context" in sources["BMW|3 Series (G20, 2019-2025)"]["sources"]
    assert "official_530i_de_launch_context" in sources["BMW|5 Series (G30, 2017-2023)"]["sources"]
    assert "official_50tfsi_quattro_scope_contradiction" in sources["Audi|A8 (D5, 2018-2026)"]["sources"]
    assert "official_45tfsi_quattro_scope_contradiction" in sources["Audi|Q7 (4M, 2016-2026)"]["sources"]

    _assert_contains_unresolved(
        sources["BMW|3 Series (G20, 2019-2025)"],
        [
            {
                "item": "BMW G20 320i production-data applicability across the full 2019-2025 row span",
                "reason": "Official 03/2021 and 07/2022 BMW technical-data sheets now prove one exact 320i RWD ratio package and show the baseline tire moving from 205/60 R16 to 225/50 R17, while the checked 2024 Germany price list confirms later automatic-only RWD continuity, but this pass did not recover a current exact numeric table proving one unchanged production mapping across the full represented span.",
            },
            {
                "item": "BMW G20 330i RWD Germany-market continuity and exact tire-option coverage",
                "reason": "Official 03/2021 BMW technical-data now proves the exact 330i RWD ratio package and 225/50 R17 baseline tire, but checked current Germany material is split between a 330i technical-data page and an xDrive-led overview, and this pass did not recover an extracted later official price-list or technical-data table closing plain-RWD continuity and wheel options across the full represented span.",
            },
        ],
    )
    _assert_contains_unresolved(
        sources["BMW|5 Series (G30, 2017-2023)"],
        [
            {
                "item": "BMW G30 530i official tire baseline and later-year continuity",
                "reason": "The recovered official BMW Germany launch price list proves a 225/55 R17 baseline with 18/19/20-inch options for the 530i, contradicting the current broad-row tire defaults, but this pass did not recover later official archived price lists proving one year-spanning 2017-2023 530i wheel matrix safe enough for a production rewrite.",
            }
        ],
    )
    _assert_contains_unresolved(
        sources["Audi|A8 (D5, 2018-2026)"],
        [
            {
                "item": "Exact Germany-market Audi A8 50 TFSI quattro mapping",
                "reason": "Checked official Germany search and facelift material resolve the petrol D5 A8 to 55 TFSI quattro, while Audi explicitly describes the lower-output 210 kW 3.0 TFSI variant as China-only, so this pass did not recover an official Germany 50 TFSI quattro technical-data sheet or price-list row.",
            }
        ],
    )
    _assert_contains_unresolved(
        sources["Audi|Q7 (4M, 2016-2026)"],
        [
            {
                "item": "Exact Germany-market Audi Q7 45 TFSI quattro mapping",
                "reason": "Checked official Germany launch/current Q7 model pages, press releases, and 2020/2026 price-list material resolve the petrol SUV to 55 TFSI quattro / 250 kW instead, and this pass did not recover an official Germany 45 TFSI quattro technical-data sheet that would justify reusing the 55 TFSI data.",
            }
        ],
    )
