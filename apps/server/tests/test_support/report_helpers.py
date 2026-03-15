"""Shared helpers for report test modules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from vibesensor.analysis import location_analysis as _test_plan_module
from vibesensor.analysis import (
    order_analysis as _order_analysis_module,
)
from vibesensor.analysis import (
    order_analysis as order_findings_module,
)
from vibesensor.analysis.order_analysis import (
    _build_order_findings as _findings_build_order_findings,
)
from vibesensor.runlog import (
    append_jsonl_records,
    create_run_end_record,
    create_run_metadata,
)

# Canonical run-end record reused across report tests.
RUN_END = {"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"}


def write_jsonl(path: Path, records: list[dict]) -> None:
    """Write a list of dicts as newline-delimited JSON."""
    path.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n",
        encoding="utf-8",
    )


def suitability_by_key(summary: dict) -> dict[str, dict]:
    """Index run_suitability items by their check_key."""
    return {
        str(item.get("check_key")): item
        for item in summary["run_suitability"]
        if isinstance(item, dict)
    }


def minimal_summary(**overrides: Any) -> dict:
    """Return a bare-minimum summary dict suitable for ``map_summary``.

    Callers can override or extend any key via keyword arguments.
    """
    base: dict = {
        "top_causes": [],
        "findings": [],
        "speed_stats": {},
        "test_plan": [],
        "run_suitability": [],
        "plots": {},
    }
    base.update(overrides)
    return base


def report_run_metadata(
    run_id: str = "run-01",
    *,
    raw_sample_rate_hz: int | None = 800,
    accel_scale_g_per_lsb: float | None = 1.0 / 256.0,
    **kwargs: Any,
) -> dict[str, Any]:
    """Return canonical report JSONL run_metadata with overridable fields."""
    metadata: dict[str, Any] = {
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
            },
        },
        "incomplete_for_order_analysis": raw_sample_rate_hz is None,
    }
    metadata.update(kwargs)
    return metadata


def report_sample(
    idx: int,
    *,
    speed_kmh: float | None,
    dominant_freq_hz: float,
    peak_amp_g: float,
    run_id: str = "run-01",
    client_id: str = "c1",
    client_name: str = "front-left wheel",
    vibration_strength_db: float = 22.0,
    strength_bucket: str = "l2",
    add_index_accel_offset: bool = False,
    include_secondary_peak: bool = False,
) -> dict[str, Any]:
    """Return canonical report JSONL sample record with optional variants.

    ``speed_kmh`` may be ``None`` for missing-speed scenarios.
    """
    accel_scale = float(idx) if add_index_accel_offset else 0.0
    peaks = [
        {
            "hz": dominant_freq_hz,
            "amp": peak_amp_g,
            "vibration_strength_db": vibration_strength_db,
            "strength_bucket": strength_bucket,
        },
    ]
    if include_secondary_peak:
        peaks.append(
            {
                "hz": dominant_freq_hz + 8.0,
                "amp": peak_amp_g * 0.45,
                "vibration_strength_db": 14.0,
                "strength_bucket": None,
            },
        )
    return {
        "record_type": "sample",
        "schema_version": "v2-jsonl",
        "run_id": run_id,
        "timestamp_utc": f"2026-02-15T12:00:{idx:02d}+00:00",
        "t_s": idx * 0.5,
        "client_id": client_id,
        "client_name": client_name,
        "speed_kmh": speed_kmh,
        "gps_speed_kmh": speed_kmh,
        "engine_rpm": None,
        "gear": None,
        "accel_x_g": 0.03 + (accel_scale * 0.0005),
        "accel_y_g": 0.02 + (accel_scale * 0.0003),
        "accel_z_g": 0.01 + (accel_scale * 0.0002),
        "dominant_freq_hz": dominant_freq_hz,
        "dominant_axis": "x",
        "top_peaks": peaks,
        "vibration_strength_db": vibration_strength_db,
        "strength_bucket": strength_bucket,
    }


def analysis_metadata(**overrides: Any) -> dict[str, Any]:
    """Return shared metadata defaults for report-analysis unit tests."""
    defaults = {
        "run_id": "test-run",
        "start_time_utc": "2025-01-01T00:00:00+00:00",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 200,
        "feature_interval_s": 0.5,
        "fft_window_size_samples": 256,
        "accel_scale_g_per_lsb": 1.0 / 256.0,
        "tire_width_mm": 285.0,
        "tire_aspect_pct": 30.0,
        "rim_in": 21.0,
        "final_drive_ratio": 3.08,
        "current_gear_ratio": 0.64,
    }
    defaults.update(overrides)
    valid_keys = create_run_metadata.__code__.co_varnames
    return create_run_metadata(**{k: v for k, v in defaults.items() if k in valid_keys})


def analysis_sample(
    t_s: float,
    speed_kmh: float,
    amp: float = 0.01,
    *,
    vibration_strength_db: float = 20.0,
    strength_bucket: str = "l2",
    client_name: str = "Front Left",
) -> dict[str, Any]:
    """Return shared default sample for report-analysis tests."""
    return analysis_sample_with_peaks(
        t_s,
        speed_kmh,
        [{"hz": 15.0, "amp": amp}],
        vibration_strength_db=vibration_strength_db,
        strength_bucket=strength_bucket,
        client_name=client_name,
    )


def analysis_sample_with_peaks(
    t_s: float,
    speed_kmh: float,
    peaks: list[dict[str, Any]],
    *,
    vibration_strength_db: float = 20.0,
    strength_bucket: str = "l2",
    client_name: str = "Front Left",
    strength_floor_amp_g: float | None = None,
) -> dict[str, Any]:
    """Return shared sample builder that supports explicit peaks per sample."""
    dominant = peaks[0] if peaks else {"hz": 10.0, "amp": 0.01}
    sample: dict[str, Any] = {
        "record_type": "sample",
        "t_s": t_s,
        "speed_kmh": speed_kmh,
        "accel_x_g": dominant["amp"],
        "accel_y_g": dominant["amp"],
        "accel_z_g": dominant["amp"],
        "dominant_freq_hz": dominant["hz"],
        "vibration_strength_db": vibration_strength_db,
        "strength_bucket": strength_bucket,
        "top_peaks": [
            {
                "hz": p["hz"],
                "amp": p["amp"],
                "vibration_strength_db": p.get("vibration_strength_db", vibration_strength_db),
                "strength_bucket": p.get("strength_bucket", strength_bucket),
            }
            for p in peaks
        ],
        "client_name": client_name,
    }
    if strength_floor_amp_g is not None:
        sample["strength_floor_amp_g"] = strength_floor_amp_g
    return sample


# ---------------------------------------------------------------------------
# Order-analysis integration helpers (merged from report_analysis_integration.py)
# ---------------------------------------------------------------------------


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
    monkeypatch.setattr(_order_analysis_module, "_corr_abs_clamped", lambda _pred, _meas: 0.0)
    monkeypatch.setattr(
        _test_plan_module,
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


def max_non_ref_confidence(findings: tuple | list) -> float:
    """Return the highest confidence among non-reference findings."""
    from vibesensor.domain.finding import Finding

    return max(
        float(f.confidence or 0.0) if isinstance(f, Finding) else float(f.get("confidence") or 0.0)
        for f in findings
        if (
            not f.finding_id.startswith("REF_")
            if isinstance(f, Finding)
            else not str(f.get("finding_id") or "").startswith("REF_")
        )
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
        accel_scale_g_per_lsb=1.0 / 256.0,
    )
    samples = [analysis_sample(float(i) * 0.5, speed, 0.01 + i * 0.001) for i in range(n_samples)]
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
