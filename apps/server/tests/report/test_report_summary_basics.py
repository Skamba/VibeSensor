from __future__ import annotations

from pathlib import Path

from _report_pdf_test_helpers import (
    KMH_TO_MPS,
    RUN_END,
    assert_pdf_contains,
    build_report_pdf,
    map_summary,
    run_metadata,
    sample,
    suitability_by_key,
    summarize_log,
    write_jsonl,
)


def test_complete_run_has_speed_bins_findings_and_plots(tmp_path: Path) -> None:
    run_path = tmp_path / "run_complete.jsonl"
    circumference_m = 2.20
    records = [
        run_metadata(
            run_id="run-01",
            raw_sample_rate_hz=800,
            tire_circumference_m=circumference_m,
        )
    ]
    for idx in range(30):
        speed = 40 + idx
        wheel_hz = (speed * KMH_TO_MPS) / circumference_m
        records.append(
            sample(
                idx,
                speed_kmh=float(speed),
                dominant_freq_hz=wheel_hz,
                peak_amp_g=0.09 + (idx * 0.001),
            )
        )
    records.append(RUN_END)
    write_jsonl(run_path, records)

    summary = summarize_log(run_path)
    assert summary["rows"] == 30
    assert summary["speed_breakdown"]
    assert summary["findings"]
    pdf = build_report_pdf(map_summary(summary))
    assert pdf.startswith(b"%PDF")
    for text in (
        "Diagnostic Worksheet",
        "Observed Signature",
        "Certainty",
        "Systems with findings",
        "Next steps",
        "Evidence",
        "Diagnostic Peaks",
    ):
        assert_pdf_contains(pdf, text)
    assert b"Spectrogram" not in pdf


def test_missing_speed_skips_speed_and_wheel_order(tmp_path: Path) -> None:
    run_path = tmp_path / "run_missing_speed.jsonl"
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx in range(20):
        records.append(sample(idx, speed_kmh=None, dominant_freq_hz=14.0, peak_amp_g=0.08))
    records.append(RUN_END)
    write_jsonl(run_path, records)
    summary = summarize_log(run_path)
    assert summary["speed_breakdown"] == []
    assert any(f.get("finding_id") == "REF_SPEED" for f in summary["findings"])
    assert build_report_pdf(map_summary(summary)).startswith(b"%PDF")


def test_run_suitability_warns_for_degraded_scenario(tmp_path: Path) -> None:
    run_path = tmp_path / "run_degraded_suitability.jsonl"
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
    write_jsonl(run_path, records)
    suit = suitability_by_key(summarize_log(run_path))
    for key in (
        "SUITABILITY_CHECK_SPEED_VARIATION",
        "SUITABILITY_CHECK_SENSOR_COVERAGE",
        "SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
        "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
        "SUITABILITY_CHECK_FRAME_INTEGRITY",
    ):
        assert suit[key]["state"] == "warn"


def test_frame_drop_per_sensor_delta_avoids_cross_sensor_overcount(tmp_path: Path) -> None:
    run_path = tmp_path / "run_multi_sensor_drops.jsonl"
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
    write_jsonl(run_path, records)
    fi = suitability_by_key(summarize_log(run_path))["SUITABILITY_CHECK_FRAME_INTEGRITY"]
    assert fi["state"] == "warn"


def test_frame_drop_delta_handles_counter_resets(tmp_path: Path) -> None:
    run_path = tmp_path / "run_frame_counter_reset.jsonl"
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx, dropped_total in enumerate([5, 6, 0, 1]):
        current_sample = sample(idx, speed_kmh=80.0, dominant_freq_hz=14.0, peak_amp_g=0.05)
        current_sample["client_id"] = "sensor-a"
        current_sample["client_name"] = "front-left"
        current_sample["frames_dropped_total"] = dropped_total
        current_sample["queue_overflow_drops"] = 0
        records.append(current_sample)
    records.append(RUN_END)
    write_jsonl(run_path, records)
    fi = suitability_by_key(summarize_log(run_path))["SUITABILITY_CHECK_FRAME_INTEGRITY"]
    assert fi["state"] == "warn"
    assert "2" in str(fi["explanation"])


