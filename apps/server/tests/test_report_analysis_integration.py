from __future__ import annotations

from pathlib import Path

import pytest

from vibesensor.report import build_findings_for_samples, summarize_log
from vibesensor.report import findings as findings_module
from vibesensor.report.findings import _speed_breakdown
from vibesensor.report.plot_data import _top_peaks_table_rows
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


def test_build_findings_orders_informational_transients_after_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_order_findings(**_kwargs) -> list[dict[str, object]]:
        return [
            {
                "finding_id": "F_PEAK",
                "severity": "diagnostic",
                "suspected_source": "wheel/tire",
                "confidence_0_to_1": 0.30,
            }
        ]

    def _fake_persistent_peaks(**_kwargs) -> list[dict[str, object]]:
        return [
            {
                "finding_id": "F_PEAK",
                "severity": "info",
                "suspected_source": "transient_impact",
                "peak_classification": "transient",
                "confidence_0_to_1": 0.22,
            }
        ]

    monkeypatch.setattr(findings_module, "_build_order_findings", _fake_order_findings)
    monkeypatch.setattr(
        findings_module,
        "_build_persistent_peak_findings",
        _fake_persistent_peaks,
    )

    findings = findings_module._build_findings(
        metadata={"units": {"accel_x_g": "g"}},
        samples=[],
        speed_sufficient=True,
        steady_speed=False,
        speed_stddev_kmh=None,
        speed_non_null_pct=100.0,
        raw_sample_rate_hz=200.0,
        lang="en",
    )
    non_ref_findings = [
        f
        for f in findings
        if isinstance(f, dict) and not str(f.get("finding_id", "")).startswith("REF_")
    ]

    assert len(non_ref_findings) >= 2
    assert str(non_ref_findings[0].get("severity") or "") != "info"
    assert str(non_ref_findings[-1].get("severity") or "") == "info"


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
    assert strongest_speed_band.endswith("km/h")
    low_str, high_str = strongest_speed_band.replace(" km/h", "").split("-", maxsplit=1)
    assert float(low_str) >= 90.0
    assert float(high_str) >= float(low_str)


def test_build_order_findings_min_match_threshold_stays_below_confidence_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Hypothesis:
        key = "wheel_1x"
        order = 1.0
        order_label_base = "wheel order"
        source = "wheel/tire"
        suspected_source = "wheel/tire"

        @staticmethod
        def predicted_hz(
            _sample: dict,
            _metadata: dict,
            _circumference: float | None,
        ) -> tuple[float, str]:
            return 1.0, "speed_kmh"

    monkeypatch.setattr(findings_module, "_order_hypotheses", lambda: [_Hypothesis()])
    monkeypatch.setattr(findings_module, "_corr_abs", lambda _pred, _meas: 0.0)
    monkeypatch.setattr(
        findings_module,
        "_location_speedbin_summary",
        lambda _points, **_kwargs: (
            "",
            {
                "weak_spatial_separation": False,
                "localization_confidence": 1.0,
                "dominance_ratio": 1.2,
            },
        ),
    )
    monkeypatch.setattr(findings_module, "ORDER_MIN_CONFIDENCE", 0.0)

    samples: list[dict] = []
    for idx in range(16):
        matched = idx < 4
        samples.append(
            {
                "t_s": float(idx),
                "speed_kmh": 40.0 + idx,
                "strength_floor_amp_g": 1000.0,
                "top_peaks": [{"hz": 1.5 if matched else 3.0, "amp": 0.001}],
                "location": "front_left",
            }
        )

    findings = findings_module._build_order_findings(
        metadata={"units": {"accel_x_g": "g"}},
        samples=samples,
        speed_sufficient=True,
        steady_speed=False,
        speed_stddev_kmh=12.0,
        tire_circumference_m=2.036,
        engine_ref_sufficient=True,
        raw_sample_rate_hz=200.0,
        accel_units="g",
        connected_locations={"front_left"},
        lang="en",
    )

    assert len(findings) == 1
    finding = findings[0]
    confidence = float(finding.get("confidence_0_to_1") or 0.0)
    match_rate = float(((finding.get("evidence_metrics") or {}).get("global_match_rate")) or 0.0)

    assert match_rate == pytest.approx(0.25)
    assert confidence < 0.25


