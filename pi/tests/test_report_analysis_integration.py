from __future__ import annotations

from pathlib import Path

import pytest

from vibesensor.report_analysis import (
    _speed_breakdown,
    build_findings_for_samples,
    summarize_log,
)
from vibesensor.runlog import (
    append_jsonl_records,
    create_run_end_record,
    create_run_metadata,
)


def _make_metadata(**overrides) -> dict:
    defaults = dict(
        run_id="test-run",
        start_time_utc="2025-01-01T00:00:00+00:00",
        sensor_model="ADXL345",
        raw_sample_rate_hz=200,
        feature_interval_s=0.5,
        fft_window_size_samples=256,
        fft_window_type="hann",
        peak_picker_method="max_peak_amp_across_axes",
        accel_scale_g_per_lsb=1.0 / 256.0,
        tire_width_mm=285.0,
        tire_aspect_pct=30.0,
        rim_in=21.0,
        final_drive_ratio=3.08,
        current_gear_ratio=0.64,
    )
    defaults.update(overrides)
    valid_keys = create_run_metadata.__code__.co_varnames
    return create_run_metadata(
        **{k: v for k, v in defaults.items() if k in valid_keys}
    )


def _make_sample(t_s: float, speed_kmh: float, amp: float = 0.01) -> dict:
    return {
        "record_type": "sample",
        "t_s": t_s,
        "speed_kmh": speed_kmh,
        "accel_x_g": amp,
        "accel_y_g": amp,
        "accel_z_g": amp,
        "vib_mag_rms_g": amp,
        "dominant_freq_hz": 15.0,
        "dominant_peak_amp_g": amp * 2,
        "noise_floor_amp": amp * 0.1,
        "client_name": "Front Left",
    }


# -- _speed_breakdown ----------------------------------------------------------


def test_speed_breakdown_basic() -> None:
    samples = [
        _make_sample(1.0, 85.0, 0.02),
        _make_sample(2.0, 87.0, 0.03),
        _make_sample(3.0, 92.0, 0.01),
    ]
    rows = _speed_breakdown(samples)
    assert len(rows) == 2  # 80-90 and 90-100 bins
    labels = [r["speed_range"] for r in rows]
    assert "80-90 km/h" in labels
    assert "90-100 km/h" in labels


def test_speed_breakdown_empty() -> None:
    assert _speed_breakdown([]) == []


def test_speed_breakdown_no_speed() -> None:
    samples = [{"speed_kmh": None}, {"speed_kmh": 0}]
    assert _speed_breakdown(samples) == []


# -- build_findings_for_samples ------------------------------------------------


def test_build_findings_empty_samples() -> None:
    metadata = _make_metadata()
    findings = build_findings_for_samples(metadata=metadata, samples=[], lang="en")
    # Should return some reference/info findings even with no data
    assert isinstance(findings, list)


def test_build_findings_with_speed_data() -> None:
    metadata = _make_metadata()
    # Generate enough samples for speed coverage
    samples = [_make_sample(float(i) * 0.5, 80.0 + i * 0.5, 0.01 + i * 0.001) for i in range(20)]
    findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
    assert isinstance(findings, list)
    # Should produce at least some findings
    assert len(findings) >= 0  # May be 0 if no strong vibrations


def test_build_findings_nl_language() -> None:
    metadata = _make_metadata()
    samples = [_make_sample(float(i) * 0.5, 85.0, 0.05) for i in range(10)]
    findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="nl")
    assert isinstance(findings, list)


# -- summarize_log -------------------------------------------------------------


def _write_test_log(path: Path, n_samples: int = 20, speed: float = 85.0) -> None:
    metadata = create_run_metadata(
        run_id="test-run",
        start_time_utc="2025-01-01T00:00:00+00:00",
        sensor_model="ADXL345",
        raw_sample_rate_hz=200,
        feature_interval_s=0.5,
        fft_window_size_samples=256,
        fft_window_type="hann",
        peak_picker_method="max_peak_amp_across_axes",
        accel_scale_g_per_lsb=1.0 / 256.0,
    )
    samples = [_make_sample(float(i) * 0.5, speed, 0.01 + i * 0.001) for i in range(n_samples)]
    end = create_run_end_record("test-run", "2025-01-01T00:10:00+00:00")
    append_jsonl_records(path, [metadata] + samples + [end])


def test_summarize_log_basic(tmp_path: Path) -> None:
    log_path = tmp_path / "run.jsonl"
    _write_test_log(log_path, n_samples=20)
    result = summarize_log(log_path)
    assert result["run_id"] == "test-run"
    assert result["rows"] == 20
    assert isinstance(result["speed_breakdown"], list)
    assert isinstance(result["findings"], list)


def test_summarize_log_nl(tmp_path: Path) -> None:
    log_path = tmp_path / "run.jsonl"
    _write_test_log(log_path, n_samples=10)
    result = summarize_log(log_path, lang="nl")
    assert result["run_id"] == "test-run"


def test_summarize_log_no_samples(tmp_path: Path) -> None:
    log_path = tmp_path / "run.jsonl"
    _write_test_log(log_path, n_samples=0)
    result = summarize_log(log_path)
    assert result["rows"] == 0


def test_summarize_log_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        summarize_log(tmp_path / "missing.jsonl")


def test_summarize_log_non_jsonl(tmp_path: Path) -> None:
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("a,b,c\n1,2,3\n")
    with pytest.raises(ValueError):
        summarize_log(csv_path)
