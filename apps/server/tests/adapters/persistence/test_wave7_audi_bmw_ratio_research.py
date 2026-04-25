"""Focused regressions for the seventh Audi/BMW ratio-research wave."""

from __future__ import annotations

import json

from vibesensor.adapters.persistence.car_library import _DATA_FILE

_RATIO_SOURCES_FILE = _DATA_FILE.with_name("car_library_ratio_sources.json")


def _ratio_sources() -> dict[str, dict[str, object]]:
    with _RATIO_SOURCES_FILE.open(encoding="utf-8") as fh:
        return json.load(fh)["cars"]


def test_wave7_ratio_source_rows_capture_exact_tt_rs_q7_x5_context_without_overwriting_broad_rows() -> (  # noqa: E501
    None
):  # noqa: E501
    sources = _ratio_sources()

    assert "official_45tfsi_quattro_exact_ratios" in sources["Audi|TT (8S, 2015-2023)"]["sources"]
    assert "official_rs4_exact_ratios" in sources["Audi|RS 4 Avant (B9, 2018-2024)"]["sources"]
    assert "official_rs5_exact_ratios" in sources["Audi|RS 5 (B9, 2018-2024)"]["sources"]
    assert "official_55tfsi_quattro_exact_ratios" in sources["Audi|Q7 (4M, 2016-2026)"]["sources"]
    assert "official_xdrive40i_exact_ratios" in sources["BMW|X5 (G05, 2019-2026)"]["sources"]
    assert "official_xdrive40i_tire_context" in sources["BMW|X5 (G05, 2019-2026)"]["sources"]

    assert sources["Audi|TT (8S, 2015-2023)"]["unresolved"] == [
        {
            "item": "Schema-safe encoding of the exact Audi TT 45 TFSI quattro dual final-drive values",  # noqa: E501
            "reason": "The checked exact Audi technical-data PDF publishes two final-drive values 4.471 / 3.304 for the target, but the current row stores only one final_drive_ratio field.",  # noqa: E501
        },
        {
            "item": "Audi TT 45 TFSI quattro production-data applicability across the full 2015-2023 row span",  # noqa: E501
            "reason": "The checked exact 2023 Germany-market technical-data PDF resolves the late-cycle 45 TFSI quattro mapping, but this pass did not recover enough year-specific official ratio sheets to prove one unchanged package across the full represented span.",  # noqa: E501
        },
        {
            "item": "Audi TT 45 TFSI quattro exact transmission-code and non-basic tire-option coverage",  # noqa: E501
            "reason": "Official Audi sources prove 7-speed S tronic wording, the full ratio set, and the 225/50 R17 basic tire, but they do not publish the gearbox code or the full optional wheel/tire matrix for the exact target.",  # noqa: E501
        },
    ]
    assert sources["Audi|RS 4 Avant (B9, 2018-2024)"]["unresolved"] == [
        {
            "item": "Audi RS 4 Avant exact production-data applicability across the full 2018-2024 row span",  # noqa: E501
            "reason": "The checked official RS 4 Avant technical-data material resolves the later-cycle mapping, but this pass did not recover a launch-year 2018 Germany/EU sheet that proves the same ratio and tire package across the full represented span.",  # noqa: E501
        },
        {
            "item": "Audi RS 4 Avant exact transmission-code and non-basic tire-option coverage",
            "reason": "Official Audi exact material proves 8-speed tiptronic wording, the full ratio set, final drive 3.204, and the 265/35 R19 basic tire, but it does not publish a gearbox-family code or a full optional wheel/tire matrix for the plain RS 4 Avant.",  # noqa: E501
        },
    ]
    assert sources["Audi|RS 5 (B9, 2018-2024)"]["unresolved"] == [
        {
            "item": "Audi RS 5 exact production-data applicability across the full 2018-2024 row span",  # noqa: E501
            "reason": "Checked official 2019 and 2024 technical-data PDFs resolve the later B9 RS 5 Coupé mapping, but this pass did not recover a launch-year 2018 Germany/EU sheet that proves the same ratio and tire package across the full represented span.",  # noqa: E501
        },
        {
            "item": "Audi RS 5 exact transmission-code and non-basic tire-option coverage",
            "reason": "Official Audi exact material proves 8-speed tiptronic wording, the full ratio set, final drive 3.204, and the 265/35 R19 basic tire, but it does not publish a gearbox-family code or the exact optional 20-inch tire dimensions for the plain RS 5 Coupé.",  # noqa: E501
        },
    ]
    assert sources["BMW|X5 (G05, 2019-2026)"]["unresolved"] == [
        {
            "item": "BMW X5 xDrive40i production-data applicability across the full G05 row span",
            "reason": "Official launch-era xDrive40i specs prove final drive 3.385, top gear 0.640, and a 255/55 R18 standard tire, while later Germany-market material changes the gearbox wording and the standard tire to 265/50 R19, so one undifferentiated 2019-2026 xDrive40i production mapping would be unsafe.",  # noqa: E501
        },
        {
            "item": "BMW X5 (G05, 2019-2026) full EU variant matrix beyond the exact xDrive45e and xDrive40i mappings",  # noqa: E501
            "reason": "This pass now resolves exact official xDrive45e and launch-era xDrive40i mappings, but it does not establish the complete official matrix for the other G05 variants represented by the broad row.",  # noqa: E501
        },
        {
            "item": "BMW X5 transmission subtype code and full optional wheel/tire matrix",
            "reason": "Official BMW sources prove transmission names, ratios, and standard or selected option tires for the checked exact variants, but they do not publish a gearbox subtype code or one complete optional wheel/tire matrix across the represented row.",  # noqa: E501
        },
    ]
