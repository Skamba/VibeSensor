"""Focused regressions for the tenth Audi/BMW ratio-research wave."""

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


def test_wave10_ratio_source_rows_capture_g22_g01_g02_q5_context() -> None:
    sources = _ratio_sources()

    assert (
        "official_430i_xdrive_current_context"
        in sources["BMW|4 Series (G22, 2021-2026)"]["sources"]
    )  # noqa: E501
    assert "official_m40i_exact_ratios" in sources["BMW|X3 (G01, 2018-2024)"]["sources"]
    assert "official_xdrive30i_exact_ratios" in sources["BMW|X4 (G02, 2019-2025)"]["sources"]
    assert "exact_40tfsi_quattro_late_fy_ratios" in sources["Audi|Q5 (FY, 2017-2026)"]["sources"]

    _assert_contains_unresolved(
        sources["BMW|4 Series (G22, 2021-2026)"],
        [
            {
                "item": "Whether this row should later expand beyond the supported petrol-family slice",
                "reason": "BMW Germany technical data confirms additional diesel xDrive variants, but issue #1034 stays narrowly focused on the confirmed petrol-family mismatch rather than broadening the supported row to every current market slice.",  # noqa: E501
            },
            {
                "item": "BMW 430i xDrive exact numeric ratios and production-data applicability across the full G22 row span",  # noqa: E501
                "reason": "Official BMW sources now prove the current Germany-market 430i xDrive naming, model code 51HB, drivetrain, transmission wording, and current 17/18/19-inch tire matrix, but the checked 03/2021 launch technical-data PDF does not list 430i xDrive and this pass did not recover any official exact 430i xDrive final-drive, top-gear, forward-ratio, or reverse-ratio table.",  # noqa: E501
            },
            {
                "item": "BMW M440i xDrive production-data applicability across the full G22 row span",
                "reason": "The checked official 07/2021 ACEA sheet resolves the M440i xDrive launch ratios, final drive, top gear, and staggered base tires, but later official Germany-market pages already show a different published output state and this pass did not recover later exact ratio/tire tables proving one unchanged 2021-2026 package.",  # noqa: E501
            },
            {
                "item": "BMW M440i xDrive official optional wheel/tire matrix and transmission subtype code",  # noqa: E501
                "reason": "Official BMW sources now prove the exact launch ratio set and standard staggered 18-inch fitment, but they do not publish a gearbox subtype code beyond Steptronic wording or one exact optional wheel/tire matrix for the full represented row.",  # noqa: E501
            },
        ],
    )
    _assert_contains_unresolved(
        sources["BMW|X3 (G01, 2018-2024)"],
        [
            {
                "item": "BMW X3 xDrive30i exact gear-ratio and reverse-ratio applicability across the full 2018-2024 row span",  # noqa: E501
                "reason": "Official BMW DE sheets now prove final drive 3.385, top gear 0.640, and the Germany-market tire matrix for xDrive30i, but the full forward gear ratios and reverse ratio differ between the checked 09/2018 and 06/2021 technical-data PDFs, so one shared gear-ratio array would be inaccurate without a year split.",  # noqa: E501
            },
            {
                "item": "BMW X3 M40i production-data applicability across the full 2018-2024 row span",
                "reason": "The checked official 04/2020 ACEA M40i sheet resolves final drive 3.385, top gear 0.640, the full forward ratio set, reverse ratio 3.712, and the standard staggered 245/45 R20 front + 275/40 R20 rear fitment, but this pass did not recover launch-year or later-year official sheets proving one unchanged M40i package across the full represented row.",  # noqa: E501
            },
            {
                "item": "BMW X3 (G01, 2018-2024) full EU variant matrix beyond the exact xDrive30i and M40i mappings",  # noqa: E501
                "reason": "This pass resolves the exact xDrive30i final drive, top gear, and Germany-market tire fitments and adds exact M40i source-ledger evidence, but it does not establish the full official ratio and tire matrix for the other G01 variants represented by the broad row.",  # noqa: E501
            },
            {
                "item": "BMW X3 xDrive30i and M40i transmission subtype code",
                "reason": "Official BMW sources prove 8-Gang Steptronic wording for the checked xDrive30i and M40i mappings but do not publish a gearbox subtype code such as a ZF 8HP variant number.",  # noqa: E501
            },
        ],
    )
    _assert_contains_unresolved(
        sources["BMW|X4 (G02, 2019-2025)"],
        [
            {
                "item": "BMW X4 xDrive30i exact gear-ratio and reverse-ratio applicability across the full G02 row span",  # noqa: E501
                "reason": "Official BMW xDrive30i technical-data sheets now prove final drive 3.385, top gear 0.640, and the standard 225/60 R18 fitment, but the full forward and reverse ratios differ between the checked 09/2018 and 03/2021 documents, so one shared production mapping would be inaccurate without a year split.",  # noqa: E501
            },
            {
                "item": "BMW X4 xDrive30i current optional wheel/tire matrix applicability and transmission subtype code",  # noqa: E501
                "reason": "Official BMW sources now prove the current Germany-market xDrive30i tire matrix and Steptronic Sport wording, but they do not publish a gearbox subtype code or one exact official matrix proving unchanged 19/20/21-inch applicability across the full represented row.",  # noqa: E501
            },
            {
                "item": "BMW X4 M40i production-data applicability across the full G02 row span",
                "reason": "Official BMW M40i technical-data sheets now prove two exact ratio packages within the represented 2019-2025 span, but the launch 08/2018 and 04/2020 exact sheets disagree on the full forward and reverse ratios, so one shared production mapping would be inaccurate without a year split.",  # noqa: E501
            },
            {
                "item": "BMW X4 (G02, 2019-2025) full EU variant matrix beyond the exact xDrive20i, xDrive30i, and M40i mappings",  # noqa: E501
                "reason": "This pass resolves exact official xDrive20i, xDrive30i, and M40i source-ledger evidence, but it does not establish the full official ratio and tire matrix for every other G02 variant represented by the broad row.",  # noqa: E501
            },
            {
                "item": "BMW X4 M40i exact optional wheel/tire matrix and transmission subtype code",
                "reason": "Official BMW sources now prove the exact standard staggered 20-inch M40i fitment and the checked ratio sets, but they do not publish a gearbox subtype code or one exact full optional wheel/tire matrix that closes the broad row safely.",  # noqa: E501
            },
        ],
    )
    _assert_contains_unresolved(
        sources["Audi|Q5 (FY, 2017-2026)"],
        [
            {
                "item": "Broad-row Audi Q5 FY 40 TFSI production-data applicability across the represented span",  # noqa: E501
                "reason": "The checked 06/04/2024 Germany FY sheet resolves a late-FY 40 TFSI quattro state, but this pass did not recover official earlier FY or later new-generation sheets proving one unchanged 40 TFSI package across the broad 2017-2026 row.",  # noqa: E501
            },
            {
                "item": "Audi Q5 FY 40 TFSI exact optional tire matrix and row-shape continuity",
                "reason": "Official Audi exact material now proves the FY 40 TFSI quattro drivetrain, full ratio set, reverse ratio, final drive 5.302, and the 235/65 R17 basic tire, but it does not close a full FY optional wheel/tire matrix or prove how the library's current front-drive 40 TFSI variant should be split from the later FY quattro state.",  # noqa: E501
            },
            {
                "item": "Broad-row Audi Q5 FY 55 TFSI e quattro top_gear_ratio applicability across the represented span",  # noqa: E501
                "reason": "Official Audi MediaCenter eTD PDFs now prove top gear 0.433 and the full gear-ratio set for the later 270 kW 55 TFSI e quattro configuration, but this pass did not verify whether every year represented by the broad FY row uses the same exact mapping.",  # noqa: E501
            },
        ],
    )
