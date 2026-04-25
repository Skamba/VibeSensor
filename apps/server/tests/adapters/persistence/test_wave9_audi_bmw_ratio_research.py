"""Focused regressions for the ninth Audi/BMW ratio-research wave."""

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


def test_wave9_x3_xdrive30i_uses_exact_official_variant_override() -> None:
    x3 = resolve_variant(_entry_for("BMW", "X3 (G01, 2018-2024)"), "xDrive30i")
    assert x3["gearboxes"] == [
        {
            "name": "8-speed Steptronic transmission",
            "final_drive_ratio": pytest.approx(3.385),
            "top_gear_ratio": pytest.approx(0.64),
        }
    ]
    assert x3["tire_options"] == [
        {
            "name": 'Standard 18"',
            "tire_width_mm": pytest.approx(225.0),
            "tire_aspect_pct": pytest.approx(60.0),
            "rim_in": pytest.approx(18.0),
        },
        {
            "name": 'Optional 19"',
            "tire_width_mm": pytest.approx(245.0),
            "tire_aspect_pct": pytest.approx(50.0),
            "rim_in": pytest.approx(19.0),
        },
        {
            "name": 'Optional staggered 20"',
            "tire_width_mm": pytest.approx(275.0),
            "tire_aspect_pct": pytest.approx(40.0),
            "rim_in": pytest.approx(20.0),
            "front": {
                "width_mm": pytest.approx(245.0),
                "aspect_pct": pytest.approx(45.0),
                "rim_in": pytest.approx(20.0),
            },
            "rear": {
                "width_mm": pytest.approx(275.0),
                "aspect_pct": pytest.approx(40.0),
                "rim_in": pytest.approx(20.0),
            },
            "default_axle_for_speed": "rear",
            "source_confidence": "official_exact",
        },
        {
            "name": 'Optional staggered 21"',
            "tire_width_mm": pytest.approx(275.0),
            "tire_aspect_pct": pytest.approx(35.0),
            "rim_in": pytest.approx(21.0),
            "front": {
                "width_mm": pytest.approx(245.0),
                "aspect_pct": pytest.approx(40.0),
                "rim_in": pytest.approx(21.0),
            },
            "rear": {
                "width_mm": pytest.approx(275.0),
                "aspect_pct": pytest.approx(35.0),
                "rim_in": pytest.approx(21.0),
            },
            "default_axle_for_speed": "rear",
            "source_confidence": "official_exact",
        },
    ]


