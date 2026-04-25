"""Focused regressions for the eleventh Audi/BMW ratio-research wave."""

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


def test_wave11_ratio_source_rows_capture_g42_g02_a5_q3_q5_context() -> None:
    sources = _ratio_sources()

    assert "official_230i_market_scope_contradiction" in sources["BMW|2 Series Coupe (G42, 2022-2026)"]["sources"]
    assert "official_xdrive20i_exact_ratios" in sources["BMW|X4 (G02, 2019-2025)"]["sources"]
    assert "exact_40tfsi_late_b9_ratios" in sources["Audi|A5 (B9, 2017-2024)"]["sources"]
    assert "official_40tdi_quattro_exact_ratios" in sources["Audi|Q3 (F3, 2019-2026)"]["sources"]
    assert "exact_40tdi_quattro_fy_states" in sources["Audi|Q5 (FY, 2017-2026)"]["sources"]

    _assert_contains_unresolved(sources["BMW|2 Series Coupe (G42, 2022-2026)"], [
        {
            "item": "Whether BMW 230i xDrive belongs in the G42 row at all",
            "reason": "Checked official BMW Germany/EU sources now consistently show 230i as rear-wheel drive and reserve xDrive for M240i xDrive, but this pass did not recover enough official non-Germany market evidence to prove whether the existing AWD 230i variant is an intentional non-EU/global carry-over or simply unsupported library data.",
        },
        {
            "item": "EU applicability of the existing '6-speed manual' gearbox entry across 2022-2026 range",
            "reason": "Checked official BMW Germany/EU launch and current-market material consistently points at 8-speed automatic/Steptronic-only support for the visible petrol lineup, but this pass still did not recover one full official transmission matrix proving when, where, or whether the broad-row 6-speed manual entry applies.",
        },
    ])
    _assert_contains_unresolved(sources["BMW|X4 (G02, 2019-2025)"], [
        {
            "item": "BMW X4 xDrive20i exact gear-ratio and reverse-ratio applicability across the full G02 row span",
            "reason": "Official BMW xDrive20i technical-data sheets now prove final drive 3.385, top gear 0.640, and the standard 225/60 R18 fitment, but the full forward and reverse ratios differ between the checked 04/2018 and 03/2021 documents, so one shared production mapping would be inaccurate without a year split.",
        },
        {
            "item": "BMW X4 xDrive20i current optional wheel/tire matrix applicability and transmission subtype code",
            "reason": "Official BMW sources now prove the current Germany-market xDrive20i tire matrix and 8-Gang Steptronic wording, but they do not publish a gearbox subtype code or one exact official matrix proving unchanged 19/20/21-inch applicability across the full represented row.",
        },
    ])
    _assert_contains_unresolved(sources["Audi|A5 (B9, 2017-2024)"], [
        {
            "item": "Broad-row Audi A5 B9 40 TFSI production-data applicability across the full represented span",
            "reason": "Checked exact late-B9 Germany Coupé and Sportback PDFs resolve the 150 kW 40 TFSI mapping, but official 2020 launch material still shows an earlier 140 kW 40 TFSI state and this pass did not recover the early exact technical-data sheets needed to prove one unchanged 2019-2024 package.",
        },
        {
            "item": "Audi A5 B9 40 TFSI transmission-code and optional tire-matrix confirmation",
            "reason": "Official Audi exact material now proves the late-B9 40 TFSI drivetrain, full ratio set, reverse ratio, final drive 4.234, and the 225/50 R17 basic tire, but it does not publish the gearbox-family code or a full optional wheel/tire matrix for the exact 40 TFSI target.",
        },
    ])
    _assert_contains_unresolved(sources["Audi|Q3 (F3, 2019-2026)"], [
        {
            "item": "Audi Q3 40 TDI quattro production-data applicability across the represented old-generation row span",
            "reason": "Checked exact Germany-market 05.06.2025 Q3 and Q3 Sportback technical-data PDFs resolve the old-generation 40 TDI quattro mapping, but this pass did not recover year-by-year official sheets proving one unchanged diesel package across the full represented span.",
        },
        {
            "item": "Schema-safe encoding of exact Audi Q3 40 TDI quattro split final-drive values",
            "reason": "The checked official 40 TDI quattro technical-data PDFs publish two final-drive values 4.813 / 3.667 for the target, but the current row stores only one final_drive_ratio field and the exact old-generation optional tire matrix still remains unresolved.",
        },
    ])
    _assert_contains_unresolved(sources["Audi|Q5 (FY, 2017-2026)"], [
        {
            "item": "Broad-row Audi Q5 FY 40 TDI quattro production-data applicability across the represented span",
            "reason": "Checked official Germany-market FY evidence now proves at least two contradictory 40 TDI quattro states within the represented row: a 2019 6-speed manual package with final drive 2.647 and a 2024 7-speed S tronic package with final drive 5.302, so no single production mapping is safe without a year split.",
        },
        {
            "item": "Audi Q5 FY 40 TDI quattro exact optional tire matrix, gearbox-family code, and FY boundary",
            "reason": "Official Audi exact material now proves both the 2019 manual and 2024 S tronic 40 TDI quattro ratio packages and the shared 235/65 R17 basic tire, but it does not publish a gearbox-family code, a full optional wheel/tire matrix, or any FY continuity beyond Audi's own 'bis 2024' boundary.",
        },
    ])
