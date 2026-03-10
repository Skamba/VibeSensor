"""Phase, timing, and speed-preparation helpers for run summaries."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from vibesensor.core.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

from ..constants import MEMS_NOISE_FLOOR_G, SPEED_COVERAGE_MIN_PCT, SPEED_MIN_POINTS
from ..domain_models import as_float_or_none as _as_float
from ..runlog import parse_iso8601
from ._types import (
    Finding,
    MetadataDict,
    PhaseSegmentSummary,
    PhaseTimelineEntry,
    Sample,
    SpeedStats,
)
from .helpers import (
    _speed_stats,
)
from .phase_segmentation import DrivingPhase, PhaseSegment, segment_run_phases


def build_phase_timeline(
    phase_segments: list[PhaseSegment],
    findings: list[Finding],
    *,
    min_confidence: float,
) -> list[PhaseTimelineEntry]:
    """Build a simple phase timeline annotated with finding evidence."""
    if not phase_segments:
        return []

    finding_phases: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        if str(finding.get("finding_id", "")).startswith("REF_"):
            continue
        conf = _as_float(finding.get("confidence_0_to_1")) or 0.0
        if conf < min_confidence:
            continue
        phase_ev = finding.get("phase_evidence")
        if isinstance(phase_ev, dict):
            detected_phases = phase_ev.get("phases_detected", [])
            if not isinstance(detected_phases, list):
                continue
            for phase in detected_phases:
                finding_phases.add(str(phase))

    return [
        {
            "phase": segment.phase.value,
            "start_t_s": None if math.isnan(segment.start_t_s) else segment.start_t_s,
            "end_t_s": None if math.isnan(segment.end_t_s) else segment.end_t_s,
            "speed_min_kmh": segment.speed_min_kmh,
            "speed_max_kmh": segment.speed_max_kmh,
            "has_fault_evidence": segment.phase.value in finding_phases,
        }
        for segment in phase_segments
    ]


def serialize_phase_segments(phase_segments: list[PhaseSegment]) -> list[PhaseSegmentSummary]:
    """Serialize phase segments to JSON-safe dicts."""
    return [
        {
            "phase": seg.phase.value,
            "start_idx": seg.start_idx,
            "end_idx": seg.end_idx,
            "start_t_s": (
                None
                if isinstance(seg.start_t_s, float) and math.isnan(seg.start_t_s)
                else seg.start_t_s
            ),
            "end_t_s": (
                None if isinstance(seg.end_t_s, float) and math.isnan(seg.end_t_s) else seg.end_t_s
            ),
            "speed_min_kmh": seg.speed_min_kmh,
            "speed_max_kmh": seg.speed_max_kmh,
            "sample_count": seg.sample_count,
        }
        for seg in phase_segments
    ]


def noise_baseline_db(run_noise_baseline_g: float | None) -> float | None:
    """Convert a run noise baseline amplitude in g to dB, or return None."""
    if run_noise_baseline_g is None:
        return None
    return float(
        canonical_vibration_db(
            peak_band_rms_amp_g=max(MEMS_NOISE_FLOOR_G, run_noise_baseline_g),
            floor_amp_g=MEMS_NOISE_FLOOR_G,
        ),
    )


def prepare_speed_and_phases(
    samples: list[Sample],
) -> tuple[list[float], SpeedStats, float, bool, list[DrivingPhase], list[PhaseSegment]]:
    """Compute speed stats and phase segmentation shared by multiple entry points."""
    speed_values = [
        speed
        for speed in (_as_float(sample.get("speed_kmh")) for sample in samples)
        if speed is not None and speed > 0
    ]
    speed_stats = _speed_stats(speed_values)
    speed_non_null_pct = (len(speed_values) / len(samples) * 100.0) if samples else 0.0
    speed_sufficient = (
        speed_non_null_pct >= SPEED_COVERAGE_MIN_PCT and len(speed_values) >= SPEED_MIN_POINTS
    )
    per_sample_phases, phase_segments = segment_run_phases(samples)
    return (
        speed_values,
        speed_stats,
        speed_non_null_pct,
        speed_sufficient,
        per_sample_phases,
        phase_segments,
    )


def compute_run_timing(
    metadata: MetadataDict,
    samples: list[Sample],
    file_name: str,
) -> tuple[str, datetime | None, datetime | None, float]:
    """Extract run_id, start/end timestamps and duration from metadata+samples."""
    run_id = str(metadata.get("run_id") or f"run-{file_name}")
    start_ts = parse_iso8601(metadata.get("start_time_utc"))
    end_ts = parse_iso8601(metadata.get("end_time_utc"))

    if end_ts is None and samples:
        sample_max_t = max((_as_float(sample.get("t_s")) or 0.0) for sample in samples)
        if start_ts is not None:
            end_ts = start_ts + timedelta(seconds=sample_max_t)
    duration_s = 0.0
    if start_ts is not None and end_ts is not None:
        duration_s = max(0.0, (end_ts - start_ts).total_seconds())
    elif samples:
        duration_s = max((_as_float(sample.get("t_s")) or 0.0) for sample in samples)

    return run_id, start_ts, end_ts, duration_s
