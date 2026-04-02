"""Shared helpers for report test modules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from test_support.findings import make_finding_payload
from vibesensor.domain import LocationHotspot
from vibesensor.use_cases.diagnostics._context import DiagnosticsContext
from vibesensor.use_cases.diagnostics._context_decode import build_diagnostics_context
from vibesensor.use_cases.diagnostics.location_analysis import LocationAnalysisResult
from vibesensor.use_cases.diagnostics.orders import (
    pipeline as order_findings_module,
)
from vibesensor.use_cases.diagnostics.orders import scoring as _order_scoring_module
from vibesensor.use_cases.diagnostics.orders import (
    statistics as _order_statistics_module,
)
from vibesensor.use_cases.diagnostics.orders.pipeline import (
    OrderAnalysisRequest,
)
from vibesensor.use_cases.diagnostics.orders.pipeline import (
    _build_order_findings as _findings_build_order_findings,
)
from vibesensor.use_cases.run.sample_builder import create_run_metadata

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
        "metadata": {},
        "report_date": "",
        "record_length": "",
        "start_time_utc": "",
        "end_time_utc": "",
        "warnings": [],
        "sensor_locations": [],
        "sensor_locations_connected_throughout": [],
        "sensor_intensity_by_location": [],
        "sensor_count_used": 0,
        "most_likely_origin": {},
        "top_causes": [],
        "findings": [],
        "speed_stats": {},
        "test_plan": [],
        "run_suitability": [],
        "plots": {},
    }
    base.update(overrides)
    return base


def sequential_same_source_summary(*, weak_spatial: bool = False) -> dict:
    """Return a report-ready summary with two same-source corners in sequence."""
    front = make_finding_payload(
        finding_id="F_FRONT",
        suspected_source="wheel/tire",
        confidence=0.64,
        strongest_location="Front Left",
        strongest_speed_band="40-60 km/h",
        dominant_phase="acceleration",
        phase_evidence={"cruise_fraction": 0.0, "phases_detected": ["acceleration"]},
        weak_spatial_separation=weak_spatial,
        frequency_hz_or_order="1x wheel order",
        matched_points=[
            {
                "speed_kmh": 48.0,
                "predicted_hz": 10.4,
                "matched_hz": 10.5,
                "location": "Front Left",
                "phase": "acceleration",
                "amp": 0.11,
            },
            {
                "speed_kmh": 54.0,
                "predicted_hz": 11.6,
                "matched_hz": 11.7,
                "location": "Front Left",
                "phase": "acceleration",
                "amp": 0.10,
            },
        ],
        confidence_label_key="CONFIDENCE_MEDIUM",
        confidence_tone="warn",
        confidence_pct="64%",
        confidence_reason="Evidence first rose during acceleration.",
    )
    rear = make_finding_payload(
        finding_id="F_REAR",
        suspected_source="wheel/tire",
        confidence=0.61,
        strongest_location="Rear Right",
        strongest_speed_band="70-90 km/h",
        dominant_phase="deceleration",
        phase_evidence={"cruise_fraction": 0.0, "phases_detected": ["deceleration"]},
        weak_spatial_separation=weak_spatial,
        frequency_hz_or_order="1x wheel order",
        matched_points=[
            {
                "speed_kmh": 82.0,
                "predicted_hz": 17.8,
                "matched_hz": 17.9,
                "location": "Rear Right",
                "phase": "deceleration",
                "amp": 0.10,
            },
            {
                "speed_kmh": 76.0,
                "predicted_hz": 16.4,
                "matched_hz": 16.3,
                "location": "Rear Right",
                "phase": "deceleration",
                "amp": 0.09,
            },
        ],
        confidence_label_key="CONFIDENCE_MEDIUM",
        confidence_tone="warn",
        confidence_pct="61%",
        confidence_reason="Evidence returned during deceleration.",
    )
    return minimal_summary(
        lang="en",
        record_length="00:18.0",
        sensor_count_used=4,
        sensor_locations=["Front Left", "Front Right", "Rear Left", "Rear Right"],
        sensor_locations_connected_throughout=[
            "Front Left",
            "Front Right",
            "Rear Left",
            "Rear Right",
        ],
        findings=[front, rear],
        top_causes=[front, rear],
        speed_stats={"steady_speed": False},
        phase_timeline=[
            {
                "phase": "acceleration",
                "start_t_s": 0.0,
                "end_t_s": 6.0,
                "speed_min_kmh": 30.0,
                "speed_max_kmh": 60.0,
                "has_fault_evidence": True,
            },
            {
                "phase": "cruise",
                "start_t_s": 6.0,
                "end_t_s": 12.0,
                "speed_min_kmh": 60.0,
                "speed_max_kmh": 80.0,
                "has_fault_evidence": False,
            },
            {
                "phase": "deceleration",
                "start_t_s": 12.0,
                "end_t_s": 18.0,
                "speed_min_kmh": 80.0,
                "speed_max_kmh": 40.0,
                "has_fault_evidence": True,
            },
        ],
    )


_GENERATED_ACTION_STEPS: dict[str, dict[str, Any]] = {
    "wheel_balance_and_runout": {
        "action_id": "wheel_balance_and_runout",
        "what": "ACTION_WHEEL_BALANCE_WHAT",
        "why": "ACTION_WHEEL_BALANCE_WHY",
        "confirm": "ACTION_WHEEL_BALANCE_CONFIRM",
        "falsify": "ACTION_WHEEL_BALANCE_FALSIFY",
        "eta": "20-45 min",
    },
    "wheel_tire_condition": {
        "action_id": "wheel_tire_condition",
        "what": "ACTION_TIRE_CONDITION_WHAT",
        "why": "ACTION_TIRE_CONDITION_WHY",
        "confirm": "ACTION_TIRE_CONDITION_CONFIRM",
        "falsify": "ACTION_TIRE_CONDITION_FALSIFY",
        "eta": "10-20 min",
    },
    "driveline_inspection": {
        "action_id": "driveline_inspection",
        "what": "ACTION_DRIVELINE_INSPECTION_WHAT",
        "why": "ACTION_DRIVELINE_INSPECTION_WHY",
        "confirm": "ACTION_DRIVELINE_INSPECTION_CONFIRM",
        "falsify": "ACTION_DRIVELINE_INSPECTION_FALSIFY",
        "eta": "20-35 min",
    },
    "driveline_mounts_and_fasteners": {
        "action_id": "driveline_mounts_and_fasteners",
        "what": "ACTION_DRIVELINE_MOUNTS_WHAT",
        "why": "ACTION_DRIVELINE_MOUNTS_WHY",
        "confirm": "ACTION_DRIVELINE_MOUNTS_CONFIRM",
        "falsify": "ACTION_DRIVELINE_MOUNTS_FALSIFY",
        "eta": "10-20 min",
    },
    "engine_mounts_and_accessories": {
        "action_id": "engine_mounts_and_accessories",
        "what": "ACTION_ENGINE_MOUNTS_WHAT",
        "why": "ACTION_ENGINE_MOUNTS_WHY",
        "confirm": "ACTION_ENGINE_MOUNTS_CONFIRM",
        "falsify": "ACTION_ENGINE_MOUNTS_FALSIFY",
        "eta": "15-30 min",
    },
    "engine_combustion_quality": {
        "action_id": "engine_combustion_quality",
        "what": "ACTION_ENGINE_COMBUSTION_WHAT",
        "why": "ACTION_ENGINE_COMBUSTION_WHY",
        "confirm": "ACTION_ENGINE_COMBUSTION_CONFIRM",
        "falsify": "ACTION_ENGINE_COMBUSTION_FALSIFY",
        "eta": "10-20 min",
    },
}


def ambiguous_primary_location_summary() -> dict:
    """Return a summary whose primary hotspot is explicitly ambiguous."""
    primary = make_finding_payload(
        finding_id="F_AMBIG",
        suspected_source="wheel/tire",
        confidence=0.82,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
        dominance_ratio=2.0,
        weak_spatial_separation=False,
        location_hotspot={
            "top_location": "Front Left",
            "location": "Front Left",
            "ambiguous_location": True,
            "alternative_locations": ["Rear Left"],
            "second_location": "Rear Left",
        },
    )
    return minimal_summary(
        lang="en",
        sensor_count_used=4,
        sensor_locations=["Front Left", "Front Right", "Rear Left", "Rear Right"],
        sensor_locations_connected_throughout=[
            "Front Left",
            "Front Right",
            "Rear Left",
            "Rear Right",
        ],
        findings=[primary],
        top_causes=[primary],
        speed_stats={"steady_speed": True},
    )


def trunk_primary_guidance_summary(*, primary_source: str) -> dict:
    """Return a summary with a trunk/body hotspot and mixed-source action plan."""
    primary_action_ids = {
        "engine": ("engine_mounts_and_accessories", "engine_combustion_quality"),
        "driveline": ("driveline_inspection", "driveline_mounts_and_fasteners"),
    }.get(primary_source)
    if primary_action_ids is None:
        raise ValueError(f"Unsupported primary source: {primary_source}")
    primary = make_finding_payload(
        finding_id="F_PRIMARY",
        suspected_source=primary_source,
        confidence=0.77,
        strongest_location="Trunk",
        strongest_speed_band="70-90 km/h",
    )
    alternative = make_finding_payload(
        finding_id="F_WHEEL",
        suspected_source="wheel/tire",
        confidence=0.71,
        strongest_location="Front Left",
        strongest_speed_band="70-90 km/h",
    )
    return minimal_summary(
        lang="en",
        sensor_count_used=4,
        sensor_locations=["Front Left", "Front Right", "Rear Left", "Rear Right"],
        sensor_locations_connected_throughout=[
            "Front Left",
            "Front Right",
            "Rear Left",
            "Rear Right",
        ],
        findings=[primary, alternative],
        top_causes=[primary, alternative],
        speed_stats={"steady_speed": True},
        test_plan=[
            dict(_GENERATED_ACTION_STEPS["wheel_balance_and_runout"]),
            dict(_GENERATED_ACTION_STEPS["wheel_tire_condition"]),
            *(dict(_GENERATED_ACTION_STEPS[action_id]) for action_id in primary_action_ids),
        ],
    )


def recapture_guidance_summary(mode: str) -> dict:
    """Return a recapture-mode summary tailored to one insufficiency mode."""
    base = {
        "lang": "en",
        "record_length": "00:20.0",
        "sensor_count_used": 4,
        "sensor_locations": ["Front Left", "Front Right", "Rear Left", "Rear Right"],
        "sensor_locations_connected_throughout": [
            "Front Left",
            "Front Right",
            "Rear Left",
            "Rear Right",
        ],
        "speed_stats": {"steady_speed": False},
    }
    if mode == "steady":
        finding = make_finding_payload(
            finding_id="F_STEADY",
            suspected_source="wheel/tire",
            confidence=0.34,
            strongest_location="Front Left",
            strongest_speed_band="40-60 km/h",
            confidence_label_key="CONFIDENCE_LOW",
            confidence_tone="neutral",
            confidence_pct="34%",
            confidence_reason="Speed was not steady during measurement",
        )
        return minimal_summary(
            **base,
            findings=[finding],
            top_causes=[finding],
            run_suitability=[
                {
                    "check_key": "SUITABILITY_CHECK_SPEED_VARIATION",
                    "state": "warn",
                    "explanation": "SUITABILITY_SPEED_VARIATION_WARN",
                }
            ],
        )
    if mode == "overlap":
        overlap_reason = (
            "Wheel and driveline evidence overlap, so the system could not strongly "
            "differentiate between them; inspect both areas."
        )
        wheel = make_finding_payload(
            finding_id="F_WHEEL_RECAPTURE",
            suspected_source="wheel/tire",
            confidence=0.35,
            strongest_location="Front Left",
            strongest_speed_band="60-80 km/h",
            signatures_observed=["1x wheel order"],
            confidence_label_key="CONFIDENCE_LOW",
            confidence_tone="neutral",
            confidence_pct="35%",
            confidence_reason=overlap_reason,
        )
        driveline = make_finding_payload(
            finding_id="F_DRIVELINE_RECAPTURE",
            suspected_source="driveline",
            confidence=0.33,
            strongest_location="Front Left",
            strongest_speed_band="60-80 km/h",
            signatures_observed=["1x driveshaft"],
            confidence_label_key="CONFIDENCE_LOW",
            confidence_tone="neutral",
            confidence_pct="33%",
            confidence_reason=overlap_reason,
        )
        return minimal_summary(
            **base,
            findings=[wheel, driveline],
            top_causes=[wheel, driveline],
        )
    if mode == "weak":
        finding = make_finding_payload(
            finding_id="F_WEAK",
            suspected_source="wheel/tire",
            confidence=0.55,
            strongest_location="Front Left",
            strongest_speed_band="50-70 km/h",
            weak_spatial_separation=True,
            confidence_label_key="CONFIDENCE_MEDIUM",
            confidence_tone="warn",
            confidence_pct="55%",
            confidence_reason="Vibration spread across multiple locations",
        )
        return minimal_summary(
            **base,
            findings=[finding],
            top_causes=[finding],
        )
    if mode == "transient":
        finding = make_finding_payload(
            finding_id="F_TRANSIENT",
            suspected_source="transient_impact",
            confidence=0.28,
            strongest_location="Rear Left",
            strongest_speed_band="20-30 km/h",
            peak_classification="transient",
            confidence_label_key="CONFIDENCE_LOW",
            confidence_tone="neutral",
            confidence_pct="28%",
            confidence_reason="Confidence downgraded due to negligible vibration strength",
        )
        return minimal_summary(
            **base,
            findings=[finding],
            top_causes=[finding],
        )
    raise ValueError(f"Unsupported recapture guidance mode: {mode}")


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


def diagnostics_context(
    metadata: dict[str, object] | None = None,
    **overrides: object,
) -> DiagnosticsContext:
    """Return a typed diagnostics context for tests."""
    raw_metadata: dict[str, object] = dict(metadata or {})
    raw_metadata.update(overrides)
    return build_diagnostics_context(raw_metadata, file_name="test")


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
        _context: object,
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
    monkeypatch.setattr(_order_statistics_module, "_corr_abs_clamped", lambda _pred, _meas: 0.0)
    monkeypatch.setattr(
        _order_scoring_module,
        "summarize_order_match_locations",
        lambda _points, **_kwargs: (
            "",
            LocationAnalysisResult(
                hotspot=LocationHotspot.from_analysis_inputs(
                    strongest_location="Front Left",
                    dominance_ratio=dominance_ratio,
                    localization_confidence=1.0,
                    weak_spatial_separation=False,
                ),
                mean_amp=0.03,
                total_samples=10,
                ambiguous_location=False,
                no_wheel_sensors=False,
                speed_range="70-80 km/h",
                dominance_ratio=dominance_ratio,
                localization_confidence=1.0,
                weak_spatial_separation=False,
                top_location="Front Left",
                second_location=None,
                partial_coverage=False,
                corroborated_by_n_sensors=1,
            ),
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
    metadata = dict(overrides.pop("metadata", {"units": {"accel_x_g": "g"}}))
    kwargs: dict[str, object] = {
        "context": overrides.pop("context", diagnostics_context(metadata)),
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
    return _findings_build_order_findings(OrderAnalysisRequest(**kwargs))


def max_non_ref_confidence(findings: tuple | list) -> float:
    """Return the highest confidence among non-reference findings."""
    from vibesensor.domain import Finding

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
    end = {
        "record_type": "run_end",
        "schema_version": "v2-jsonl",
        "run_id": "test-run",
        "end_time_utc": "2025-01-01T00:10:00+00:00",
    }
    records = [metadata] + samples + [end]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )


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
