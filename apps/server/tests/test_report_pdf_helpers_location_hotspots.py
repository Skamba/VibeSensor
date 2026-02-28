from __future__ import annotations

from vibesensor.report.pdf_helpers import location_hotspots


def _tr(key: str, **kwargs: object) -> str:
    templates = {
        "SENSOR_ID_SUFFIX": "Sensor {sensor_id}",
        "UNLABELED_SENSOR": "Unlabeled sensor",
        "LOCATION_ANALYSIS_UNAVAILABLE": "Unavailable",
        "NO_USABLE_AMPLITUDE_BY_LOCATION_DATA_WAS_FOUND": "No data",
        "VIBRATION_SIGNATURE_WAS_DETECTED_AT_ACTIVE_COUNT_OF": (
            "Peak at {strongest_loc} ({strongest_peak:.4f} g)."
        ),
        "VIBRATION_SIGNATURE_WAS_DETECTED_AT_ACTIVE_COUNT_OF_DB": (
            "Peak at {strongest_loc} ({strongest_peak:.1f} dB)."
        ),
        "ORDER_MATCHED_COMPARISON_SUMMARY": (
            "Order-matched comparison: strongest response is at "
            "{strongest_loc} ({strongest_peak:.4f} g)."
        ),
        "SINCE_ALL_SENSORS_SAW_THE_SIGNATURE_BUT_STRONGEST": "",
    }
    template = templates[key]
    return template.format(**kwargs) if kwargs else template


def _text_fn(en: str, _nl: str) -> str:
    return en


def test_location_hotspots_fallback_uses_db_unit() -> None:
    rows, summary, _, _ = location_hotspots(
        [
            {"client_name": "front-left wheel", "vibration_strength_db": 22.5},
            {"client_name": "rear-right wheel", "vibration_strength_db": 18.0},
        ],
        [],
        tr=_tr,
        text_fn=_text_fn,
    )

    assert rows[0]["unit"] == "db"
    assert "peak_db" in rows[0]
    assert "peak_g" not in rows[0]
    assert "dB" in summary
    assert " g" not in summary


def test_location_hotspots_matched_points_still_uses_db_unit() -> None:
    rows, summary, _, _ = location_hotspots(
        [{"client_name": "front-left wheel", "vibration_strength_db": 22.5}],
        [{"matched_points": [{"location": "front-left wheel", "amp": 0.15}]}],
        tr=_tr,
        text_fn=_text_fn,
    )

    assert rows[0]["unit"] == "db"
    assert "peak_db" in rows[0]
    assert "peak_g" not in rows[0]
    assert "dB" in summary
