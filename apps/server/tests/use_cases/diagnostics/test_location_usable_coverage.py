from __future__ import annotations

from pathlib import Path

from test_support.report_helpers import RUN_END, report_sample, write_jsonl
from test_support.report_helpers import report_run_metadata as run_metadata

from vibesensor.adapters.analysis_summary import summarize_log
from vibesensor.use_cases.diagnostics._sensor_locations import _locations_connected_throughout_run
from vibesensor.use_cases.diagnostics.signal_aggregation import _sensor_intensity_by_location


def _typed_samples(mappings: list[dict[str, object]]):
    from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings

    return sensor_frames_from_mappings(mappings)


def test_locations_connected_throughout_requires_usable_vibration_metrics() -> None:
    samples = []
    for t_s in range(11):
        samples.append(
            {
                "t_s": float(t_s),
                "client_name": "Front Left",
                "vibration_strength_db": None if t_s in {0, 10} else 22.0,
            }
        )
        samples.append(
            {
                "t_s": float(t_s),
                "client_name": "Rear Right",
                "vibration_strength_db": 18.0,
            }
        )

    connected = _locations_connected_throughout_run(_typed_samples(samples))

    assert connected == {"Rear Right"}


def test_sensor_intensity_by_location_tracks_observed_and_usable_coverage() -> None:
    rows = _sensor_intensity_by_location(
        _typed_samples(
            [
                {
                    "t_s": 0.0,
                    "client_name": "Front Left",
                    "vibration_strength_db": 20.0,
                },
                {
                    "t_s": 1.0,
                    "client_name": "Front Left",
                    "vibration_strength_db": None,
                },
                {
                    "t_s": 2.0,
                    "client_name": "Front Left",
                    "vibration_strength_db": 24.0,
                },
                {
                    "t_s": 0.0,
                    "client_name": "Rear Right",
                    "vibration_strength_db": 21.0,
                },
                {
                    "t_s": 1.0,
                    "client_name": "Rear Right",
                    "vibration_strength_db": 22.0,
                },
                {
                    "t_s": 2.0,
                    "client_name": "Rear Right",
                    "vibration_strength_db": 23.0,
                },
            ]
        ),
        connected_locations={"Rear Right"},
    )

    front_left = next(row for row in rows if row.location == "Front Left")
    assert front_left.sample_count == 3
    assert front_left.sample_coverage_ratio == 1.0
    assert front_left.usable_sample_count == 2
    assert front_left.usable_sample_coverage_ratio == (2 / 3)
    assert front_left.partial_coverage is True


def test_summary_exposes_usable_location_coverage_without_overstating_connected_rows(
    tmp_path: Path,
) -> None:
    run_path = tmp_path / "run_location_usable_coverage.jsonl"
    records = [run_metadata(run_id="run-usable-coverage", raw_sample_rate_hz=800)]
    for idx in range(10):
        full_sensor = report_sample(
            idx,
            speed_kmh=60.0 + idx,
            dominant_freq_hz=20.0,
            peak_amp_g=0.09 + (idx * 0.001),
        )
        full_sensor["client_id"] = "full-1"
        full_sensor["client_name"] = "front-left wheel"
        full_sensor["vibration_strength_db"] = 22.0
        records.append(full_sensor)

        flaky_sensor = report_sample(
            idx,
            speed_kmh=60.0 + idx,
            dominant_freq_hz=19.0,
            peak_amp_g=0.08 + (idx * 0.001),
        )
        flaky_sensor["client_id"] = "flaky-2"
        flaky_sensor["client_name"] = "front-right wheel"
        flaky_sensor["vibration_strength_db"] = None if idx in {0, 1, 8, 9} else 18.0
        records.append(flaky_sensor)
    records.append(RUN_END)
    write_jsonl(run_path, records)

    summary = summarize_log(run_path, include_samples=False)

    assert summary["sensor_locations"] == ["front-left wheel", "front-right wheel"]
    assert summary["sensor_locations_connected_throughout"] == ["front-left wheel"]
    flaky_row = next(
        row
        for row in summary["sensor_intensity_by_location"]
        if row["location"] == "front-right wheel"
    )
    assert flaky_row["sample_count"] == 10
    assert flaky_row["usable_sample_count"] == 6
    assert flaky_row["sample_coverage_ratio"] == 1.0
    assert flaky_row["usable_sample_coverage_ratio"] == 0.6
    assert flaky_row["partial_coverage"] is True
