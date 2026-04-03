"""Tests for building the normalized renderer payload used by report rendering."""

from __future__ import annotations

from vibesensor.shared.boundaries.report_renderer_payload import (
    PreparedReportRendererPayload,
    build_report_renderer_payload,
)


def test_build_report_renderer_payload_cleans_metadata_and_date() -> None:
    payload = {
        "run_id": "run-123",
        "metadata": {
            "run_id": "run-123",
            "active_car_snapshot": {
                "name": "  Track Car  ",
                "type": " coupe ",
            },
            "recorded_utc_offset_seconds": "7200",
        },
        "report_date": " 2026-03-25T10:00:00Z ",
    }

    renderer_payload = build_report_renderer_payload(payload)

    assert renderer_payload == PreparedReportRendererPayload(
        run_id="run-123",
        car_name="Track Car",
        car_type="coupe",
        report_date="2026-03-25T10:00:00Z",
        duration_s=None,
        sample_count=0,
        sensor_count=0,
        peak_table_rows=(),
        recorded_utc_offset_seconds=7200,
    )


def test_build_report_renderer_payload_coerces_counts_and_duration() -> None:
    payload = {
        "run_id": "counts",
        "rows": "18",
        "sensor_count_used": "3",
        "duration_s": "12.5",
    }

    renderer_payload = build_report_renderer_payload(payload)

    assert renderer_payload.sample_count == 18
    assert renderer_payload.sensor_count == 3
    assert renderer_payload.duration_s == 12.5


def test_build_report_renderer_payload_defaults_invalid_values() -> None:
    payload = {
        "rows": "bad",
        "sensor_count_used": "",
        "duration_s": "bad",
        "metadata": "bad",
        "report_date": "",
    }

    renderer_payload = build_report_renderer_payload(payload)

    assert renderer_payload.run_id == "unknown"
    assert renderer_payload.car_name is None
    assert renderer_payload.car_type is None
    assert renderer_payload.report_date is None
    assert renderer_payload.duration_s is None
    assert renderer_payload.sample_count == 0
    assert renderer_payload.sensor_count == 0
    assert renderer_payload.peak_table_rows == ()


def test_build_report_renderer_payload_keeps_peak_table_rows() -> None:
    payload = {
        "run_id": "peaks",
        "plots": {
            "peaks_table": [
                {"rank": 1, "strength_db": 12.0},
                {"rank": 2, "strength_db": 8.5},
            ]
        },
    }

    renderer_payload = build_report_renderer_payload(payload)

    assert renderer_payload.peak_table_rows == (
        {"rank": 1, "strength_db": 12.0},
        {"rank": 2, "strength_db": 8.5},
    )


def test_build_report_renderer_payload_drops_invalid_recorded_offset() -> None:
    renderer_payload = build_report_renderer_payload(
        {
            "run_id": "bad-offset",
            "metadata": {
                "run_id": "bad-offset",
                "recorded_utc_offset_seconds": "bad",
            },
        },
    )

    assert renderer_payload.recorded_utc_offset_seconds is None
