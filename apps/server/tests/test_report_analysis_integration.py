from __future__ import annotations

from pathlib import Path

import pytest

from vibesensor.report import build_findings_for_samples, summarize_log
from vibesensor.report.findings import _speed_breakdown
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
    return create_run_metadata(**{k: v for k, v in defaults.items() if k in valid_keys})


def _make_sample(t_s: float, speed_kmh: float, amp: float = 0.01) -> dict:
    return {
        "record_type": "sample",
        "t_s": t_s,
        "speed_kmh": speed_kmh,
        "accel_x_g": amp,
        "accel_y_g": amp,
        "accel_z_g": amp,
        "dominant_freq_hz": 15.0,
        "vibration_strength_db": 20.0,
        "strength_bucket": "l2",
        "top_peaks": [
            {"hz": 15.0, "amp": amp, "vibration_strength_db": 20.0, "strength_bucket": "l2"},
        ],
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
    assert len(findings) > 0, "Expected at least one finding for samples with speed data"


def test_build_findings_nl_language() -> None:
    metadata = _make_metadata()
    samples = [_make_sample(float(i) * 0.5, 85.0, 0.05) for i in range(10)]
    findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="nl")
    assert isinstance(findings, list)
    # Verify the function accepts "nl" without error; the small dataset may not
    # produce actionable findings, so we only verify return type.


def test_build_findings_detects_sparse_high_speed_only_fault() -> None:
    from vibesensor.analysis_settings import wheel_hz_from_speed_kmh

    metadata = {
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 200.0,
        "tire_circumference_m": 2.036,
        "final_drive_ratio": 3.08,
        "current_gear_ratio": 0.64,
        "units": {"accel_x_g": "g"},
    }
    samples = []
    for idx in range(30):
        speed_kmh = 40.0 + (2.0 * idx)
        wheel_hz = wheel_hz_from_speed_kmh(speed_kmh, 2.036) or 10.0
        high_speed_band = speed_kmh >= 90.0
        samples.append(
            {
                **_make_sample(float(idx), speed_kmh, 0.03 if high_speed_band else 0.01),
                "strength_floor_amp_g": 0.003,
                "top_peaks": [
                    {"hz": wheel_hz, "amp": 0.03}
                    if high_speed_band
                    else {"hz": wheel_hz + 7.0, "amp": 0.01}
                ],
            }
        )

    findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
    wheel_finding = next(
        (f for f in findings if str(f.get("finding_key") or "") == "wheel_1x"),
        None,
    )

    assert wheel_finding is not None
    strongest_speed_band = str(wheel_finding.get("strongest_speed_band") or "")
    assert strongest_speed_band in {"90-100 km/h", "100-110 km/h"}


def test_build_findings_detects_driveline_2x_order() -> None:
    from vibesensor.analysis_settings import wheel_hz_from_speed_kmh

    metadata = {
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 200.0,
        "tire_circumference_m": 2.036,
        "final_drive_ratio": 3.08,
        "units": {"accel_x_g": "g"},
    }
    samples = []
    for idx in range(24):
        speed_kmh = 55.0 + (2.0 * idx)
        wheel_hz = wheel_hz_from_speed_kmh(speed_kmh, 2.036) or 10.0
        samples.append(
            {
                **_make_sample(float(idx), speed_kmh, 0.04),
                "strength_floor_amp_g": 0.002,
                "top_peaks": [
                    {"hz": wheel_hz * 3.08 * 2.0, "amp": 0.04},
                ],
            }
        )

    findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
    driveline_2x = next(
        (f for f in findings if str(f.get("finding_key") or "") == "driveshaft_2x"),
        None,
    )

    assert driveline_2x is not None
    assert driveline_2x.get("suspected_source") == "driveline"
    assert driveline_2x.get("frequency_hz_or_order") == "2x driveshaft order"


def test_location_speedbin_summary_reports_ambiguous_location_for_near_tie() -> None:
    from vibesensor.report.test_plan import _location_speedbin_summary

    matches = [
        {"speed_kmh": 85.0, "amp": 0.0110, "location": "Rear Right"},
        {"speed_kmh": 85.0, "amp": 0.0102, "location": "Rear Left"},
        {"speed_kmh": 86.0, "amp": 0.0112, "location": "Rear Right"},
        {"speed_kmh": 86.0, "amp": 0.0103, "location": "Rear Left"},
    ]

    sentence, hotspot = _location_speedbin_summary(matches, lang="en")

    assert hotspot is not None
    assert bool(hotspot.get("ambiguous_location"))
    assert hotspot.get("location") == "ambiguous location: Rear Right / Rear Left"
    assert hotspot.get("ambiguous_locations") == ["Rear Right", "Rear Left"]
    assert float(hotspot.get("localization_confidence") or 0.0) < 0.4
    assert "ambiguous location" in sentence


