from __future__ import annotations

import json
import re
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from vibesensor import __version__
from vibesensor.constants import KMH_TO_MPS
from vibesensor.report import summarize_log
from vibesensor.report.pdf_builder import build_report_pdf


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n",
        encoding="utf-8",
    )


def _assert_pdf_contains(pdf_bytes: bytes, text: str) -> None:
    assert text.encode("latin-1", errors="ignore") in pdf_bytes


def _extract_media_box(pdf_bytes: bytes) -> tuple[float, float, float, float]:
    text = pdf_bytes.decode("latin-1", errors="ignore")
    match = re.search(
        r"/MediaBox\s*\[\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*\]",
        text,
    )
    assert match is not None
    return tuple(float(match.group(idx)) for idx in range(1, 5))


def _run_metadata(
    *,
    run_id: str,
    raw_sample_rate_hz: int | None,
    tire_circumference_m: float | None = None,
    tire_width_mm: float | None = None,
    tire_aspect_pct: float | None = None,
    rim_in: float | None = None,
    final_drive_ratio: float | None = None,
    current_gear_ratio: float | None = None,
    accel_scale_g_per_lsb: float | None = 1.0 / 256.0,
) -> dict:
    metadata = {
        "record_type": "run_metadata",
        "schema_version": "v2-jsonl",
        "run_id": run_id,
        "start_time_utc": "2026-02-15T12:00:00+00:00",
        "end_time_utc": "2026-02-15T12:01:00+00:00",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": raw_sample_rate_hz,
        "feature_interval_s": 0.5,
        "fft_window_size_samples": 2048,
        "fft_window_type": "hann",
        "peak_picker_method": "max_peak_amp_across_axes",
        "accel_scale_g_per_lsb": accel_scale_g_per_lsb,
        "units": {
            "t_s": "s",
            "speed_kmh": "km/h",
            "accel_x_g": "g",
            "accel_y_g": "g",
            "accel_z_g": "g",
            "vibration_strength_db": "dB",
        },
        "amplitude_definitions": {
            "vibration_strength_db": {
                "statistic": "Peak band RMS vs noise floor",
                "units": "dB",
                "definition": "20*log10((peak_band_rms + eps) / (floor + eps))",
            }
        },
        "incomplete_for_order_analysis": raw_sample_rate_hz is None,
    }
    if tire_circumference_m is not None:
        metadata["tire_circumference_m"] = tire_circumference_m
    if tire_width_mm is not None:
        metadata["tire_width_mm"] = tire_width_mm
    if tire_aspect_pct is not None:
        metadata["tire_aspect_pct"] = tire_aspect_pct
    if rim_in is not None:
        metadata["rim_in"] = rim_in
    if final_drive_ratio is not None:
        metadata["final_drive_ratio"] = final_drive_ratio
    if current_gear_ratio is not None:
        metadata["current_gear_ratio"] = current_gear_ratio
    return metadata


def _sample(
    idx: int,
    *,
    speed_kmh: float | None,
    dominant_freq_hz: float,
    peak_amp_g: float,
) -> dict:
    t_s = idx * 0.5
    return {
        "record_type": "sample",
        "schema_version": "v2-jsonl",
        "run_id": "run-01",
        "timestamp_utc": f"2026-02-15T12:00:{idx:02d}+00:00",
        "t_s": t_s,
        "client_id": "c1",
        "client_name": "front-left wheel",
        "speed_kmh": speed_kmh,
        "gps_speed_kmh": speed_kmh,
        "engine_rpm": None,
        "gear": None,
        "accel_x_g": 0.03 + (idx * 0.0005),
        "accel_y_g": 0.02 + (idx * 0.0003),
        "accel_z_g": 0.01 + (idx * 0.0002),
        "dominant_freq_hz": dominant_freq_hz,
        "dominant_axis": "x",
        "top_peaks": [
            {
                "hz": dominant_freq_hz,
                "amp": peak_amp_g,
                "vibration_strength_db": 22.0,
                "strength_bucket": "l2",
            },
            {
                "hz": dominant_freq_hz + 8.0,
                "amp": peak_amp_g * 0.45,
                "vibration_strength_db": 14.0,
                "strength_bucket": None,
            },
        ],
        "vibration_strength_db": 22.0,
        "strength_bucket": "l2",
    }


