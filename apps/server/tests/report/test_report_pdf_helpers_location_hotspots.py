from __future__ import annotations

import pytest

from vibesensor.report.pdf_helpers import location_hotspots


def _tr(key: str, **kwargs: object) -> str:
    templates = {
        "SENSOR_ID_SUFFIX": "Sensor {sensor_id}",
        "UNLABELED_SENSOR": "Unlabeled sensor",
        "LOCATION_ANALYSIS_UNAVAILABLE": "Unavailable",
        "NO_USABLE_AMPLITUDE_BY_LOCATION_DATA_WAS_FOUND": "No data",
        "VIBRATION_SIGNATURE_WAS_DETECTED_AT_ACTIVE_COUNT_OF_DB": (
            "Peak at {strongest_loc} ({strongest_peak:.1f} dB)."
        ),
        "SINCE_ALL_SENSORS_SAW_THE_SIGNATURE_BUT_STRONGEST": "",
    }
    template = templates[key]
    return template.format(**kwargs) if kwargs else template


def _text_fn(en: str, _nl: str) -> str:
    return en


@pytest.mark.parametrize(
    "summaries, findings, expect_no_g_in_summary",
    [
        pytest.param(
            [
                {"client_name": "front-left wheel", "vibration_strength_db": 22.5},
                {"client_name": "rear-right wheel", "vibration_strength_db": 18.0},
            ],
            [],
            True,
            id="fallback_uses_db_unit",
        ),
        pytest.param(
            [{"client_name": "front-left wheel", "vibration_strength_db": 22.5}],
            [{"matched_points": [{"location": "front-left wheel", "amp": 0.15}]}],
            False,
            id="matched_points_still_uses_db_unit",
        ),
    ],
)
def test_location_hotspots_uses_db_unit(
    summaries: list[dict[str, object]],
    findings: list[dict[str, object]],
    expect_no_g_in_summary: bool,
) -> None:
    rows, summary, _, _ = location_hotspots(
        summaries, findings, tr=_tr, text_fn=_text_fn
    )

    assert rows[0]["unit"] == "db"
    assert "peak_db" in rows[0]
    assert "peak_g" not in rows[0]
    assert "dB" in summary
    if expect_no_g_in_summary:
        assert " g" not in summary
