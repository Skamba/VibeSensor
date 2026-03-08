"""Context extraction helpers for summary-to-report mapping."""

from __future__ import annotations

from collections.abc import Callable

from ..runlog import as_float_or_none as _as_float
from ..runlog import utc_now_iso
from ._types import Finding, SummaryData
from .diagnosis_candidates import normalize_origin_location, select_effective_top_causes
from .report_mapping_common import extract_confidence, human_source


def extract_run_context(
    summary: SummaryData,
) -> tuple[
    SummaryData,
    str | None,
    str | None,
    str,
    list[Finding],
    list[Finding],
    list[Finding],
    SummaryData,
    SummaryData,
]:
    """Extract and normalize the structural context fields from a run summary."""
    meta = summary.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
    car_name = str(meta.get("car_name") or "").strip() or None
    car_type = str(meta.get("car_type") or "").strip() or None
    report_date = summary.get("report_date") or utc_now_iso()
    date_str = str(report_date)[:19].replace("T", " ") + " UTC"

    findings, findings_non_ref, _top_causes_all, top_causes = select_effective_top_causes(
        summary.get("top_causes", []),
        summary.get("findings", []),
    )

    speed_stats = summary.get("speed_stats")
    if not isinstance(speed_stats, dict):
        speed_stats = {}

    origin = summary.get("most_likely_origin", {})
    if not isinstance(origin, dict):
        origin = {}

    return (
        meta,
        car_name,
        car_type,
        date_str,
        top_causes,
        findings_non_ref,
        findings,
        speed_stats,
        origin,
    )


def extract_sensor_locations(summary: SummaryData) -> list[str]:
    """Return active sensor locations for report rendering."""
    sensor_locations_all = summary.get("sensor_locations", [])
    if not isinstance(sensor_locations_all, list):
        sensor_locations_all = []
    connected_locations = summary.get("sensor_locations_connected_throughout", [])
    if not isinstance(connected_locations, list):
        connected_locations = []
    sensor_locations_active = [str(loc) for loc in connected_locations if str(loc).strip()]
    if not sensor_locations_active:
        sensor_locations_active = [str(loc) for loc in sensor_locations_all if str(loc).strip()]
    return sensor_locations_active


def resolve_primary_candidate(
    top_causes: list[Finding],
    findings_non_ref: list[Finding],
    origin_location: str,
    tr: Callable[[str], str],
) -> tuple[Finding | None, object, str, str, str, float]:
    """Resolve the primary diagnosis candidate used by the report."""
    primary_candidates = top_causes or findings_non_ref
    primary_candidate = primary_candidates[0] if primary_candidates else None
    if primary_candidate:
        primary_source = primary_candidate.get("source") or primary_candidate.get(
            "suspected_source"
        )
        primary_system = human_source(primary_source, tr=tr)
        primary_location = origin_location or str(
            primary_candidate.get("strongest_location") or tr("UNKNOWN")
        )
        primary_speed = str(
            primary_candidate.get("strongest_speed_band")
            or primary_candidate.get("speed_band")
            or tr("UNKNOWN")
        )
        conf = extract_confidence(primary_candidate)
    else:
        primary_source = None
        primary_system = tr("UNKNOWN")
        primary_location = origin_location or tr("UNKNOWN")
        primary_speed = tr("UNKNOWN")
        conf = 0.0
    return primary_candidate, primary_source, primary_system, primary_location, primary_speed, conf


def normalized_origin_location(origin: SummaryData) -> str:
    """Return the report-ready origin location string."""
    return normalize_origin_location(origin.get("location"))


def resolve_sensor_count(summary: SummaryData, sensor_locations_active: list[str]) -> int:
    """Resolve the effective sensor count used by report certainty logic."""
    sensor_count = len(sensor_locations_active)
    if sensor_count <= 0:
        sensor_count = int(_as_float(summary.get("sensor_count_used")) or 0)
    return sensor_count
