"""Focused regressions for the fourth Audi/BMW ratio-research wave."""

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


def test_wave4_ratio_source_rows_keep_ev_schema_limits_explicit() -> None:
    sources = _ratio_sources()

    assert "official_i5_m60_tire_context" in sources["BMW|5 Series (G60, 2024-2026)"]["sources"]
    assert "issue_1034_i7_ratio_reference" in sources["BMW|7 Series (G70, 2023-2026)"]["sources"]
    assert "official_ix1_xdrive30_exact_ev_mapping" in sources["BMW|X1 (U11, 2023-2026)"]["sources"]
    assert "official_etrongt_quattro_exact_ev_mapping" in sources["Audi|e-tron GT (J1, 2022-2026)"]["sources"]
    assert "official_rs_etrongt_exact_ev_mapping" in sources["Audi|e-tron GT (J1, 2022-2026)"]["sources"]

    for item in [
        {
            "item": "Per-axle reduction detail for the i5 M60 xDrive",
            "reason": "BMW publishes distinct front and rear overall reduction ratios for the dual-motor M60, but the current single-gearbox schema stores one representative EV reduction value for the variant.",
        },
        {
            "item": "Exact i5 M60 xDrive staggered tire-pair representation",
            "reason": "Official BMW Germany sources now prove staggered 19-, 20-, and 21-inch tire packages for the exact i5 M60 xDrive, but the current shared row shape does not safely promote those exact front/rear pairs into production data.",
        },
    ]:
        assert item in sources["BMW|5 Series (G60, 2024-2026)"]["known_limits"]
    _assert_contains_unresolved(
        sources["BMW|7 Series (G70, 2023-2026)"],
        [
            {
                "item": "Variant-level final_drive_ratio and top_gear_ratio confirmation for the EU combustion/PHEV variants",
                "reason": "The official BMW launch material used for issue #1034 confirms the EU-supported 740d xDrive, 750e xDrive, and M760e xDrive variants, but it does not publish extractable numeric ratio fields for those entries.",
            },
            {
                "item": "Schema-safe encoding of axle-split EV reduction ratios and top-gear data for the i7 M70 xDrive",
                "reason": "Official BMW technical-data PDFs now publish exact front and rear reduction ratios for the i7 M70 xDrive, but the current schema stores only one final_drive_ratio and one top_gear_ratio field and cannot safely encode the axle split.",
            },
            {
                "item": "Exact i7 M70 xDrive staggered tire-pair promotion into the broad G70 row",
                "reason": "Official BMW Germany sources now prove staggered 21-inch standard tires and a 20-inch staggered option for the exact i7 M70 xDrive, but the broad G70 row mixes combustion, PHEV, and EV variants and should not absorb one exact EV tire package without a safer row shape.",
            },
        ],
    )
    assert sources["BMW|X1 (U11, 2023-2026)"]["unresolved"] == [
        {
            "item": "Schema-safe encoding of iX1 xDrive30 axle-split EV reduction ratios",
            "reason": "Official BMW sources now publish exact front 11.190 and rear 10.050 fixed reductions for the iX1 xDrive30, but the current row shape stores only one gearbox and one final_drive_ratio value.",
        },
        {
            "item": "Mixed ICE/EV row applicability for U11 tire and gearbox data",
            "reason": "The broad U11 row still mixes ICE and EV variants, so the exact iX1 xDrive30 single-speed gearbox and 17/18/19/20-inch EV tire matrix should remain source-ledger-only until the row shape is split or extended safely.",
        },
    ]
    assert sources["Audi|e-tron GT (J1, 2022-2026)"]["unresolved"] == [
        {
            "item": "Audi e-tron GT quattro exact axle reduction ratios and schema-safe top-gear mapping",
            "reason": "Exact Germany-market base-car technical sheets confirm AWD, 2-speed automatic wording, top speed, and staggered tires, but the checked official sources did not publish a schema-safe single reduction-ratio or top-gear value for the base e-tron GT quattro.",
        },
        {
            "item": "Audi RS e-tron GT axle-split ratio continuity and exact optional tire dimensions",
            "reason": "Official Audi sources show the RS e-tron GT uses axle-split and rear-two-speed hardware, but the checked facelift/current technical sheets do not publish the same reduction-ratio detail as the 2022 launch material, and this pass did not recover exact official 21-inch tire dimensions.",
        },
    ]