def test_build_order_findings_dominant_phase_set_when_phase_onset_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dominant_phase is populated when the majority of matched samples share a phase."""

    class _Hypothesis:
        key = "wheel_1x"
        order = 1.0
        order_label_base = "wheel order"
        source = "wheel/tire"
        suspected_source = "wheel/tire"

        @staticmethod
        def predicted_hz(
            _sample: dict,
            _metadata: dict,
            _circumference: float | None,
        ) -> tuple[float, str]:
            return 1.0, "speed_kmh"

    monkeypatch.setattr(findings_module, "_order_hypotheses", lambda: [_Hypothesis()])
    monkeypatch.setattr(findings_module, "_corr_abs", lambda _pred, _meas: 0.0)
    monkeypatch.setattr(
        findings_module,
        "_location_speedbin_summary",
        lambda _points, **_kwargs: (
            "",
            {
                "weak_spatial_separation": False,
                "localization_confidence": 1.0,
                "dominance_ratio": 2.0,
            },
        ),
    )
    monkeypatch.setattr(findings_module, "ORDER_MIN_CONFIDENCE", 0.0)

    from vibesensor.report.phase_segmentation import DrivingPhase

    # 20 samples all in acceleration phase, all matching at 1.0 Hz
    n = 20
    samples: list[dict] = [
        {
            "t_s": float(i),
            "speed_kmh": 40.0 + float(i),
            "strength_floor_amp_g": 0.001,
            "top_peaks": [{"hz": 1.0, "amp": 0.05}],
            "location": "front_left",
        }
        for i in range(n)
    ]
    per_sample_phases = [DrivingPhase.ACCELERATION] * n

    findings = findings_module._build_order_findings(
        metadata={"units": {"accel_x_g": "g"}},
        samples=samples,
        speed_sufficient=True,
        steady_speed=False,
        speed_stddev_kmh=12.0,
        tire_circumference_m=2.036,
        engine_ref_sufficient=True,
        raw_sample_rate_hz=200.0,
        accel_units="g",
        connected_locations={"front_left"},
        lang="en",
        per_sample_phases=per_sample_phases,
    )

    assert len(findings) == 1
    assert findings[0].get("dominant_phase") == "acceleration"


def test_build_order_findings_dominant_phase_none_without_phases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dominant_phase is None when per_sample_phases is not provided."""

    class _Hypothesis:
        key = "wheel_1x"
        order = 1.0
        order_label_base = "wheel order"
        source = "wheel/tire"
        suspected_source = "wheel/tire"

        @staticmethod
        def predicted_hz(
            _sample: dict,
            _metadata: dict,
            _circumference: float | None,
        ) -> tuple[float, str]:
            return 1.0, "speed_kmh"

    monkeypatch.setattr(findings_module, "_order_hypotheses", lambda: [_Hypothesis()])
    monkeypatch.setattr(findings_module, "_corr_abs", lambda _pred, _meas: 0.0)
    monkeypatch.setattr(
        findings_module,
        "_location_speedbin_summary",
        lambda _points, **_kwargs: (
            "",
            {
                "weak_spatial_separation": False,
                "localization_confidence": 1.0,
                "dominance_ratio": 2.0,
            },
        ),
    )
    monkeypatch.setattr(findings_module, "ORDER_MIN_CONFIDENCE", 0.0)

    n = 20
    samples: list[dict] = [
        {
            "t_s": float(i),
            "speed_kmh": 40.0 + float(i),
            "strength_floor_amp_g": 0.001,
            "top_peaks": [{"hz": 1.0, "amp": 0.05}],
            "location": "front_left",
        }
        for i in range(n)
    ]

    findings = findings_module._build_order_findings(
        metadata={"units": {"accel_x_g": "g"}},
        samples=samples,
        speed_sufficient=True,
        steady_speed=False,
        speed_stddev_kmh=12.0,
        tire_circumference_m=2.036,
        engine_ref_sufficient=True,
        raw_sample_rate_hz=200.0,
        accel_units="g",
        connected_locations={"front_left"},
        lang="en",
    )

    assert len(findings) == 1
    assert findings[0].get("dominant_phase") is None


