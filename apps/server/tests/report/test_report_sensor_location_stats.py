from __future__ import annotations

from pathlib import Path

import pytest

from _report_pdf_test_helpers import RUN_END
from _report_pdf_test_helpers import run_metadata
from _report_pdf_test_helpers import sample
from _report_pdf_test_helpers import summarize_log
from _report_pdf_test_helpers import write_jsonl


def test_sensor_location_stats_include_percentiles_and_strength_distribution(tmp_path: Path) -> None:
    run_path = tmp_path / "run_location_stats.jsonl"
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx, amp in enumerate([0.1, 0.2, 0.3, 0.4]):
        current_sample = sample(idx, speed_kmh=55.0 + idx, dominant_freq_hz=18.0, peak_amp_g=amp)
        current_sample["frames_dropped_total"] = idx * 2
        current_sample["queue_overflow_drops"] = idx
        records.append(current_sample)
    records.append(RUN_END)
    write_jsonl(run_path, records)
    row = summarize_log(run_path, include_samples=False)["sensor_intensity_by_location"][0]
    assert row["sample_count"] == 4
    assert row["p50_intensity_db"] == pytest.approx(22.0, rel=1e-6)
    assert row["p95_intensity_db"] == pytest.approx(22.0, rel=1e-6)
    assert row["max_intensity_db"] == pytest.approx(22.0, rel=1e-6)
    assert row["dropped_frames_delta"] == 6
    assert row["queue_overflow_drops_delta"] == 3
    strength = row["strength_bucket_distribution"]
    assert set(strength["counts"].keys()) == {"l0", "l1", "l2", "l3", "l4", "l5"}


def test_sensor_location_stats_include_partial_run_sensors(tmp_path: Path) -> None:
    run_path = tmp_path / "run_location_stats_partial_sensor.jsonl"
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx in range(10):
        full_sensor = sample(idx, speed_kmh=60.0 + idx, dominant_freq_hz=20.0, peak_amp_g=0.09 + (idx * 0.001))
        full_sensor["client_id"] = "full-1"
        full_sensor["client_name"] = "front-left wheel"
        records.append(full_sensor)
        if 2 <= idx <= 7:
            partial_sensor = sample(idx, speed_kmh=60.0 + idx, dominant_freq_hz=19.0, peak_amp_g=0.07 + (idx * 0.001))
            partial_sensor["client_id"] = "partial-2"
            partial_sensor["client_name"] = "front-right wheel"
            records.append(partial_sensor)
    records.append(RUN_END)
    write_jsonl(run_path, records)
    summary = summarize_log(run_path, include_samples=False)
    assert summary["sensor_locations"] == ["front-left wheel", "front-right wheel"]
    assert {row["location"] for row in summary["sensor_intensity_by_location"]} == {"front-left wheel", "front-right wheel"}


def test_sensor_location_stats_handle_counter_reset_and_l0_percent(tmp_path: Path) -> None:
    run_path = tmp_path / "run_location_stats_counter_reset.jsonl"
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    buckets = ["l0", "l0", "l1", "l1"]
    dropped = [5, 6, 0, 1]
    overflow = [1, 2, 0, 1]
    for idx in range(4):
        current_sample = sample(idx, speed_kmh=55.0 + idx, dominant_freq_hz=18.0, peak_amp_g=0.1)
        current_sample["frames_dropped_total"] = dropped[idx]
        current_sample["queue_overflow_drops"] = overflow[idx]
        current_sample["strength_bucket"] = buckets[idx]
        records.append(current_sample)
    records.append(RUN_END)
    write_jsonl(run_path, records)
    row = summarize_log(run_path, include_samples=False)["sensor_intensity_by_location"][0]
    assert row["dropped_frames_delta"] == 2
    assert row["queue_overflow_drops_delta"] == 2
    assert row["strength_bucket_distribution"]["percent_time_l0"] == pytest.approx(50.0, rel=1e-6)


def test_sensor_location_stats_warn_on_sparse_sensor_keeps_ranking_stable(tmp_path: Path) -> None:
    run_path = tmp_path / "run_location_stats_sparse_sensor.jsonl"
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx in range(50):
        full_sensor = sample(idx, speed_kmh=60.0 + idx, dominant_freq_hz=20.0, peak_amp_g=0.08)
        full_sensor["client_id"] = "full-1"
        full_sensor["client_name"] = "front-left wheel"
        full_sensor["vibration_strength_db"] = 22.0
        records.append(full_sensor)
        if idx < 10:
            sparse_sensor = sample(idx, speed_kmh=60.0 + idx, dominant_freq_hz=19.0, peak_amp_g=0.09)
            sparse_sensor["client_id"] = "sparse-2"
            sparse_sensor["client_name"] = "front-right wheel"
            sparse_sensor["vibration_strength_db"] = 40.0
            records.append(sparse_sensor)
    records.append(RUN_END)
    write_jsonl(run_path, records)
    rows = summarize_log(run_path, include_samples=False)["sensor_intensity_by_location"]
    assert rows[0]["location"] == "front-left wheel"
    sparse_row = next(row for row in rows if row["location"] == "front-right wheel")
    assert sparse_row["sample_count"] == 10
    assert sparse_row["sample_coverage_ratio"] == pytest.approx(0.2, rel=1e-6)
    assert bool(sparse_row["sample_coverage_warning"]) is True


def test_sensor_location_stats_stay_stable_when_client_name_changes(tmp_path: Path) -> None:
    run_path = tmp_path / "run_location_stats_stable_location_code.jsonl"
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    first_sample = sample(0, speed_kmh=60.0, dominant_freq_hz=20.0, peak_amp_g=0.09)
    first_sample["client_id"] = "sensor-1"
    first_sample["client_name"] = "Front Left"
    first_sample["location"] = "front_left_wheel"
    records.append(first_sample)
    renamed_sample = sample(1, speed_kmh=61.0, dominant_freq_hz=20.0, peak_amp_g=0.091)
    renamed_sample["client_id"] = "sensor-1"
    renamed_sample["client_name"] = "Front-Left Renamed"
    renamed_sample["location"] = "front_left_wheel"
    records.append(renamed_sample)
    records.append(RUN_END)
    write_jsonl(run_path, records)
    summary = summarize_log(run_path, include_samples=False)
    assert summary["sensor_locations"] == ["Front Left Wheel"]
    assert summary["sensor_intensity_by_location"][0]["sample_count"] == 2