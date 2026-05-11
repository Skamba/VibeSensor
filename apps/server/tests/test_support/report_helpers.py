"""Shared helpers for report test modules."""

from __future__ import annotations

from typing import Any

import pytest

from test_support.core import canonicalize_run_context_metadata
from test_support.findings import make_finding_payload
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
from test_support.report_record_builders import (
    write_jsonl as write_jsonl,
)
from test_support.report_record_builders import (
    write_test_log as write_test_log,
)
from vibesensor.domain import LocationHotspot
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
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


def suitability_by_key(summary: dict) -> dict[str, dict]:
    """Index run_suitability items by their check_key."""
    return {
        str(item.get("check_key")): item
        for item in summary["run_suitability"]
        if isinstance(item, dict)
    }


def minimal_summary(**overrides: Any) -> dict:
    """Return a bare-minimum summary dict suitable for ``build_report_document``.

    Callers can override or extend any key via keyword arguments.
    """
    base: dict = {
        "run_id": "run-01",
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
    raw_metadata = base.get("metadata")
    raw_run_id = str(base.get("run_id") or "").strip()
    if isinstance(raw_metadata, dict) and raw_metadata and raw_run_id:
        metadata = dict(raw_metadata)
        metadata.setdefault("run_id", raw_run_id)
        base["metadata"] = metadata
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
            "ambiguous_location": True,
            "ambiguous_locations": ["Rear Left"],
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