def test_build_findings_order_exposes_structured_speed_profile() -> None:
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
    for idx in range(24):
        speed_kmh = 60.0 + float(idx)
        wheel_hz = wheel_hz_from_speed_kmh(speed_kmh, 2.036) or 10.0
        amp = 0.01 + (0.0008 * idx)
        samples.append(
            {
                **_make_sample(float(idx), speed_kmh, amp),
                "strength_floor_amp_g": 0.002,
                "top_peaks": [{"hz": wheel_hz, "amp": amp}],
            }
        )

    findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
    wheel_finding = next(
        (f for f in findings if str(f.get("finding_key") or "") == "wheel_1x"),
        None,
    )
    assert wheel_finding is not None

    peak_speed = wheel_finding.get("peak_speed_kmh")
    speed_window = wheel_finding.get("speed_window_kmh")
    assert isinstance(peak_speed, float)
    assert isinstance(speed_window, list)
    assert len(speed_window) == 2
    low = float(speed_window[0])
    high = float(speed_window[1])
    assert low <= high
    assert low <= peak_speed <= (60.0 + 23.0)
    assert str(wheel_finding.get("strongest_speed_band") or "").endswith("km/h")


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


def test_build_findings_persistent_peak_exposes_structured_speed_profile() -> None:
    metadata = {
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 200.0,
        "units": {"accel_x_g": "g"},
    }
    samples = []
    for idx in range(28):
        speed_kmh = 50.0 + float(idx)
        amp = 0.012 + (0.010 * (1.0 - abs(speed_kmh - 68.0) / 20.0))
        samples.append(
            {
                **_make_sample(float(idx), speed_kmh, amp),
                "strength_floor_amp_g": 0.002,
                "top_peaks": [{"hz": 73.0, "amp": max(0.004, amp)}],
            }
        )

    findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
    persistent = next(
        (f for f in findings if str(f.get("finding_key") or "").startswith("peak_")),
        None,
    )
    assert persistent is not None

    peak_speed = persistent.get("peak_speed_kmh")
    speed_window = persistent.get("speed_window_kmh")
    assert isinstance(peak_speed, float)
    assert isinstance(speed_window, list)
    assert len(speed_window) == 2
    low = float(speed_window[0])
    high = float(speed_window[1])
    assert low <= high
    assert low <= peak_speed <= (50.0 + 27.0)
    assert str(persistent.get("strongest_speed_band") or "").endswith("km/h")


def test_speed_band_semantics_are_aligned_across_findings_and_peak_table() -> None:
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
    for idx, speed_kmh in enumerate(range(40, 121)):
        speed_val = float(speed_kmh)
        wheel_hz = wheel_hz_from_speed_kmh(speed_val, 2.036) or 10.0
        amp = 0.08 if 75 <= speed_kmh <= 90 else 0.01
        samples.append(
            {
                **_make_sample(float(idx), speed_val, amp),
                "strength_floor_amp_g": 0.003,
                "top_peaks": [
                    {"hz": wheel_hz, "amp": amp},
                    {"hz": 43.0, "amp": amp},
                ],
            }
        )

    findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")

    wheel_finding = next(
        (f for f in findings if str(f.get("finding_key") or "") == "wheel_1x"),
        None,
    )
    persistent = next(
        (f for f in findings if str(f.get("finding_key") or "").startswith("peak_")),
        None,
    )

    assert wheel_finding is not None
    assert persistent is not None

    order_band = str(wheel_finding.get("strongest_speed_band") or "")
    persistent_band = str(persistent.get("strongest_speed_band") or "")

    rows = _top_peaks_table_rows(samples, top_n=6, freq_bin_hz=1.0)
    target_row = min(rows, key=lambda row: abs(float(row.get("frequency_hz") or 0.0) - 43.0))
    peak_table_band = str(target_row.get("typical_speed_band") or "")

    assert order_band
    assert persistent_band
    assert peak_table_band and peak_table_band != "-"
    assert order_band == persistent_band == peak_table_band

    low_str, high_str = order_band.replace(" km/h", "").split("-", maxsplit=1)
    low = float(low_str)
    high = float(high_str)
    assert 70.0 <= low <= 90.0
    assert 80.0 <= high <= 100.0
    assert (high - low) <= 20.0


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
    focused_range = str(focused.get("speed_range") or "")
    low_text, high_text = focused_range.replace(" km/h", "").split("-", maxsplit=1)
    assert float(low_text) >= 100.0
    assert float(high_text) <= 110.0