def test_location_speedbin_summary_weak_spatial_threshold_adapts_to_location_count() -> None:
    from vibesensor.report.test_plan import _location_speedbin_summary

    base_matches = [
        {"speed_kmh": 85.0, "amp": 1.30, "location": "Front Left"},
        {"speed_kmh": 85.0, "amp": 1.00, "location": "Front Right"},
    ]

    _, hotspot_2 = _location_speedbin_summary(base_matches, lang="en")
    assert hotspot_2 is not None
    assert hotspot_2.get("weak_spatial_separation") is False

    matches_3 = base_matches + [{"speed_kmh": 85.0, "amp": 0.40, "location": "Rear Left"}]
    _, hotspot_3 = _location_speedbin_summary(matches_3, lang="en")
    assert hotspot_3 is not None
    assert hotspot_3.get("weak_spatial_separation") is True

    matches_4 = matches_3 + [{"speed_kmh": 85.0, "amp": 0.35, "location": "Rear Right"}]
    _, hotspot_4 = _location_speedbin_summary(matches_4, lang="en")
    assert hotspot_4 is not None
    assert hotspot_4.get("weak_spatial_separation") is True


def test_most_likely_origin_summary_uses_adaptive_weak_spatial_fallback() -> None:
    from vibesensor.report.summary import _most_likely_origin_summary

    findings = [
        {
            "suspected_source": "wheel/tire",
            "strongest_location": "Front Left",
            "strongest_speed_band": "80-90 km/h",
            "dominance_ratio": 1.30,
            "weak_spatial_separation": False,
            "location_hotspot": {"location_count": 3},
            "confidence_0_to_1": 0.8,
        }
    ]

    origin = _most_likely_origin_summary(findings, "en")
    assert origin["weak_spatial_separation"] is True


def test_location_speedbin_summary_can_restrict_to_relevant_speed_bins() -> None:
    from vibesensor.report.test_plan import _location_speedbin_summary

    matches = [
        {"speed_kmh": 65.0, "amp": 0.030, "location": "Rear Left"},
        {"speed_kmh": 66.0, "amp": 0.028, "location": "Rear Left"},
        {"speed_kmh": 105.0, "amp": 0.019, "location": "Front Right"},
        {"speed_kmh": 106.0, "amp": 0.020, "location": "Front Right"},
    ]

    _, unconstrained = _location_speedbin_summary(matches, lang="en")
    _, focused = _location_speedbin_summary(
        matches,
        lang="en",
        relevant_speed_bins=["100-110 km/h"],
    )

    assert unconstrained is not None
    assert focused is not None
    assert unconstrained.get("location") == "Rear Left"
    assert focused.get("location") == "Front Right"
    assert focused.get("speed_range") == "100-110 km/h"


def test_build_findings_penalizes_low_localization_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vibesensor.analysis_settings import wheel_hz_from_speed_kmh
    from vibesensor.report import findings as findings_module

    metadata = {
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 200.0,
        "tire_circumference_m": 2.036,
        "final_drive_ratio": 3.08,
        "current_gear_ratio": 0.64,
        "units": {"accel_x_g": "g"},
    }
    samples = []
    for idx in range(24):
        speed = 70.0 + idx
        wheel_hz = wheel_hz_from_speed_kmh(speed, 2.036) or 10.0
        samples.append(
            {
                **_make_sample(float(idx), speed, 0.03),
                "top_peaks": [{"hz": wheel_hz, "amp": 0.03}],
            }
        )

    monkeypatch.setattr(
        findings_module,
        "_location_speedbin_summary",
        lambda matched_points, lang, relevant_speed_bins=None: (
            "strong location",
            {
                "location": "Front Left",
                "speed_range": "70-80 km/h",
                "dominance_ratio": 2.0,
                "weak_spatial_separation": False,
                "localization_confidence": 1.0,
            },
        ),
    )
    high_conf_findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
    high_conf = max(
        float(f.get("confidence_0_to_1") or 0.0)
        for f in high_conf_findings
        if not str(f.get("finding_id") or "").startswith("REF_")
    )

    monkeypatch.setattr(
        findings_module,
        "_location_speedbin_summary",
        lambda matched_points, lang, relevant_speed_bins=None: (
            "ambiguous location",
            {
                "location": "ambiguous location: Front Left / Front Right",
                "speed_range": "70-80 km/h",
                "dominance_ratio": 1.05,
                "weak_spatial_separation": False,
                "localization_confidence": 0.1,
            },
        ),
    )
    low_conf_findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
    low_conf = max(
        float(f.get("confidence_0_to_1") or 0.0)
        for f in low_conf_findings
        if not str(f.get("finding_id") or "").startswith("REF_")
    )

    assert low_conf < high_conf


