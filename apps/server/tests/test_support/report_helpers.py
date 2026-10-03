"""Shared helpers for report test modules."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from test_support.core import canonicalize_run_context_metadata
from test_support.findings import NO_FAULT_DIAGNOSIS
from test_support.report_record_builders import (
    RUN_END as RUN_END,
)
from test_support.report_record_builders import (
    analysis_metadata as analysis_metadata,
)
from test_support.report_record_builders import (
    analysis_sample as analysis_sample,
)
from test_support.report_record_builders import (
    analysis_sample_with_peaks as analysis_sample_with_peaks,
)
from test_support.report_record_builders import (
    diagnostics_context as diagnostics_context,
)
from test_support.report_record_builders import (
    make_order_finding_samples as make_order_finding_samples,
)
from test_support.report_record_builders import (
    report_run_metadata as report_run_metadata,
)
from test_support.report_record_builders import (
    report_sample as report_sample,
)
from vibesensor.analysis.location_analysis import LocationAnalysisResult
from vibesensor.analysis.orders import pipeline as order_findings_module
from vibesensor.analysis.orders import scoring as _order_scoring_module
from vibesensor.analysis.orders import statistics as _order_statistics_module
from vibesensor.analysis.orders.pipeline import (
    OrderAnalysisRequest,
)
from vibesensor.analysis.orders.pipeline import (
    _build_order_findings as _findings_build_order_findings,
)
from vibesensor.domain.location_hotspot import LocationHotspot
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings


def suitability_by_key(summary: dict) -> dict[str, dict]:
    """Index run_suitability items by their check_key."""
    return {
        str(item.get("check_key")): item
        for item in summary["run_suitability"]
        if isinstance(item, dict)
    }


def minimal_summary(**overrides: Any) -> dict:
    """Return a bare-minimum analysis summary that the report view model accepts.

    Callers can override or extend any key via keyword arguments.
    """
    base: dict = {
        "run_id": "run-01",
        "lang": "en",
        "metadata": {},
        "report_date": "",
        "record_length": "",
        "duration_s": 0.0,
        "raw_sample_rate_hz": None,
        "start_time_utc": "",
        "end_time_utc": "",
        "warnings": [],
        "sensor_locations": [],
        "sensor_locations_connected_throughout": [],
        "sensor_intensity_by_location": [],
        "sensor_count_used": 0,
        "most_likely_origin": {},
        "diagnosis": deepcopy(NO_FAULT_DIAGNOSIS),
        "top_causes": [],
        "findings": [],
        "speed_stats": {"min_kmh": None, "max_kmh": None},
        "phase_info": {"phase_pcts": {}},
        "test_plan": [],
        "run_suitability": [],
        "plots": {},
    }
    base.update(overrides)
    raw_metadata = base.get("metadata")
    raw_run_id = str(base.get("run_id") or "").strip()
    if isinstance(raw_metadata, dict) and raw_metadata and raw_run_id:
        metadata = dict(raw_metadata)
        metadata.setdefault("run_id", raw_run_id)
        base["metadata"] = metadata
    return base


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
    return canonicalize_run_context_metadata(base)


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
        "samples": sensor_frames_from_mappings(samples),
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