def test_wave9_ratio_source_rows_capture_g22_g01_g02_q3_context() -> None:
    sources = _ratio_sources()

    g22_key = "BMW|4 Series (G22, 2021-2026)"
    g01_key = "BMW|X3 (G01, 2018-2024)"
    g02_key = "BMW|X4 (G02, 2019-2025)"
    q3_key = "Audi|Q3 (F3, 2019-2026)"

    assert "official_m440i_xdrive_launch_exact_ratios" in sources[g22_key]["sources"]
    assert "official_xdrive30i_exact_ratios" in sources[g01_key]["sources"]
    assert "official_m40i_launch_exact_ratios" in sources[g02_key]["sources"]
    assert "official_40tfsi_quattro_exact_ratios" in sources[q3_key]["sources"]

    _assert_contains_unresolved(
        sources[g22_key],
        [
            {
                "item": "Whether this row should later expand beyond the supported petrol-family slice",  # noqa: E501
                "reason": (
                    "BMW Germany technical data confirms additional diesel xDrive "
                    "variants, but issue #1034 stays narrowly focused on the "
                    "confirmed petrol-family mismatch rather than broadening the "
                    "supported row to every current market slice."
                ),
            },
            {
                "item": (
                    "BMW 430i xDrive exact numeric ratios and production-data "
                    "applicability across the full G22 row span"
                ),
                "reason": (
                    "Official BMW sources now prove the current Germany-market 430i "
                    "xDrive naming, model code 51HB, drivetrain, transmission "
                    "wording, and current 17/18/19-inch tire matrix, but the checked "
                    "03/2021 launch technical-data PDF does not list 430i xDrive and "
                    "this pass did not recover any official exact 430i xDrive "
                    "final-drive, top-gear, forward-ratio, or reverse-ratio table."
                ),
            },
            {
                "item": (
                    "BMW M440i xDrive production-data applicability across the full G22 row span"
                ),
                "reason": (
                    "The checked official 07/2021 ACEA sheet resolves the M440i "
                    "xDrive launch ratios, final drive, top gear, and staggered base "
                    "tires, but later official Germany-market pages already show a "
                    "different published output state and this pass did not recover "
                    "later exact ratio/tire tables proving one unchanged 2021-2026 "
                    "package."
                ),
            },
            {
                "item": (
                    "BMW M440i xDrive official optional wheel/tire matrix and "
                    "transmission subtype code"
                ),
                "reason": (
                    "Official BMW sources now prove the exact launch ratio set and "
                    "standard staggered 18-inch fitment, but they do not publish a "
                    "gearbox subtype code beyond Steptronic wording or one exact "
                    "optional wheel/tire matrix for the full represented row."
                ),
            },
        ],
    )
    _assert_contains_unresolved(
        sources[g01_key],
        [
            {
                "item": (
                    "BMW X3 xDrive30i exact gear-ratio and reverse-ratio "
                    "applicability across the full 2018-2024 row span"
                ),
                "reason": (
                    "Official BMW DE sheets now prove final drive 3.385, top gear "
                    "0.640, and the Germany-market tire matrix for xDrive30i, but "
                    "the full forward gear ratios and reverse ratio differ between "
                    "the checked 09/2018 and 06/2021 technical-data PDFs, so one "
                    "shared gear-ratio array would be inaccurate without a year "
                    "split."
                ),
            },
            {
                "item": (
                    "BMW X3 M40i production-data applicability across the full 2018-2024 row span"
                ),
                "reason": (
                    "The checked official 04/2020 ACEA M40i sheet resolves final "
                    "drive 3.385, top gear 0.640, the full forward ratio set, "
                    "reverse ratio 3.712, and the standard staggered 245/45 R20 "
                    "front + 275/40 R20 rear fitment, but this pass did not recover "
                    "launch-year or later-year official sheets proving one unchanged "
                    "M40i package across the full represented row."
                ),
            },
            {
                "item": (
                    "BMW X3 (G01, 2018-2024) full EU variant matrix beyond the "
                    "exact xDrive30i and M40i mappings"
                ),
                "reason": (
                    "This pass resolves the exact xDrive30i final drive, top gear, "
                    "and Germany-market tire fitments and adds exact M40i "
                    "source-ledger evidence, but it does not establish the full "
                    "official ratio and tire matrix for the other G01 variants "
                    "represented by the broad row."
                ),
            },
            {
                "item": ("BMW X3 xDrive30i and M40i transmission subtype code"),
                "reason": (
                    "Official BMW sources prove 8-Gang Steptronic wording for the "
                    "checked xDrive30i and M40i mappings but do not publish a "
                    "gearbox subtype code such as a ZF 8HP variant number."
                ),
            },
        ],
    )
    _assert_contains_unresolved(
        sources[g02_key],
        [
            {
                "item": (
                    "BMW X4 xDrive30i exact gear-ratio and reverse-ratio "
                    "applicability across the full G02 row span"
                ),
                "reason": (
                    "Official BMW xDrive30i technical-data sheets now prove final "
                    "drive 3.385, top gear 0.640, and the standard 225/60 R18 "
                    "fitment, but the full forward and reverse ratios differ "
                    "between the checked 09/2018 and 03/2021 documents, so one "
                    "shared production mapping would be inaccurate without a year "
                    "split."
                ),
            },
            {
                "item": (
                    "BMW X4 xDrive30i current optional wheel/tire matrix "
                    "applicability and transmission subtype code"
                ),
                "reason": (
                    "Official BMW sources now prove the current Germany-market "
                    "xDrive30i tire matrix and Steptronic Sport wording, but they "
                    "do not publish a gearbox subtype code or one exact official "
                    "matrix proving unchanged 19/20/21-inch applicability across the "
                    "full represented row."
                ),
            },
            {
                "item": ("BMW X4 M40i production-data applicability across the full G02 row span"),
                "reason": (
                    "Official BMW M40i technical-data sheets now prove two exact "
                    "ratio packages within the represented 2019-2025 span, but the "
                    "launch 08/2018 and 04/2020 exact sheets disagree on the full "
                    "forward and reverse ratios, so one shared production mapping "
                    "would be inaccurate without a year split."
                ),
            },
            {
                "item": (
                    "BMW X4 (G02, 2019-2025) full EU variant matrix beyond the "
                    "exact xDrive20i, xDrive30i, and M40i mappings"
                ),
                "reason": (
                    "This pass resolves exact official xDrive20i, xDrive30i, and "
                    "M40i source-ledger evidence, but it does not establish the "
                    "full official ratio and tire matrix for every other G02 "
                    "variant represented by the broad row."
                ),
            },
            {
                "item": (
                    "BMW X4 M40i exact optional wheel/tire matrix and transmission subtype code"
                ),
                "reason": (
                    "Official BMW sources now prove the exact standard staggered "
                    "20-inch M40i fitment and the checked ratio sets, but they do "
                    "not publish a gearbox subtype code or one exact full optional "
                    "wheel/tire matrix that closes the broad row safely."
                ),
            },
        ],
    )
    _assert_contains_unresolved(
        sources[q3_key],
        [
            {
                "item": (
                    "Audi Q3 40 TFSI quattro production-data applicability across "
                    "the represented old-generation row span"
                ),
                "reason": (
                    "Checked exact Germany-market 05.06.2025 Q3 and Q3 Sportback "
                    "technical-data PDFs resolve the old-generation 40 TFSI quattro "
                    "mapping, but this pass did not recover year-by-year official "
                    "sheets proving one unchanged package across the full "
                    "represented span."
                ),
            },
            {
                "item": (
                    "Schema-safe encoding of exact Audi Q3 40 TFSI quattro split final-drive values"
                ),
                "reason": (
                    "The checked official technical-data PDFs publish two "
                    "final-drive values 4.813 / 3.667 for the target, but the "
                    "current row stores only one final_drive_ratio field."
                ),
            },
            {
                "item": (
                    "Audi Q3 (F3, 2019-2026) model-year boundary, transmission-code, "
                    "and optional tire-matrix confirmation"
                ),
                "reason": (
                    "Official Audi sources now prove the old-generation exact ratio "
                    "block, reverse ratio, and basic tire, and they also show the "
                    "new third-generation Q3 arrives in summer 2025, but this pass "
                    "did not recover a full old-generation optional wheel/tire "
                    "matrix or an official gearbox-family code."
                ),
            },
        ],
    )


def test_wave9_variant_source_doc_tracks_x3_override_update() -> None:
    variant_doc = _VARIANT_SOURCES_FILE.read_text(encoding="utf-8")
    assert (
        "| xDrive30i | B48 2.0L I4 Turbo | AWD | "
        "8-speed Steptronic FD 3.385 TG 0.640 | "
        "BMW PressClub technical data / DE price list | High |"
    ) in variant_doc