def test_build_findings_passes_focused_speed_band_to_location_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vibesensor.analysis_settings import wheel_hz_from_speed_kmh
    from vibesensor.report import findings as findings_module

    metadata = {
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 200.0,
        "tire_circumference_m": 2.036,
        "final_drive_ratio": 3.08,
        "current_gear_ratio": 0.64,
        "units": {"accel_x_g": "g"},
    }

    seen_relevant_speed_bins: list[str] = []

    def _fake_location_summary(matches, lang, relevant_speed_bins=None):
        if isinstance(relevant_speed_bins, list):
            seen_relevant_speed_bins.extend(str(item) for item in relevant_speed_bins if item)
        chosen_band = seen_relevant_speed_bins[0] if seen_relevant_speed_bins else "90-100 km/h"
        return (
            "focused location",
            {
                "location": "Front Right",
                "speed_range": chosen_band,
                "dominance_ratio": 1.4,
                "weak_spatial_separation": False,
                "localization_confidence": 0.8,
            },
        )

    monkeypatch.setattr(findings_module, "_location_speedbin_summary", _fake_location_summary)

    samples = []
    for idx in range(30):
        speed_kmh = 40.0 + (2.0 * idx)
        wheel_hz = wheel_hz_from_speed_kmh(speed_kmh, 2.036) or 10.0
        high_speed_band = speed_kmh >= 90.0
        sample = {
            **_make_sample(float(idx), speed_kmh, 0.03 if high_speed_band else 0.01),
            "strength_floor_amp_g": 0.003,
            "top_peaks": [
                {"hz": wheel_hz, "amp": 0.03}
                if high_speed_band
                else {"hz": wheel_hz + 7.0, "amp": 0.01}
            ],
        }
        samples.append(sample)

    findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
    wheel_finding = next(
        (f for f in findings if str(f.get("finding_key") or "") == "wheel_1x"),
        None,
    )

    assert wheel_finding is not None
    assert seen_relevant_speed_bins, "Expected focused speed-bin filter to be passed"
    assert seen_relevant_speed_bins[0] in {"90-100 km/h", "100-110 km/h"}
    assert wheel_finding.get("strongest_location") == "Front Right"


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


def test_summarize_log_missing_precomputed_strength_metrics_raises(tmp_path: Path) -> None:
    log_path = tmp_path / "run_missing_strength.jsonl"
    metadata = _make_metadata()
    sample = _make_sample(0.0, 80.0, 0.02)
    sample.pop("vibration_strength_db", None)
    end = create_run_end_record("test-run", "2025-01-01T00:00:10+00:00")
    append_jsonl_records(log_path, [metadata, sample, end])
    with pytest.raises(ValueError, match="Missing required precomputed strength metrics"):
        summarize_log(log_path)


def test_summarize_log_allows_partial_missing_precomputed_strength_metrics(tmp_path: Path) -> None:
    log_path = tmp_path / "run_partial_missing_strength.jsonl"
    metadata = _make_metadata()
    sample_missing = _make_sample(0.0, 80.0, 0.02)
    sample_missing.pop("vibration_strength_db", None)
    sample_valid = _make_sample(0.5, 82.0, 0.021)
    end = create_run_end_record("test-run", "2025-01-01T00:00:10+00:00")
    append_jsonl_records(log_path, [metadata, sample_missing, sample_valid, end])

    summary = summarize_log(log_path)
    assert summary["rows"] == 2
    assert summary["findings"] is not None