def test_location_speedbin_summary_reports_weighted_boundary_straddling_window() -> None:
    from vibesensor.report.test_plan import _location_speedbin_summary

    matches = [
        {"speed_kmh": 74.0, "amp": 0.005, "location": "Front Left"},
        {"speed_kmh": 75.0, "amp": 0.005, "location": "Front Left"},
        {"speed_kmh": 76.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 77.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 78.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 79.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 80.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 81.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 82.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 83.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 84.0, "amp": 0.005, "location": "Front Left"},
    ]

    _, hotspot = _location_speedbin_summary(matches, lang="en")

    assert hotspot is not None
    speed_range = str(hotspot.get("speed_range") or "")
    low_text, high_text = speed_range.replace(" km/h", "").split("-", maxsplit=1)
    low, high = float(low_text), float(high_text)
    assert 75.0 <= low <= 77.0
    assert 83.0 <= high <= 85.0
    assert speed_range not in {"70-80 km/h", "80-90 km/h"}


def test_location_speedbin_summary_prefers_better_sample_coverage_over_tiny_outlier_bin() -> None:
    from vibesensor.report.test_plan import _location_speedbin_summary

    sparse_loud_bin = [
        {"speed_kmh": 85.0, "amp": 0.120, "location": "Rear Left"},
        {"speed_kmh": 86.0, "amp": 0.120, "location": "Rear Left"},
    ]
    dense_moderate_bin = [
        {"speed_kmh": 95.0 + (0.1 * idx), "amp": 0.090, "location": "Front Left"}
        for idx in range(20)
    ]

    _, hotspot = _location_speedbin_summary(sparse_loud_bin + dense_moderate_bin, lang="en")

    assert hotspot is not None
    assert hotspot.get("location") == "Front Left"
    speed_range = str(hotspot.get("speed_range") or "")
    low_text, high_text = speed_range.replace(" km/h", "").split("-", maxsplit=1)
    low, high = float(low_text), float(high_text)
    assert 95.0 <= low <= high <= 97.0


def test_location_speedbin_summary_prefers_multi_sensor_corroborated_location() -> None:
    from vibesensor.report.test_plan import _location_speedbin_summary

    matches = [
        {
            "speed_kmh": 92.0,
            "amp": 0.120,
            "location": "Front Right",
            "matched_hz": 33.0,
            "rel_error": 0.40,
        },
        {
            "speed_kmh": 92.0,
            "amp": 0.055,
            "location": "Front Left",
            "matched_hz": 40.0,
            "rel_error": 0.01,
        },
        {
            "speed_kmh": 92.0,
            "amp": 0.048,
            "location": "Rear Left",
            "matched_hz": 40.1,
            "rel_error": 0.01,
        },
        {
            "speed_kmh": 92.0,
            "amp": 0.047,
            "location": "Rear Right",
            "matched_hz": 39.9,
            "rel_error": 0.01,
        },
    ]

    _, hotspot = _location_speedbin_summary(matches, lang="en")

    assert hotspot is not None
    assert hotspot.get("top_location") == "Front Left"
    assert int(hotspot.get("corroborated_by_n_sensors") or 0) >= 3


