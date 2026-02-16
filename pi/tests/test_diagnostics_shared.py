from __future__ import annotations

import json
from pathlib import Path

from vibesensor.diagnostics_shared import (
    build_diagnostic_settings,
    classify_peak_hz,
    severity_from_peak,
    tolerance_for_order,
    vehicle_orders_hz,
)
from vibesensor.live_diagnostics import LiveDiagnosticsEngine
from vibesensor.report_analysis import build_findings_for_samples, summarize_log


def test_tolerance_for_order_honors_floor_and_cap() -> None:
    rel = tolerance_for_order(
        6.0,
        5.0,
        0.0,
        min_abs_band_hz=0.5,
        max_band_half_width_pct=8.0,
    )
    # 0.5 Hz absolute minimum at 5 Hz means at least 10% relative, but cap is 8%.
    assert rel == 0.08


def test_classify_peak_matches_wheel_order() -> None:
    settings = build_diagnostic_settings({})
    speed_mps = 27.7777777778  # 100 km/h
    orders = vehicle_orders_hz(speed_mps=speed_mps, settings=settings)
    assert orders is not None

    cls = classify_peak_hz(
        peak_hz=orders["wheel_hz"] * 1.02,
        speed_mps=speed_mps,
        settings=settings,
    )
    assert cls["key"] == "wheel1"
    assert cls["suspected_source"] == "wheel/tire"


def test_classify_peak_matches_engine_order() -> None:
    settings = build_diagnostic_settings({})
    speed_mps = 27.7777777778  # 100 km/h
    orders = vehicle_orders_hz(speed_mps=speed_mps, settings=settings)
    assert orders is not None

    cls = classify_peak_hz(
        peak_hz=orders["engine_hz"] * 0.99,
        speed_mps=speed_mps,
        settings=settings,
    )
    assert cls["key"] in {"eng1", "shaft_eng1"}


def test_severity_from_peak_thresholds() -> None:
    state = None
    low = severity_from_peak(strength_db=4.0, band_rms=0.002, sensor_count=1, prior_state=state)
    assert low is not None
    assert low["key"] is None
    high = None
    for _ in range(3):
        high = severity_from_peak(strength_db=35.0, band_rms=0.06, sensor_count=1, prior_state=state)
        state = None if high is None else dict(high.get("state") or {})
    assert high is not None
    assert high["key"] == "l5"


def test_live_and_report_paths_align_on_wheel_source(tmp_path: Path) -> None:
    settings = build_diagnostic_settings({})
    speed_mps = 27.7777777778
    orders = vehicle_orders_hz(speed_mps=speed_mps, settings=settings)
    assert orders is not None
    wheel_hz = orders["wheel_hz"]

    # Live diagnostics path (websocket spectra).
    engine = LiveDiagnosticsEngine()
    freq = [idx / 10.0 for idx in range(0, 1201)]
    spike_idx = min(range(len(freq)), key=lambda idx: abs(freq[idx] - wheel_hz))
    base = [1.0 for _ in freq]
    spec = base[:]
    spec[spike_idx] = 150.0
    live = engine.update(
        speed_mps=speed_mps,
        clients=[{"id": "c1", "name": "front-left"}],
        spectra={"freq": freq, "clients": {"c1": {"freq": freq, "x": spec, "y": spec, "z": spec}}},
        settings=settings,
    )
    assert live["events"]
    assert any(event.get("class_key") == "wheel1" for event in live["events"])

    # Report path (logged JSONL).
    run_path = tmp_path / "run.jsonl"
    records: list[dict] = [
        {
            "record_type": "run_metadata",
            "schema_version": "v2-jsonl",
            "run_id": "run-01",
            "start_time_utc": "2026-02-15T12:00:00+00:00",
            "end_time_utc": "2026-02-15T12:00:30+00:00",
            "sensor_model": "ADXL345",
            "raw_sample_rate_hz": 800,
            "feature_interval_s": 0.25,
            "fft_window_size_samples": 2048,
            "fft_window_type": "hann",
            "peak_picker_method": "max_peak_amp_across_axes",
            "tire_width_mm": settings["tire_width_mm"],
            "tire_aspect_pct": settings["tire_aspect_pct"],
            "rim_in": settings["rim_in"],
            "final_drive_ratio": settings["final_drive_ratio"],
            "current_gear_ratio": settings["current_gear_ratio"],
        }
    ]
    speed_kmh = speed_mps * 3.6
    for idx in range(40):
        records.append(
            {
                "record_type": "sample",
                "schema_version": "v2-jsonl",
                "run_id": "run-01",
                "timestamp_utc": f"2026-02-15T12:00:{idx:02d}+00:00",
                "t_s": idx * 0.25,
                "client_id": "c1",
                "client_name": "front-left",
                "speed_kmh": speed_kmh,
                "gps_speed_kmh": speed_kmh,
                "accel_x_g": 0.02,
                "accel_y_g": 0.015,
                "accel_z_g": 0.01,
                "accel_magnitude_rms_g": 0.04,
                "dominant_freq_hz": wheel_hz * 1.01,
                "dominant_peak_amp_g": 0.09 + (idx * 0.0005),
            }
        )
    records.append({"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"})
    run_path.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n",
        encoding="utf-8",
    )
    summary = summarize_log(run_path)
    assert any(
        finding.get("suspected_source") == "wheel/tire" for finding in summary.get("findings", [])
    )
    assert any(
        "wheel order" in str(finding.get("frequency_hz_or_order", "")).lower()
        for finding in summary.get("findings", [])
    )