def test_frame_drop_delta_ignores_samples_without_client_id(tmp_path: Path) -> None:
    run_path = tmp_path / "run_frame_missing_client_id.jsonl"
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx in range(4):
        current_sample = sample(idx, speed_kmh=80.0, dominant_freq_hz=14.0, peak_amp_g=0.05)
        current_sample["client_id"] = ""
        current_sample["frames_dropped_total"] = idx + 1
        current_sample["queue_overflow_drops"] = idx + 1
        records.append(current_sample)
    records.append(RUN_END)
    write_jsonl(run_path, records)
    fi = suitability_by_key(summarize_log(run_path))["SUITABILITY_CHECK_FRAME_INTEGRITY"]
    assert fi["state"] == "pass"


def test_missing_raw_sample_rate_adds_reference_finding(tmp_path: Path) -> None:
    run_path = tmp_path / "run_missing_sample_rate.jsonl"
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=None)]
    for idx in range(20):
        records.append(
            sample(
                idx,
                speed_kmh=float(60 + idx),
                dominant_freq_hz=20.0,
                peak_amp_g=0.06 + (idx * 0.0005),
            )
        )
    records.append(RUN_END)
    write_jsonl(run_path, records)
    summary = summarize_log(run_path)
    assert summary["raw_sample_rate_hz"] is None
    assert any(f.get("finding_id") == "REF_SAMPLE_RATE" for f in summary["findings"])
    assert build_report_pdf(map_summary(summary)).startswith(b"%PDF")


def test_data_quality_outliers_include_zero_strength_values(tmp_path: Path) -> None:
    run_path = tmp_path / "run_zero_strength_values.jsonl"
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx, vib_db in enumerate([0.0, 10.0, 20.0]):
        current_sample = sample(idx, speed_kmh=50.0 + idx, dominant_freq_hz=14.0, peak_amp_g=0.05)
        current_sample["vibration_strength_db"] = vib_db
        records.append(current_sample)
    records.append(RUN_END)
    write_jsonl(run_path, records)
    outliers = summarize_log(run_path, include_samples=False)["data_quality"][
        "outliers"
    ]["amplitude_metric"]
    assert outliers["count"] == 3


def test_derive_references_from_vehicle_parameters(tmp_path: Path) -> None:
    run_path = tmp_path / "run_derived_references.jsonl"
    records = [
        run_metadata(
            run_id="run-01",
            raw_sample_rate_hz=800,
            tire_width_mm=285,
            tire_aspect_pct=30,
            rim_in=21,
            final_drive_ratio=3.08,
            current_gear_ratio=0.64,
        )
    ]
    for idx in range(28):
        records.append(
            sample(
                idx,
                speed_kmh=float(45 + idx),
                dominant_freq_hz=6.5 + (idx * 0.05),
                peak_amp_g=0.08 + (idx * 0.0008),
            )
        )
    records.append(RUN_END)
    write_jsonl(run_path, records)
    finding_ids = {str(f.get("finding_id")) for f in summarize_log(run_path)["findings"]}
    assert "REF_WHEEL" not in finding_ids
    assert "REF_ENGINE" not in finding_ids


def test_metadata_accel_scale_and_units_are_exposed(tmp_path: Path) -> None:
    run_path = tmp_path / "run_units.jsonl"
    records = [
        run_metadata(
            run_id="run-01",
            raw_sample_rate_hz=800,
            tire_circumference_m=2.2,
            accel_scale_g_per_lsb=1.0 / 256.0,
        )
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
            )
        )
    records.append(RUN_END)
    write_jsonl(run_path, records)
    summary = summarize_log(run_path)
    assert summary["accel_scale_g_per_lsb"] == (1.0 / 256.0)
    assert summary["metadata"]["units"]["accel_x_g"] == "g"
    assert summary["metadata"]["units"]["vibration_strength_db"] == "dB"


def test_steady_speed_report_wording(tmp_path: Path) -> None:
    run_path = tmp_path / "run_steady_speed.jsonl"
    records = [run_metadata(run_id="run-01", raw_sample_rate_hz=800, tire_circumference_m=2.2)]
    for idx in range(24):
        records.append(
            sample(
                idx,
                speed_kmh=100.0 + ((idx % 3) * 0.4),
                dominant_freq_hz=22.0 + (idx * 0.02),
                peak_amp_g=0.08 + (idx * 0.0003),
            )
        )
    records.append(RUN_END)
    write_jsonl(run_path, records)
    summary = summarize_log(run_path)
    assert bool(summary["speed_stats"]["steady_speed"]) is True
    pdf = build_report_pdf(map_summary(summary))
    assert_pdf_contains(pdf, "Certainty")
    assert_pdf_contains(pdf, "Diagnostic Worksheet")
