"""Analysis-summary and persisted-analysis reconstruction helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from vibesensor.domain import Finding, coerce_int
from vibesensor.domain.driving_segment import DrivingPhase, DrivingSegment
from vibesensor.domain.run_capture import RunCapture, RunSetup
from vibesensor.domain.sensor import Sensor
from vibesensor.domain.speed_profile import SpeedProfile
from vibesensor.domain.speed_source import SpeedSource
from vibesensor.domain.test_plan import RecommendedAction, TestPlan
from vibesensor.domain.test_run import TestRun
from vibesensor.shared.boundaries.codecs import (
    driving_phase_summary_from_mapping,
    speed_profile_summary_from_mapping,
)
from vibesensor.shared.boundaries.runs.capture import (
    configuration_snapshot_from_run_metadata,
)
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.runs.suitability import run_suitability_from_payload
from vibesensor.shared.boundaries.summary_fields.finding import finding_from_payload
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis

from ._origin_enrichment import enrich_primary_origin_from_summary

__all__ = ["test_run_from_persisted_analysis", "test_run_from_summary"]


def _actions_from_steps(steps: object) -> tuple[RecommendedAction, ...]:
    if not isinstance(steps, list):
        return ()
    actions: list[RecommendedAction] = []
    for idx, step in enumerate(steps):
        if not isinstance(step, Mapping):
            continue
        actions.append(
            RecommendedAction(
                action_id=str(step.get("action_id") or f"action-{idx + 1}"),
                what=str(step.get("what") or ""),
                why=str(step.get("why") or ""),
                confirm=str(step.get("confirm") or ""),
                falsify=str(step.get("falsify") or ""),
                eta=str(step.get("eta") or "") or None,
                priority=idx,
            )
        )
    return tuple(actions)


def _segments_from_summary(summary: Mapping[str, object]) -> tuple[DrivingSegment, ...]:
    raw_segments = summary.get("phase_segments")
    if not isinstance(raw_segments, list):
        return ()
    segments: list[DrivingSegment] = []
    for segment in raw_segments:
        if not isinstance(segment, Mapping):
            continue
        phase_raw = str(segment.get("phase") or "cruise").upper()
        try:
            phase = DrivingPhase[phase_raw]
        except KeyError:
            phase = DrivingPhase.CRUISE
        segments.append(
            DrivingSegment(
                phase=phase,
                start_idx=(
                    int(_si) if (_si := _as_float(segment.get("start_idx"))) is not None else None
                ),
                end_idx=(
                    int(_ei) if (_ei := _as_float(segment.get("end_idx"))) is not None else None
                ),
                start_t_s=_as_float(segment.get("start_t_s")),
                end_t_s=_as_float(segment.get("end_t_s")),
                speed_min_kmh=_as_float(segment.get("speed_min_kmh")),
                speed_max_kmh=_as_float(segment.get("speed_max_kmh")),
                sample_count=int(_as_float(segment.get("sample_count")) or 0),
            )
        )
    return tuple(segments)


def _summary_sensor_locations(summary: Mapping[str, object]) -> list[str]:
    raw_locations = summary.get("sensor_locations")
    if isinstance(raw_locations, (str, bytes, bytearray)) or not isinstance(
        raw_locations,
        Sequence,
    ):
        return []
    return [str(location).strip() for location in raw_locations if str(location).strip()]


def _findings_from_payloads(raw_findings: object) -> tuple[Finding, ...]:
    if not isinstance(raw_findings, list):
        return ()
    return tuple(
        finding_from_payload(payload) for payload in raw_findings if isinstance(payload, Mapping)
    )


def _resolve_run_id(payload: Mapping[str, object], meta: Mapping[str, object]) -> str:
    for candidate in (payload.get("run_id"), meta.get("run_id"), payload.get("file_name")):
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
    return "unknown"


def _test_run_from_payload(payload: Mapping[str, object]) -> TestRun:
    metadata = payload.get("metadata")
    meta = metadata if isinstance(metadata, Mapping) else {}
    findings = _findings_from_payloads(payload.get("findings"))
    top_causes = _findings_from_payloads(payload.get("top_causes"))
    if top_causes:
        merged = list(findings)
        for tc in top_causes:
            if not any(
                tc == f or (tc.finding_id and tc.finding_id == f.finding_id) for f in merged
            ):
                merged.append(tc)
        findings = tuple(merged)
    findings, top_causes = enrich_primary_origin_from_summary(
        payload,
        findings=findings,
        top_causes=top_causes,
    )
    actions = _actions_from_steps(payload.get("test_plan"))
    raw_speed_stats = payload.get("speed_stats")
    phase_info = payload.get("phase_info")
    if not isinstance(phase_info, Mapping):
        phase_info = payload.get("phase_summary")
    speed_profile = (
        SpeedProfile.from_stats(
            speed_profile_summary_from_mapping(raw_speed_stats),
            (
                driving_phase_summary_from_mapping(phase_info)
                if isinstance(phase_info, Mapping)
                else None
            ),
        )
        if isinstance(raw_speed_stats, Mapping)
        else None
    )
    raw_suitability_payload = payload.get("run_suitability")
    suitability = (
        run_suitability_from_payload(raw_suitability_payload)
        if isinstance(raw_suitability_payload, list)
        else None
    )

    _steady = speed_profile.steady_speed if speed_profile is not None else True
    sensor_loc_list = _summary_sensor_locations(payload)
    _sensor_count = max(len(sensor_loc_list), 1)
    _amp_summary = payload.get("amplitude_summary")
    _band_key = (
        _amp_summary.get("overall_band", "moderate")
        if isinstance(_amp_summary, Mapping)
        else "moderate"
    )
    _has_ref_gaps = suitability.has_reference_gaps if suitability else False

    findings = tuple(
        replace(
            f,
            confidence_assessment=replace(
                f.confidence_assessment,
                steady_speed=_steady,
                has_reference_gaps=_has_ref_gaps,
                weak_spatial=f.weak_spatial_separation,
            ),
        )
        if f.confidence_assessment is not None
        else f.with_confidence_assessment(
            strength_band_key=_band_key,
            steady_speed=_steady,
            has_reference_gaps=_has_ref_gaps,
            sensor_count=_sensor_count,
        )
        for f in findings
    )
    top_causes = tuple(
        replace(
            f,
            confidence_assessment=replace(
                f.confidence_assessment,
                steady_speed=_steady,
                has_reference_gaps=_has_ref_gaps,
                weak_spatial=f.weak_spatial_separation,
            ),
        )
        if f.confidence_assessment is not None
        else f.with_confidence_assessment(
            strength_band_key=_band_key,
            steady_speed=_steady,
            has_reference_gaps=_has_ref_gaps,
            sensor_count=_sensor_count,
        )
        for f in top_causes
    )

    setup = RunSetup(
        sensors=Sensor.from_location_codes(sensor_loc_list) if sensor_loc_list else (),
        speed_source=SpeedSource(),
        configuration_snapshot=configuration_snapshot_from_run_metadata(
            run_metadata_from_mapping(meta),
        ),
    )
    rows_raw = payload.get("rows")
    try:
        row_count = coerce_int(rows_raw) if rows_raw is not None else 0
    except (TypeError, ValueError):
        row_count = 0
    capture = RunCapture(
        run_id=_resolve_run_id(payload, meta),
        setup=setup,
        sample_count=row_count,
    )
    return TestRun(
        capture=capture,
        driving_segments=_segments_from_summary(payload),
        findings=findings,
        top_causes=top_causes,
        speed_profile=speed_profile,
        suitability=suitability,
        test_plan=TestPlan(
            actions=actions,
            requires_additional_data=not bool(findings),
        ),
    )


def test_run_from_summary(summary: Mapping[str, object]) -> TestRun:
    """Reconstruct a TestRun from an outward analysis-summary payload."""
    return _test_run_from_payload(summary)


def test_run_from_persisted_analysis(
    analysis: PersistedAnalysis,
) -> TestRun:
    """Reconstruct a TestRun from a storage-owned persisted-analysis payload."""
    return _test_run_from_payload(analysis.payload)
