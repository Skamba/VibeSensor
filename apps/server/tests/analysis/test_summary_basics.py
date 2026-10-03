"""End-to-end summary-to-report smoke tests for complete and degraded runs."""

from __future__ import annotations

from pathlib import Path

from _persistence_helpers import sample
from test_support.report_helpers import (
    RUN_END,
    suitability_by_key,
)
from test_support.report_helpers import (
    report_run_metadata as run_metadata,
)
from test_support.report_record_builders import summarize_records

from vibesensor.common.units import KMH_TO_MPS


def test_run_suitability_warns_for_degraded_scenario(tmp_path: Path) -> None:
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx in range(15):
        current_sample = sample(idx, speed_kmh=None, dominant_freq_hz=14.0, peak_amp_g=0.08)
        current_sample["client_id"] = "solo-1"
        current_sample["client_name"] = "front-left wheel"
        current_sample["frames_dropped_total"] = idx * 2
        current_sample["queue_overflow_drops"] = idx
        if idx in {0, 5, 10}:
            current_sample["accel_x_g"] = 15.9
        records.append(current_sample)
    records.append(RUN_END)
    suit = suitability_by_key(summarize_records(records))
    for key in (
        "SUITABILITY_CHECK_SPEED_VARIATION",
        "SUITABILITY_CHECK_SENSOR_COVERAGE",
        "SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
        "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
        "SUITABILITY_CHECK_FRAME_INTEGRITY",
    ):
        assert suit[key]["state"] == "warn"


def test_frame_drop_per_sensor_delta_avoids_cross_sensor_overcount(tmp_path: Path) -> None:
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx in range(10):
        sample_a = sample(idx, speed_kmh=80.0, dominant_freq_hz=14.0, peak_amp_g=0.05)
        sample_a["client_id"] = "sensor-a"
        sample_a["client_name"] = "front-left"
        sample_a["frames_dropped_total"] = 100 + (idx // 2)
        sample_a["queue_overflow_drops"] = 0
        records.append(sample_a)

        sample_b = sample(idx, speed_kmh=80.0, dominant_freq_hz=14.0, peak_amp_g=0.05)
        sample_b["client_id"] = "sensor-b"
        sample_b["client_name"] = "front-right"
        sample_b["frames_dropped_total"] = 1 if idx >= 8 else 0
        sample_b["queue_overflow_drops"] = 0
        records.append(sample_b)
    records.append(RUN_END)
    fi = suitability_by_key(summarize_records(records))["SUITABILITY_CHECK_FRAME_INTEGRITY"]
    assert fi["state"] == "warn"


def test_frame_drop_delta_handles_counter_resets(tmp_path: Path) -> None:
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx, dropped_total in enumerate([5, 6, 0, 1]):
        current_sample = sample(idx, speed_kmh=80.0, dominant_freq_hz=14.0, peak_amp_g=0.05)
        current_sample["client_id"] = "sensor-a"
        current_sample["client_name"] = "front-left"
        current_sample["frames_dropped_total"] = dropped_total
        current_sample["queue_overflow_drops"] = 0
        records.append(current_sample)
    records.append(RUN_END)
    fi = suitability_by_key(summarize_records(records))["SUITABILITY_CHECK_FRAME_INTEGRITY"]
    assert fi["state"] == "warn"
    assert "2" in str(fi["explanation"])


def test_frame_drop_delta_ignores_samples_without_client_id(tmp_path: Path) -> None:
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx in range(4):
        current_sample = sample(idx, speed_kmh=80.0, dominant_freq_hz=14.0, peak_amp_g=0.05)
        current_sample["client_id"] = ""
        current_sample["frames_dropped_total"] = idx + 1
        current_sample["queue_overflow_drops"] = idx + 1
        records.append(current_sample)
    records.append(RUN_END)
    fi = suitability_by_key(summarize_records(records))["SUITABILITY_CHECK_FRAME_INTEGRITY"]
    assert fi["state"] == "pass"


def test_data_quality_outliers_include_zero_strength_values(tmp_path: Path) -> None:
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx, vib_db in enumerate([0.0, 10.0, 20.0]):
        current_sample = sample(idx, speed_kmh=50.0 + idx, dominant_freq_hz=14.0, peak_amp_g=0.05)
        current_sample["vibration_strength_db"] = vib_db
        records.append(current_sample)
    records.append(RUN_END)
    outliers = summarize_records(records, include_samples=False)["data_quality"]["outliers"][
        "amplitude_metric"
    ]
    assert outliers["count"] == 3


def test_derive_references_from_vehicle_parameters(tmp_path: Path) -> None:
    records = [
        run_metadata(
            run_id="run-01",
            raw_sample_rate_hz=800,
            tire_width_mm=285,
            tire_aspect_pct=30,
            rim_in=21,
            final_drive_ratio=3.08,
            current_gear_ratio=0.64,
        ),
    ]
    for idx in range(28):
        records.append(
            sample(
                idx,
                speed_kmh=float(45 + idx),
                dominant_freq_hz=6.5 + (idx * 0.05),
                peak_amp_g=0.08 + (idx * 0.0008),
            ),
        )
    records.append(RUN_END)
    finding_ids = {str(f.get("finding_id")) for f in summarize_records(records)["findings"]}
    assert "REF_WHEEL" not in finding_ids
    assert "REF_ENGINE" not in finding_ids


def test_metadata_accel_scale_is_exposed_without_legacy_unit_metadata(tmp_path: Path) -> None:
    records = [
        run_metadata(
            run_id="run-01",
            raw_sample_rate_hz=800,
            tire_circumference_m=2.2,
            accel_scale_g_per_lsb=1.0 / 256.0,
        ),
    ]
    for idx in range(10):
        speed = 50 + idx
        wheel_hz = (speed * KMH_TO_MPS) / 2.2
        records.append(
            sample(
                idx,
                speed_kmh=float(speed),
                dominant_freq_hz=wheel_hz,
                peak_amp_g=0.08 + (idx * 0.0006),
            ),
        )
    records.append(RUN_END)
    summary = summarize_records(records)
    assert summary["accel_scale_g_per_lsb"] == (1.0 / 256.0)
    assert "units" not in summary["metadata"]
    assert "amplitude_definitions" not in summary["metadata"]