def test_live_top_finding_uses_same_report_finding_logic() -> None:
    settings = build_diagnostic_settings({})
    speed_mps = 27.7777777778
    orders = vehicle_orders_hz(speed_mps=speed_mps, settings=settings)
    assert orders is not None
    wheel_hz = orders["wheel_hz"]
    speed_kmh = speed_mps * 3.6

    metadata = {
        "run_id": "live-run",
        "start_time_utc": "2026-02-15T12:00:00+00:00",
        "end_time_utc": "2026-02-15T12:00:30+00:00",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 0.25,
        "fft_window_size_samples": 2048,
        "fft_window_type": "hann",
        "peak_picker_method": "max_peak_amp_across_axes",
        "tire_width_mm": settings["tire_width_mm"],
        "tire_aspect_pct": settings["tire_aspect_pct"],
        "rim_in": settings["rim_in"],
        "final_drive_ratio": settings["final_drive_ratio"],
        "current_gear_ratio": settings["current_gear_ratio"],
        "wheel_bandwidth_pct": settings["wheel_bandwidth_pct"],
        "driveshaft_bandwidth_pct": settings["driveshaft_bandwidth_pct"],
        "engine_bandwidth_pct": settings["engine_bandwidth_pct"],
        "speed_uncertainty_pct": settings["speed_uncertainty_pct"],
        "tire_diameter_uncertainty_pct": settings["tire_diameter_uncertainty_pct"],
        "final_drive_uncertainty_pct": settings["final_drive_uncertainty_pct"],
        "gear_uncertainty_pct": settings["gear_uncertainty_pct"],
        "min_abs_band_hz": settings["min_abs_band_hz"],
        "max_band_half_width_pct": settings["max_band_half_width_pct"],
    }
    samples = [
        {
            "t_s": idx * 0.25,
            "client_id": "c1",
            "client_name": "front-left",
            "speed_kmh": speed_kmh,
            "dominant_freq_hz": wheel_hz * 1.01,
            "dominant_peak_amp_g": 0.09 + (idx * 0.0005),
        }
        for idx in range(60)
    ]

    report_findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
    report_top = next(
        (
            finding
            for finding in report_findings
            if not str(finding.get("finding_id", "")).startswith(("REF", "INFO_"))
        ),
        report_findings[0],
    )

    live = LiveDiagnosticsEngine().update(
        speed_mps=speed_mps,
        clients=[],
        spectra=None,
        settings=settings,
        finding_metadata=metadata,
        finding_samples=samples,
    )
    live_top = live.get("top_finding")
    assert isinstance(live_top, dict)
    assert live_top.get("suspected_source") == report_top.get("suspected_source")
    assert live_top.get("frequency_hz_or_order") == report_top.get("frequency_hz_or_order")