def test_complete_run_has_speed_bins_findings_and_plots(tmp_path: Path) -> None:
    run_path = tmp_path / "run_complete.jsonl"
    circumference_m = 2.20
    records: list[dict] = [
        _run_metadata(
            run_id="run-01",
            raw_sample_rate_hz=800,
            tire_circumference_m=circumference_m,
        )
    ]
    for idx in range(30):
        speed = 40 + idx
        wheel_hz = (speed * KMH_TO_MPS) / circumference_m
        records.append(
            _sample(
                idx,
                speed_kmh=float(speed),
                dominant_freq_hz=wheel_hz,
                peak_amp_g=0.09 + (idx * 0.001),
            )
        )
    records.append({"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"})
    _write_jsonl(run_path, records)

    summary = summarize_log(run_path)
    assert summary["rows"] == 30
    assert not summary["speed_breakdown_skipped_reason"]
    assert summary["speed_breakdown"]
    assert summary["findings"]
    assert any("order" in str(f.get("frequency_hz_or_order", "")) for f in summary["findings"])
    plots = summary["plots"]
    assert plots["vib_magnitude"]
    assert any(
        "wheel order" in str(series.get("label", "")).lower()
        for series in plots.get("matched_amp_vs_speed", [])
        if isinstance(series, dict)
    )

    pdf = build_report_pdf(summary)
    assert pdf.startswith(b"%PDF")
    _assert_pdf_contains(pdf, "Diagnostic Worksheet")
    _assert_pdf_contains(pdf, "Observed Signature")
    _assert_pdf_contains(pdf, "Certainty")
    _assert_pdf_contains(pdf, "Systems with findings")
    _assert_pdf_contains(pdf, "Next steps")
    _assert_pdf_contains(pdf, "Evidence")
    _assert_pdf_contains(pdf, "Diagnostic Peaks")
    assert b"Spectrogram" not in pdf