def test_location_speedbin_summary_prefers_connected_throughout_locations() -> None:
    from vibesensor.report.test_plan import _location_speedbin_summary

    matches = [
        {"speed_kmh": 85.0, "amp": 0.022, "location": "Front Left"},
        {"speed_kmh": 86.0, "amp": 0.023, "location": "Front Left"},
        {"speed_kmh": 85.0, "amp": 0.050, "location": "Rear Right"},
        {"speed_kmh": 86.0, "amp": 0.048, "location": "Rear Right"},
    ]

    _, hotspot = _location_speedbin_summary(
        matches,
        lang="en",
        connected_locations={"Front Left"},
    )

    assert hotspot is not None
    assert hotspot.get("top_location") == "Front Left"
    assert bool(hotspot.get("partial_coverage")) is False


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
        lambda matched_points, lang, relevant_speed_bins=None, connected_locations=None: (
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
        lambda matched_points, lang, relevant_speed_bins=None, connected_locations=None: (
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


def test_build_findings_penalizes_weak_spatial_separation_by_dominance_ratio(
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
        speed = 65.0 + idx
        wheel_hz = wheel_hz_from_speed_kmh(speed, 2.036) or 10.0
        samples.append(
            {
                **_make_sample(float(idx), speed, 0.03),
                "top_peaks": [{"hz": wheel_hz, "amp": 0.03}],
            }
        )

    def _max_conf(findings: list[dict[str, object]]) -> float:
        return max(
            float(f.get("confidence_0_to_1") or 0.0)
            for f in findings
            if not str(f.get("finding_id") or "").startswith("REF_")
        )

    monkeypatch.setattr(
        findings_module,
        "_location_speedbin_summary",
        lambda matched_points, lang, relevant_speed_bins=None, connected_locations=None: (
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
    baseline_conf = _max_conf(
        build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
    )

    monkeypatch.setattr(
        findings_module,
        "_location_speedbin_summary",
        lambda matched_points, lang, relevant_speed_bins=None, connected_locations=None: (
            "weak location",
            {
                "location": "Front Left",
                "speed_range": "70-80 km/h",
                "dominance_ratio": 1.15,
                "weak_spatial_separation": True,
                "localization_confidence": 1.0,
            },
        ),
    )
    weak_conf = _max_conf(build_findings_for_samples(metadata=metadata, samples=samples, lang="en"))

    monkeypatch.setattr(
        findings_module,
        "_location_speedbin_summary",
        lambda matched_points, lang, relevant_speed_bins=None, connected_locations=None: (
            "near tie location",
            {
                "location": "ambiguous location: Front Left / Front Right",
                "speed_range": "70-80 km/h",
                "dominance_ratio": 1.04,
                "weak_spatial_separation": True,
                "localization_confidence": 1.0,
            },
        ),
    )
    near_tie_conf = _max_conf(
        build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
    )

    assert weak_conf <= (baseline_conf * 0.80) + 1e-9
    assert near_tie_conf <= (baseline_conf * 0.70) + 1e-9
    assert near_tie_conf < weak_conf


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

    def _fake_location_summary(matches, lang, relevant_speed_bins=None, connected_locations=None):
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


def test_build_findings_excludes_partial_coverage_sensor_from_strongest_location() -> None:
    from vibesensor.analysis_settings import wheel_hz_from_speed_kmh

    metadata = {
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 200.0,
        "tire_circumference_m": 2.036,
        "final_drive_ratio": 3.08,
        "current_gear_ratio": 0.64,
        "units": {"accel_x_g": "g"},
    }

    samples: list[dict[str, object]] = []
    for idx in range(20):
        speed_kmh = 70.0 + idx
        wheel_hz = wheel_hz_from_speed_kmh(speed_kmh, 2.036) or 10.0

        full_sensor = {
            **_make_sample(float(idx), speed_kmh, 0.02),
            "client_name": "Front Left",
            "strength_floor_amp_g": 0.002,
            "top_peaks": [{"hz": wheel_hz, "amp": 0.02}],
        }
        samples.append(full_sensor)

        if idx < 6:
            partial_sensor = {
                **_make_sample(float(idx), speed_kmh, 0.05),
                "client_name": "Rear Right",
                "strength_floor_amp_g": 0.002,
                "top_peaks": [{"hz": wheel_hz, "amp": 0.05}],
            }
            samples.append(partial_sensor)

    findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
    wheel_finding = next(
        (f for f in findings if str(f.get("finding_key") or "") == "wheel_1x"),
        None,
    )

    assert wheel_finding is not None
    assert wheel_finding.get("strongest_location") == "Front Left"
    hotspot = wheel_finding.get("location_hotspot")
    assert isinstance(hotspot, dict)
    assert bool(hotspot.get("partial_coverage")) is False


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
