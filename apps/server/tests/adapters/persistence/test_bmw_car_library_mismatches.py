"""Regression coverage for the BMW variant and ratio-source corrections."""

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


def _entry_for(model: str) -> dict[str, object]:
    for entry in load_car_library():
        if entry["brand"] == "BMW" and entry["model"] == model:
            return entry
    raise AssertionError(f"BMW model not found: {model}")


def _variant_map(entry: dict[str, object]) -> dict[str, tuple[str, str]]:
    return {
        variant["name"]: (variant["engine"], variant["drivetrain"]) for variant in entry["variants"]
    }


def _variant_source_rows(model: str) -> list[str]:
    lines = _VARIANT_SOURCES_FILE.read_text().splitlines()
    heading = f"### {model}"
    start = lines.index(heading)
    rows: list[str] = []
    in_table = False

    for line in lines[start + 1 :]:
        if line.startswith("### "):
            break
        if line.startswith("| Variant |"):
            in_table = True
            continue
        if not in_table or line.startswith("|---------|"):
            continue
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip().split("|")[1:-1]]
            if cells and cells[0]:
                rows.append(cells[0])

    return rows


@pytest.mark.parametrize(
    ("model", "expected_variants"),
    [
        (
            "4 Series (G22, 2021-2026)",
            {
                "420i": ("B48 2.0L I4 Turbo", "RWD"),
                "430i xDrive": ("B48 2.0L I4 Turbo", "AWD"),
                "M440i xDrive": ("B58 3.0L I6 Turbo", "AWD"),
            },
        ),
        (
            "5 Series (G60, 2024-2026)",
            {
                "520i": ("B48 2.0L I4 Turbo", "RWD"),
                "i5 eDrive40": ("Electric Single Motor", "RWD"),
                "i5 M60 xDrive": ("Electric Dual Motor", "AWD"),
            },
        ),
        (
            "7 Series (G70, 2023-2026)",
            {
                "740d xDrive": ("B57 3.0L I6 Diesel", "AWD"),
                "750e xDrive": ("B58 3.0L I6 Turbo PHEV", "AWD"),
                "M760e xDrive": ("B58 3.0L I6 Turbo PHEV", "AWD"),
                "i7 eDrive50": ("Electric Single Motor", "RWD"),
                "i7 M70 xDrive": ("Electric Dual Motor", "AWD"),
            },
        ),
    ],
)
def test_confirmed_bmw_rows_match_corrected_variant_scope(
    model: str, expected_variants: dict[str, tuple[str, str]]
) -> None:
    entry = _entry_for(model)
    assert _variant_map(entry) == expected_variants


def test_f45_documented_transmissions_are_explicit() -> None:
    entry = _entry_for("2 Series Active Tourer (F45, 2014-2021)")

    assert [gearbox["name"] for gearbox in entry["gearboxes"]] == ["8-speed automatic (Aisin)"]

    resolved_220i = resolve_variant(entry, "220i")
    assert resolved_220i["gearboxes"] == [
        {
            "name": "7-speed Steptronic dual-clutch transmission",
            "final_drive_ratio": pytest.approx(3.231),
            "top_gear_ratio": pytest.approx(0.698),
        }
    ]

    resolved_225xe = resolve_variant(entry, "225xe")
    assert resolved_225xe["gearboxes"] == [
        {
            "name": "6-speed Steptronic (225xe iPerformance)",
            "final_drive_ratio": pytest.approx(3.944),
            "top_gear_ratio": pytest.approx(0.672),
        }
    ]


@pytest.mark.parametrize(
    ("model", "variant", "expected_ratio"),
    [
        ("5 Series (G60, 2024-2026)", "i5 eDrive40", 11.115),
        ("5 Series (G60, 2024-2026)", "i5 M60 xDrive", 9.374),
        ("7 Series (G70, 2023-2026)", "i7 eDrive50", 11.1),
        ("7 Series (G70, 2023-2026)", "i7 M70 xDrive", 11.1),
    ],
)
def test_confirmed_bmw_ev_variants_no_longer_inherit_ice_gearboxes(
    model: str, variant: str, expected_ratio: float
) -> None:
    entry = _entry_for(model)
    resolved = resolve_variant(entry, variant)

    assert resolved["gearboxes"] != entry["gearboxes"]
    assert resolved["gearboxes"] == [
        {
            "name": "Single-speed fixed gear (EV)",
            "final_drive_ratio": pytest.approx(expected_ratio),
            "top_gear_ratio": pytest.approx(1.0),
        }
    ]


@pytest.mark.parametrize(
    ("model", "expected_variants"),
    [
        (
            "4 Series (G22, 2021-2026)",
            ["420i", "430i xDrive", "M440i xDrive"],
        ),
        (
            "5 Series (G60, 2024-2026)",
            ["520i", "i5 eDrive40", "i5 M60 xDrive"],
        ),
        (
            "7 Series (G70, 2023-2026)",
            ["740d xDrive", "750e xDrive", "M760e xDrive", "i7 eDrive50", "i7 M70 xDrive"],
        ),
    ],
)
def test_bmw_variant_source_docs_match_corrected_rows(
    model: str, expected_variants: list[str]
) -> None:
    assert _variant_source_rows(model) == expected_variants


def test_issue_1034_ratio_source_metadata_tracks_manual_fix() -> None:
    with _RATIO_SOURCES_FILE.open() as fh:
        ratio_sources = json.load(fh)["cars"]

    assert (
        "issue_1034_220i_ratio_reference"
        in ratio_sources["BMW|2 Series Active Tourer (F45, 2014-2021)"]["sources"]
    )
    assert "issue_1034_eu_scope" in ratio_sources["BMW|7 Series (G70, 2023-2026)"]["sources"]
    assert (
        "issue_1034_i7_ratio_reference" in ratio_sources["BMW|7 Series (G70, 2023-2026)"]["sources"]
    )