def test_missing_speed_skips_speed_and_wheel_order(tmp_path: Path) -> None:
    run_path = tmp_path / "run_missing_speed.jsonl"
    records: list[dict] = [_run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx in range(20):
        records.append(
            _sample(
                idx,
                speed_kmh=None,
                dominant_freq_hz=14.0,
                peak_amp_g=0.08,
            )
        )
    records.append({"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"})
    _write_jsonl(run_path, records)

    summary = summarize_log(run_path)
    assert (
        summary["speed_breakdown_skipped_reason"]
        == "Speed data missing or insufficient; speed-binned and wheel-order analysis skipped."
    )
    assert summary["speed_breakdown"] == []
    assert any(f.get("finding_id") == "REF_SPEED" for f in summary["findings"])
    assert all(
        "wheel order" not in str(f.get("frequency_hz_or_order", "")).lower()
        for f in summary["findings"]
    )

    pdf = build_report_pdf(summary)
    assert pdf.startswith(b"%PDF")


def test_missing_raw_sample_rate_adds_reference_finding(tmp_path: Path) -> None:
    run_path = tmp_path / "run_missing_sample_rate.jsonl"
    records: list[dict] = [_run_metadata(run_id="run-01", raw_sample_rate_hz=None)]
    for idx in range(20):
        speed = 60 + idx
        records.append(
            _sample(
                idx,
                speed_kmh=float(speed),
                dominant_freq_hz=20.0,
                peak_amp_g=0.06 + (idx * 0.0005),
            )
        )
    records.append({"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"})
    _write_jsonl(run_path, records)

    summary = summarize_log(run_path)
    assert summary["raw_sample_rate_hz"] is None
    assert any(f.get("finding_id") == "REF_SAMPLE_RATE" for f in summary["findings"])
    assert all(
        "order" not in str(f.get("frequency_hz_or_order", "")).lower()
        for f in summary["findings"]
        if str(f.get("finding_id", "")).startswith("F")
    )
    assert summary["findings"]

    pdf = build_report_pdf(summary)
    assert pdf.startswith(b"%PDF")


def test_derive_references_from_vehicle_parameters(tmp_path: Path) -> None:
    run_path = tmp_path / "run_derived_references.jsonl"
    records: list[dict] = [
        _run_metadata(
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
        speed = 45 + idx
        # close to 1x wheel order for these parameters
        records.append(
            _sample(
                idx,
                speed_kmh=float(speed),
                dominant_freq_hz=6.5 + (idx * 0.05),
                peak_amp_g=0.08 + (idx * 0.0008),
            )
        )
    records.append({"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"})
    _write_jsonl(run_path, records)

    summary = summarize_log(run_path)
    finding_ids = {str(f.get("finding_id")) for f in summary["findings"]}
    assert "REF_WHEEL" not in finding_ids
    assert "REF_ENGINE" not in finding_ids


def test_metadata_accel_scale_and_units_are_exposed(tmp_path: Path) -> None:
    run_path = tmp_path / "run_units.jsonl"
    records: list[dict] = [
        _run_metadata(
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
            _sample(
                idx,
                speed_kmh=float(speed),
                dominant_freq_hz=wheel_hz,
                peak_amp_g=0.08 + (idx * 0.0006),
            )
        )
    records.append({"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"})
    _write_jsonl(run_path, records)

    summary = summarize_log(run_path)
    assert summary["accel_scale_g_per_lsb"] == (1.0 / 256.0)
    units = summary["metadata"]["units"]
    assert units["accel_x_g"] == "g"
    assert units["vibration_strength_db"] == "dB"


def test_steady_speed_report_wording(tmp_path: Path) -> None:
    run_path = tmp_path / "run_steady_speed.jsonl"
    records: list[dict] = [
        _run_metadata(
            run_id="run-01",
            raw_sample_rate_hz=800,
            tire_circumference_m=2.2,
        )
    ]
    for idx in range(24):
        # narrow speed spread to trigger steady-speed branch
        speed = 100.0 + ((idx % 3) * 0.4)
        records.append(
            _sample(
                idx,
                speed_kmh=speed,
                dominant_freq_hz=22.0 + (idx * 0.02),
                peak_amp_g=0.08 + (idx * 0.0003),
            )
        )
    records.append({"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"})
    _write_jsonl(run_path, records)

    summary = summarize_log(run_path)
    assert bool(summary["speed_stats"]["steady_speed"]) is True

    pdf = build_report_pdf(summary)
    assert pdf.startswith(b"%PDF")
    # New layout shows certainty reason for steady speed
    _assert_pdf_contains(pdf, "Certainty")
    _assert_pdf_contains(pdf, "Diagnostic Worksheet")


def test_sensor_location_stats_include_percentiles_and_strength_distribution(
    tmp_path: Path,
) -> None:
    run_path = tmp_path / "run_location_stats.jsonl"
    records: list[dict] = [_run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    amps = [0.1, 0.2, 0.3, 0.4]
    for idx, amp in enumerate(amps):
        sample = _sample(
            idx,
            speed_kmh=55.0 + idx,
            dominant_freq_hz=18.0,
            peak_amp_g=amp,
        )
        # amp is no longer used for vibration_strength_db (already set to 22.0 in _sample)
        sample["frames_dropped_total"] = idx * 2
        sample["queue_overflow_drops"] = idx
        records.append(sample)
    records.append({"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"})
    _write_jsonl(run_path, records)

    summary = summarize_log(run_path, include_samples=False)
    assert "samples" not in summary
    rows = summary["sensor_intensity_by_location"]
    assert rows
    row = rows[0]
    assert row["sample_count"] == 4
    assert row["p50_intensity_db"] == pytest.approx(22.0, rel=1e-6)
    assert row["p95_intensity_db"] == pytest.approx(22.0, rel=1e-6)
    assert row["max_intensity_db"] == pytest.approx(22.0, rel=1e-6)
    assert row["dropped_frames_delta"] == 6
    assert row["queue_overflow_drops_delta"] == 3
    strength = row["strength_bucket_distribution"]
    assert strength["total"] > 0
    assert set(strength["counts"].keys()) == {"l1", "l2", "l3", "l4", "l5"}
    pct_sum = sum(strength[f"percent_time_l{idx}"] for idx in range(1, 6))
    assert pct_sum == pytest.approx(100.0, rel=1e-6)


def test_sensor_location_stats_include_partial_run_sensors(tmp_path: Path) -> None:
    run_path = tmp_path / "run_location_stats_partial_sensor.jsonl"
    records: list[dict] = [_run_metadata(run_id="run-01", raw_sample_rate_hz=800)]

    for idx in range(10):
        full_sensor = _sample(
            idx,
            speed_kmh=60.0 + idx,
            dominant_freq_hz=20.0,
            peak_amp_g=0.09 + (idx * 0.001),
        )
        full_sensor["client_id"] = "full-1"
        full_sensor["client_name"] = "front-left wheel"
        records.append(full_sensor)

        if 2 <= idx <= 7:
            partial_sensor = _sample(
                idx,
                speed_kmh=60.0 + idx,
                dominant_freq_hz=19.0,
                peak_amp_g=0.07 + (idx * 0.001),
            )
            partial_sensor["client_id"] = "partial-2"
            partial_sensor["client_name"] = "front-right wheel"
            records.append(partial_sensor)

    records.append({"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"})
    _write_jsonl(run_path, records)

    summary = summarize_log(run_path, include_samples=False)
    assert summary["sensor_locations"] == ["front-left wheel", "front-right wheel"]
    rows = summary["sensor_intensity_by_location"]
    assert len(rows) == 2
    assert {row["location"] for row in rows} == {"front-left wheel", "front-right wheel"}


def test_sensor_location_stats_stay_stable_when_client_name_changes(tmp_path: Path) -> None:
    run_path = tmp_path / "run_location_stats_stable_location_code.jsonl"
    records: list[dict] = [_run_metadata(run_id="run-01", raw_sample_rate_hz=800)]

    first_sample = _sample(
        0,
        speed_kmh=60.0,
        dominant_freq_hz=20.0,
        peak_amp_g=0.09,
    )
    first_sample["client_id"] = "sensor-1"
    first_sample["client_name"] = "Front Left"
    first_sample["location"] = "front_left_wheel"
    records.append(first_sample)

    renamed_sample = _sample(
        1,
        speed_kmh=61.0,
        dominant_freq_hz=20.0,
        peak_amp_g=0.091,
    )
    renamed_sample["client_id"] = "sensor-1"
    renamed_sample["client_name"] = "Front-Left Renamed"
    renamed_sample["location"] = "front_left_wheel"
    records.append(renamed_sample)

    records.append({"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"})
    _write_jsonl(run_path, records)

    summary = summarize_log(run_path, include_samples=False)
    assert summary["sensor_locations"] == ["Front Left Wheel"]
    rows = summary["sensor_intensity_by_location"]
    assert len(rows) == 1
    assert rows[0]["location"] == "Front Left Wheel"
    assert rows[0]["sample_count"] == 2


def test_report_pdf_uses_a4_portrait_media_box(tmp_path: Path) -> None:
    run_path = tmp_path / "run_a4_portrait.jsonl"
    records: list[dict] = [_run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx in range(12):
        records.append(
            _sample(
                idx,
                speed_kmh=55.0 + idx,
                dominant_freq_hz=14.0 + (idx * 0.2),
                peak_amp_g=0.07 + (idx * 0.0006),
            )
        )
    records.append({"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"})
    _write_jsonl(run_path, records)

    summary = summarize_log(run_path)
    pdf = build_report_pdf(summary)
    x0, y0, x1, y1 = _extract_media_box(pdf)
    width = x1 - x0
    height = y1 - y0

    assert height > width
    assert width == pytest.approx(595.3, abs=2.0)
    assert height == pytest.approx(841.9, abs=2.0)


def test_report_pdf_allows_samples_without_strength_bucket(tmp_path: Path) -> None:
    run_path = tmp_path / "run_missing_strength_bucket.jsonl"
    records: list[dict] = [_run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx in range(12):
        sample = _sample(
            idx,
            speed_kmh=60.0 + idx,
            dominant_freq_hz=15.0 + (idx * 0.2),
            peak_amp_g=0.08 + (idx * 0.0004),
        )
        if idx % 3 == 0:
            sample["strength_bucket"] = None
        records.append(sample)
    records.append({"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"})
    _write_jsonl(run_path, records)

    summary = summarize_log(run_path, include_samples=False)
    row = summary["sensor_intensity_by_location"][0]
    assert row["sample_count"] == 12
    assert row["strength_bucket_distribution"]["total"] == 8

    pdf = build_report_pdf(summary)
    assert pdf.startswith(b"%PDF")


def test_report_pdf_footer_contains_version_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_SHA", "a1b2c3d4e5f6")

    run_path = tmp_path / "run_version_marker.jsonl"
    records: list[dict] = [_run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx in range(8):
        records.append(
            _sample(
                idx,
                speed_kmh=48.0 + idx,
                dominant_freq_hz=16.0,
                peak_amp_g=0.05 + (idx * 0.001),
            )
        )
    records.append({"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"})
    _write_jsonl(run_path, records)

    summary = summarize_log(run_path)
    pdf = build_report_pdf(summary)
    marker = f"v{__version__} (a1b2c3d4)"
    reader = PdfReader(BytesIO(pdf))
    text_blob = "\n".join((page.extract_text() or "") for page in reader.pages)
    meta = reader.metadata
    meta_blob = " ".join(
        str(value)
        for value in (getattr(meta, "title", None), getattr(meta, "subject", None))
        if value
    )
    assert marker in text_blob or marker in meta_blob


def test_report_pdf_worksheet_has_single_next_steps_heading(tmp_path: Path) -> None:
    run_path = tmp_path / "run_single_next_steps_heading.jsonl"
    records: list[dict] = [
        _run_metadata(run_id="run-01", raw_sample_rate_hz=800, tire_circumference_m=2.2)
    ]
    for idx in range(14):
        speed = 55.0 + idx
        wheel_hz = (speed * KMH_TO_MPS) / 2.2
        records.append(
            _sample(
                idx,
                speed_kmh=speed,
                dominant_freq_hz=wheel_hz,
                peak_amp_g=0.08 + (idx * 0.0005),
            )
        )
    records.append({"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"})
    _write_jsonl(run_path, records)

    summary = summarize_log(run_path)
    pdf = build_report_pdf(summary)
    reader = PdfReader(BytesIO(pdf))
    text_blob = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert text_blob.count("Next steps") == 1


def test_report_pdf_nl_localizes_header_metadata_labels(tmp_path: Path) -> None:
    run_path = tmp_path / "run_nl_header_metadata.jsonl"
    records: list[dict] = [_run_metadata(run_id="run-01", raw_sample_rate_hz=800)]
    for idx in range(10):
        records.append(
            {
                **_sample(
                    idx,
                    speed_kmh=50.0 + idx,
                    dominant_freq_hz=15.0,
                    peak_amp_g=0.06 + (idx * 0.0007),
                ),
                "client_id": "client1234",
            }
        )
    records.append({"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"})
    _write_jsonl(run_path, records)

    summary = summarize_log(run_path, lang="nl")
    pdf = build_report_pdf(summary)
    reader = PdfReader(BytesIO(pdf))
    text_blob = "\n".join((page.extract_text() or "") for page in reader.pages)

    assert "Duur:" in text_blob
    assert "Sensoren:" in text_blob
    assert "Aantal samples:" in text_blob
    assert "Bemonsteringsfrequentie (Hz):" in text_blob
    assert " sensors" not in text_blob.lower()
