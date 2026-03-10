"""Shared helpers for report analysis integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from test_support.report_helpers import analysis_sample as _make_sample
from vibesensor.analysis.findings import order_findings as order_findings_module
from vibesensor.analysis.findings.order_findings import (
    _build_order_findings as _findings_build_order_findings,
)
from vibesensor.runlog import (
    append_jsonl_records,
    create_run_end_record,
    create_run_metadata,
)


class HypothesisStub:
    """Stub hypothesis for monkeypatching order findings."""

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
        return 5.0, "speed_kmh"


def wheel_metadata(**overrides: object) -> dict[str, object]:
    """Return a standard wheel-analysis metadata dict, optionally overridden."""
    base: dict[str, object] = {
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 200.0,
        "tire_circumference_m": 2.036,
        "final_drive_ratio": 3.08,
        "current_gear_ratio": 0.64,
        "units": {"accel_x_g": "g"},
    }
    base.update(overrides)
    return base


def patch_order_hypothesis(
    monkeypatch: pytest.MonkeyPatch,
    *,
    dominance_ratio: float = 2.0,
) -> None:
    """Apply standard order-hypothesis stubs to order-findings internals."""
    monkeypatch.setattr(order_findings_module, "_order_hypotheses", lambda: [HypothesisStub()])
    monkeypatch.setattr(order_findings_module, "_corr_abs_clamped", lambda _pred, _meas: 0.0)
    monkeypatch.setattr(
        order_findings_module,
        "_location_speedbin_summary",
        lambda _points, **_kwargs: (
            "",
            {
                "weak_spatial_separation": False,
                "localization_confidence": 1.0,
                "dominance_ratio": dominance_ratio,
            },
        ),
    )
    monkeypatch.setattr(order_findings_module, "ORDER_MIN_CONFIDENCE", 0.0)


def call_build_order_findings(
    samples: list[dict],
    *,
    per_sample_phases=None,
    speed_stddev_kmh: float = 12.0,
    engine_ref_sufficient: bool = True,
    **overrides: object,
) -> list[dict]:
    """Thin wrapper around _build_order_findings with sensible defaults."""
    kwargs: dict[str, object] = {
        "metadata": {"units": {"accel_x_g": "g"}},
        "samples": samples,
        "speed_sufficient": True,
        "steady_speed": False,
        "speed_stddev_kmh": speed_stddev_kmh,
        "tire_circumference_m": 2.036,
        "engine_ref_sufficient": engine_ref_sufficient,
        "raw_sample_rate_hz": 200.0,
        "connected_locations": {"front_left"},
        "lang": "en",
    }
    if per_sample_phases is not None:
        kwargs["per_sample_phases"] = per_sample_phases
    kwargs.update(overrides)
    return _findings_build_order_findings(**kwargs)


def max_non_ref_confidence(findings: list[dict[str, object]]) -> float:
    """Return the highest confidence among non-reference findings."""
    return max(
        float(f.get("confidence_0_to_1") or 0.0)
        for f in findings
        if not str(f.get("finding_id") or "").startswith("REF_")
    )


def write_test_log(path: Path, n_samples: int = 20, speed: float = 85.0) -> None:
    """Write a small run log with precomputed strength metrics."""
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


def make_order_finding_samples(
    n: int,
    speed_kmh: float,
    wheel_hz: float,
    *,
    amp: float = 0.05,
    floor_amp: float = 0.002,
) -> list[dict]:
    """Build minimal samples that produce a matched wheel-order peak."""
    return [
        {
            "t_s": float(i),
            "speed_kmh": speed_kmh,
            "vibration_strength_db": 30.0,
            "strength_floor_amp_g": floor_amp,
            "top_peaks": [{"hz": wheel_hz, "amp": amp}],
            "location": "front_left",
        }
        for i in range(n)
    ]
